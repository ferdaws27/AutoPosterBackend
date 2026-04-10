from flask import Blueprint, current_app, jsonify
from datetime import datetime, timedelta
import random
import re

test_bp = Blueprint("test", __name__)

COMMENTS = [
    "Super post !",
    "Très intéressant !",
    "J'adore !",
    "Bien dit !",
    "Merci pour le partage !",
    "lol",
    "parfaitement d'accord !",
    "Très utile, merci !",
]

# -------------------------------
# PARSE DATE
# -------------------------------
def parse_schedule_date(schedule_date):
    if not schedule_date:
        return None

    if isinstance(schedule_date, datetime):
        return schedule_date.replace(tzinfo=None)

    if isinstance(schedule_date, str):
        s = schedule_date.strip()

        # YYYY-MM-DD (le plus courant)
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            pass

        # ISO avec Z ou timezone offset
        try:
            s_clean = re.sub(r'Z$', '', s)
            s_clean = re.sub(r'\+\d{2}:\d{2}$', '', s_clean).strip()
            return datetime.fromisoformat(s_clean)
        except ValueError:
            pass

        # Regex fallback : extraire YYYY-MM-DD dans n'importe quel string
        match = re.search(r'(\d{4}-\d{2}-\d{2})', s)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d")
            except ValueError:
                pass

    return None


# -------------------------------
# GENERATE INTERACTIONS POUR 1 POST
# -------------------------------
def _generate_for_post(post_id_str, schedule_date, now):
    delta_seconds = int((now - schedule_date).total_seconds())
    followers_count = random.randint(1000, 6000)
    audience = [f"follower_{i}" for i in range(followers_count)]
    sample = random.sample(audience, k=min(300, len(audience)))

    interactions = []

    for user_id in sample:
        prob = random.random()
        random_seconds = random.randint(0, max(delta_seconds, 1))
        interaction_time = schedule_date + timedelta(seconds=random_seconds)

        if prob < 0.6:
            interaction = {"type": "like"}
        elif prob < 0.8:
            interaction = {"type": "comment", "content": random.choice(COMMENTS)}
        elif prob < 0.9:
            interaction = {"type": "share"}
        else:
            continue  # 10% ne font rien

        interaction.update({
            "post_id": post_id_str,
            "user_id": user_id,
            "created_at": interaction_time
        })
        interactions.append(interaction)

    # Garantir au moins 1 interaction
    if not interactions:
        interactions.append({
            "post_id": post_id_str,
            "user_id": "auto_system",
            "type": "like",
            "created_at": schedule_date
        })

    return interactions


# -------------------------------
# ROUTE 1 : RESET + GENERATE
# Supprime tout puis regenère pour
# tous les posts dont date <= now
# APPELER CETTE ROUTE EN PREMIER
# -------------------------------
@test_bp.route("/reset-and-generate")
def reset_and_generate():
    now = datetime.utcnow()
    posts = list(current_app.mongo.posts.find())

    # Supprimer toutes les interactions existantes
    deleted = current_app.mongo.interactions.delete_many({})

    total_interactions = 0
    processed = []
    skipped = []

    for post in posts:
        raw_date = post.get("schedule_date")
        schedule_date = parse_schedule_date(raw_date)
        post_id_str = str(post["_id"])

        print(f"[RESET-GEN] {post_id_str} | raw={raw_date!r} | parsed={schedule_date}")

        if schedule_date is None:
            skipped.append({"post_id": post_id_str, "reason": "no_date"})
            continue

        if schedule_date > now:
            skipped.append({
                "post_id": post_id_str,
                "reason": "future",
                "schedule_date": schedule_date.isoformat()
            })
            continue

        interactions = _generate_for_post(post_id_str, schedule_date, now)
        current_app.mongo.interactions.insert_many(interactions)
        total_interactions += len(interactions)
        processed.append({
            "post_id": post_id_str,
            "content_preview": post.get("content", "")[:40],
            "interactions_inserted": len(interactions)
        })

    return jsonify({
        "message": "Reset + génération terminée",
        "now_utc": now.isoformat(),
        "interactions_deleted": deleted.deleted_count,
        "total_interactions_created": total_interactions,
        "posts_processed": processed,
        "posts_skipped": skipped
    })


# -------------------------------
# ROUTE 2 : GENERATE ONLY
# Ajoute seulement pour les posts
# sans interactions existantes
# -------------------------------
@test_bp.route("/generate-realistic-interactions")
def generate_realistic_interactions():
    now = datetime.utcnow()
    posts = list(current_app.mongo.posts.find())

    total_interactions = 0
    processed = []
    skipped = []

    for post in posts:
        raw_date = post.get("schedule_date")
        schedule_date = parse_schedule_date(raw_date)
        post_id_str = str(post["_id"])

        print(f"[GEN] {post_id_str} | raw={raw_date!r} | parsed={schedule_date}")

        if schedule_date is None:
            skipped.append({"post_id": post_id_str, "reason": "no_date"})
            continue

        if schedule_date > now:
            skipped.append({
                "post_id": post_id_str,
                "reason": "future",
                "schedule_date": schedule_date.isoformat()
            })
            continue

        # Skip si interactions déjà présentes
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing > 0:
            skipped.append({
                "post_id": post_id_str,
                "reason": "already_has_interactions",
                "count": existing
            })
            continue

        interactions = _generate_for_post(post_id_str, schedule_date, now)
        current_app.mongo.interactions.insert_many(interactions)
        total_interactions += len(interactions)
        processed.append({
            "post_id": post_id_str,
            "content_preview": post.get("content", "")[:40],
            "interactions_inserted": len(interactions)
        })

    return jsonify({
        "message": "Génération terminée",
        "now_utc": now.isoformat(),
        "total_interactions_created": total_interactions,
        "posts_processed": processed,
        "posts_skipped": skipped
    })


# -------------------------------
# ROUTE 3 : POSTS WITH INTERACTIONS
# -------------------------------
@test_bp.route("/posts-with-interactions")
def posts_with_interactions():
    posts = list(current_app.mongo.posts.find())
    result = []

    for post in posts:
        post_id_str = str(post["_id"])

        interactions = list(
            current_app.mongo.interactions.find({"post_id": post_id_str})
        )

        likes    = sum(1 for i in interactions if i["type"] == "like")
        comments = sum(1 for i in interactions if i["type"] == "comment")
        shares   = sum(1 for i in interactions if i["type"] == "share")

        for i in interactions:
            i["_id"]     = str(i["_id"])
            i["post_id"] = str(i["post_id"])
            if isinstance(i.get("created_at"), datetime):
                i["created_at"] = i["created_at"].isoformat()

        result.append({
            "post_id":              post_id_str,
            "content":              post.get("content", "")[:80],
            "schedule_date":        post.get("schedule_date"),
            "total_interactions":   len(interactions),
            "likes":                likes,
            "comments":             comments,
            "shares":               shares,
            "interactions_details": interactions
        })

    return jsonify({"posts": result})