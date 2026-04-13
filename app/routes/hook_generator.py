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
    Retourne le code de langue (fr, en, es, de, it, pt, ar)
    """
    try:
        topic_lower = topic.lower().strip()
        
        # Mots/abréviations courants en français (y compris termes tech utilisés en FR)
        french_indicators = [
            'le', 'la', 'les', 'de', 'du', 'des', 'et', 'est', 'sont', 'pour', 'avec',
            'dans', 'sur', 'une', 'un', 'ce', 'cette', 'qui', 'que', 'comment',
            'pourquoi', 'quoi', 'faire', 'créer', 'avoir', 'être', 'nous', 'vous',
            'mon', 'mes', 'son', 'ses', 'leur', 'leurs', 'tout', 'tous', 'très',
            'plus', 'moins', 'aussi', 'bien', 'mal', 'ici', 'là', 'donc', 'mais',
            'ou', 'où', 'ni', 'car', 'parce', 'depuis', 'vers', 'chez', 'entre',
            'sans', 'sous', 'par', 'après', 'avant', 'pendant', 'contre',
            'marketing digital', 'intelligence artificielle', 'réseaux sociaux',
            'stratégie', 'contenu', 'numérique', 'développement', 'entreprise'
        ]
        
        # Check for French characters
        french_chars = ['é', 'è', 'ê', 'ë', 'à', 'â', 'ù', 'û', 'ô', 'î', 'ï', 'ç', 'œ', 'æ']
        if any(c in topic_lower for c in french_chars):
            return 'fr'
        
        # Check for Arabic characters
        if any('\u0600' <= c <= '\u06FF' for c in topic):
            return 'ar'
        
        # Split into words for matching
        words = topic_lower.split()
        
        # Check French indicators (both single words and multi-word phrases)
        french_word_matches = sum(1 for w in words if w in french_indicators)
        for phrase in french_indicators:
            if ' ' in phrase and phrase in topic_lower:
                french_word_matches += 2
        
        if french_word_matches >= 1:
            return 'fr'
        
        # For longer text, use langdetect
        if len(topic) >= 15:
            detected = langdetect.detect(topic)
            lang_map = {
                'fr': 'fr', 'en': 'en', 'es': 'es', 'de': 'de',
                'it': 'it', 'pt': 'pt', 'ar': 'ar'
            }
            return lang_map.get(detected, 'en')
        
        # Default to English for very short unrecognized text
        return 'en'
    except:
        return 'en'


def get_language_instructions(language):
    """
    Retourne les instructions spécifiques à la langue pour l'IA
    """
    instructions = {
        'fr': "ÉCRIS TOUT EN FRANÇAIS. Chaque hook doit être rédigé en français naturel et engageant. PAS un seul mot en anglais dans le texte du hook.",
        'en': "Write EVERYTHING in English. Every hook must be written in natural, engaging English.",
        'es': "ESCRIBE TODO EN ESPAÑOL. Cada hook debe estar escrito en español natural y atractivo.",
        'de': "SCHREIBE ALLES AUF DEUTSCH. Jeder Hook muss in natürlichem, ansprechendem Deutsch geschrieben sein.",
        'it': "SCRIVI TUTTO IN ITALIANO. Ogni hook deve essere scritto in italiano naturale e coinvolgente.",
        'pt': "ESCREVA TUDO EM PORTUGUÊS. Cada hook deve ser escrito em português natural e envolvente.",
        'ar': "اكتب كل شيء باللغة العربية. يجب أن يكون كل خطاف مكتوبًا بالعربية الطبيعية والجذابة."
    }
    return instructions.get(language, instructions['en'])


def build_prompt(topic, platforms, language="fr", tone="dynamic", count=5, content_length=None, voice_profile=None):
    platform_data = [
        {
            "platform": p,
            "max_chars": PLATFORM_RULES[p]["max_chars"],
            "style": PLATFORM_RULES[p]["style"]
        }
        for p in platforms
    ]
    
    lang_instruction = get_language_instructions(language)
    twitter_max_chars = PLATFORM_RULES.get('twitter', {}).get('max_chars', 280)

    length_instruction = ""
    if content_length:
        length_instruction = f"\nCONTENT LENGTH PREFERENCE: {content_length} — adapt hook length and depth accordingly."

    voice_instruction = ""
    if voice_profile and isinstance(voice_profile, dict):
        vp_tone = voice_profile.get("tone", "")
        vp_sentiment = voice_profile.get("sentiment", "")
        vp_style = voice_profile.get("writingStyle", "")
        vp_theme = voice_profile.get("primaryTheme", "")
        vp_keywords = ", ".join((voice_profile.get("keywords") or [])[:5])
        if vp_tone or vp_style:
            voice_instruction = f"""
VOICE PROFILE TO MATCH (replicate this writing style):
- Tone: {vp_tone} / {vp_sentiment}
- Style: {vp_style}
- Theme: {vp_theme}
- Signature keywords: {vp_keywords}"""

    return f"""You are a world-class social media copywriter who has written hooks for viral posts with millions of impressions.

TASK: Generate {count} scroll-stopping hooks about: "{topic}"

HOOK PSYCHOLOGY FRAMEWORK — Every great hook uses at least one:
1. CURIOSITY GAP: Tease a surprising outcome without revealing it ("I stopped doing X... here's what happened")
2. PATTERN INTERRUPT: Challenge a common belief ("Everyone says X, but data shows the opposite")
3. SPECIFICITY: Use precise numbers and details, never vague claims ("3 clients. 47 days. $2.1M in pipeline.")
4. EMOTIONAL TRIGGER: Tap into fear, ambition, frustration, or relief
5. IDENTITY HOOK: Make the reader feel seen ("If you're a founder who can't stop checking Slack at 11 PM...")
6. AUTHORITY SIGNAL: Demonstrate expertise without bragging ("After 200+ campaigns, I noticed one pattern")

LANGUAGE: {language} — {lang_instruction}
TONE: {tone}{length_instruction}{voice_instruction}

PLATFORM-SPECIFIC RULES:
{json.dumps(platform_data, ensure_ascii=False)}

Platform mastery:
- Twitter: Maximum punch in minimum words. First 5 words decide if they read. Use line breaks for rhythm. Stay under {twitter_max_chars} chars.
- LinkedIn: Open with a bold first line (it's the preview). Create a "read more" moment. Professional but human.
- Medium: Lead with intellectual curiosity. Promise a transformation or insight worth 5 minutes of reading.

STRICT RULES:
- Each hook MUST directly relate to "{topic}" — no generic motivational filler
- NO fake statistics or made-up percentages
- NO cliché openings ("In today's world...", "Did you know...", "As a...")
- NO two hooks should start with the same word or structure
- Vary hook types: use at least 3 different types from the framework above
- Score honestly: 80-85 = solid, 86-90 = strong, 91-95 = excellent, 96-98 = exceptional
- ALL content MUST be written in {language}
- The "text" field of every hook MUST be in {language} — not English (unless {language} IS English)
- The "reason" field can stay in English

Return ONLY valid JSON, no markdown, no code fences:
{{
  "hooks": [
    {{
      "text": "hook text here",
      "type": "question|bold-statement|contrarian|story|statistic|curiosity|urgency|how-to",
      "score": 91,
      "platform": "linkedin",
      "reason": "1-sentence explanation of which psychology principle makes this work"
    }}
  ]
}}
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


def call_openrouter(topic, platforms, language="fr", tone="dynamic", count=5, temperature=0.9, model=None, content_length=None, voice_profile=None):
    api_key = current_app.config.get("OPENROUTER_API_KEY")
    default_model = current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    use_model = model or default_model
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")

    if not api_key:
        raise ValueError("OPENROUTER_API_KEY manquant dans la configuration.")

    prompt = build_prompt(
        topic=topic,
        platforms=platforms,
        language=language,
        tone=tone,
        count=count,
        content_length=content_length,
        voice_profile=voice_profile
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
            "model": use_model,
            "messages": [
                {
                    "role": "system",
                    "content": f"You generate high-quality social media hooks in {language} and return strict JSON only. ALL hook text MUST be written in {language}."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": temperature,
            "max_tokens": 2000
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
        content_length = payload.get("contentLength")
        voice_profile = payload.get("voiceProfile")
        req_model = payload.get("model")

        try:
            req_temperature = float(payload.get("temperature", 0.9))
            req_temperature = max(0.0, min(2.0, req_temperature))
        except (TypeError, ValueError):
            req_temperature = 0.9

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
            count=count,
            temperature=req_temperature,
            model=req_model,
            content_length=content_length,
            voice_profile=voice_profile
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
        content_length = payload.get("contentLength")
        voice_profile = payload.get("voiceProfile")
        req_model = payload.get("model")

        try:
            req_temperature = float(payload.get("temperature", 0.9))
            req_temperature = max(0.0, min(2.0, req_temperature))
        except (TypeError, ValueError):
            req_temperature = 0.9

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
            count=1,
            temperature=req_temperature,
            model=req_model,
            content_length=content_length,
            voice_profile=voice_profile
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