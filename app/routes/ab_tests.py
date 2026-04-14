import json
import re
import threading
import time
import random
from datetime import datetime, timedelta

import requests
from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request

ab_tests_bp = Blueprint("ab_tests", __name__)


def _call_openrouter(prompt, system_msg="You are a social media A/B testing expert. Return strict JSON only.", max_tokens=1500):
    """Call OpenRouter API with proper error handling for credit limits."""
    api_key = current_app.config.get("OPENROUTER_API_KEY")
    model = current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not configured")

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": current_app.config.get("FRONTEND_URL", "http://localhost:5173"),
            "X-Title": "AutoPoster AB Tester",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )

    if resp.status_code == 402:
        raise CreditError("OpenRouter credits exhausted. Please recharge at https://openrouter.ai/settings/credits")

    if resp.status_code != 200:
        error_text = resp.text[:200]
        raise ValueError(f"OpenRouter API error ({resp.status_code}): {error_text}")

    data = resp.json()
    if not data.get("choices"):
        raise ValueError("OpenRouter returned no choices")

    content = data["choices"][0]["message"]["content"].strip()
    # Extract JSON
    if content.startswith("```"):
        content = re.sub(r"```(?:json)?", "", content).strip()
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start != -1 and brace_end != -1:
        content = content[brace_start:brace_end + 1]
    # Try array
    if content.startswith("["):
        bracket_end = content.rfind("]")
        if bracket_end != -1:
            content = content[:bracket_end + 1]

    return json.loads(content)


class CreditError(Exception):
    """Raised when OpenRouter credits are exhausted."""
    pass


# ─── GET all tests ───
@ab_tests_bp.route("/", methods=["GET"])
def get_tests():
    try:
        col = current_app.mongo["ab_tests"]
        tests = list(col.find().sort("created_at", -1).limit(50))
        for t in tests:
            t["_id"] = str(t["_id"])
        return jsonify(tests), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── GET stats ───
@ab_tests_bp.route("/stats", methods=["GET"])
def get_stats():
    try:
        col = current_app.mongo["ab_tests"]
        total = col.count_documents({})
        completed = col.count_documents({"status": "completed"})
        active = col.count_documents({"status": {"$in": ["running", "generating", "ready"]}})

        # Calculate average improvement from completed tests
        completed_tests = list(col.find({"status": "completed", "improvement": {"$exists": True}}))
        improvements = []
        for t in completed_tests:
            imp = t.get("improvement", "")
            if isinstance(imp, str):
                try:
                    improvements.append(float(imp.replace("%", "").replace("+", "")))
                except (ValueError, TypeError):
                    pass

        avg_imp = round(sum(improvements) / len(improvements), 1) if improvements else 0
        win_count = sum(1 for t in completed_tests if t.get("winner"))
        win_rate = round((win_count / len(completed_tests)) * 100) if completed_tests else 0

        return jsonify({
            "total": total,
            "completed": completed,
            "active": active,
            "avg_improvement": f"+{avg_imp}%" if avg_imp >= 0 else f"{avg_imp}%",
            "win_rate": f"{win_rate}%",
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── CREATE a new A/B test ───
@ab_tests_bp.route("/", methods=["POST"])
def create_test():
    try:
        data = request.get_json() or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"error": "Content is required"}), 400

        name = data.get("name") or "Untitled Test"
        variation_type = data.get("variation_type", "tone")
        platforms = data.get("platforms", ["twitter", "linkedin"])
        duration = data.get("duration", "24h")

        # Duration to rounds mapping
        duration_rounds = {"24h": 24, "48h": 48, "72h": 72, "1w": 168}
        total_rounds = duration_rounds.get(duration, 24)

        doc = {
            "name": name,
            "content": content,
            "variation_type": variation_type,
            "platforms": platforms,
            "duration": duration,
            "status": "generating",
            "total_rounds": total_rounds,
            "current_round": 0,
            "variant_a": None,
            "variant_b": None,
            "winner": None,
            "improvement": None,
            "total_impressions": 0,
            "rounds_history": [],
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
        }

        col = current_app.mongo["ab_tests"]
        result = col.insert_one(doc)
        test_id = str(result.inserted_id)

        # Generate variations in background
        app = current_app._get_current_object()
        thread = threading.Thread(target=_generate_variations, args=(app, test_id, content, variation_type, platforms))
        thread.daemon = True
        thread.start()

        doc["_id"] = test_id
        return jsonify(doc), 201

    except CreditError as e:
        return jsonify({"error": str(e)}), 402
    except Exception as e:
        current_app.logger.exception("Create AB test error")
        return jsonify({"error": str(e)}), 500


def _generate_variations(app, test_id, content, variation_type, platforms):
    """Background task to generate A/B variations using AI."""
    with app.app_context():
        col = app.mongo["ab_tests"]
        try:
            variation_prompts = {
                "tone": "Create two variations: Variant A should be professional and formal, Variant B should be casual and conversational.",
                "structure": "Create two variations: Variant A should use a storytelling structure, Variant B should be direct and structured with clear points.",
                "cta": "Create two variations: Variant A should end with a compelling question, Variant B should end with a bold statement or call-to-action.",
                "length": "Create two variations: Variant A should be concise and punchy (under 150 words), Variant B should be detailed and comprehensive.",
                "emoji": "Create two variations: Variant A should use strategic emojis, Variant B should be clean text without emojis.",
            }

            instruction = variation_prompts.get(variation_type, variation_prompts["tone"])
            platform_str = ", ".join(platforms)

            prompt = f"""Given this original post content:
---
{content[:1000]}
---

{instruction}

Both variants should be optimized for: {platform_str}
Both must preserve the core message but differ in the specified way.

Return JSON:
{{
  "variant_a": {{
    "label": "short label for variant A style (3-5 words)",
    "content": "the full post text for variant A"
  }},
  "variant_b": {{
    "label": "short label for variant B style (3-5 words)",
    "content": "the full post text for variant B"
  }}
}}"""

            result = _call_openrouter(prompt)

            va = result.get("variant_a", {})
            vb = result.get("variant_b", {})

            col.update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {
                    "status": "ready",
                    "variant_a": {
                        "label": va.get("label", "Variant A"),
                        "content": va.get("content", content),
                        "likes": 0, "comments": 0, "shares": 0, "engagement_rate": 0,
                    },
                    "variant_b": {
                        "label": vb.get("label", "Variant B"),
                        "content": vb.get("content", content),
                        "likes": 0, "comments": 0, "shares": 0, "engagement_rate": 0,
                    },
                }},
            )
        except Exception as e:
            print(f"[AB] Variation generation error: {e}")
            col.update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {"status": "error"}},
            )


# ─── RUN a test (start simulation) ───
@ab_tests_bp.route("/<test_id>/run", methods=["POST"])
def run_test(test_id):
    try:
        col = current_app.mongo["ab_tests"]
        test = col.find_one({"_id": ObjectId(test_id)})
        if not test:
            return jsonify({"error": "Test not found"}), 404

        if test["status"] not in ("ready", "paused"):
            return jsonify({"error": f"Cannot run test in '{test['status']}' status"}), 400

        col.update_one(
            {"_id": ObjectId(test_id)},
            {"$set": {
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
            }},
        )

        # Start simulation in background
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_simulation, args=(app, test_id))
        thread.daemon = True
        thread.start()

        return jsonify({"message": "Test started"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _run_simulation(app, test_id):
    """Simulate engagement rounds in background."""
    with app.app_context():
        col = app.mongo["ab_tests"]

        while True:
            test = col.find_one({"_id": ObjectId(test_id)})
            if not test or test["status"] != "running":
                break

            current_round = test.get("current_round", 0) + 1
            total_rounds = test.get("total_rounds", 24)

            if current_round > total_rounds:
                # Complete the test
                va = test.get("variant_a", {})
                vb = test.get("variant_b", {})
                a_score = (va.get("likes", 0)) + (va.get("comments", 0) * 3) + (va.get("shares", 0) * 5)
                b_score = (vb.get("likes", 0)) + (vb.get("comments", 0) * 3) + (vb.get("shares", 0) * 5)

                winner = "A" if a_score >= b_score else "B"
                loser_score = min(a_score, b_score)
                imp_pct = round(((max(a_score, b_score) - loser_score) / max(loser_score, 1)) * 100, 1)

                col.update_one(
                    {"_id": ObjectId(test_id)},
                    {"$set": {
                        "status": "completed",
                        "winner": winner,
                        "improvement": f"+{imp_pct}%",
                        "completed_at": datetime.utcnow().isoformat(),
                    }},
                )
                break

            # Simulate engagement for this round
            a_likes = random.randint(2, 15)
            a_comments = random.randint(0, 5)
            a_shares = random.randint(0, 3)
            b_likes = random.randint(2, 15)
            b_comments = random.randint(0, 5)
            b_shares = random.randint(0, 3)

            impressions = random.randint(50, 200)

            va = test.get("variant_a", {})
            vb = test.get("variant_b", {})

            new_a = {
                "likes": va.get("likes", 0) + a_likes,
                "comments": va.get("comments", 0) + a_comments,
                "shares": va.get("shares", 0) + a_shares,
            }
            new_b = {
                "likes": vb.get("likes", 0) + b_likes,
                "comments": vb.get("comments", 0) + b_comments,
                "shares": vb.get("shares", 0) + b_shares,
            }

            total_a = new_a["likes"] + new_a["comments"] + new_a["shares"]
            total_b = new_b["likes"] + new_b["comments"] + new_b["shares"]
            total_imp = test.get("total_impressions", 0) + impressions

            new_a["engagement_rate"] = round((total_a / max(total_imp / 2, 1)) * 100, 2)
            new_b["engagement_rate"] = round((total_b / max(total_imp / 2, 1)) * 100, 2)

            # Keep label and content
            new_a["label"] = va.get("label", "Variant A")
            new_a["content"] = va.get("content", "")
            new_b["label"] = vb.get("label", "Variant B")
            new_b["content"] = vb.get("content", "")

            a_score = new_a["likes"] + new_a["comments"] * 3 + new_a["shares"] * 5
            b_score = new_b["likes"] + new_b["comments"] * 3 + new_b["shares"] * 5
            loser = min(a_score, b_score)
            imp = round(((max(a_score, b_score) - loser) / max(loser, 1)) * 100, 1) if loser > 0 else 0

            round_entry = {
                "round": current_round,
                "a_likes": a_likes, "a_comments": a_comments, "a_shares": a_shares,
                "b_likes": b_likes, "b_comments": b_comments, "b_shares": b_shares,
                "improvement_pct": imp,
            }

            col.update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {
                    "current_round": current_round,
                    "total_impressions": total_imp,
                    "variant_a": new_a,
                    "variant_b": new_b,
                }, "$push": {"rounds_history": round_entry}},
            )

            time.sleep(3)  # 3 seconds between rounds for demo speed


# ─── PAUSE a test ───
@ab_tests_bp.route("/<test_id>/pause", methods=["POST"])
def pause_test(test_id):
    try:
        col = current_app.mongo["ab_tests"]
        result = col.update_one(
            {"_id": ObjectId(test_id), "status": "running"},
            {"$set": {"status": "paused"}},
        )
        if result.modified_count == 0:
            return jsonify({"error": "Test not found or not running"}), 404
        return jsonify({"message": "Test paused"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── DELETE a test ───
@ab_tests_bp.route("/<test_id>", methods=["DELETE"])
def delete_test(test_id):
    try:
        col = current_app.mongo["ab_tests"]
        result = col.delete_one({"_id": ObjectId(test_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "Test not found"}), 404
        return jsonify({"message": "Test deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── AI Assist ───
@ab_tests_bp.route("/ai-assist", methods=["POST"])
def ai_assist():
    try:
        data = request.get_json() or {}
        content = (data.get("content") or "").strip()
        action = data.get("action", "improve")

        if not content:
            return jsonify({"error": "Content is required"}), 400

        action_prompts = {
            "generate": f"Generate a compelling social media post about: {content}",
            "improve": f"Improve this social media post while keeping the core message:\n{content}",
            "hook": f"Rewrite this post with a much better, scroll-stopping hook:\n{content}",
            "shorter": f"Make this post more concise and punchy while keeping the core message:\n{content}",
            "engaging": f"Make this post significantly more engaging with better emotional triggers:\n{content}",
        }

        prompt = action_prompts.get(action, action_prompts["improve"])
        prompt += "\n\nReturn JSON: {\"result\": \"the improved post text\"}"

        result = _call_openrouter(prompt, max_tokens=800)
        return jsonify({"result": result.get("result", content)}), 200

    except CreditError as e:
        return jsonify({"error": str(e)}), 402
    except Exception as e:
        current_app.logger.exception("AI assist error")
        return jsonify({"error": str(e)}), 500


# ─── Analysis for a specific test ───
@ab_tests_bp.route("/<test_id>/analysis", methods=["GET"])
def get_analysis(test_id):
    try:
        col = current_app.mongo["ab_tests"]
        test = col.find_one({"_id": ObjectId(test_id)})
        if not test:
            return jsonify({"error": "Test not found"}), 404

        va = test.get("variant_a", {})
        vb = test.get("variant_b", {})

        prompt = f"""Analyze these two A/B test variants:

Variant A ({va.get('label', 'A')}):
"{va.get('content', '')}"
Stats: {va.get('likes', 0)} likes, {va.get('comments', 0)} comments, {va.get('shares', 0)} shares

Variant B ({vb.get('label', 'B')}):
"{vb.get('content', '')}"
Stats: {vb.get('likes', 0)} likes, {vb.get('comments', 0)} comments, {vb.get('shares', 0)} shares

Return JSON:
{{
  "summary": "2-3 sentence AI analysis of the test",
  "variant_a_analysis": "1-2 sentence analysis of variant A's strengths/weaknesses",
  "variant_b_analysis": "1-2 sentence analysis of variant B's strengths/weaknesses",
  "hook_quality_a": 7.5,
  "readability_a": 8.0,
  "engagement_potential_a": 7.0,
  "hook_quality_b": 8.0,
  "readability_b": 7.5,
  "engagement_potential_b": 8.5,
  "recommendation": "1-2 sentence actionable recommendation"
}}

Scores should be 1-10 scale. Be specific and data-driven."""

        result = _call_openrouter(prompt)
        return jsonify(result), 200

    except CreditError as e:
        return jsonify({"error": str(e)}), 402
    except Exception as e:
        return jsonify({"summary": "Could not generate analysis. Try again later.", "error": str(e)}), 200


# ─── Insights (aggregate learnings) ───
@ab_tests_bp.route("/insights", methods=["GET"])
def get_insights():
    try:
        col = current_app.mongo["ab_tests"]
        completed = list(col.find({"status": "completed"}).sort("completed_at", -1).limit(20))

        if not completed:
            return jsonify({
                "tone_preference": {"winning_tone": "N/A", "description": "Complete more tests to see insights", "confidence": 0},
                "optimal_timing": {"best_duration": "N/A", "description": "Complete more tests to see insights", "confidence": 0},
                "content_length": {"optimal": "N/A", "description": "Complete more tests to see insights", "confidence": 0},
                "overall_recommendation": "Run at least 3 A/B tests to start seeing actionable insights.",
            }), 200

        tests_summary = []
        for t in completed[:10]:
            va = t.get("variant_a", {})
            vb = t.get("variant_b", {})
            tests_summary.append({
                "name": t.get("name", "Untitled"),
                "type": t.get("variation_type", "tone"),
                "winner": t.get("winner", "?"),
                "improvement": t.get("improvement", "0%"),
                "duration": t.get("duration", "24h"),
                "a_label": va.get("label", "A"),
                "b_label": vb.get("label", "B"),
            })

        prompt = f"""Analyze these completed A/B test results and extract patterns:

{json.dumps(tests_summary, indent=2)}

Return JSON:
{{
  "tone_preference": {{
    "winning_tone": "the tone that wins most",
    "description": "1-2 sentence explanation",
    "confidence": 75,
    "tip": "actionable advice"
  }},
  "optimal_timing": {{
    "best_duration": "optimal test duration",
    "description": "1-2 sentence explanation",
    "confidence": 60,
    "tip": "actionable advice"
  }},
  "content_length": {{
    "optimal": "short/medium/long",
    "description": "1-2 sentence explanation",
    "confidence": 65,
    "tip": "actionable advice"
  }},
  "overall_recommendation": "2-3 sentence strategic recommendation based on all patterns"
}}"""

        result = _call_openrouter(prompt)
        return jsonify(result), 200

    except CreditError as e:
        return jsonify({"error": str(e)}), 402
    except Exception as e:
        return jsonify({
            "tone_preference": {"winning_tone": "N/A", "description": "Analysis unavailable", "confidence": 0},
            "optimal_timing": {"best_duration": "N/A", "description": "Analysis unavailable", "confidence": 0},
            "content_length": {"optimal": "N/A", "description": "Analysis unavailable", "confidence": 0},
            "overall_recommendation": "Could not generate insights at this time.",
        }), 200


# ─── Settings ───
@ab_tests_bp.route("/settings", methods=["GET"])
def get_settings():
    try:
        col = current_app.mongo["ab_test_settings"]
        settings = col.find_one({"_id": "default"})
        if not settings:
            settings = {
                "_id": "default",
                "default_duration": "24h",
                "min_sample_size": 1000,
                "statistical_significance": 95,
                "notify_complete": True,
                "daily_progress": True,
                "weekly_summary": False,
                "auto_apply_winner": True,
            }
            col.insert_one(settings)

        settings["_id"] = str(settings["_id"])
        return jsonify(settings), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ab_tests_bp.route("/settings", methods=["PUT"])
def save_settings():
    try:
        data = request.get_json() or {}
        col = current_app.mongo["ab_test_settings"]

        allowed_keys = ["default_duration", "min_sample_size", "statistical_significance",
                        "notify_complete", "daily_progress", "weekly_summary", "auto_apply_winner"]
        update = {k: data[k] for k in allowed_keys if k in data}

        col.update_one(
            {"_id": "default"},
            {"$set": update},
            upsert=True,
        )
        return jsonify({"message": "Settings saved"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
