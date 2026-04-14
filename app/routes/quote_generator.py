from flask import Blueprint, request, jsonify, current_app
import os
import json
import requests
from datetime import datetime

quote_generator_bp = Blueprint("quote_generator", __name__)


def normalize_platform_name(platform: str) -> str:
    mapping = {
        "twitter": "Twitter",
        "x": "Twitter",
        "linkedin": "LinkedIn",
        "medium": "Medium",
    }
    return mapping.get(platform.lower(), platform.capitalize())


def build_prompt(quote: str, selected_platforms: list, brand_enabled: bool) -> str:
    platforms = [normalize_platform_name(p) for p in selected_platforms]

    return f"""You are a world-class social media copywriter with 10+ years of experience crafting viral content for Fortune 500 brands. You transform quotes into scroll-stopping, platform-native posts that drive engagement.

CRITICAL LANGUAGE RULE:
Detect the language of the original quote below. Write ALL variations in THAT SAME LANGUAGE.
- French quote → French output
- English quote → English output
- Arabic quote → Arabic output
- NEVER translate. NEVER switch languages. Match the quote's language exactly.

ORIGINAL QUOTE:
"{quote}"

TARGET PLATFORMS: {", ".join(platforms)}

TRANSFORMATION METHODOLOGY:

STEP 1 — DECODE THE QUOTE:
- Identify the core insight, emotion, and implicit audience
- Find the tension, contrast, or surprise inside the message
- Determine if it's aspirational, contrarian, educational, or emotional

STEP 2 — PLATFORM-NATIVE REWRITING:
Each variation must feel like it was BORN on that platform, not adapted to it.

TWITTER (max 280 chars):
- Lead with the most powerful phrase — first 5 words decide everything
- Use rhythm: short sentence. Shorter sentence. Punch.
- Line breaks create visual breathing room and dramatic pacing
- If the quote has a contrast, use "X. But Y." structure
- End with a mic-drop line, not a generic CTA
- Hashtags: 1-2 max, only if they add genuine discovery value

LINKEDIN:
- Open with a bold, standalone first line (this is the "see more" preview — it MUST hook)
- Add 1-2 sentences of personal context or a "why this matters" bridge BEFORE the quote
- Use strategic line breaks — every 1-2 sentences
- Frame as a leadership insight or hard-won lesson, never a motivational poster
- End with a reflective question that invites genuine discussion (not "Agree?")
- Hashtags: 2-3 industry-relevant tags at the end

MEDIUM:
- Adopt an editorial, essay-like voice — think published columnist
- Open with a scene, anecdote, or provocative question that leads INTO the quote
- Expand the thought: add a "what this really means" layer
- Use a rhetorical question or future-looking statement to close
- No hashtags — this is long-form territory

STEP 3 — QUALITY GATES (every variation must pass ALL):
✓ Would a real human post this? (no corporate-speak, no AI-sounding filler)
✓ Does it stop the scroll? (first line must create curiosity or emotion)
✓ Is the original meaning preserved and amplified, not diluted?
✓ Does it match the platform's native voice and culture?
✓ Would someone save, share, or screenshot this?

ANTI-PATTERNS — INSTANT REJECTION:
✗ Starting with "In today's fast-paced world..." or any generic opener
✗ Starting every variation with the same word or structure
✗ Watering down a bold statement to sound "safer"
✗ Adding hollow calls-to-action ("Like if you agree!", "Tag a friend!")
✗ Using buzzwords without substance ("game-changer", "paradigm shift")
✗ Making the quote longer without making it better
✗ Losing the emotional core of the original message
✗ Writing in a DIFFERENT language than the original quote — this is an instant fail

Brand signature enabled: {str(brand_enabled).lower()}
If brand signature is enabled, append exactly: — @EtkanAI

Return ONLY valid JSON, no markdown, no explanation:
[
  {{
    "platform": "Twitter",
    "tone": "the dominant emotion (e.g. bold, reflective, urgent, hopeful, defiant, vulnerable)",
    "text": "Generated text here"
  }}
]
"""


def call_openrouter(prompt: str):
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    app_url = os.getenv("APP_URL", "http://localhost:5173")
    app_name = os.getenv("APP_NAME", "Quote Generator")

    if not api_key:
        raise ValueError("OPENROUTER_API_KEY non défini dans .env")

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": app_url,
        "X-Title": app_name,
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a world-class social media copywriter. You transform quotes into platform-native, scroll-stopping content. Return ONLY valid JSON arrays — no markdown, no explanation, no code fences."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.8,
        "max_tokens": 1500
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def parse_model_output(content: str):
    content = content.strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed

    raise ValueError("Le modèle n'a pas retourné un JSON valide")


@quote_generator_bp.route("/generate", methods=["POST"])
def generate_quotes():
    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "JSON body invalide"}), 400

        quote = data.get("quote", "").strip()
        selected_platforms = data.get("selectedPlatforms", [])
        brand_enabled = data.get("brandEnabled", False)

        if not quote:
            return jsonify({"error": "Le champ quote est obligatoire"}), 400

        if len(quote) < 10:
            return jsonify({"error": "Le quote doit contenir au moins 10 caractères"}), 400

        if not selected_platforms or not isinstance(selected_platforms, list):
            return jsonify({"error": "Au moins une plateforme est requise"}), 400

        prompt = build_prompt(quote, selected_platforms, brand_enabled)
        ai_response = call_openrouter(prompt)

        content = ai_response["choices"][0]["message"]["content"]
        variations = parse_model_output(content)

        document = {
            "quote": quote,
            "selectedPlatforms": selected_platforms,
            "brandEnabled": brand_enabled,
            "variations": variations,
            "createdAt": datetime.utcnow(),
            "type": "quote_generation"
        }

        result = current_app.mongo.quote_generations.insert_one(document)

        return jsonify({
            "success": True,
            "id": str(result.inserted_id),
            "variations": variations
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({
            "error": "Erreur OpenRouter",
            "details": str(e)
        }), 500

    except ValueError as e:
        return jsonify({
            "error": str(e)
        }), 500

    except Exception as e:
        return jsonify({
            "error": "Erreur interne serveur",
            "details": str(e)
        }), 500


@quote_generator_bp.route("/history", methods=["GET"])
def get_quote_history():
    try:
        limit = request.args.get("limit", 10, type=int)
        limit = min(limit, 50)

        items = list(
            current_app.mongo.quote_generations
            .find({}, {"_id": 1, "quote": 1, "selectedPlatforms": 1, "brandEnabled": 1, "variations": 1, "createdAt": 1})
            .sort("createdAt", -1)
            .limit(limit)
        )

        history = []
        for item in items:
            history.append({
                "id": str(item["_id"]),
                "quote": item.get("quote"),
                "selectedPlatforms": item.get("selectedPlatforms", []),
                "brandEnabled": item.get("brandEnabled", False),
                "variations": item.get("variations", []),
                "createdAt": item["createdAt"].isoformat() if item.get("createdAt") else None
            })

        return jsonify({
            "success": True,
            "count": len(history),
            "history": history
        }), 200

    except Exception as e:
        return jsonify({
            "error": "Impossible de récupérer l'historique",
            "details": str(e)
        }), 500


@quote_generator_bp.route("/history/<quote_id>", methods=["DELETE"])
def delete_quote_history(quote_id):
    try:
        from bson import ObjectId

        result = current_app.mongo.quote_generations.delete_one({
            "_id": ObjectId(quote_id)
        })

        if result.deleted_count == 0:
            return jsonify({"error": "Élément introuvable"}), 404

        return jsonify({
            "success": True,
            "message": "Historique supprimé avec succès"
        }), 200

    except Exception as e:
        return jsonify({
            "error": "Impossible de supprimer l'élément",
            "details": str(e)
        }), 500