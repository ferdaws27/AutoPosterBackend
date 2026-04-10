from flask import Blueprint, current_app, jsonify
from collections import defaultdict
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/analytics", methods=["GET"])
@jwt_required()
def get_analytics():

    # 🔥 récupérer user connecté
    current_user_id = get_jwt_identity()
    
    # 🔥 Get user email to handle posts stored with email as user_id
    try:
        current_user = current_app.mongo.users.find_one({"_id": ObjectId(current_user_id)})
    except:
        current_user = current_app.mongo.users.find_one({"_id": current_user_id})
    
    user_email = current_user.get("email") if current_user else None

    # 🔥 récupérer SEULEMENT ses posts (check both user_id and email)
    query = {"$or": [{"user_id": ObjectId(current_user_id)}, {"user_id": current_user_id}]}
    if user_email:
        # Also search for posts where user_id is the email address
        query = {"$or": [{"user_id": ObjectId(current_user_id)}, {"user_id": current_user_id}, {"user_id": user_email}]}

    posts = list(current_app.mongo.posts.find(query))

    # 🔥 récupérer interactions de SES posts seulement
    post_ids = [str(post["_id"]) for post in posts]

    interactions = list(current_app.mongo.interactions.find({
        "post_id": {"$in": post_ids}
    }))

    # 🔹 Map post_id → interactions
    post_stats = defaultdict(lambda: {"likes": 0, "comments": 0, "shares": 0})

    for inter in interactions:
        post_id = str(inter["post_id"])
        t = inter["type"]

        if t == "like":
            post_stats[post_id]["likes"] += 1
        elif t == "comment":
            post_stats[post_id]["comments"] += 1
        elif t == "share":
            post_stats[post_id]["shares"] += 1

    enriched_posts = []

    for post in posts:
        pid = str(post["_id"])

        stats = post_stats.get(pid, {"likes": 0, "comments": 0, "shares": 0})
        total = stats["likes"] + stats["comments"] + stats["shares"]

        if total > 0:
            enriched_posts.append({
                "_id": pid,
                "content": post.get("content", ""),
                "createdAt": post.get("created_at", post.get("schedule_date")),  # ✅ Use created_at first, fallback to schedule_date
                "scheduleDate": post.get("schedule_date"),
                "platforms": post.get("platforms", {}),
                "engagement": stats,
                "totalEngagement": total
            })

    return jsonify(enriched_posts)