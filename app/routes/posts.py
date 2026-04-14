from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.post import Post
from bson.objectid import ObjectId
from datetime import datetime
import requests as http_requests
import json
import re
import threading

posts_bp = Blueprint("posts_bp", __name__, url_prefix="/api/posts")

CONTENT_TYPES = [
    "tutorial", "story", "insight", "case_study", "motivational",
    "short_tip", "news", "opinion", "deep_dive", "analysis"
]


def _detect_single_content_type(app, post_id, content):
    """Detect content_type for a single post via OpenRouter (runs in background thread)."""
    with app.app_context():
        try:
            prompt = f"""You are an expert content strategist who classifies social media posts with high precision. Analyze the writing style, structure, intent, and vocabulary to determine the exact content type.

Allowed types: {json.dumps(CONTENT_TYPES)}

Post content:
\"\"\"
{content[:500]}
\"\"\"

CLASSIFICATION GUIDE — Use these signal patterns:

"tutorial" → Contains step-by-step instructions, numbered lists, "how to", "here's how", teaching language, actionable steps
"story" → Personal narrative with timeline ("I was...", "When I...", "Last year..."), anecdotes, character arc, emotional journey
"insight" → Key observation or lesson learned, reflective tone ("I realized...", "The truth is...", "What most people miss..."), wisdom distilled from experience
"case_study" → Real-world example with specific results, metrics, before/after comparison, company/client references, data points
"motivational" → Inspirational language, encouragement, mindset-focused, empowerment, "you can", "believe", "don't give up"
"short_tip" → Quick actionable advice in 1-3 sentences, "Pro tip:", "Quick hack:", one specific recommendation
"news" → Industry updates, announcements, trending topics, recent events, "breaking", "just launched", time-sensitive
"opinion" → Personal stance, "I think", "Hot take:", debate-starting, "Unpopular opinion:", challenging norms
"deep_dive" → In-depth exploration with multiple sections, thorough analysis, comprehensive coverage, 500+ word detailed breakdown
"analysis" → Data-driven breakdown, comparison, statistics, trends, charts/graphs referenced, "the data shows", metrics-heavy

DECISION RULES:
- If it teaches AND tells a story → choose whichever is the PRIMARY intent
- If it's short advice → "short_tip" (regardless of other elements)
- If it has data/metrics as the core → "analysis" over "case_study" (case_study needs a narrative arc)
- If unsure between "insight" and "opinion" → "insight" if reflective, "opinion" if argumentative

Respond in strict JSON:
{{"content_type": "one_of_allowed_types", "confidence": 0.0-1.0}}

Only return valid JSON, no markdown."""

            response = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {app.config['OPENROUTER_API_KEY']}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": app.config.get("FRONTEND_URL", "http://localhost:5173"),
                    "X-Title": "AutoPoster Content Classifier"
                },
                json={
                    "model": app.config["OPENROUTER_MODEL"],
                    "messages": [
                        {"role": "system", "content": "You are a precision content classifier. Analyze writing patterns, structure, and intent to classify social media posts. Return strict JSON only — no markdown, no explanation."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500
                },
                timeout=30
            )

            result = response.json()
            raw = result["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            parsed = json.loads(raw)
            content_type = parsed.get("content_type", "").strip().lower()
            confidence = parsed.get("confidence", 0)

            if content_type not in CONTENT_TYPES:
                content_type = "insight"

            app.mongo.posts.update_one(
                {"_id": post_id},
                {"$set": {
                    "content_type": content_type,
                    "content_type_confidence": round(float(confidence), 2)
                }}
            )
            print(f"[CONTENT-TYPE] Post {post_id} -> {content_type} ({confidence})")

        except Exception as e:
            print(f"[CONTENT-TYPE] Error for post {post_id}: {e}")


def _find_post(collection, post_id, user_id=None):
    """Find a post by _id, trying both string and ObjectId formats."""
    query = {"_id": post_id}
    if user_id:
        query["user_id"] = user_id
    doc = collection.find_one(query)
    if doc:
        return doc, post_id

    # Try ObjectId
    try:
        oid = ObjectId(post_id)
        query_oid = {"_id": oid}
        if user_id:
            query_oid["user_id"] = user_id
        doc = collection.find_one(query_oid)
        if doc:
            return doc, oid
    except Exception:
        pass

    return None, post_id


# =========================
# ✅ GET POSTS
# =========================
@posts_bp.get("/getPosts")
@jwt_required()  # ✅ REQUIRE AUTHENTICATION for user isolation
def get_posts():
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo

        status = request.args.get("status")
        platform = request.args.get("platform")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        # Filter by user_id - ONLY this user's posts
        query = {"user_id": user_id}

        if status:
            query["status"] = status

        if platform:
            query[f"platforms.{platform}"] = True

        posts_collection = mongo[Post.collection_name]

        posts_cursor = (
            posts_collection.find(query)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )

        posts = []
        for post_doc in posts_cursor:
            post_doc["_id"] = str(post_doc["_id"])  # ✅ FIX ObjectId
            posts.append(post_doc)

        total_count = posts_collection.count_documents(query)

        return jsonify({
            "success": True,
            "data": {
                "posts": posts,
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ CREATE POST
# =========================
@posts_bp.post("/")
@jwt_required()  # ✅ Require authentication to create posts
def create_post():
    try:
        data = request.get_json()

        content = data.get("content") or data.get("idea")

        if not content:
            return jsonify({
                "success": False,
                "error": "Content is required"
            }), 400

        # Get authenticated user_id from JWT
        user_id = get_jwt_identity()
        
        if not user_id:
            return jsonify({
                "success": False,
                "error": "User authentication required"
            }), 401

        post = Post(
            user_id=user_id,
            content=content,
            idea=data.get("idea"),
            platforms=data.get("platforms", {}),
            status=data.get("status", "draft"),
            schedule_date=data.get("schedule_date"),
            schedule_time=data.get("schedule_time"),
            engagement=data.get("engagement", {}),
            selected_images=data.get("selectedImages", [])
        )

        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        result = posts_collection.insert_one(post.to_dict())

        post._id = result.inserted_id

        # Auto-detect content_type in background
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=_detect_single_content_type,
            args=(app, str(post._id), content)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "_id": str(post._id),
                "idea": post.idea,
                "content": post.content,
                "platforms": post.platforms,
                "status": post.status,
                "schedule_date": post.schedule_date,
                "schedule_time": post.schedule_time,
                "engagement": post.engagement,
                "selectedImages": post.selected_images,
                "created_at": post.created_at.isoformat() if post.created_at else None,
                "updated_at": post.updated_at.isoformat() if post.updated_at else None
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ GET POST BY ID
# =========================
@posts_bp.get("/<post_id>")
@jwt_required()
def get_post(post_id):
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        post_doc, _ = _find_post(posts_collection, post_id, user_id)

        if not post_doc:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        post_doc["_id"] = str(post_doc["_id"])

        return jsonify({
            "success": True,
            "data": post_doc
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ UPDATE POST
# =========================
@posts_bp.put("/<post_id>")
@jwt_required()
def update_post(post_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        # Find post with string or ObjectId
        post_doc, actual_id = _find_post(posts_collection, post_id, user_id)

        if not post_doc:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        update_data = {"updated_at": datetime.utcnow()}

        fields = [
            "idea",
            "content",
            "platforms",
            "status",
            "schedule_date",
            "schedule_time",
            "engagement",
            "selectedImages",
            "content_type"
        ]

        for field in fields:
            if field in data:
                update_data[field] = data[field]

        posts_collection.update_one(
            {"_id": actual_id},
            {"$set": update_data}
        )

        updated_post = posts_collection.find_one({"_id": actual_id})
        updated_post["_id"] = str(updated_post["_id"])

        return jsonify({
            "success": True,
            "data": updated_post
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ DELETE POST
# =========================
@posts_bp.delete("/<post_id>")
@jwt_required()
def delete_post(post_id):
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        post_doc, actual_id = _find_post(posts_collection, post_id, user_id)

        if not post_doc:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        result = posts_collection.delete_one({"_id": actual_id})

        if result.deleted_count == 0:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        return jsonify({
            "success": True,
            "message": "Post deleted successfully"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ DUPLICATE POST
# =========================
@posts_bp.post("/<post_id>/duplicate")
@jwt_required()
def duplicate_post(post_id):
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        original, _ = _find_post(posts_collection, post_id, user_id)

        if not original:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        # Create duplicate with string _id (consistent with create_post)
        new_id = str(ObjectId())
        original["_id"] = new_id
        original["status"] = "draft"
        original["created_at"] = datetime.utcnow()
        original["updated_at"] = datetime.utcnow()
        original["schedule_date"] = None
        original["schedule_time"] = None

        posts_collection.insert_one(original)

        original["_id"] = new_id

        return jsonify({
            "success": True,
            "data": original
        }), 201

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ STATS
# =========================
@posts_bp.get("/stats/summary")
@jwt_required()  # ✅ REQUIRE AUTHENTICATION
def get_posts_stats():
    """Get post statistics for the authenticated user only."""
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        # Filter by user_id - only get this user's stats
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]

        stats_result = list(posts_collection.aggregate(pipeline))

        stats = {
            "draft": 0,
            "scheduled": 0,
            "posted": 0,
            "total": 0
        }

        for stat in stats_result:
            stats[stat["_id"]] = stat["count"]
            stats["total"] += stat["count"]

        return jsonify({
            "success": True,
            "data": stats
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
