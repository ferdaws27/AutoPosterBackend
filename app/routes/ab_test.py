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


_PROMPT_BASE = (
    "You are a top-performing social media ghostwriter. "
    "Your posts sound like a real person sharing genuine thoughts — never like AI-generated content. "
    "Rules you MUST follow:\n"
    "- Write like a human: use natural rhythm, sentence fragments, and real talk. No corporate jargon.\n"
    "- Open with a hook that stops the scroll (bold claim, surprising stat, hot take, or vulnerable admission).\n"
    "- Use white space and line breaks — no walls of text.\n"
    "- End with something that makes people want to reply, not just like.\n"
    "- NEVER use filler phrases like 'In today's world', 'Let me share', 'Here's the thing', or 'It's important to note'.\n"
    "- NEVER start with 'I' — vary your opening.\n"
    "- Avoid hashtags unless explicitly asked.\n"
    "- Keep it authentic: imperfect, opinionated, and specific. Generic = invisible.\n\n"
)

VARIATION_PROMPTS = {
    "tone": (
        _PROMPT_BASE
        + "Rewrite the following post in a {style} tone.\n"
        "Keep the core message but make it sound like something a real person would actually post — "
        "not a press release, not a motivational poster.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post, nothing else.",
        [
            "confident and authoritative — like a respected industry insider sharing hard-won insights",
            "casual and relatable — like texting a smart friend who happens to be an expert",
        ],
    ),
    "structure": (
        _PROMPT_BASE
        + "Rewrite the following post using a {style} structure.\n"
        "The post must feel alive and engaging — the kind of post people screenshot and share.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post, nothing else.",
        [
            "storytelling narrative — start with a vivid moment or experience, build tension, land a clear takeaway",
            "punchy list format — bold opening line, then 3-5 rapid-fire points with line breaks, close with a strong one-liner",
        ],
    ),
    "cta": (
        _PROMPT_BASE
        + "Rewrite the following post and end it with a {style}.\n"
        "The ending should feel natural, not forced — like you actually want to hear from people.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post, nothing else.",
        [
            "genuine question that sparks debate — something people will have different opinions on and feel compelled to answer",
            "bold call-to-action — tell the reader exactly what to do next, make it feel urgent and valuable",
        ],
    ),
    "length": (
        _PROMPT_BASE
        + "Rewrite the following post in a {style} format.\n"
        "Every single word must earn its place — no padding, no fluff.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post, nothing else.",
        [
            "short and punchy (2-3 sentences max) — hit hard and fast like a mic-drop moment. Make every word count",
            "detailed deep-dive (3-5 short paragraphs) — use specific examples, numbers, or mini-stories to back up the point. Still conversational, not an essay",
        ],
    ),
    "emoji": (
        _PROMPT_BASE
        + "Rewrite the following post {style}.\n"
        "The post should still feel organic and human regardless of emoji usage.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post, nothing else.",
        [
            "with strategic emojis that add personality and visual breaks — use them to emphasize points, not decorate randomly",
            "with zero emojis — rely purely on sharp writing, strong verbs, and rhythm to carry the energy",
        ],
    ),
}


def _call_ai(app, prompt, max_tokens=500):
    """Call OpenRouter AI and return the generated text."""
    api_key = app.config["OPENROUTER_API_KEY"]
    model = app.config["OPENROUTER_MODEL"]
    lang_enforcement = (
        "## ABSOLUTE HIGHEST-PRIORITY RULE — LANGUAGE:\n"
        "Detect the language of the user's content below.\n"
        "Your ENTIRE response MUST be written in that SAME language.\n"
        "- French input → respond 100% in French\n"
        "- English input → respond 100% in English\n"
        "- Arabic input → respond 100% in Arabic\n"
        "NEVER mix languages. NEVER switch to English.\n\n"
    )
    system_msg = lang_enforcement + (
        "You are a viral social media writer. You write like a real human — opinionated, "
        "specific, and conversational. You never sound like AI. Your posts get high engagement "
        "because they feel authentic, have strong hooks, and make people want to respond. "
        "Output ONLY the post text, no labels, no quotes, no commentary."
    )
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
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.75,
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


# ───────── A/B TEST SETTINGS ─────────
SETTINGS_COLLECTION = "ab_test_settings"


def _settings_col():
    return current_app.mongo[SETTINGS_COLLECTION]


@ab_test_bp.route("/settings", methods=["GET", "PUT"])
@jwt_required()
def ab_settings():
    user_id = get_jwt_identity()

    if request.method == "GET":
        doc = _settings_col().find_one({"user_id": user_id})
        if not doc:
            return jsonify({
                "default_duration": "24h",
                "min_sample_size": 1000,
                "statistical_significance": 95,
                "notify_complete": True,
                "daily_progress": True,
                "weekly_summary": False,
                "auto_apply_winner": True,
            }), 200
        doc["_id"] = str(doc["_id"])
        return jsonify(doc), 200

    # PUT
    data = request.get_json() or {}
    allowed = ["default_duration", "min_sample_size", "statistical_significance",
               "notify_complete", "daily_progress", "weekly_summary", "auto_apply_winner"]
    update = {k: data[k] for k in allowed if k in data}
    update["user_id"] = user_id

    _settings_col().update_one(
        {"user_id": user_id},
        {"$set": update},
        upsert=True,
    )
    return jsonify({"message": "Settings saved"}), 200


# ───────── RUN (simulate engagement) ─────────
@ab_test_bp.route("/<test_id>/run", methods=["POST"])
@jwt_required()
def run_ab_test(test_id):
    user_id = get_jwt_identity()
    doc = _col().find_one({"_id": ObjectId(test_id), "user_id": user_id})
    if not doc:
        return jsonify({"message": "Test not found"}), 404
    if doc["status"] not in ("ready", "paused"):
        return jsonify({"message": "Test is not in a runnable state"}), 400

    # Mark as running immediately
    _col().update_one(
        {"_id": ObjectId(test_id)},
        {"$set": {"status": "running", "started_at": datetime.utcnow().isoformat()}},
    )

    # Run simulation in background so the response returns fast
    app = current_app._get_current_object()
    threading.Thread(
        target=_simulate_engagement,
        args=(app, test_id),
        daemon=True,
    ).start()

    return jsonify({"message": "Simulation started"}), 200


DURATION_ROUNDS = {
    "24h": 8,
    "48h": 16,
    "72h": 24,
    "1w": 56,
}

TICK_SECONDS = 60  # 1 minute between each round


def _simulate_engagement(app, test_id):
    """Incrementally add random engagement every 3 minutes until duration ends."""
    with app.app_context():
        try:
            _col_bg = app.mongo[COLLECTION]
            doc = _col_bg.find_one({"_id": ObjectId(test_id)})
            duration = doc.get("duration", "24h") if doc else "24h"
            total_rounds = DURATION_ROUNDS.get(duration, 8)

            # Pick which side gets a boost (stays consistent across all rounds)
            boosted_side = random.choice(["A", "B"])
            boost = random.uniform(1.15, 1.50)

            # Running totals
            a_likes = 0
            a_comments = 0
            a_shares = 0
            b_likes = 0
            b_comments = 0
            b_shares = 0

            for round_num in range(1, total_rounds + 1):
                # Check if the test was deleted or stopped
                current = _col_bg.find_one({"_id": ObjectId(test_id)})
                if not current or current.get("status") != "running":
                    return

                # Random new interactions this round
                new_likes = random.randint(5, 60)
                new_comments = random.randint(1, 15)
                new_shares = random.randint(0, 8)

                # Apply boost to the favored side, natural variance to the other
                variance_a = random.uniform(0.7, 1.3)
                variance_b = random.uniform(0.7, 1.3)

                if boosted_side == "A":
                    a_likes += int(new_likes * boost * variance_a)
                    a_comments += int(new_comments * boost * variance_a)
                    a_shares += int(new_shares * boost * variance_a)
                    b_likes += int(new_likes * variance_b)
                    b_comments += int(new_comments * variance_b)
                    b_shares += int(new_shares * variance_b)
                else:
                    a_likes += int(new_likes * variance_a)
                    a_comments += int(new_comments * variance_a)
                    a_shares += int(new_shares * variance_a)
                    b_likes += int(new_likes * boost * variance_b)
                    b_comments += int(new_comments * boost * variance_b)
                    b_shares += int(new_shares * boost * variance_b)

                # Engagement rate
                a_score = a_likes + a_comments * 3 + a_shares * 5
                b_score = b_likes + b_comments * 3 + b_shares * 5
                total_reach = max(a_score + b_score, 1)
                a_rate = round(a_score / total_reach * 100, 1)
                b_rate = round(b_score / total_reach * 100, 1)

                is_last_round = round_num == total_rounds

                # Determine current leader / final winner
                winner = "A" if a_score > b_score else "B"
                diff = abs(a_score - b_score)
                loser_score = min(a_score, b_score)
                improvement_pct = round(diff / max(loser_score, 1) * 100)
                improvement = f"+{improvement_pct}%"

                total_impressions = (a_likes + b_likes) * 12 + (a_comments + b_comments) * 25 + (a_shares + b_shares) * 40

                # Round snapshot for time-series analytics
                round_snapshot = {
                    "round": round_num,
                    "timestamp": datetime.utcnow().isoformat(),
                    "a": {"likes": a_likes, "comments": a_comments, "shares": a_shares, "score": a_score, "rate": a_rate},
                    "b": {"likes": b_likes, "comments": b_comments, "shares": b_shares, "score": b_score, "rate": b_rate},
                    "delta": abs(a_score - b_score),
                    "improvement_pct": improvement_pct,
                }

                update_fields = {
                    "variant_a.likes": a_likes,
                    "variant_a.comments": a_comments,
                    "variant_a.shares": a_shares,
                    "variant_a.engagement_rate": a_rate,
                    "variant_b.likes": b_likes,
                    "variant_b.comments": b_comments,
                    "variant_b.shares": b_shares,
                    "variant_b.engagement_rate": b_rate,
                    "current_round": round_num,
                    "total_rounds": total_rounds,
                    "total_impressions": total_impressions,
                }

                if is_last_round:
                    update_fields["status"] = "completed"
                    update_fields["winner"] = winner
                    update_fields["improvement"] = improvement
                    update_fields["completed_at"] = datetime.utcnow().isoformat()

                _col_bg.update_one(
                    {"_id": ObjectId(test_id)},
                    {"$set": update_fields, "$push": {"rounds_history": round_snapshot}},
                )

                if not is_last_round:
                    time.sleep(TICK_SECONDS)

        except Exception as e:
            print(f"AB simulation error: {e}")
            app.mongo[COLLECTION].update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {"status": "error"}},
            )


# ───────── PAUSE / STOP ─────────
@ab_test_bp.route("/<test_id>/pause", methods=["POST"])
@jwt_required()
def pause_ab_test(test_id):
    user_id = get_jwt_identity()
    doc = _col().find_one({"_id": ObjectId(test_id), "user_id": user_id})
    if not doc:
        return jsonify({"message": "Test not found"}), 404
    if doc["status"] != "running":
        return jsonify({"message": "Test is not running"}), 400

    a_score = (
        (doc["variant_a"].get("likes", 0))
        + (doc["variant_a"].get("comments", 0)) * 3
        + (doc["variant_a"].get("shares", 0)) * 5
    )
    b_score = (
        (doc["variant_b"].get("likes", 0))
        + (doc["variant_b"].get("comments", 0)) * 3
        + (doc["variant_b"].get("shares", 0)) * 5
    )
    winner = "A" if a_score > b_score else "B"
    diff = abs(a_score - b_score)
    loser_score = min(a_score, b_score)
    improvement_pct = round(diff / max(loser_score, 1) * 100)

    _col().update_one(
        {"_id": ObjectId(test_id)},
        {
            "$set": {
                "status": "completed",
                "winner": winner,
                "improvement": f"+{improvement_pct}%",
                "completed_at": datetime.utcnow().isoformat(),
            }
        },
    )
    return jsonify({"message": "Test stopped and winner declared"}), 200


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


# ───────── AI WRITING ASSISTANT ─────────
AI_ASSIST_PROMPTS = {
    "generate": (
        "You are a viral social media ghostwriter. "
        "Generate an engaging social media post about the following topic. "
        "Write like a real human — opinionated, specific, conversational. Never sound like AI. "
        "Use a strong hook, natural rhythm, and make people want to engage.\n"
        "- NO filler phrases. NO 'In today's world'. NO starting with 'I'.\n"
        "- Use line breaks and white space.\n"
        "- Be specific and authentic.\n\n"
        "Topic: \"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the post text."
    ),
    "improve": (
        "You are a viral social media ghostwriter. "
        "Improve the following post to make it more engaging, authentic, and scroll-stopping. "
        "Fix weak openings, remove filler, sharpen the message, and add a better hook. "
        "Keep the same core message but make it sound like something that would go viral.\n"
        "- NO corporate jargon. NO generic advice.\n"
        "- Add line breaks for readability.\n"
        "- Make every word earn its place.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the improved post."
    ),
    "hook": (
        "You are a viral social media ghostwriter. "
        "Rewrite the following post with a much stronger opening hook. "
        "The first line should stop people mid-scroll — use a bold claim, surprising stat, "
        "hot take, or vulnerable admission. Keep the rest of the message intact but tighten it.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post."
    ),
    "shorter": (
        "You are a viral social media ghostwriter. "
        "Condense the following post into 2-3 punchy sentences maximum. "
        "Keep the strongest point, cut everything else. Make it a mic-drop moment.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the shortened post."
    ),
    "engaging": (
        "You are a viral social media ghostwriter. "
        "Rewrite the following post to maximize engagement and replies. "
        "Add a polarizing take or a question that people can't resist answering. "
        "Make it feel like a real conversation starter, not a broadcast.\n\n"
        "Original post:\n\"\"\"\n{content}\n\"\"\"\n\n"
        "Return ONLY the rewritten post."
    ),
}


@ab_test_bp.route("/ai-assist", methods=["POST"])
@jwt_required()
def ai_assist():
    """
    AI Writing Assistant — helps users write/improve post content.
    Expects JSON: { "content": "...", "action": "generate|improve|hook|shorter|engaging" }
    """
    data = request.get_json()
    content = (data.get("content") or "").strip()
    action = data.get("action", "improve")

    if not content:
        return jsonify({"message": "content is required"}), 400

    if action not in AI_ASSIST_PROMPTS:
        return jsonify({"message": f"Invalid action: {action}"}), 400

    try:
        prompt = AI_ASSIST_PROMPTS[action].format(content=content)
        result = _call_ai(current_app._get_current_object(), prompt, max_tokens=400)
        return jsonify({"result": result}), 200
    except Exception as e:
        return jsonify({"message": f"AI error: {str(e)[:200]}"}), 500


# ───────── AI TEST ANALYSIS ─────────
@ab_test_bp.route("/<test_id>/analysis", methods=["GET"])
@jwt_required()
def get_test_analysis(test_id):
    """AI analyzes the current A/B test and gives insights on both variants."""
    user_id = get_jwt_identity()
    doc = _col().find_one({"_id": ObjectId(test_id), "user_id": user_id})
    if not doc:
        return jsonify({"message": "Test not found"}), 404

    va = doc.get("variant_a", {})
    vb = doc.get("variant_b", {})

    prompt = (
        "You are an expert social media strategist analyzing an A/B test.\n\n"
        f"VARIANT A — \"{va.get('label', 'Variant A')}\":\n"
        f"Content: \"\"\"{va.get('content', '')}\"\"\"\n"
        f"Likes: {va.get('likes', 0)} | Comments: {va.get('comments', 0)} | "
        f"Shares: {va.get('shares', 0)} | Engagement: {va.get('engagement_rate', 0)}%\n\n"
        f"VARIANT B — \"{vb.get('label', 'Variant B')}\":\n"
        f"Content: \"\"\"{vb.get('content', '')}\"\"\"\n"
        f"Likes: {vb.get('likes', 0)} | Comments: {vb.get('comments', 0)} | "
        f"Shares: {vb.get('shares', 0)} | Engagement: {vb.get('engagement_rate', 0)}%\n\n"
        f"Variation type: {doc.get('variation_type', 'tone')}\n"
        f"Platforms: {', '.join(doc.get('platforms', []))}\n\n"
        "Provide a concise analysis in this exact JSON format (no markdown, just raw JSON):\n"
        "{\n"
        '  "summary": "1-2 sentence overview of how the test is going",\n'
        '  "variant_a_analysis": "What makes variant A strong or weak (2-3 sentences)",\n'
        '  "variant_b_analysis": "What makes variant B strong or weak (2-3 sentences)",\n'
        '  "recommendation": "What should the user do next (1-2 sentences)",\n'
        '  "hook_quality_a": 1-10,\n'
        '  "hook_quality_b": 1-10,\n'
        '  "readability_a": 1-10,\n'
        '  "readability_b": 1-10,\n'
        '  "engagement_potential_a": 1-10,\n'
        '  "engagement_potential_b": 1-10\n'
        "}"
    )

    try:
        raw = _call_ai(current_app._get_current_object(), prompt, max_tokens=500)
        # Try to parse as JSON, fallback to raw text
        try:
            # Strip potential markdown code fences
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            analysis = json.loads(cleaned.strip())
        except (json.JSONDecodeError, IndexError):
            analysis = {"summary": raw}

        return jsonify(analysis), 200
    except Exception as e:
        return jsonify({"message": f"AI error: {str(e)[:200]}"}), 500


# ───────── AI LEARNING INSIGHTS ─────────
@ab_test_bp.route("/insights", methods=["GET"])
@jwt_required()
def get_insights():
    """AI analyzes all completed tests to extract Tone Preference, Optimal Timing, and Content Length insights."""
    user_id = get_jwt_identity()
    completed = list(
        _col().find({"user_id": user_id, "status": "completed"}).sort("completed_at", -1).limit(20)
    )

    if len(completed) < 1:
        return jsonify({"message": "Need at least 1 completed test"}), 400

    # Build summary of all tests for AI
    test_summaries = []
    for i, t in enumerate(completed, 1):
        va = t.get("variant_a", {})
        vb = t.get("variant_b", {})
        winner_label = va.get("label", "A") if t.get("winner") == "A" else vb.get("label", "B")
        loser_label = vb.get("label", "B") if t.get("winner") == "A" else va.get("label", "A")
        winner_v = va if t.get("winner") == "A" else vb
        loser_v = vb if t.get("winner") == "A" else va

        test_summaries.append(
            f"Test {i}: Type={t.get('variation_type','unknown')}, "
            f"Winner=\"{winner_label}\" (likes={winner_v.get('likes',0)}, "
            f"comments={winner_v.get('comments',0)}, shares={winner_v.get('shares',0)}, "
            f"rate={winner_v.get('engagement_rate',0)}%), "
            f"Loser=\"{loser_label}\" (likes={loser_v.get('likes',0)}, "
            f"comments={loser_v.get('comments',0)}, shares={loser_v.get('shares',0)}, "
            f"rate={loser_v.get('engagement_rate',0)}%), "
            f"Improvement={t.get('improvement','N/A')}, "
            f"Platforms={','.join(t.get('platforms',[]))}, "
            f"Duration={t.get('duration','24h')}, "
            f"Winner content snippet: \"{winner_v.get('content','')[:150]}...\""
        )

    tests_data = "\n".join(test_summaries)

    prompt = (
        "You are an expert social media data analyst. Analyze these A/B test results and extract actionable insights.\n\n"
        f"COMPLETED TESTS ({len(completed)} total):\n{tests_data}\n\n"
        "Based on the patterns in winners vs losers, provide insights in this exact JSON format "
        "(no markdown, raw JSON only):\n"
        "{\n"
        '  "tone_preference": {\n'
        '    "winning_tone": "The tone/style that wins most often (e.g. Professional, Casual, Story, Direct)",\n'
        '    "confidence": 1-100,\n'
        '    "description": "2-3 sentences explaining why this tone works better based on the data",\n'
        '    "tip": "One actionable tip for the user"\n'
        "  },\n"
        '  "content_length": {\n'
        '    "optimal": "Short/Medium/Long — which length performs best",\n'
        '    "confidence": 1-100,\n'
        '    "description": "2-3 sentences about what content length patterns you see in winners",\n'
        '    "tip": "One actionable tip"\n'
        "  },\n"
        '  "optimal_timing": {\n'
        '    "best_duration": "Which test duration gives clearest results (24h, 48h, etc)",\n'
        '    "confidence": 1-100,\n'
        '    "description": "2-3 sentences about timing patterns and engagement velocity",\n'
        '    "tip": "One actionable tip"\n'
        "  },\n"
        '  "overall_recommendation": "A 2-3 sentence overall recommendation combining all insights"\n'
        "}"
    )

    try:
        raw = _call_ai(current_app._get_current_object(), prompt, max_tokens=500)
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            insights = json.loads(cleaned.strip())
        except (json.JSONDecodeError, IndexError):
            insights = {"overall_recommendation": raw}

        return jsonify(insights), 200
    except Exception as e:
        return jsonify({"message": f"AI error: {str(e)[:200]}"}), 500


