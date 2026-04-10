from flask import Blueprint, current_app, jsonify
from collections import defaultdict
from flask_jwt_extended import jwt_required, get_jwt_identity

analytics_bp = Blueprint("analytics", __name__)

@analytics_bp.route("/analytics", methods=["GET"])
@jwt_required()
def get_analytics():

    # 🔥 récupérer user connecté
    current_user_id = get_jwt_identity()

    # 🔥 récupérer SEULEMENT ses posts
    posts = list(current_app.mongo.posts.find({
        "user_id": current_user_id
    }))

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
                "createdAt": post.get("schedule_date"),  # ✅ schedule_date utilisé par test_route.py
                "platforms": post.get("platforms", {}),
                "engagement": stats,
                "totalEngagement": total
            })

    return jsonify(enriched_posts)