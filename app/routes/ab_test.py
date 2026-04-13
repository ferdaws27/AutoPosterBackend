from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson.objectid import ObjectId
from datetime import datetime
import random
import threading
import time
import requests as http_requests
import json

ab_test_bp = Blueprint("ab_test_bp", __name__, url_prefix="/api/ab-tests")

COLLECTION = "ab_tests"


def _col():
    return current_app.mongo[COLLECTION]


VARIATION_PROMPTS = {
    "tone": (
        "Rewrite the following post in a {style} tone. Keep the same core message.\n\nOriginal post:\n\"\"\"\n{content}\n\"\"\"\n\nReturn ONLY the rewritten post, no comments.",
        ["professional and polished", "casual and conversational"],
    ),
    "structure": (
        "Rewrite the following post using a {style} structure. Keep the same core message.\n\nOriginal post:\n\"\"\"\n{content}\n\"\"\"\n\nReturn ONLY the rewritten post, no comments.",
        ["storytelling narrative", "direct and concise bullet-point"],
    ),
    "cta": (
        "Rewrite the following post ending with a {style}. Keep the same core message.\n\nOriginal post:\n\"\"\"\n{content}\n\"\"\"\n\nReturn ONLY the rewritten post, no comments.",
        ["thought-provoking question to the audience", "strong call-to-action statement"],
    ),
    "length": (
        "Rewrite the following post in a {style} format. Keep the same core message.\n\nOriginal post:\n\"\"\"\n{content}\n\"\"\"\n\nReturn ONLY the rewritten post, no comments.",
        ["short and punchy (2-3 sentences max)", "detailed and in-depth (multiple paragraphs)"],
    ),
    "emoji": (
        "Rewrite the following post {style}. Keep the same core message.\n\nOriginal post:\n\"\"\"\n{content}\n\"\"\"\n\nReturn ONLY the rewritten post, no comments.",
        ["with relevant emojis sprinkled throughout", "without any emojis, purely text-based"],
    ),
}


def _call_ai(app, prompt, max_tokens=500):
    """Call OpenRouter AI and return the generated text."""
    api_key = app.config["OPENROUTER_API_KEY"]
    model = app.config["OPENROUTER_MODEL"]
    response = http_requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": app.config.get("BACKEND_URL", "http://127.0.0.1:5000"),
            "X-Title": "AutoPoster AB Tester",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    if response.status_code != 200:
        raise Exception(f"OpenRouter error {response.status_code}: {response.text[:200]}")
    return response.json()["choices"][0]["message"]["content"].strip()


# ───────── CREATE ─────────
@ab_test_bp.route("/", methods=["POST"])
@jwt_required()
def create_ab_test():
    """
    Expects JSON:
    {
      "name": "optional label",
      "content": "User's post idea / text",
      "platforms": ["twitter","linkedin"],
      "variation_type": "tone",
      "duration": "24h"
    }
    AI generates two variations from the content.
    """
    data = request.get_json()
    content = (data.get("content") or "").strip()

    if not content:
        return jsonify({"message": "content is required"}), 400

    user_id = get_jwt_identity()
    doc = {
        "user_id": user_id,
        "name": data.get("name") or "Untitled Test",
        "original_content": content,
        "variation_type": data.get("variation_type", "tone"),
        "platforms": data.get("platforms", ["twitter", "linkedin"]),
        "duration": data.get("duration", "24h"),
        "status": "generating",
        "variant_a": {
            "label": "Variant A",
            "content": "",
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "engagement_rate": 0,
        },
        "variant_b": {
            "label": "Variant B",
            "content": "",
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "engagement_rate": 0,
        },
        "winner": None,
        "improvement": None,
        "created_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }
    result = _col().insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    # Generate AI variations in background
    app = current_app._get_current_object()
    threading.Thread(
        target=_generate_variants,
        args=(app, str(result.inserted_id), content, doc["variation_type"]),
        daemon=True,
    ).start()

    return jsonify(doc), 201


def _generate_variants(app, test_id, content, variation_type):
    """Background: call AI twice to produce two post variations."""
    with app.app_context():
        try:
            template, styles = VARIATION_PROMPTS.get(
                variation_type, VARIATION_PROMPTS["tone"]
            )

            prompt_a = template.format(content=content, style=styles[0])
            prompt_b = template.format(content=content, style=styles[1])

            variant_a_text = _call_ai(app, prompt_a)
            variant_b_text = _call_ai(app, prompt_b)

            labels = {
                "tone": ["Professional", "Casual"],
                "structure": ["Storytelling", "Direct"],
                "cta": ["Question CTA", "Statement CTA"],
                "length": ["Short & Punchy", "Detailed"],
                "emoji": ["With Emojis", "Text Only"],
            }
            label_pair = labels.get(variation_type, ["Variant A", "Variant B"])

            _col_bg = app.mongo[COLLECTION]
            _col_bg.update_one(
                {"_id": ObjectId(test_id)},
                {
                    "$set": {
                        "status": "ready",
                        "variant_a.content": variant_a_text,
                        "variant_a.label": label_pair[0],
                        "variant_b.content": variant_b_text,
                        "variant_b.label": label_pair[1],
                    }
                },
            )
        except Exception as e:
            print(f"AB variant generation error: {e}")
            app.mongo[COLLECTION].update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {"status": "error"}},
            )


# ───────── LIST ─────────
@ab_test_bp.route("/", methods=["GET"])
@jwt_required()
def list_ab_tests():
    user_id = get_jwt_identity()
    tests = list(
        _col().find({"user_id": user_id}).sort("created_at", -1)
    )
    for t in tests:
        t["_id"] = str(t["_id"])
    return jsonify(tests), 200


# ───────── RUN (simulate engagement) ─────────
@ab_test_bp.route("/<test_id>/run", methods=["POST"])
@jwt_required()
def run_ab_test(test_id):
    user_id = get_jwt_identity()
    doc = _col().find_one({"_id": ObjectId(test_id), "user_id": user_id})
    if not doc:
        return jsonify({"message": "Test not found"}), 404
    if doc["status"] not in ("ready",):
        return jsonify({"message": "Test is not in a runnable state"}), 400

    # Mark as running immediately
    _col().update_one(
        {"_id": ObjectId(test_id)},
        {"$set": {"status": "running"}},
    )

    # Run simulation in background so the response returns fast
    app = current_app._get_current_object()
    threading.Thread(
        target=_simulate_engagement,
        args=(app, test_id),
        daemon=True,
    ).start()

    return jsonify({"message": "Simulation started"}), 200


def _simulate_engagement(app, test_id):
    """Generate fake engagement numbers with a clear gap, pick winner."""
    with app.app_context():
        try:
            # Small delay to make the "running" state visible on the UI
            time.sleep(3)

            # Base engagement ranges (likes, comments, shares)
            base_likes = random.randint(80, 500)
            base_comments = random.randint(10, 120)
            base_shares = random.randint(5, 60)

            # Random multiplier so one variant clearly beats the other
            boost = random.uniform(1.15, 1.60)  # 15 % – 60 % gap
            boosted_side = random.choice(["A", "B"])

            if boosted_side == "A":
                a_likes = int(base_likes * boost)
                a_comments = int(base_comments * boost)
                a_shares = int(base_shares * boost)
                b_likes = base_likes
                b_comments = base_comments
                b_shares = base_shares
            else:
                a_likes = base_likes
                a_comments = base_comments
                a_shares = base_shares
                b_likes = int(base_likes * boost)
                b_comments = int(base_comments * boost)
                b_shares = int(base_shares * boost)

            # Engagement rate = (likes + comments*3 + shares*5) / base * 100
            a_score = a_likes + a_comments * 3 + a_shares * 5
            b_score = b_likes + b_comments * 3 + b_shares * 5
            total_reach = max(a_score + b_score, 1)
            a_rate = round(a_score / total_reach * 100, 1)
            b_rate = round(b_score / total_reach * 100, 1)

            # Determine winner
            winner = "A" if a_score > b_score else "B"
            diff = abs(a_score - b_score)
            loser_score = min(a_score, b_score)
            improvement_pct = round(diff / max(loser_score, 1) * 100)
            improvement = f"+{improvement_pct}%"

            _col_bg = app.mongo[COLLECTION]
            _col_bg.update_one(
                {"_id": ObjectId(test_id)},
                {
                    "$set": {
                        "status": "completed",
                        "variant_a.likes": a_likes,
                        "variant_a.comments": a_comments,
                        "variant_a.shares": a_shares,
                        "variant_a.engagement_rate": a_rate,
                        "variant_b.likes": b_likes,
                        "variant_b.comments": b_comments,
                        "variant_b.shares": b_shares,
                        "variant_b.engagement_rate": b_rate,
                        "winner": winner,
                        "improvement": improvement,
                        "completed_at": datetime.utcnow().isoformat(),
                    }
                },
            )
        except Exception as e:
            print(f"AB simulation error: {e}")
            app.mongo[COLLECTION].update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {"status": "error"}},
            )


# ───────── DELETE ─────────
@ab_test_bp.route("/<test_id>", methods=["DELETE"])
@jwt_required()
def delete_ab_test(test_id):
    user_id = get_jwt_identity()
    result = _col().delete_one({"_id": ObjectId(test_id), "user_id": user_id})
    if result.deleted_count == 0:
        return jsonify({"message": "Test not found"}), 404
    return jsonify({"message": "Deleted"}), 200


# ───────── STATS ─────────
@ab_test_bp.route("/stats", methods=["GET"])
@jwt_required()
def ab_stats():
    user_id = get_jwt_identity()
    tests = list(_col().find({"user_id": user_id}))

    total = len(tests)
    completed = [t for t in tests if t.get("status") == "completed"]
    active = [t for t in tests if t.get("status") in ("ready", "running", "generating")]

    improvements = []
    for t in completed:
        try:
            val = int((t.get("improvement") or "0").replace("+", "").replace("%", ""))
            improvements.append(val)
        except ValueError:
            pass

    avg_imp = round(sum(improvements) / len(improvements)) if improvements else 0
    wins = len([t for t in completed if t.get("winner")])
    win_rate = round(wins / len(completed) * 100) if completed else 0

    return jsonify({
        "total": total,
        "completed": len(completed),
        "active": len(active),
        "avg_improvement": f"+{avg_imp}%",
        "win_rate": f"{win_rate}%",
    }), 200
