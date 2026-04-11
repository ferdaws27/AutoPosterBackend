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
            "_id": post_id,
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

        # Debug logs
        print(f"DEBUG: Attempting to update post {post_id}")
        print(f"DEBUG: User ID from JWT: {user_id}")
        print(f"DEBUG: User ID type: {type(user_id)}")
        
        # Check if post exists with string ID (posts are stored as strings)
        post_exists = posts_collection.find_one({"_id": post_id})
        print(f"DEBUG: Post exists: {post_exists is not None}")
        if post_exists:
            print(f"DEBUG: Post user_id: {post_exists.get('user_id')}")
            print(f"DEBUG: Post user_id type: {type(post_exists.get('user_id'))}")
            print(f"DEBUG: User IDs match: {post_exists.get('user_id') == user_id}")

        update_data = {"updated_at": datetime.utcnow()}

        fields = [
            "content",
            "platforms",
            "status",
            "schedule_date",
            "schedule_time",
            "engagement",
            "selectedImages"
        ]

        for field in fields:
            if field in data:
                update_data[field] = data[field]

        # Use string ID instead of ObjectId (posts are stored as strings)
        result = posts_collection.update_one(
            {"_id": post_id, "user_id": user_id},
            {"$set": update_data}
        )

        print(f"DEBUG: Update result - matched_count: {result.matched_count}")

        if result.matched_count == 0:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        updated_post = posts_collection.find_one({
            "_id": post_id
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
        print(f"=== DELETE POST DEBUG ===")
        print(f"Post ID: {post_id}")
        
        user_id = get_jwt_identity()
        print(f"User ID from JWT: {user_id}")
        print(f"User ID type: {type(user_id)}")
        
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        # First check if post exists and belongs to user
        print(f"Searching for post with _id='{post_id}' and user_id='{user_id}'")
        post = posts_collection.find_one({
            "_id": post_id,
            "user_id": user_id
        })
        
        print(f"Post found: {post is not None}")
        if post:
            print(f"Post details: _id='{post['_id']}', user_id='{post.get('user_id')}'")
        
        if not post:
            print("Post not found - returning 404")
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        # Delete the post
        print(f"Attempting to delete post...")
        result = posts_collection.delete_one({
            "_id": post_id,
            "user_id": user_id
        })

        print(f"Delete result - deleted_count: {result.deleted_count}")

        if result.deleted_count == 0:
            print("No documents deleted - returning 404")
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        print("Post deleted successfully - returning 200")
        return jsonify({
            "success": True,
            "message": "Post deleted successfully"
        })

    except Exception as e:
        print(f"Exception in delete_post: {str(e)}")
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
        print(f"=== DUPLICATE POST DEBUG ===")
        print(f"Post ID to duplicate: {post_id}")
        
        user_id = get_jwt_identity()
        print(f"User ID from JWT: {user_id}")
        
        mongo = current_app.mongo
        posts_collection = mongo[Post.collection_name]

        print(f"Searching for post with _id='{post_id}' and user_id='{user_id}'")
        original = posts_collection.find_one({
            "_id": post_id,
            "user_id": user_id
        })
        
        print(f"Original post found: {original is not None}")
        if original:
            print(f"Original post _id: {original.get('_id')}")
            print(f"Original post keys: {list(original.keys())}")

        if not original:
            return jsonify({
                "success": False,
                "error": "Post not found"
            }), 404

        print("Creating duplicate post...")
        original["_id"] = ObjectId()
        original["status"] = "draft"
        original["created_at"] = datetime.utcnow()
        original["updated_at"] = datetime.utcnow()
        original["schedule_date"] = None
        original["schedule_time"] = None

        print("Inserting duplicate post into database...")
        result = posts_collection.insert_one(original)
        print(f"Insert result: {result.inserted_id}")

        original["_id"] = str(result.inserted_id)
        print(f"Final duplicate post _id: {original['_id']}")

        response_data = {
            "success": True,
            "data": original
        }
        print(f"Returning response: {response_data}")
        return jsonify(response_data), 201

    except Exception as e:
        print(f"Exception in duplicate_post: {str(e)}")
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
