import json
import re

import requests
from flask import Blueprint, current_app, jsonify, request

ai_ideas_bp = Blueprint("ai_ideas", __name__)

GENERATION_THEMES = [
    {
        "phase": "découverte",
        "focus": "tendances émergentes et innovations récentes",
        "angle": "ce qui est nouveau et surprenant",
    },
    {
        "phase": "approfondissement",
        "focus": "stratégies avancées et techniques concrètes",
        "angle": "comment appliquer et optimiser",
    },
    {
        "phase": "spécialisation",
        "focus": "niches spécifiques et expertises pointues",
        "angle": "sujets techniques et avancés",
    },
    {
        "phase": "expérimentation",
        "focus": "approches non conventionnelles et tests",
        "angle": "essayer ce que les autres ne font pas",
    },
    {
        "phase": "domination",
        "focus": "stratégies de leadership et d'autorité",
        "angle": "devenir la référence dans son domaine",
    },
]


@ai_ideas_bp.route("/generate", methods=["POST"])
def generate_ideas():
    try:
        data = request.get_json() or {}
        generation_count = int(data.get("generationCount", 1))
        model = data.get("model", current_app.config["OPENROUTER_MODEL"])
        temperature = float(data.get("temperature", 0.9))

        theme_index = (generation_count - 1) % len(GENERATION_THEMES)
        current_theme = GENERATION_THEMES[theme_index]

        from datetime import datetime

        date_str = datetime.now().strftime("%A %d %B %Y")

        prompt = f"""Tu es un expert en marketing digital et création de contenu. C'est la GÉNÉRATION {generation_count}.

CONTEXTE: {date_str}
PHASE ACTUELLE: {current_theme['phase']}
FOCUS SPÉCIFIQUE: {current_theme['focus']}
ANGLE D'APPROCHE: {current_theme['angle']}

GÉNÈRE 5 idées de contenu UNIQUEMENT pour cette phase {current_theme['phase']}.
Ces idées doivent être COMPLÈTEMENT DIFFÉRENTES des générations précédentes.

FORMAT JSON EXACT:
[
  {{
    "category": "Trending|Insights|Growth|Strategy|Tips|Tech|Business",
    "platform": "twitter|linkedin|medium",
    "title": "TITRE SPÉCIFIQUE (max 60 caractères)",
    "desc": "Description avec VALEUR CONCRÈTE (max 150 caractères)",
    "status": "Scheduled|Review|Draft"
  }}
]

IMPORTANT: Sois SPÉCIFIQUE à cette phase. Retourne UNIQUEMENT le JSON valide avec 5 objets."""

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
                "title": str(idea.get("title", "Nouvelle idée"))[:80],
                "desc": str(idea.get("desc", "Description à venir"))[:200],
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
