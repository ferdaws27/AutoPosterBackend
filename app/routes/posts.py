from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.post import Post
from bson.objectid import ObjectId
from datetime import datetime

posts_bp = Blueprint("posts_bp", __name__, url_prefix="/api/posts")


# =========================
# ✅ GET POSTS
# =========================
@posts_bp.get("/getPosts")
@jwt_required()
def get_posts():
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo

        status = request.args.get("status")
        platform = request.args.get("platform")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        # Filter by user_id - each user only sees their own posts
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
            platforms=data.get("platforms", {}),
            status=data.get("status", "draft"),
            schedule_date=data.get("schedule_date"),
            schedule_time=data.get("schedule_time"),
            engagement=data.get("engagement", {})
        )

        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        result = posts_collection.insert_one(post.to_dict())

        post._id = result.inserted_id

        return jsonify({
            "success": True,
            "data": {
                "_id": str(post._id),
                "content": post.content,
                "platforms": post.platforms,
                "status": post.status,
                "schedule_date": post.schedule_date,
                "schedule_time": post.schedule_time,
                "engagement": post.engagement,
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

        post_doc = posts_collection.find_one({
            "_id": ObjectId(post_id),
            "user_id": user_id
        })

        if not post_doc:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        post_doc["_id"] = str(post_doc["_id"])  # ✅ FIX

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

        update_data = {"updated_at": datetime.utcnow()}

        fields = [
            "content",
            "platforms",
            "status",
            "schedule_date",
            "schedule_time",
            "engagement"
        ]

        for field in fields:
            if field in data:
                update_data[field] = data[field]

        result = posts_collection.update_one(
            {"_id": ObjectId(post_id), "user_id": user_id},
            {"$set": update_data}
        )

        if result.matched_count == 0:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        updated_post = posts_collection.find_one({
            "_id": ObjectId(post_id)
        })

        updated_post["_id"] = str(updated_post["_id"])  # ✅ FIX

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

        result = posts_collection.delete_one({
            "_id": ObjectId(post_id),
            "user_id": user_id
        })

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

        original = posts_collection.find_one({
            "_id": ObjectId(post_id),
            "user_id": user_id
        })

        if not original:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        original["_id"] = ObjectId()
        original["status"] = "draft"
        original["created_at"] = datetime.utcnow()
        original["updated_at"] = datetime.utcnow()
        original["schedule_date"] = None
        original["schedule_time"] = None

        result = posts_collection.insert_one(original)

        original["_id"] = str(result.inserted_id)

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
def get_posts_stats():
    """Get post statistics. Works with or without authentication."""
    try:
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        # Build pipeline - if user is authenticated, filter by user_id
        try:
            user_id = get_jwt_identity()
            match_stage = {"$match": {"user_id": user_id}}
        except:
            # No authentication - get all posts
            match_stage = {"$match": {}}

        pipeline = [
            match_stage,
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]

        stats_result = list(posts_collection.aggregate(pipeline))

        stats = {
            "draft": 0,
            "scheduled": 0,
            "published": 0,
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
