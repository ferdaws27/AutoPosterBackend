import json
import re

import requests
from flask import Blueprint, current_app, jsonify, request

ai_generate_bp = Blueprint("ai_generate", __name__)


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

        api_key = current_app.config["OPENROUTER_API_KEY"]
        if not api_key:
            return jsonify({"success": False, "error": "OpenRouter API key not configured on server"}), 500

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
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60,
        )

        if response.status_code != 200:
            return jsonify({"success": False, "error": f"OpenRouter error: {response.status_code}"}), 502

        ai_content = response.json()["choices"][0]["message"]["content"].strip()
        return jsonify({"success": True, "content": ai_content})

    except Exception as e:
        current_app.logger.error(f"AI generate error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
