import json
import re
from datetime import datetime
import langdetect

import requests
from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request


hook_generator_bp = Blueprint("hook_generator", __name__)


PLATFORM_RULES = {
    "twitter": {
        "max_chars": 280,
        "style": "short, punchy, curiosity-driven, fast-paced"
    },
    "linkedin": {
        "max_chars": 300,
        "style": "professional, sharp, credible, value-driven"
    },
    "medium": {
        "max_chars": 400,
        "style": "insightful, narrative, thoughtful, clear"
    }
}

ALLOWED_TYPES = {
    "question",
    "bold-statement",
    "contrarian",
    "story",
    "statistic",
    "curiosity",
    "urgency",
    "how-to"
}


def clean_text(value, max_length=None):
    if value is None:
        return ""
    value = str(value).strip()
    value = re.sub(r"\s+", " ", value)
    if max_length:
        value = value[:max_length]
    return value


def normalize_platforms(platforms):
    if not isinstance(platforms, list):
        return ["twitter"]

    valid = []
    for p in platforms:
        p = str(p).strip().lower()
        if p in PLATFORM_RULES and p not in valid:
            valid.append(p)

    return valid or ["twitter"]


def detect_language(topic):
    """
    Détecte automatiquement la langue du topic.
    Retourne le code de langue (fr, en, es, de, it, pt)
    """
    try:
        # Pour les textes courts, ajoute du contexte si nécessaire
        if len(topic) < 10:
            # Si le texte est très court, vérifier s'il contient des mots français courants
            french_words = ['le', 'la', 'les', 'de', 'du', 'des', 'et', 'est', 'sont', 'pour', 'avec', 'dans', 'sur']
            topic_lower = topic.lower()
            if any(word in topic_lower for word in french_words):
                return 'fr'
            # Mots anglais courants
            english_words = ['the', 'and', 'for', 'are', 'with', 'from', 'that', 'this', 'have', 'been', 'has']
            if any(word in topic_lower for word in english_words):
                return 'en'
        
        # Utilise langdetect pour détecter la langue
        detected = langdetect.detect(topic)
        
        # Map des langues supportées
        lang_map = {
            'fr': 'fr',  # Français
            'en': 'en',  # Anglais
            'es': 'es',  # Espagnol
            'de': 'de',  # Allemand
            'it': 'it',  # Italien
            'pt': 'pt'   # Portugais
        }
        
        # Si la langue détectée n'est pas supportée, utiliser l'anglais par défaut
        detected_lang = lang_map.get(detected, 'en')
        
        # Vérification supplémentaire pour les textes courts
        if len(topic) < 20 and detected_lang not in ['fr', 'en']:
            # Par défaut, utiliser l'anglais pour les textes courts non identifiés
            return 'en'
            
        return detected_lang
    except:
        return 'en'  # Par défaut si détection échoue


def get_language_instructions(language):
    """
    Retourne les instructions spécifiques à la langue pour l'IA
    """
    instructions = {
        'fr': "Écris en français. Utilise un style naturel et engageant pour le public francophone.",
        'en': "Write in English. Use a natural and engaging style for English-speaking audience.",
        'es': "Escribe en español. Usa un estilo natural y atractivo para el público hispanohablante.",
        'de': "Schreibe auf Deutsch. Verwende einen natürlichen und ansprechenden Stil für das deutschsprachige Publikum.",
        'it': "Scrivi in italiano. Usa uno stile naturale e coinvolgente per il pubblico di lingua italiana.",
        'pt': "Escreva em português. Use um estilo natural e envolvente para o público de língua portuguesa."
    }
    return instructions.get(language, instructions['en'])


def build_prompt(topic, platforms, language="fr", tone="dynamic", count=5):
    platform_data = [
        {
            "platform": p,
            "max_chars": PLATFORM_RULES[p]["max_chars"],
            "style": PLATFORM_RULES[p]["style"]
        }
        for p in platforms
    ]
    
    lang_instruction = get_language_instructions(language)

    return f"""
You are an elite social media copywriter specialized in writing viral hooks.

Task:
Generate {count} highly engaging hooks about this topic:
"{topic}"

Constraints:
- Language: {language} ({lang_instruction})
- Tone: {tone}
- Hooks must be logical, dynamic, specific, and natural
- Avoid clichés and generic phrases
- Avoid fake statistics
- Avoid repetitive openings
- Avoid generic AI buzzwords
- Each hook must be adapted to one of the requested platforms
- Vary hook styles across outputs
- Return ONLY valid JSON
- Do not include markdown or code fences

Platforms:
{json.dumps(platform_data, ensure_ascii=False)}

Return this exact JSON structure:
{{
  "hooks": [
    {{
      "text": "hook text here",
      "type": "question|bold-statement|contrarian|story|statistic|curiosity|urgency|how-to",
      "score": 91,
      "platform": "linkedin",
      "reason": "brief explanation of why this hook works"
    }}
  ]
}}

Rules:
- score must be an integer between 80 and 98
- hook text must respect the platform style and stay concise
- reason must be short and useful
- All content must be in the specified language: {language}
"""


def extract_json(content):
    """
    Essaie de parser directement le JSON.
    Sinon, extrait le premier bloc JSON trouvé.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError("Le modèle n'a pas retourné de JSON valide.")


def normalize_hook(hook, fallback_platform="twitter"):
    text = clean_text(hook.get("text", ""), max_length=500)
    reason = clean_text(hook.get("reason", ""), max_length=300)

    hook_type = clean_text(hook.get("type", "curiosity"), max_length=50)
    if hook_type not in ALLOWED_TYPES:
        hook_type = "curiosity"

    platform = clean_text(hook.get("platform", fallback_platform), max_length=50).lower()
    if platform not in PLATFORM_RULES:
        platform = fallback_platform

    try:
        score = int(hook.get("score", 88))
    except (TypeError, ValueError):
        score = 88

    score = max(80, min(98, score))

    return {
        "text": text,
        "type": hook_type,
        "score": score,
        "platform": platform,
        "reason": reason
    }


def call_openrouter(topic, platforms, language="fr", tone="dynamic", count=5):
    api_key = current_app.config.get("OPENROUTER_API_KEY")
    model = current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")

    if not api_key:
        raise ValueError("OPENROUTER_API_KEY manquant dans la configuration.")

    prompt = build_prompt(
        topic=topic,
        platforms=platforms,
        language=language,
        tone=tone,
        count=count
    )

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": frontend_url,
            "X-Title": "AutoPoster Hook Generator"
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You generate high-quality social media hooks and return strict JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.9
        },
        timeout=60
    )

    if response.status_code != 200:
        raise ValueError(f"Erreur OpenRouter: {response.text}")

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError("Réponse OpenRouter invalide.")

    parsed = extract_json(content)
    raw_hooks = parsed.get("hooks", [])

    if not isinstance(raw_hooks, list) or len(raw_hooks) == 0:
        raise ValueError("Aucun hook valide retourné par le modèle.")

    normalized_hooks = []
    for index, hook in enumerate(raw_hooks):
        fallback_platform = platforms[index % len(platforms)]
        normalized_hooks.append(normalize_hook(hook, fallback_platform=fallback_platform))

    return normalized_hooks


@hook_generator_bp.route("/generate", methods=["POST"])
def generate_hooks():
    try:
        payload = request.get_json(force=True) or {}

        topic = clean_text(payload.get("topic"), max_length=500)
        platforms = normalize_platforms(payload.get("platforms", ["twitter"]))
        language = clean_text(payload.get("language", "fr"), max_length=20) or "fr"
        tone = clean_text(payload.get("tone", "dynamic"), max_length=50) or "dynamic"

        try:
            count = int(payload.get("count", 5))
        except (TypeError, ValueError):
            count = 5

        count = max(1, min(10, count))

        if not topic:
            return jsonify({"error": "Topic is required"}), 400

        # Détection automatique de la langue si "auto" est spécifié ou si non spécifiée
        if not language or language == "auto":
            detected_lang = detect_language(topic)
            language = detected_lang
            current_app.logger.info(f"Langue détectée automatiquement: {detected_lang}")

        hooks = call_openrouter(
            topic=topic,
            platforms=platforms,
            language=language,
            tone=tone,
            count=count
        )

        doc = {
            "topic": topic,
            "platforms": platforms,
            "language": language,
            "tone": tone,
            "count": count,
            "hooks": hooks,
            "created_at": datetime.utcnow()
        }

        result = current_app.mongo["hook_generations"].insert_one(doc)

        return jsonify({
            "message": "Hooks generated successfully",
            "generation_id": str(result.inserted_id),
            "hooks": hooks
        }), 200

    except Exception as e:
        current_app.logger.exception("Hook generation error")
        return jsonify({"error": str(e)}), 500


@hook_generator_bp.route("/regenerate-one", methods=["POST"])
def regenerate_one():
    try:
        payload = request.get_json(force=True) or {}

        topic = clean_text(payload.get("topic"), max_length=500)
        platform = clean_text(payload.get("platform", "twitter"), max_length=50).lower()
        language = clean_text(payload.get("language", "fr"), max_length=20) or "fr"
        tone = clean_text(payload.get("tone", "dynamic"), max_length=50) or "dynamic"

        if not topic:
            return jsonify({"error": "Topic is required"}), 400

        if platform not in PLATFORM_RULES:
            platform = "twitter"

        # Détection automatique de la langue si "auto" est spécifié ou si non spécifiée
        if not language or language == "auto":
            detected_lang = detect_language(topic)
            language = detected_lang
            current_app.logger.info(f"Langue détectée automatiquement: {detected_lang}")

        hooks = call_openrouter(
            topic=topic,
            platforms=[platform],
            language=language,
            tone=tone,
            count=1
        )

        if not hooks:
            return jsonify({"error": "No hook generated"}), 500

        return jsonify({
            "message": "Hook regenerated successfully",
            "hook": hooks[0]
        }), 200

    except Exception as e:
        current_app.logger.exception("Regenerate one hook error")
        return jsonify({"error": str(e)}), 500


@hook_generator_bp.route("/history", methods=["GET"])
def get_history():
    try:
        limit = request.args.get("limit", 20)

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20

        limit = max(1, min(100, limit))

        items = list(
            current_app.mongo["hook_generations"]
            .find({}, {"topic": 1, "platforms": 1, "language": 1, "tone": 1, "hooks": 1, "created_at": 1})
            .sort("created_at", -1)
            .limit(limit)
        )

        for item in items:
            item["_id"] = str(item["_id"])

        return jsonify({"history": items}), 200

    except Exception as e:
        current_app.logger.exception("Get history error")
        return jsonify({"error": str(e)}), 500


@hook_generator_bp.route("/history/<generation_id>", methods=["GET"])
def get_one_history(generation_id):
    try:
        if not ObjectId.is_valid(generation_id):
            return jsonify({"error": "Invalid generation_id"}), 400

        item = current_app.mongo["hook_generations"].find_one({"_id": ObjectId(generation_id)})

        if not item:
            return jsonify({"error": "Generation not found"}), 404

        item["_id"] = str(item["_id"])

        return jsonify({"generation": item}), 200

    except Exception as e:
        current_app.logger.exception("Get one history error")
        return jsonify({"error": str(e)}), 500


@hook_generator_bp.route("/favorite", methods=["POST"])
def favorite_hook():
    try:
        payload = request.get_json(force=True) or {}

        hook = payload.get("hook")
        topic = clean_text(payload.get("topic"), max_length=500)
        note = clean_text(payload.get("note", ""), max_length=300)
        language = clean_text(payload.get("language", "auto"), max_length=20) or "auto"

        if not hook or not isinstance(hook, dict):
            return jsonify({"error": "Hook object is required"}), 400

        normalized = normalize_hook(
            hook,
            fallback_platform=clean_text(hook.get("platform", "twitter")).lower() or "twitter"
        )

        # Détection automatique de la langue si "auto" est spécifié ou si non spécifiée
        if not language or language == "auto":
            detected_lang = detect_language(topic)
            language = detected_lang
            current_app.logger.info(f"Langue détectée automatiquement: {detected_lang}")

        doc = {
            "topic": topic,
            "hook": normalized,
            "language": language,
            "note": note,
            "created_at": datetime.utcnow()
        }

        result = current_app.mongo["favorite_hooks"].insert_one(doc)

        return jsonify({
            "message": "Hook saved to favorites",
            "favorite_id": str(result.inserted_id),
            "hook": normalized
        }), 201

    except Exception as e:
        current_app.logger.exception("Favorite hook error")
        return jsonify({"error": str(e)}), 500


@hook_generator_bp.route("/favorites", methods=["GET"])
def get_favorites():
    try:
        items = list(
            current_app.mongo["favorite_hooks"]
            .find({}, {"topic": 1, "hook": 1, "note": 1, "created_at": 1})
            .sort("created_at", -1)
            .limit(50)
        )

        for item in items:
            item["_id"] = str(item["_id"])

        return jsonify({"favorites": items}), 200

    except Exception as e:
        current_app.logger.exception("Get favorites error")
        return jsonify({"error": str(e)}), 500