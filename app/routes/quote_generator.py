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


def build_prompt(quote: str, selected_platforms: list, brand_enabled: bool, voice_profile: dict = None, style_preset: str = None) -> str:
    platforms = [normalize_platform_name(p) for p in selected_platforms]

    voice_context = ""
    if voice_profile:
        voice_context = f"""\n\nWRITING VOICE PROFILE (apply this style to ALL variations):
- Tone: {voice_profile.get('tone', 'Neutral')}
- Sentence Style: {voice_profile.get('sentenceStyle', 'Medium')}
- Structure: {voice_profile.get('structure', '')}
- Hook Style: {voice_profile.get('hookStyle', '')}
- CTA Style: {voice_profile.get('ctaStyle', '')}
- Emoji Usage: {voice_profile.get('emojiUsage', 'Minimal')}
- Hashtag Usage: {voice_profile.get('hashtagUsage', 'Minimal')}
- Vocabulary Level: {voice_profile.get('vocabularyLevel', 'Intermediate')}
- Writing Patterns: {', '.join(voice_profile.get('writingPatterns', []))}
- Unique Traits: {', '.join(voice_profile.get('uniqueTraits', []))}
Adapt all variations to match this voice profile while staying platform-native."""

    style_context = ""
    if style_preset:
        style_map = {
            "motivational": "Write in an uplifting, inspiring, high-energy style. Use power words, exclamation marks, and emotional impact. Make the reader feel empowered.",
            "professional": "Write in a polished, authoritative, corporate-ready style. Use data-driven language, measured tone, and credibility signals. Suitable for executives.",
            "humorous": "Write with wit, clever wordplay, and unexpected twists. Use humor to make the point memorable. Keep it smart, not silly.",
            "poetic": "Write with lyrical, evocative language. Use metaphors, rhythm, and imagery. Create an emotional, almost literary experience.",
            "provocative": "Write with a bold, contrarian, challenge-the-status-quo style. Push boundaries, ask uncomfortable questions, and make people think.",
        }
        instruction = style_map.get(style_preset, "")
        if instruction:
            style_context = f"\n\nSTYLE PRESET — {style_preset.upper()}:\n{instruction}"

    # Build platform-specific rules only for selected platforms
    platform_rules = {
        "Twitter": """TWITTER (max 280 chars):
- Generate a powerful, standalone citation/quote
- Must be punchy, memorable, and tweetable
- Use line breaks for rhythm if needed
- No hashtags unless they truly add value (1 max)""",
        "LinkedIn": """LINKEDIN:
- Generate a professional, thought-provoking citation
- Can be slightly longer and more nuanced
- Should sound like wisdom from an industry leader
- No hashtags, no CTA — just the pure citation""",
        "Medium": """MEDIUM:
- Generate a deep, reflective, essay-worthy citation
- Can be longer and more literary
- Should feel like the opening line of a great article
- Poetic or philosophical tone welcome""",
    }

    selected_rules = "\n\n".join(platform_rules[p] for p in platforms if p in platform_rules)

    return f"""You are a master quote/citation generator. Your job is to generate NEW, ORIGINAL citations inspired by a given theme or idea.

WHAT YOU DO:
- You receive a TOPIC, IDEA, or THEME from the user.
- You generate powerful, original CITATIONS — standalone phrases that could be attributed to a thought leader.
- These are NOT social media posts. They are PURE CITATIONS — no intro, no context, no CTA, no commentary.
- Think of quotes you'd see on a poster, in a book, or shared as an image.

WHAT A CITATION IS:
- A standalone memorable phrase or sentence
- Sounds like it was said by a wise person, a leader, or a visionary
- Self-contained — needs no explanation
- Examples: "The best time to plant a tree was 20 years ago. The second best time is now."
- Examples: "Move fast and break things." — Mark Zuckerberg{voice_context}{style_context}

CRITICAL LANGUAGE RULE:
Detect the language of the user's input. Write ALL citations in THAT SAME LANGUAGE.
- French input → French citations
- English input → English citations
- Arabic input → Arabic citations
- NEVER switch languages.

USER'S INPUT (topic/theme/idea):
"{quote}"

TARGET PLATFORMS: {", ".join(platforms)}
Generate EXACTLY one citation per platform, adapted to the platform's tone.

PLATFORM-SPECIFIC TONE:

{selected_rules}

RULES:
✓ Each citation must be ORIGINAL — not a copy of an existing famous quote
✓ Must be powerful, memorable, and shareable
✓ Must relate directly to the user's topic
✓ PURE citation only — no intro text, no "Here's a quote:", no commentary, no hashtags (unless specified)
✓ NO brand signature or attribution should be appended unless explicitly requested

DO NOT:
✗ Add any text before or after the citation (no "This quote means...", no "Share this!")
✗ Add brand signatures like "— @EtkanAI" unless explicitly enabled
✗ Copy existing famous quotes
✗ Write generic platitudes ("Believe in yourself!", "Follow your dreams!")
✗ Add social media formatting (hashtags, emojis, CTAs)

Return ONLY valid JSON with EXACTLY {len(platforms)} citations, no markdown, no explanation:
[
  {{
    "platform": "Twitter",
    "tone": "the dominant emotion (e.g. bold, reflective, urgent, hopeful, defiant, vulnerable)",
    "text": "The citation text here — nothing else"
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
                "content": "You generate original, powerful citations/quotes based on a given topic. Output PURE citations only — no social media post formatting, no commentary, no intro. Return ONLY valid JSON arrays — no markdown, no explanation, no code fences."
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
        voice_profile = data.get("voiceProfile")
        style_preset = data.get("stylePreset")

        if not quote:
            return jsonify({"error": "Le champ quote est obligatoire"}), 400

        if len(quote) < 10:
            return jsonify({"error": "Le quote doit contenir au moins 10 caractères"}), 400

        if not selected_platforms or not isinstance(selected_platforms, list):
            return jsonify({"error": "Au moins une plateforme est requise"}), 400

        prompt = build_prompt(quote, selected_platforms, brand_enabled, voice_profile, style_preset)
        ai_response = call_openrouter(prompt)

        content = ai_response["choices"][0]["message"]["content"]
        variations = parse_model_output(content)

        # Filter to only selected platforms (AI may generate extras)
        normalized_selected = [normalize_platform_name(p) for p in selected_platforms]
        variations = [v for v in variations if v.get("platform") in normalized_selected]

        # Remove brand signature if not enabled
        if not brand_enabled:
            for variation in variations:
                if "text" in variation:
                    # Remove @EtkanAI or similar brand signatures
                    variation["text"] = variation["text"].replace(" — @EtkanAI", "").replace("— @EtkanAI", "").replace(" —@EtkanAI", "").replace("—@EtkanAI", "").strip()

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


@quote_generator_bp.route("/templates", methods=["POST"])
def save_template():
    """Save a quote variation as a reusable template."""
    try:
        data = request.get_json() or {}
        quote = data.get("quote", "").strip()
        variation = data.get("variation")
        name = data.get("name", "").strip()

        if not quote or not variation:
            return jsonify({"error": "quote and variation are required"}), 400

        doc = {
            "name": name or quote[:50],
            "quote": quote,
            "variation": variation,
            "createdAt": datetime.utcnow(),
        }
        result = current_app.mongo.quote_templates.insert_one(doc)
        return jsonify({"success": True, "id": str(result.inserted_id)}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quote_generator_bp.route("/templates", methods=["GET"])
def get_templates():
    """Get saved quote templates."""
    try:
        items = list(
            current_app.mongo.quote_templates
            .find()
            .sort("createdAt", -1)
            .limit(50)
        )
        templates = []
        for item in items:
            templates.append({
                "id": str(item["_id"]),
                "name": item.get("name", ""),
                "quote": item.get("quote", ""),
                "variation": item.get("variation", {}),
                "createdAt": item["createdAt"].isoformat() if item.get("createdAt") else None,
            })
        return jsonify({"success": True, "templates": templates}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quote_generator_bp.route("/templates/<template_id>", methods=["DELETE"])
def delete_template(template_id):
    """Delete a saved template."""
    try:
        from bson import ObjectId
        result = current_app.mongo.quote_templates.delete_one({"_id": ObjectId(template_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "Template not found"}), 404
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quote_generator_bp.route("/analytics", methods=["GET"])
def get_analytics():
    """Get quote generation analytics."""
    try:
        total = current_app.mongo.quote_generations.count_documents({})
        templates_count = current_app.mongo.quote_templates.count_documents({})

        # Platform breakdown (only Twitter, LinkedIn, Medium)
        allowed_platforms = ["twitter", "linkedin", "medium"]
        pipeline = [
            {"$unwind": "$selectedPlatforms"},
            {"$match": {"selectedPlatforms": {"$in": allowed_platforms}}},
            {"$group": {"_id": "$selectedPlatforms", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        platform_stats = list(current_app.mongo.quote_generations.aggregate(pipeline))

        # Recent activity (last 7 days)
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_count = current_app.mongo.quote_generations.count_documents(
            {"createdAt": {"$gte": week_ago}}
        )

        # Average variations per gen
        var_pipeline = [
            {"$project": {"varCount": {"$size": {"$ifNull": ["$variations", []]}}}},
            {"$group": {"_id": None, "avg": {"$avg": "$varCount"}}},
        ]
        var_result = list(current_app.mongo.quote_generations.aggregate(var_pipeline))
        avg_variations = round(var_result[0]["avg"], 1) if var_result else 0

        return jsonify({
            "success": True,
            "total_generations": total,
            "saved_templates": templates_count,
            "this_week": recent_count,
            "avg_variations": avg_variations,
            "platforms": {s["_id"]: s["count"] for s in platform_stats if s["_id"] in allowed_platforms},
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500