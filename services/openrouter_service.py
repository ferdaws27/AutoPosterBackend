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

    twitter_max_chars = PLATFORM_RULES.get('twitter', {}).get('max_chars', 280)

    return f"""You are a world-class social media copywriter who has written hooks for viral posts with millions of impressions.

TASK: Generate {count} scroll-stopping hooks about: "{topic}"

HOOK PSYCHOLOGY FRAMEWORK — Every great hook uses at least one:
1. CURIOSITY GAP: Tease a surprising outcome without revealing it ("I stopped doing X... here's what happened")
2. PATTERN INTERRUPT: Challenge a common belief ("Everyone says X, but data shows the opposite")
3. SPECIFICITY: Use precise numbers and details, never vague claims ("3 clients. 47 days. $2.1M in pipeline.")
4. EMOTIONAL TRIGGER: Tap into fear, ambition, frustration, or relief
5. IDENTITY HOOK: Make the reader feel seen ("If you're a founder who can't stop checking Slack at 11 PM...")
6. AUTHORITY SIGNAL: Demonstrate expertise without bragging ("After 200+ campaigns, I noticed one pattern")

LANGUAGE: {language}
TONE: {tone}

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
                    "content": "You generate high-quality social media hooks and return strict JSON only. No markdown, no code fences."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.9,
            "max_tokens": 2000
        },
        timeout=60
    )

    if response.status_code == 402:
        raise ValueError("OpenRouter credits exhausted. Please recharge at https://openrouter.ai/settings/credits")
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
