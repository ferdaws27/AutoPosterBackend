import json
import re

import requests
from flask import Blueprint, current_app, jsonify, request

ai_ideas_bp = Blueprint("ai_ideas", __name__)

GENERATION_THEMES = [
    {
        "phase": "discovery",
        "focus": "emerging trends and recent innovations",
        "angle": "what is new and surprising",
    },
    {
        "phase": "deep-dive",
        "focus": "advanced strategies and concrete techniques",
        "angle": "how to apply and optimize",
    },
    {
        "phase": "specialization",
        "focus": "specific niches and sharp expertise",
        "angle": "technical and advanced topics",
    },
    {
        "phase": "experimentation",
        "focus": "unconventional approaches and tests",
        "angle": "try what others don't",
    },
    {
        "phase": "domination",
        "focus": "leadership and authority strategies",
        "angle": "become the reference in your field",
    },
]


@ai_ideas_bp.route("/generate", methods=["POST"])
def generate_ideas():
    try:
        data = request.get_json() or {}
        generation_count = int(data.get("generationCount", 1))
        model = data.get("model", current_app.config["OPENROUTER_MODEL"])
        temperature = float(data.get("temperature", 0.9))
        tone = data.get("tone", "friendly")
        creativity = data.get("creativity", "Balanced")
        content_length = data.get("contentLength", "Medium (100–200 words)")
        voice_profile = data.get("voiceProfile")
        language = data.get("language", "en")

        theme_index = (generation_count - 1) % len(GENERATION_THEMES)
        current_theme = GENERATION_THEMES[theme_index]

        from datetime import datetime

        date_str = datetime.now().strftime("%A %d %B %Y")

        # Resolve language name from code
        lang_map = {
            "fr": "French", "en": "English", "ar": "Arabic",
            "es": "Spanish", "de": "German", "pt": "Portuguese",
            "it": "Italian", "nl": "Dutch", "tr": "Turkish",
            "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
            "hi": "Hindi", "ru": "Russian",
        }
        lang_code = language.split("-")[0].lower() if language else "en"
        lang_name = lang_map.get(lang_code, "English")

        # Build voice context
        voice_context = ""
        if voice_profile:
            voice_context = f"""\nUSER'S VOICE PROFILE (match this style):
- Tone: {voice_profile.get('tone', '')}/{voice_profile.get('sentiment', '')}
- Style: {voice_profile.get('writingStyle', '')}
- Theme: {voice_profile.get('primaryTheme', '')}
- Keywords: {', '.join((voice_profile.get('keywords') or [])[:5])}"""

        prompt = f"""You are an expert in digital marketing and content creation. This is GENERATION {generation_count}.

CONTEXT: {date_str}
CURRENT PHASE: {current_theme['phase']}
SPECIFIC FOCUS: {current_theme['focus']}
APPROACH ANGLE: {current_theme['angle']}

USER PREFERENCES:
- Tone: {tone}
- Creativity: {creativity}
- Content length: {content_length}{voice_context}

GENERATE 5 content ideas SPECIFICALLY for this {current_theme['phase']} phase.
Ideas must be COMPLETELY DIFFERENT from previous generations.
Ideas should match the user's tone ({tone}) and creativity level ({creativity}).

CRITICAL LANGUAGE RULE — HIGHEST PRIORITY:
The user's language is {lang_name}. You MUST write ALL "title" and "desc" fields ENTIRELY in {lang_name}.
- If {lang_name} is French → titles and descriptions in French
- If {lang_name} is English → titles and descriptions in English  
- If {lang_name} is Arabic → titles and descriptions in Arabic
- NEVER mix languages. NEVER default to English if the language is different.
- The JSON keys (category, platform, status) stay in English. Only "title" and "desc" values must be in {lang_name}.

EXACT JSON FORMAT:
[
  {{
    "category": "Trending|Insights|Growth|Strategy|Tips|Tech|Business",
    "platform": "twitter|linkedin|medium",
    "title": "SPECIFIC TITLE in {lang_name} (max 60 chars)",
    "desc": "Description in {lang_name} with CONCRETE VALUE (max 150 chars)",
    "status": "Scheduled|Review|Draft"
  }}
]

IMPORTANT: Be SPECIFIC to this phase. Return ONLY valid JSON with 5 objects."""

        api_key = current_app.config["OPENROUTER_API_KEY"]
        if not api_key:
            return jsonify({"success": False, "error": "OpenRouter API key not configured on server"}), 500

        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": current_app.config.get("BACKEND_URL", "http://127.0.0.1:5000"),
                "X-Title": "AutoPoster - AI Ideas Generator",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 1000,
                "top_p": 0.95,
            },
            timeout=60,
        )

        if response.status_code != 200:
            return jsonify({"success": False, "error": f"OpenRouter error: {response.status_code}"}), 502

        ai_content = response.json()["choices"][0]["message"]["content"]

        try:
            ideas = json.loads(ai_content)
        except json.JSONDecodeError:
            json_match = re.search(r"\[[\s\S]*\]", ai_content)
            if json_match:
                ideas = json.loads(json_match.group(0))
            else:
                return jsonify({"success": False, "error": "Invalid response format from AI"}), 502

        formatted = []
        for i, idea in enumerate(ideas):
            formatted.append({
                "category": str(idea.get("category", "Strategy"))[:30],
                "platform": idea.get("platform", "twitter") if idea.get("platform") in ("twitter", "linkedin", "medium") else "twitter",
                "title": str(idea.get("title", "New idea"))[:80],
                "desc": str(idea.get("desc", "Description coming soon"))[:200],
                "status": idea.get("status", "Draft") if idea.get("status") in ("Scheduled", "Review", "Draft") else "Draft",
            })

        return jsonify({
            "success": True,
            "ideas": formatted,
            "phase": current_theme["phase"],
            "generationCount": generation_count,
        })

    except Exception as e:
        current_app.logger.error(f"AI ideas generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
