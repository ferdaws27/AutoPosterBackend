from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.post import Post
from bson.objectid import ObjectId
from datetime import datetime

posts_bp = Blueprint("posts_bp", __name__, url_prefix="/api/posts")


@posts_bp.get("/")
@jwt_required()
def get_posts():
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo

        status = request.args.get("status")
        platform = request.args.get("platform")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

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
            post = Post.from_dict(post_doc)
            posts.append(post.to_dict())

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
        return jsonify({"success": False, "error": str(e)}), 500


@posts_bp.post("/")
@jwt_required()
def create_post():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        if not data or not data.get("content"):
            return jsonify({
                "success": False,
                "error": "Content is required"
            }), 400

        post = Post(
            user_id=user_id,
            content=data["content"],
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
            "data": post.to_dict()
        }), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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

        post = Post.from_dict(post_doc)

        return jsonify({
            "success": True,
            "data": post.to_dict()
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@posts_bp.put("/<post_id>")
@jwt_required()
def update_post(post_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()
        mongo = current_app.mongo

        posts_collection = mongo[Post.collection_name]

        update_data = {"updated_at": datetime.utcnow()}
        if "content" in data:
            update_data["content"] = data["content"]
        if "platforms" in data:
            update_data["platforms"] = data["platforms"]
        if "status" in data:
            update_data["status"] = data["status"]
        if "schedule_date" in data:
            update_data["schedule_date"] = data["schedule_date"]
        if "schedule_time" in data:
            update_data["schedule_time"] = data["schedule_time"]
        if "engagement" in data:
            update_data["engagement"] = data["engagement"]

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
            "_id": ObjectId(post_id),
            "user_id": user_id
        })
        post = Post.from_dict(updated_post)

        return jsonify({
            "success": True,
            "data": post.to_dict()
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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
        return jsonify({"success": False, "error": str(e)}), 500


@posts_bp.post("/<post_id>/duplicate")
@jwt_required()
def duplicate_post(post_id):
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo

        posts_collection = mongo[Post.collection_name]
        original_post_doc = posts_collection.find_one({
            "_id": ObjectId(post_id),
            "user_id": user_id
        })

        if not original_post_doc:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        duplicate_post = Post.from_dict(original_post_doc)
        duplicate_post._id = ObjectId()
        duplicate_post.status = "draft"
        duplicate_post.created_at = datetime.utcnow()
        duplicate_post.updated_at = datetime.utcnow()
        duplicate_post.schedule_date = None
        duplicate_post.schedule_time = None

        result = posts_collection.insert_one(duplicate_post.to_dict())

        duplicate_post._id = result.inserted_id
        return jsonify({
            "success": True,
            "data": duplicate_post.to_dict()
        }), 201

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@posts_bp.get("/stats/summary")
@jwt_required()
def get_posts_stats():
    try:
        user_id = get_jwt_identity()
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

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
            "published": 0,
            "total": 0
        }

        for stat in stats_result:
            status = stat["_id"]
            count = stat["count"]
            stats[status] = count
            stats["total"] += count

        recent_posts = list(
            posts_collection.find({"user_id": user_id})
            .sort("created_at", -1)
            .limit(10)
        )

        recent_posts_data = []
        for post_doc in recent_posts:
            post = Post.from_dict(post_doc)
            recent_posts_data.append({
                "id": str(post._id),
                "content": post.content[:100] + "..." if len(post.content) > 100 else post.content,
                "status": post.status,
                "platforms": post.platforms,
                "created_at": post.created_at.isoformat() if post.created_at else None,
                "engagement": post.engagement
            })

        return jsonify({
            "success": True,
            "data": {
                "stats": stats,
                "recent_posts": recent_posts_data
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500