from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.post import Post
from bson.objectid import ObjectId
from datetime import datetime
import requests as http_requests
from urllib.parse import quote as url_quote
import json
import re
import os
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

        # Auto-publish: mark overdue scheduled posts as posted
        now = datetime.utcnow()
        today_str = now.strftime("%Y-%m-%d")
        now_time = now.strftime("%H:%M")
        overdue_query = {
            "user_id": user_id,
            "status": "scheduled",
            "schedule_date": {"$lte": today_str},
        }
        overdue_posts = list(posts_collection.find(overdue_query))
        for op in overdue_posts:
            sd = op.get("schedule_date", "")
            st = op.get("schedule_time", "23:59")
            if sd < today_str or (sd == today_str and st <= now_time):
                posts_collection.update_one(
                    {"_id": op["_id"]},
                    {"$set": {
                        "status": "posted",
                        "published_at": now,
                        "updated_at": now,
                    }}
                )

        posts_cursor = (
            posts_collection.find(query)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )

        posts = []
        for post_doc in posts_cursor:
            post_doc["_id"] = str(post_doc["_id"])  # ✅ FIX ObjectId
            # Serialize datetime fields to ISO strings
            for dt_field in ("created_at", "updated_at", "published_at"):
                if isinstance(post_doc.get(dt_field), datetime):
                    post_doc[dt_field] = post_doc[dt_field].isoformat()
            posts.append(post_doc)

        # Enrich posts with engagement from interactions collection
        post_ids = [p["_id"] for p in posts]
        if post_ids:
            interactions_col = mongo["interactions"]
            pipeline = [
                {"$match": {"post_id": {"$in": post_ids}}},
                {"$group": {
                    "_id": "$post_id",
                    "likes": {"$sum": {"$cond": [{"$eq": ["$type", "like"]}, 1, 0]}},
                    "comments": {"$sum": {"$cond": [{"$eq": ["$type", "comment"]}, 1, 0]}},
                    "shares": {"$sum": {"$cond": [{"$eq": ["$type", "share"]}, 1, 0]}},
                }}
            ]
            eng_map = {}
            for doc in interactions_col.aggregate(pipeline):
                eng_map[doc["_id"]] = {
                    "likes": doc["likes"],
                    "comments": doc["comments"],
                    "shares": doc["shares"],
                }
            for p in posts:
                if p["_id"] in eng_map:
                    p["engagement"] = eng_map[p["_id"]]

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


# =========================
# ✅ PUBLISH POST TO LINKEDIN
# =========================
@posts_bp.post("/<post_id>/publish")
@jwt_required()
def publish_post(post_id):
    """Publish a post to LinkedIn via the UGC Posts API."""
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]
        users_collection = mongo["users"]

        # 1) Find the post
        post_doc, actual_id = _find_post(posts_collection, post_id, user_id)
        if not post_doc:
            return jsonify({"success": False, "error": "Post not found"}), 404

        # 2) Get user with LinkedIn token
        user = users_collection.find_one({"email": user_id})
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        linkedin_token = user.get("linkedin_access_token")
        linkedin_id = user.get("linkedin_id")

        if not linkedin_token:
            return jsonify({
                "success": False,
                "error": "LinkedIn not connected. Please reconnect your LinkedIn account."
            }), 401

        if not linkedin_id:
            return jsonify({
                "success": False,
                "error": "LinkedIn user ID missing. Please reconnect your LinkedIn account."
            }), 401

        # Check token expiration
        token_expires = user.get("linkedin_token_expires_at")
        if token_expires and datetime.utcnow() > token_expires:
            return jsonify({
                "success": False,
                "error": "LinkedIn token expired. Please reconnect your LinkedIn account."
            }), 401

        content = post_doc.get("content", "")
        if not content:
            return jsonify({"success": False, "error": "Post has no content"}), 400

        # 3) Build UGC Post payload
        author_urn = f"urn:li:person:{linkedin_id}"

        ugc_payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {
                        "text": content
                    },
                    "shareMediaCategory": "NONE"
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            }
        }

        # 4) Post to LinkedIn
        li_response = http_requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {linkedin_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=ugc_payload,
            timeout=15,
        )

        if li_response.status_code not in (200, 201):
            error_detail = li_response.text
            print(f"[LINKEDIN] Post failed ({li_response.status_code}): {error_detail}")
            return jsonify({
                "success": False,
                "error": f"LinkedIn API error: {li_response.status_code}",
                "detail": error_detail
            }), 502

        linkedin_post_id = li_response.headers.get("X-RestLi-Id", "")
        print(f"[LINKEDIN] Post published successfully: {linkedin_post_id}")

        # 5) Update post status in MongoDB
        posts_collection.update_one(
            {"_id": actual_id},
            {"$set": {
                "status": "posted",
                "published_at": datetime.utcnow(),
                "linkedin_post_id": linkedin_post_id,
                "updated_at": datetime.utcnow(),
            }}
        )

        return jsonify({
            "success": True,
            "message": "Post published to LinkedIn successfully",
            "linkedin_post_id": linkedin_post_id
        })

    except Exception as e:
        print(f"[LINKEDIN] Publish error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ REFRESH ENGAGEMENT VIA APIFY SCRAPING
# =========================
@posts_bp.post("/refresh-engagement")
@jwt_required()
def refresh_all_engagement():
    """Scrape LinkedIn profile via Apify to get engagement for all published posts."""
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]
        users_collection = mongo["users"]

        user = users_collection.find_one({"email": user_id})
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        linkedin_id = user.get("linkedin_id")
        linkedin_profile_url = user.get("linkedin_profile_url")
        if not linkedin_profile_url:
            if not linkedin_id:
                return jsonify({"success": False, "error": "LinkedIn not connected"}), 400
            return jsonify({
                "success": False,
                "error": "LinkedIn profile URL not set. Go to Settings → Integrations → LinkedIn → Configure to add your profile URL."
            }), 400

        apify_key = current_app.config.get("APIFY_KEY") or os.environ.get("APIFY_KEY")
        if not apify_key:
            return jsonify({"success": False, "error": "APIFY_KEY not configured"}), 500

        profile_url = linkedin_profile_url

        # Use harvestapi LinkedIn profile posts scraper (no cookies needed)
        actor_id = "harvestapi~linkedin-profile-posts"
        actor_input = {
            "targetUrls": [profile_url],
            "maxPosts": 50,
        }

        # Start the actor run
        run_resp = http_requests.post(
            f"https://api.apify.com/v2/acts/{actor_id}/runs",
            params={"token": apify_key},
            headers={"Content-Type": "application/json"},
            json=actor_input,
            timeout=30,
        )

        if run_resp.status_code not in (200, 201):
            return jsonify({"success": False, "error": f"Apify start failed: {run_resp.status_code}"}), 502

        run_id = run_resp.json().get("data", {}).get("id")
        if not run_id:
            return jsonify({"success": False, "error": "Apify run ID missing"}), 502

        # Poll for completion (max ~90 seconds)
        import time
        dataset_id = None
        for _ in range(30):
            time.sleep(3)
            status_resp = http_requests.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                params={"token": apify_key},
                timeout=15,
            )
            if status_resp.status_code != 200:
                continue
            status_data = status_resp.json().get("data", {})
            run_status = status_data.get("status")
            if run_status == "SUCCEEDED":
                dataset_id = status_data.get("defaultDatasetId")
                break
            elif run_status in ("FAILED", "ABORTED", "TIMED-OUT"):
                return jsonify({"success": False, "error": f"Apify run {run_status}"}), 502

        if not dataset_id:
            return jsonify({"success": False, "error": "Apify scraping timed out"}), 504

        # Fetch dataset items
        items_resp = http_requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items",
            params={"token": apify_key, "format": "json"},
            timeout=30,
        )
        if items_resp.status_code != 200:
            return jsonify({"success": False, "error": "Failed to fetch Apify results"}), 502

        scraped_posts = items_resp.json()
        print(f"[ENGAGEMENT] Scraped {len(scraped_posts)} items from LinkedIn")

        # Get all published posts for this user
        db_posts = list(posts_collection.find({
            "user_id": user_id,
            "status": "posted",
            "platforms.LinkedIn": True,
        }))

        matched = 0
        for db_post in db_posts:
            db_content = (db_post.get("content") or "").strip()
            if not db_content:
                continue

            # Try to match by content similarity (first 80 chars)
            db_snippet = db_content[:80].lower().strip()

            for item in scraped_posts:
                # harvestapi actor uses "content" field for post text
                scraped_text = (
                    item.get("content")
                    or item.get("text")
                    or item.get("postText")
                    or item.get("description")
                    or ""
                ).strip()

                if not scraped_text:
                    continue

                scraped_snippet = scraped_text[:80].lower().strip()

                if db_snippet == scraped_snippet or (len(db_snippet) > 30 and db_snippet in scraped_text.lower()):
                    # harvestapi actor nests stats under "engagement" object
                    eng = item.get("engagement") or {}
                    likes = eng.get("likes") or item.get("numLikes") or 0
                    comments = eng.get("comments") or item.get("numComments") or 0
                    shares = eng.get("shares") or item.get("numShares") or 0

                    engagement = {
                        "likes": int(likes) if likes else 0,
                        "comments": int(comments) if comments else 0,
                        "shares": int(shares) if shares else 0,
                    }

                    posts_collection.update_one(
                        {"_id": db_post["_id"]},
                        {"$set": {
                            "engagement": engagement,
                            "engagement_updated_at": datetime.utcnow(),
                        }}
                    )
                    matched += 1
                    print(f"[ENGAGEMENT] Post {db_post['_id']}: {likes} likes, {comments} comments, {shares} shares")
                    break

        return jsonify({
            "success": True,
            "message": f"Updated engagement for {matched} post(s) out of {len(db_posts)}",
            "matched": matched,
            "total": len(db_posts),
            "scraped": len(scraped_posts),
        })

    except Exception as e:
        print(f"[ENGAGEMENT] Scrape error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
