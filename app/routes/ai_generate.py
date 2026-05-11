import json
import re
import unicodedata

import requests
from flask import Blueprint, current_app, jsonify, request

ai_generate_bp = Blueprint("ai_generate", __name__)


def detect_language(text):
    """Detect language from text using character/word analysis."""
    if not text:
        return "English"

    # Check for Arabic characters
    arabic_count = sum(1 for c in text if '\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F' or '\uFB50' <= c <= '\uFDFF' or '\uFE70' <= c <= '\uFEFF')
    if arabic_count > len(text) * 0.1:
        return "Arabic"

    # Check for French indicators - VERY AGGRESSIVE DETECTION
    french_chars = sum(1 for c in text if c in 'àâäéèêëïîôùûüçœæÀÂÄÉÈÊËÏÎÔÙÛÜÇŒÆ')
    french_words = ['les', 'des', 'une', 'est', 'dans', 'pour', 'sur', 'avec', 'qui', 'que',
                    'pas', 'sont', 'mais', 'aussi', 'cette', 'tout', 'fait', 'comme', 'nous',
                    'leur', 'entre', 'très', 'être', 'avoir', 'faire', 'peut', 'plus', 'bien',
                    'comment', 'pourquoi', 'quand', 'où', 'donc', 'alors', 'parce', 'je', 'tu',
                    'il', 'elle', 'on', 'vous', 'ils', 'elles', 'mon', 'ton', 'son', 'ma', 'ta',
                    'sa', 'mes', 'tes', 'ses', 'notre', 'votre', 'leur', 'nos', 'vos', 'leurs',
                    'le', 'la', 'un', 'du', 'au', 'aux', 'de', 'en', 'par', 'sans', 'avec',
                    'pour', 'sur', 'sous', 'vers', 'chez', 'dans', 'y', 'en', 'ne', 'ni', 'or',
                    'car', 'si', 'comme', 'lorsque', 'puisque', 'quoique', 'bien', 'mal',
                    'peu', 'beaucoup', 'trop', 'assez', 'tel', 'telle', 'tels', 'telles',
                    'cet', 'cette', 'ces', 'ce', 'ces', 'aucun', 'aucune', 'aucuns', 'aucunes',
                    'chaque', 'plusieurs', 'certains', 'certaines', 'tout', 'tous', 'toute',
                    'toutes', 'rien', 'quelque', 'quelques', 'quelqu\'un', 'personne',
                    'intelligence', 'artificielle', 'données', 'numérique', 'technologie',
                    'développement', 'création', 'monde', 'nouveau', 'nouvelle', 'importante',
                    'changement', 'changer', 'futur', 'avenir', 'solution', 'problème']
    words = re.findall(r'\b\w+\b', text.lower())
    french_word_count = sum(1 for w in words if w in french_words)
    # FORCE FRENCH DETECTION: Any French char OR any French word (10% threshold) OR 1+ French word in any text
    if french_chars > 0 or (len(words) > 0 and french_word_count >= 1) or (len(words) > 0 and french_word_count / len(words) > 0.1):
        return "French"

    # Check for Spanish
    spanish_chars = sum(1 for c in text if c in 'ñáéíóúüÑÁÉÍÓÚÜ¿¡')
    spanish_words = ['los', 'las', 'una', 'del', 'que', 'por', 'con', 'para', 'como', 'pero', 'más', 'esta', 'esto']
    spanish_word_count = sum(1 for w in words if w in spanish_words)
    if spanish_chars > 0 or (len(words) > 3 and spanish_word_count >= 2):
        return "Spanish"

    # Check for German
    german_words = ['der', 'die', 'das', 'und', 'ist', 'ein', 'eine', 'für', 'mit', 'auf', 'nicht', 'sich', 'auch', 'über']
    german_word_count = sum(1 for w in words if w in german_words)
    if len(words) > 3 and german_word_count >= 2:
        return "German"

    return "English"


@ai_generate_bp.route("/", methods=["POST"])
def generate():
    """Generic AI text generation proxy.

    Accepts: { prompt, model?, temperature?, max_tokens? }
    Returns: { success, content }
    """
    try:
        data = request.get_json() or {}
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"success": False, "error": "prompt is required"}), 400

        model = data.get("model", current_app.config["OPENROUTER_MODEL"])
        temperature = float(data.get("temperature", 0.7))
        max_tokens = int(data.get("max_tokens", 500))
        system_msg = data.get("system", "")
        # user_content = the raw user text (idea/post), NOT the full prompt with instructions
        user_content = data.get("user_content", "")

        api_key = current_app.config["OPENROUTER_API_KEY"]
        if not api_key:
            return jsonify({"success": False, "error": "OpenRouter API key not configured on server"}), 500

        # Use explicit language from frontend settings if provided, otherwise auto-detect
        explicit_lang = data.get("language", "")
        lang_map = {"fr": "French", "en": "English", "es": "Spanish", "de": "German", "ar": "Arabic", "it": "Italian", "pt": "Portuguese"}
        if explicit_lang and explicit_lang in lang_map:
            detected_lang = lang_map[explicit_lang]
        else:
            detected_lang = detect_language(user_content) if user_content else detect_language(prompt)
        current_app.logger.info(f"Language: {detected_lang} (explicit={explicit_lang}, user_content='{user_content[:50]}...', prompt='{prompt[:50]}...')")

        # Build messages — enforce detected language
        messages = []
        lang_rule = f"You MUST write your ENTIRE response in {detected_lang}. Every word — titles, body, hashtags, CTAs, questions — must be in {detected_lang}. Do NOT use any other language."
        if system_msg:
            messages.append({"role": "system", "content": lang_rule + "\n\n" + system_msg})
        else:
            messages.append({"role": "system", "content": lang_rule})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": current_app.config.get("BACKEND_URL", "http://127.0.0.1:5000"),
                "X-Title": "AutoPoster",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )

        if response.status_code == 402:
            return jsonify({"success": False, "error": "OpenRouter credits exhausted. Please recharge at https://openrouter.ai/settings/credits"}), 402
        if response.status_code != 200:
            return jsonify({"success": False, "error": f"OpenRouter error: {response.status_code}"}), 502

        ai_content = response.json()["choices"][0]["message"]["content"].strip()
        return jsonify({"success": True, "content": ai_content})

    except Exception as e:
        current_app.logger.error(f"AI generate error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
