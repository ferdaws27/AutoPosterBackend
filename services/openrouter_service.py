import json
import re
import requests
from flask import current_app

PLATFORM_RULES = {
    "twitter": {
        "max_chars": 280,
        "style": "short, punchy, curiosity-driven"
    },
    "linkedin": {
        "max_chars": 300,
        "style": "professional, sharp, authority-building"
    },
    "medium": {
        "max_chars": 400,
        "style": "insightful, narrative, intellectually engaging"
    }
}

def build_prompt(topic, platforms, language="fr", tone="dynamic", count=5):
    platform_data = [
        {
            "platform": p,
            "max_chars": PLATFORM_RULES.get(p, {}).get("max_chars", 300),
            "style": PLATFORM_RULES.get(p, {}).get("style", "engaging")
        }
        for p in platforms
    ]

    return f"""
You are an elite copywriter specialized in social media hooks.

Generate {count} hooks about:
"{topic}"

Constraints:
- Language: {language}
- Tone: {tone}
- Hooks must be logical, dynamic, specific, and engaging
- Avoid generic wording
- Avoid fake statistics
- Avoid repetitive openings
- Return valid JSON only
- No markdown

Platforms:
{json.dumps(platform_data, ensure_ascii=False)}

Return:
{{
  "hooks": [
    {{
      "text": "hook text",
      "type": "question",
      "score": 91,
      "platform": "linkedin",
      "reason": "why it works"
    }}
  ]
}}
"""

def call_openrouter(topic, platforms, language="fr", tone="dynamic", count=5):
    prompt = build_prompt(topic, platforms, language, tone, count)

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {current_app.config['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": current_app.config["FRONTEND_URL"],
            "X-Title": "Autoposter Hook Generator"
        },
        json={
            "model": current_app.config["OPENROUTER_MODEL"],
            "messages": [
                {
                    "role": "system",
                    "content": "You return strict JSON only."
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
        raise ValueError(f"OpenRouter error: {response.text}")

    data = response.json()
    content = data["choices"][0]["message"]["content"]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError("Invalid JSON returned by model")
        parsed = json.loads(match.group(0))

    hooks = parsed.get("hooks", [])
    normalized = []

    for i, hook in enumerate(hooks):
        platform = hook.get("platform")
        if platform not in platforms:
            platform = platforms[i % len(platforms)]

        normalized.append({
            "text": str(hook.get("text", "")).strip(),
            "type": str(hook.get("type", "curiosity")).strip(),
            "score": max(80, min(98, int(hook.get("score", 88)))),
            "platform": platform,
            "reason": str(hook.get("reason", "")).strip()
        })

    return normalized
