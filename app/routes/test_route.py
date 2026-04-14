from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from collections import defaultdict
from bson import ObjectId
import random
import requests as http_requests
import json
import re

test_bp = Blueprint("test", __name__)

PERSONAS = ["Entrepreneurs", "AI Students", "Writers", "Investors"]
PLATFORMS = ["LinkedIn", "Twitter", "Medium"]
LOCATIONS = ["USA", "UK", "Canada", "Germany", "France", "Tunisia"]
INDUSTRIES = ["Tech", "Marketing", "Finance", "Education"]

COMMENTS = [
    "Super post !",
    "Très intéressant !",
    "J'adore !",
    "Bien dit !",
    "Merci pour le partage !",
    "lol",
    "parfaitement d'accord !",
    "Très utile, merci !",
]

# -------------------------------
# PARSE DATE
# -------------------------------
def parse_schedule_date(schedule_date):
    if not schedule_date:
        return None

    if isinstance(schedule_date, datetime):
        return schedule_date.replace(tzinfo=None)

    if isinstance(schedule_date, str):
        s = schedule_date.strip()

        # YYYY-MM-DD (le plus courant)
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            pass

        # ISO avec Z ou timezone offset
        try:
            s_clean = re.sub(r'Z$', '', s)
            s_clean = re.sub(r'\+\d{2}:\d{2}$', '', s_clean).strip()
            return datetime.fromisoformat(s_clean)
        except ValueError:
            pass

        # Regex fallback : extraire YYYY-MM-DD dans n'importe quel string
        match = re.search(r'(\d{4}-\d{2}-\d{2})', s)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d")
            except ValueError:
                pass

    return None


# Hour weights for realistic engagement distribution
HOUR_WEIGHTS = {
    0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 2,
    6: 4, 7: 7, 8: 12, 9: 15, 10: 13, 11: 10,
    12: 14, 13: 12, 14: 16, 15: 13, 16: 10, 17: 11,
    18: 9, 19: 7, 20: 6, 21: 5, 22: 3, 23: 2
}

# Platform weights per content type — which platforms each content type performs best on
PLATFORM_WEIGHTS_BY_TYPE = {
    "tutorial":      {"LinkedIn": 50, "Twitter": 20, "Medium": 30},
    "story":         {"LinkedIn": 25, "Twitter": 50, "Medium": 25},
    "insight":       {"LinkedIn": 45, "Twitter": 35, "Medium": 20},
    "deep_dive":     {"LinkedIn": 30, "Twitter": 10, "Medium": 60},
    "motivational":  {"LinkedIn": 40, "Twitter": 45, "Medium": 15},
    "news":          {"LinkedIn": 20, "Twitter": 60, "Medium": 20},
    "short_tip":     {"LinkedIn": 30, "Twitter": 55, "Medium": 15},
    "opinion":       {"LinkedIn": 35, "Twitter": 50, "Medium": 15},
    "analysis":      {"LinkedIn": 40, "Twitter": 15, "Medium": 45},
    "case_study":    {"LinkedIn": 55, "Twitter": 15, "Medium": 30},
    "unclassified":  {"LinkedIn": 34, "Twitter": 33, "Medium": 33},
}

# Persona weights per content type — who engages with what
# Widened gaps so each persona has a clear dominant content type
PERSONA_WEIGHTS_BY_TYPE = {
    "tutorial":      {"Entrepreneurs": 10, "AI Students": 65, "Writers": 5,  "Investors": 20},
    "story":         {"Entrepreneurs": 10, "AI Students": 5,  "Writers": 70, "Investors": 15},
    "insight":       {"Entrepreneurs": 55, "AI Students": 15, "Writers": 10, "Investors": 20},
    "deep_dive":     {"Entrepreneurs": 10, "AI Students": 60, "Writers": 10, "Investors": 20},
    "motivational":  {"Entrepreneurs": 60, "AI Students": 10, "Writers": 20, "Investors": 10},
    "news":          {"Entrepreneurs": 15, "AI Students": 10, "Writers": 10, "Investors": 65},
    "short_tip":     {"Entrepreneurs": 50, "AI Students": 25, "Writers": 15, "Investors": 10},
    "opinion":       {"Entrepreneurs": 15, "AI Students": 5,  "Writers": 65, "Investors": 15},
    "analysis":      {"Entrepreneurs": 10, "AI Students": 15, "Writers": 5,  "Investors": 70},
    "case_study":    {"Entrepreneurs": 15, "AI Students": 10, "Writers": 5,  "Investors": 70},
    "unclassified":  {"Entrepreneurs": 30, "AI Students": 30, "Writers": 20, "Investors": 20},
}

# Location weights per platform — geographic audience per platform
LOCATION_WEIGHTS_BY_PLATFORM = {
    "LinkedIn": {"USA": 35, "UK": 20, "Canada": 15, "Germany": 12, "France": 10, "Tunisia": 8},
    "Twitter":  {"USA": 40, "UK": 15, "Canada": 10, "Germany": 8, "France": 12, "Tunisia": 15},
    "Medium":   {"USA": 30, "UK": 18, "Canada": 12, "Germany": 15, "France": 15, "Tunisia": 10},
}

# Industry weights per persona — what industries each persona is in
INDUSTRY_WEIGHTS_BY_PERSONA = {
    "Entrepreneurs": {"Tech": 40, "Marketing": 30, "Finance": 20, "Education": 10},
    "AI Students":   {"Tech": 55, "Marketing": 10, "Finance": 10, "Education": 25},
    "Writers":       {"Tech": 15, "Marketing": 35, "Finance": 10, "Education": 40},
    "Investors":     {"Tech": 30, "Marketing": 15, "Finance": 45, "Education": 10},
}

# Engagement rate multiplier per content type (how many of the 300 sample actually interact)
ENGAGEMENT_RATE_BY_TYPE = {
    "tutorial":      0.75,
    "story":         0.85,
    "insight":       0.60,
    "deep_dive":     0.45,
    "motivational":  0.90,
    "news":          0.35,
    "short_tip":     0.70,
    "opinion":       0.55,
    "analysis":      0.40,
    "case_study":    0.50,
    "unclassified":  0.55,
}

# Interaction type distribution per content type
INTERACTION_TYPE_BY_CONTENT = {
    "tutorial":      {"like": 0.50, "comment": 0.30, "share": 0.20},
    "story":         {"like": 0.55, "comment": 0.35, "share": 0.10},
    "insight":       {"like": 0.60, "comment": 0.25, "share": 0.15},
    "deep_dive":     {"like": 0.40, "comment": 0.35, "share": 0.25},
    "motivational":  {"like": 0.70, "comment": 0.20, "share": 0.10},
    "news":          {"like": 0.45, "comment": 0.15, "share": 0.40},
    "short_tip":     {"like": 0.65, "comment": 0.15, "share": 0.20},
    "opinion":       {"like": 0.40, "comment": 0.45, "share": 0.15},
    "analysis":      {"like": 0.50, "comment": 0.20, "share": 0.30},
    "case_study":    {"like": 0.45, "comment": 0.25, "share": 0.30},
    "unclassified":  {"like": 0.60, "comment": 0.20, "share": 0.20},
}


def _pick_weighted(options_dict):
    """Pick from a dict {option: weight}."""
    items = list(options_dict.keys())
    weights = list(options_dict.values())
    return random.choices(items, weights=weights, k=1)[0]


def _pick_weighted_hour():
    """Pick an hour of day weighted by typical social media engagement patterns."""
    return _pick_weighted(HOUR_WEIGHTS)


# -------------------------------
# GENERATE INTERACTIONS POUR 1 POST
# -------------------------------
def _generate_for_post(post_id_str, schedule_date, now, content_type="unclassified"):
    delta_seconds = int((now - schedule_date).total_seconds())
    delta_days = max(delta_seconds // 86400, 1)
    followers_count = random.randint(1000, 6000)
    audience = [f"follower_{i}" for i in range(followers_count)]
    sample = random.sample(audience, k=min(300, len(audience)))

    # Get content-type-specific weights
    ct = content_type if content_type in ENGAGEMENT_RATE_BY_TYPE else "unclassified"
    engage_rate = ENGAGEMENT_RATE_BY_TYPE[ct]
    platform_w = PLATFORM_WEIGHTS_BY_TYPE.get(ct, PLATFORM_WEIGHTS_BY_TYPE["unclassified"])
    persona_w = PERSONA_WEIGHTS_BY_TYPE.get(ct, PERSONA_WEIGHTS_BY_TYPE["unclassified"])
    interaction_dist = INTERACTION_TYPE_BY_CONTENT.get(ct, INTERACTION_TYPE_BY_CONTENT["unclassified"])

    interactions = []

    for user_id in sample:
        # Skip based on content-type engagement rate
        if random.random() > engage_rate:
            continue

        # Pick a realistic hour, then a random day offset & minute
        hour = _pick_weighted_hour()
        day_offset = random.randint(0, delta_days - 1)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        interaction_time = schedule_date + timedelta(days=day_offset, hours=hour - schedule_date.hour, minutes=minute, seconds=second)
        # Clamp to valid range
        if interaction_time < schedule_date:
            interaction_time = schedule_date + timedelta(hours=hour, minutes=minute)
        if interaction_time > now:
            interaction_time = now - timedelta(minutes=random.randint(1, 60))

        # Pick interaction type based on content type
        roll = random.random()
        if roll < interaction_dist["like"]:
            interaction = {"type": "like"}
        elif roll < interaction_dist["like"] + interaction_dist["comment"]:
            interaction = {"type": "comment", "content": random.choice(COMMENTS)}
        else:
            interaction = {"type": "share"}

        # Pick platform, persona, location, industry — all weighted
        platform = _pick_weighted(platform_w)
        persona = _pick_weighted(persona_w)
        location_w = LOCATION_WEIGHTS_BY_PLATFORM.get(platform, LOCATION_WEIGHTS_BY_PLATFORM["LinkedIn"])
        industry_w = INDUSTRY_WEIGHTS_BY_PERSONA.get(persona, INDUSTRY_WEIGHTS_BY_PERSONA["Entrepreneurs"])

        interaction.update({
            "post_id": post_id_str,
            "user_id": user_id,
            "created_at": interaction_time,
            "persona": persona,
            "platform": platform,
            "location": _pick_weighted(location_w),
            "industry": _pick_weighted(industry_w)
        })
        interactions.append(interaction)

    # Garantir au moins 1 interaction
    if not interactions:
        interactions.append({
            "post_id": post_id_str,
            "user_id": "auto_system",
            "type": "like",
            "created_at": schedule_date,
            "persona": random.choice(PERSONAS),
            "platform": random.choice(PLATFORMS),
            "location": random.choice(LOCATIONS),
            "industry": random.choice(INDUSTRIES)
        })

    return interactions


# -------------------------------
# ROUTE 1 : RESET + GENERATE
# Supprime tout puis regenère pour
# tous les posts dont date <= now
# APPELER CETTE ROUTE EN PREMIER
# -------------------------------
@test_bp.route("/reset-and-generate")
def reset_and_generate():
    now = datetime.utcnow()
    posts = list(current_app.mongo.posts.find())

    # Supprimer toutes les interactions existantes
    deleted = current_app.mongo.interactions.delete_many({})

    total_interactions = 0
    processed = []
    skipped = []

    for post in posts:
        raw_date = post.get("schedule_date")
        schedule_date = parse_schedule_date(raw_date)
        post_id_str = str(post["_id"])

        print(f"[RESET-GEN] {post_id_str} | raw={raw_date!r} | parsed={schedule_date}")

        if schedule_date is None:
            skipped.append({"post_id": post_id_str, "reason": "no_date"})
            continue

        if schedule_date > now:
            skipped.append({
                "post_id": post_id_str,
                "reason": "future",
                "schedule_date": schedule_date.isoformat()
            })
            continue

        interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
        current_app.mongo.interactions.insert_many(interactions)
        total_interactions += len(interactions)
        processed.append({
            "post_id": post_id_str,
            "content_preview": post.get("content", "")[:40],
            "interactions_inserted": len(interactions)
        })

    return jsonify({
        "message": "Reset + génération terminée",
        "now_utc": now.isoformat(),
        "interactions_deleted": deleted.deleted_count,
        "total_interactions_created": total_interactions,
        "posts_processed": processed,
        "posts_skipped": skipped
    })


# -------------------------------
# ROUTE 2 : GENERATE ONLY
# Ajoute seulement pour les posts
# sans interactions existantes
# -------------------------------
@test_bp.route("/generate-realistic-interactions")
def generate_realistic_interactions():
    now = datetime.utcnow()
    posts = list(current_app.mongo.posts.find())

    total_interactions = 0
    processed = []
    skipped = []

    for post in posts:
        raw_date = post.get("schedule_date")
        schedule_date = parse_schedule_date(raw_date)
        post_id_str = str(post["_id"])

        print(f"[GEN] {post_id_str} | raw={raw_date!r} | parsed={schedule_date}")

        if schedule_date is None:
            skipped.append({"post_id": post_id_str, "reason": "no_date"})
            continue

        if schedule_date > now:
            skipped.append({
                "post_id": post_id_str,
                "reason": "future",
                "schedule_date": schedule_date.isoformat()
            })
            continue

        # Skip si interactions déjà présentes
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing > 0:
            skipped.append({
                "post_id": post_id_str,
                "reason": "already_has_interactions",
                "count": existing
            })
            continue

        interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
        current_app.mongo.interactions.insert_many(interactions)
        total_interactions += len(interactions)
        processed.append({
            "post_id": post_id_str,
            "content_preview": post.get("content", "")[:40],
            "interactions_inserted": len(interactions)
        })

    return jsonify({
        "message": "Génération terminée",
        "now_utc": now.isoformat(),
        "total_interactions_created": total_interactions,
        "posts_processed": processed,
        "posts_skipped": skipped
    })


# -------------------------------
# ROUTE 3 : POSTS WITH INTERACTIONS
# -------------------------------
@test_bp.route("/posts-with-interactions")
def posts_with_interactions():
    posts = list(current_app.mongo.posts.find())
    result = []

    for post in posts:
        post_id_str = str(post["_id"])

        interactions = list(
            current_app.mongo.interactions.find({"post_id": post_id_str})
        )

        likes    = sum(1 for i in interactions if i["type"] == "like")
        comments = sum(1 for i in interactions if i["type"] == "comment")
        shares   = sum(1 for i in interactions if i["type"] == "share")

        for i in interactions:
            i["_id"]     = str(i["_id"])
            i["post_id"] = str(i["post_id"])
            if isinstance(i.get("created_at"), datetime):
                i["created_at"] = i["created_at"].isoformat()

        result.append({
            "post_id":              post_id_str,
            "content":              post.get("content", "")[:80],
            "schedule_date":        post.get("schedule_date"),
            "total_interactions":   len(interactions),
            "likes":                likes,
            "comments":             comments,
            "shares":               shares,
            "interactions_details": interactions
        })

    return jsonify({"posts": result})


# -------------------------------
# ROUTE 4 : AUDIENCE ANALYTICS
# Calcule les distributions persona,
# platform, location, industry +
# engagement rate et active users
# -------------------------------
@test_bp.route("/audience-analytics")
@jwt_required(optional=True)
def audience_analytics():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    persona_count = defaultdict(int)
    platform_count = defaultdict(int)
    location_count = defaultdict(int)
    industry_count = defaultdict(int)
    unique_users = set()

    # Per-persona engagement breakdown
    persona_likes = defaultdict(int)
    persona_comments = defaultdict(int)
    persona_shares = defaultdict(int)

    for i in interactions:
        # Backfill missing profile fields on the fly
        if not i.get("persona"):
            i["persona"] = random.choice(PERSONAS)
            i["platform"] = random.choice(PLATFORMS)
            i["location"] = random.choice(LOCATIONS)
            i["industry"] = random.choice(INDUSTRIES)
            current_app.mongo.interactions.update_one(
                {"_id": i["_id"]},
                {"$set": {
                    "persona": i["persona"],
                    "platform": i["platform"],
                    "location": i["location"],
                    "industry": i["industry"]
                }}
            )

        persona = i["persona"]
        persona_count[persona] += 1
        platform_count[i["platform"]] += 1
        location_count[i["location"]] += 1
        industry_count[i["industry"]] += 1
        unique_users.add(i.get("user_id", ""))

        itype = i.get("type", "like")
        if itype == "like":
            persona_likes[persona] += 1
        elif itype == "comment":
            persona_comments[persona] += 1
        elif itype == "share":
            persona_shares[persona] += 1

    total_interactions = len(interactions)
    total_posts = len(posts) if posts else 1
    engagement_rate = round(total_interactions / total_posts, 2)

    # Generate AI insights based on real data
    insights = []

    # Top persona insight
    if persona_count:
        top_persona = max(persona_count, key=persona_count.get)
        top_pct = round(persona_count[top_persona] / max(total_interactions, 1) * 100)
        insights.append({
            "icon": "fa-users",
            "color": "cyan",
            "title": f"{top_persona} are your most engaged audience",
            "description": f"They represent {top_pct}% of all interactions ({persona_count[top_persona]:,} total)"
        })

    # Top platform insight
    if platform_count:
        top_platform = max(platform_count, key=platform_count.get)
        top_plat_pct = round(platform_count[top_platform] / max(total_interactions, 1) * 100)
        insights.append({
            "icon": "fa-share-nodes",
            "color": "violet",
            "title": f"{top_platform} drives the most engagement",
            "description": f"{top_plat_pct}% of interactions come from {top_platform} ({platform_count[top_platform]:,} interactions)"
        })

    # Top location insight
    if location_count:
        top_location = max(location_count, key=location_count.get)
        top_loc_pct = round(location_count[top_location] / max(total_interactions, 1) * 100)
        insights.append({
            "icon": "fa-globe",
            "color": "teal",
            "title": f"Most of your audience is based in {top_location}",
            "description": f"{top_loc_pct}% of engagers are from {top_location} ({location_count[top_location]:,} interactions)"
        })

    # Top industry insight
    if industry_count:
        top_industry = max(industry_count, key=industry_count.get)
        top_ind_pct = round(industry_count[top_industry] / max(total_interactions, 1) * 100)
        insights.append({
            "icon": "fa-briefcase",
            "color": "yellow",
            "title": f"{top_industry} professionals engage the most",
            "description": f"{top_ind_pct}% of your audience works in {top_industry} ({industry_count[top_industry]:,} interactions)"
        })

    # Build per-persona engagement breakdown
    persona_breakdown = {}
    for p in PERSONAS:
        total_p = persona_count.get(p, 0)
        if total_p > 0:
            persona_breakdown[p] = {
                "total": total_p,
                "likes": persona_likes.get(p, 0),
                "comments": persona_comments.get(p, 0),
                "shares": persona_shares.get(p, 0),
                "like_rate": round(persona_likes.get(p, 0) / total_p * 100),
                "comment_rate": round(persona_comments.get(p, 0) / total_p * 100),
                "share_rate": round(persona_shares.get(p, 0) / total_p * 100),
            }
        else:
            persona_breakdown[p] = {
                "total": 0, "likes": 0, "comments": 0, "shares": 0,
                "like_rate": 0, "comment_rate": 0, "share_rate": 0,
            }

    return jsonify({
        "personas": dict(persona_count),
        "platforms": dict(platform_count),
        "locations": dict(location_count),
        "industries": dict(industry_count),
        "engagement_rate": engagement_rate,
        "active_users": len(unique_users),
        "total_interactions": total_interactions,
        "total_posts": total_posts,
        "insights": insights,
        "persona_breakdown": persona_breakdown
    })


# -------------------------------
# ROUTE 5 : AI PERSONA ANALYSIS
# Sends analytics data to AI for
# deep persona insights
# -------------------------------
@test_bp.route("/ai-persona-analysis")
@jwt_required(optional=True)
def ai_persona_analysis():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    persona_count = defaultdict(int)
    platform_count = defaultdict(int)
    location_count = defaultdict(int)
    industry_count = defaultdict(int)

    for i in interactions:
        persona_count[i.get("persona", "Unknown")] += 1
        platform_count[i.get("platform", "Unknown")] += 1
        location_count[i.get("location", "Unknown")] += 1
        industry_count[i.get("industry", "Unknown")] += 1

    total_interactions = len(interactions)
    total_posts = len(posts) if posts else 1

    # Build prompt with real data
    data_summary = (
        f"Total posts: {total_posts}\n"
        f"Total interactions: {total_interactions}\n"
        f"Engagement rate: {round(total_interactions / total_posts, 2)} interactions/post\n\n"
        f"Persona distribution: {dict(persona_count)}\n"
        f"Platform distribution: {dict(platform_count)}\n"
        f"Location distribution: {dict(location_count)}\n"
        f"Industry distribution: {dict(industry_count)}"
    )

    prompt = f"""You are a senior social media strategist and audience intelligence analyst. Analyze this engagement data to uncover deep audience personas, behavioral patterns, and growth opportunities.

DATA:
{data_summary}

ANALYSIS FRAMEWORK:
1. PERSONA DECODING: Don't just label personas — explain their behavior, motivation, and content preferences
2. ENGAGEMENT PATTERNS: Identify what drives each persona to interact (comment vs like vs share)
3. TIMING INTELLIGENCE: Map personas to their peak activity windows based on platform + industry patterns
4. GROWTH VECTORS: Find the gap between current performance and untapped potential

PERSONA INSIGHT RULES:
- Each persona must have a SPECIFIC, actionable engagement tip (not generic "post more")
- best_content must reference actual content formats (carousel, thread, long-form, video, poll, infographic)
- best_time must include day AND time with timezone reasoning
- growth_potential must be justified by the data, not arbitrary

Respond in strict JSON with this format:
{{
  "persona_insights": [
    {{
      "persona": "persona name",
      "icon": "fontawesome icon class (fa-rocket, fa-graduation-cap, fa-feather, fa-chart-line, fa-briefcase, fa-users, fa-lightbulb, fa-code)",
      "color": "cyan or violet or teal or yellow",
      "engagement_tip": "one specific, actionable tip referencing this persona's behavior pattern",
      "best_content": "specific content format + topic type that resonates with this persona",
      "best_time": "specific day and time like Tuesday 2:00 PM, with brief reasoning",
      "growth_potential": "low/medium/high"
    }}
  ],
  "overall_strategy": "2-3 sentence strategy that connects persona insights into a cohesive content plan. Reference specific data points.",
  "top_opportunity": "1 sentence identifying the single highest-ROI action based on the data"
}}

Only return valid JSON, no markdown."""

    try:
        api_key = current_app.config.get('OPENROUTER_API_KEY')
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured")

        response = http_requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": current_app.config.get("FRONTEND_URL", "http://localhost:5173"),
                "X-Title": "AutoPoster Audience Analyzer"
            },
            json={
                "model": current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": "You are a senior audience intelligence analyst. Decode engagement patterns, identify growth opportunities, and provide data-backed persona insights. Return strict JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=30
        )

        if response.status_code == 402:
            raise ValueError("OpenRouter credits exhausted. Please recharge at https://openrouter.ai/settings/credits")

        result = response.json()

        # Check for API-level errors
        if "error" in result:
            error_msg = result["error"].get("message", str(result["error"])) if isinstance(result["error"], dict) else str(result["error"])
            print(f"[AI-PERSONA] OpenRouter API error: {error_msg}")
            raise ValueError(f"OpenRouter API error: {error_msg}")

        if "choices" not in result or not result["choices"]:
            print(f"[AI-PERSONA] Unexpected API response: {json.dumps(result)[:500]}")
            raise ValueError("OpenRouter returned no choices")

        content = result["choices"][0]["message"]["content"]

        # Clean markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        ai_data = json.loads(content)

        return jsonify({
            "success": True,
            "data": ai_data,
            "data_summary": {
                "personas": dict(persona_count),
                "platforms": dict(platform_count),
                "locations": dict(location_count),
                "industries": dict(industry_count),
                "total_interactions": total_interactions,
                "total_posts": total_posts
            }
        })

    except Exception as e:
        print(f"[AI-PERSONA] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "data_summary": {
                "personas": dict(persona_count),
                "platforms": dict(platform_count),
                "locations": dict(location_count),
                "industries": dict(industry_count),
                "total_interactions": total_interactions,
                "total_posts": total_posts
            }
        }), 500


# -------------------------------
# HELPER: gather user analytics data
# -------------------------------
def _gather_analytics_data():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    user_post_ids = [str(post["_id"]) for post in posts]

    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    persona_count = defaultdict(int)
    platform_count = defaultdict(int)
    location_count = defaultdict(int)
    industry_count = defaultdict(int)

    for i in interactions:
        persona_count[i.get("persona", "Unknown")] += 1
        platform_count[i.get("platform", "Unknown")] += 1
        location_count[i.get("location", "Unknown")] += 1
        industry_count[i.get("industry", "Unknown")] += 1

    total_interactions = len(interactions)
    total_posts = len(posts) if posts else 1

    return {
        "persona_count": dict(persona_count),
        "platform_count": dict(platform_count),
        "location_count": dict(location_count),
        "industry_count": dict(industry_count),
        "total_interactions": total_interactions,
        "total_posts": total_posts,
        "engagement_rate": round(total_interactions / total_posts, 2)
    }


def _build_data_summary(data):
    return (
        f"Total posts: {data['total_posts']}\n"
        f"Total interactions: {data['total_interactions']}\n"
        f"Engagement rate: {data['engagement_rate']} interactions/post\n\n"
        f"Persona distribution: {data['persona_count']}\n"
        f"Platform distribution: {data['platform_count']}\n"
        f"Location distribution: {data['location_count']}\n"
        f"Industry distribution: {data['industry_count']}"
    )


def _call_openrouter(prompt, system_msg="You are an audience analytics expert. Return strict JSON only."):
    api_key = current_app.config.get('OPENROUTER_API_KEY')
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not configured")

    response = http_requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": current_app.config.get("FRONTEND_URL", "http://localhost:5173"),
            "X-Title": "AutoPoster Audience Analyzer"
        },
        json={
            "model": current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        },
        timeout=30
    )

    if response.status_code == 402:
        raise ValueError("OpenRouter credits exhausted. Please recharge at https://openrouter.ai/settings/credits")

    result = response.json()

    if "error" in result:
        error_msg = result["error"].get("message", str(result["error"])) if isinstance(result["error"], dict) else str(result["error"])
        raise ValueError(f"OpenRouter API error: {error_msg}")

    if "choices" not in result or not result["choices"]:
        raise ValueError("OpenRouter returned no choices")

    content = result["choices"][0]["message"]["content"]
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    return json.loads(content)


# -------------------------------
# ROUTE 6 : AI AUDIENCE INSIGHTS
# Generates AI-powered insights
# from real analytics data
# -------------------------------
@test_bp.route("/ai-audience-insights")
@jwt_required(optional=True)
def ai_audience_insights():
    try:
        data = _gather_analytics_data()
        data_summary = _build_data_summary(data)

        prompt = f"""You are a data-driven social media intelligence analyst. Extract non-obvious, actionable insights from this engagement data. Go beyond surface-level observations — find patterns, correlations, and opportunities hidden in the numbers.

DATA:
{data_summary}

INSIGHT GENERATION FRAMEWORK:
1. CORRELATION MINING: Find connections between personas, platforms, locations, and industries
2. ANOMALY DETECTION: Identify surprising patterns (e.g., unusually high engagement from unexpected segments)
3. OPPORTUNITY GAPS: Find underserved segments with high potential
4. COMPETITIVE INTELLIGENCE: What do the platform distributions reveal about audience behavior?

QUALITY RULES FOR EACH INSIGHT:
- Title must be specific and attention-grabbing (not "Good engagement" — instead "Tech Professionals Drive 73% of LinkedIn Shares")
- Description must reference SPECIFIC numbers from the data
- Each insight must suggest a CONCRETE action the user can take
- Insights must cover DIFFERENT dimensions (don't repeat the same angle)
- Prioritize insights by potential business impact

Respond in strict JSON with this format:
{{
  "insights": [
    {{
      "icon": "fontawesome icon class (e.g. fa-users, fa-share-nodes, fa-globe, fa-briefcase, fa-lightbulb, fa-chart-line, fa-fire, fa-bullseye, fa-eye, fa-trophy)",
      "color": "cyan or violet or teal or yellow",
      "title": "specific, data-backed insight title (max 10 words)",
      "description": "1-2 sentence actionable description referencing specific numbers from the data. End with a recommended action."
    }}
  ]
}}

Generate exactly 4-5 unique, data-driven insights. Each must pass this test: "Would a social media manager change their strategy based on this?"

Only return valid JSON, no markdown."""

        ai_data = _call_openrouter(prompt)

        return jsonify({
            "success": True,
            "insights": ai_data.get("insights", []),
            "data_summary": data
        })

    except Exception as e:
        print(f"[AI-INSIGHTS] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# -------------------------------
# ROUTE 7 : AI GENERATE STRATEGY
# Generates a full AI content strategy
# -------------------------------
@test_bp.route("/ai-generate-strategy")
@jwt_required(optional=True)
def ai_generate_strategy():
    try:
        data = _gather_analytics_data()
        data_summary = _build_data_summary(data)

        prompt = f"""You are a senior social media strategist who has managed content strategies for brands with 100K+ followers. Build a comprehensive, data-driven content strategy based on the audience data below.

DATA:
{data_summary}

STRATEGY BUILDING METHODOLOGY:

1. AUDIENCE-FIRST SCHEDULING: Map each persona to optimal posting windows based on their industry, platform preference, and engagement patterns. Don't guess — derive from data.

2. CONTENT MIX OPTIMIZATION: Recommend content types based on what resonates with the actual audience composition. Consider: educational content for professional personas, storytelling for creative personas, data-driven content for analytical personas.

3. PLATFORM STRATEGY: Each platform serves a different purpose in the funnel. Define the role of each platform (awareness, engagement, conversion, thought leadership).

4. QUICK WINS: Identify 3 specific actions that can be implemented THIS WEEK for immediate impact.

QUALITY REQUIREMENTS:
- Every recommendation must reference specific data points
- Posting times must include timezone reasoning based on audience location
- Content mix percentages must add up to 100%
- Quick wins must be concrete (not "post more" — instead "Create a Tuesday 2PM LinkedIn carousel targeting Tech Professionals about [specific topic]")

Respond in strict JSON with this format:
{{
  "posting_schedule": [
    {{
      "persona": "persona name from data",
      "best_time": "specific day and time (e.g. Tuesday 2:00 PM EST)",
      "audience_pct": percentage number based on actual data,
      "tip": "specific posting tip for this persona, referencing their platform and content preferences"
    }}
  ],
  "content_mix": [
    {{
      "type": "content type name (e.g. Educational Carousels, Story-driven Posts, Data Insights, Industry Commentary)",
      "percentage": percentage number (all must sum to 100),
      "description": "why this content type works for YOUR specific audience composition"
    }}
  ],
  "platform_focus": [
    {{
      "platform": "platform name from data",
      "strategy": "1-2 sentence platform-specific strategy referencing which personas are active there"
    }}
  ],
  "overall_strategy": "2-3 sentence cohesive strategy that ties together scheduling, content mix, and platform focus. Reference key data points.",
  "top_opportunity": "1 sentence identifying the single biggest growth lever with expected impact",
  "quick_wins": ["specific actionable quick win 1 with target persona and platform", "specific quick win 2 with content format and timing", "specific quick win 3 with measurable expected outcome"]
}}

Use real numbers from the data. Every recommendation must be traceable to a data point.
Only return valid JSON, no markdown."""

        ai_data = _call_openrouter(prompt)

        return jsonify({
            "success": True,
            "strategy": ai_data,
            "data_summary": data
        })

    except Exception as e:
        print(f"[AI-STRATEGY] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# -------------------------------
# ROUTE 8 : AI CONTENT PREFERENCES
# Generates content type performance
# and optimal posting times per persona
# -------------------------------
@test_bp.route("/ai-content-preferences")
@jwt_required(optional=True)
def ai_content_preferences():
    try:
        data = _gather_analytics_data()
        data_summary = _build_data_summary(data)

        prompt = f"""You are a content performance analyst specializing in social media engagement optimization. Analyze this audience data to determine which content types perform best and when each persona is most active.

DATA:
{data_summary}

ANALYSIS METHODOLOGY:

1. CONTENT TYPE RANKING: Evaluate which content formats would generate the highest engagement given the persona and platform mix. Consider:
   - Professional personas → value educational, data-driven content
   - Creative personas → engage with storytelling, visual content
   - Technical personas → prefer tutorials, deep dives, case studies
   - General audience → responds to tips, motivation, trending topics

2. TIMING OPTIMIZATION: Map each persona to their peak engagement window based on:
   - Industry norms (tech workers = early morning/lunch, marketers = mid-morning, executives = before 9 AM)
   - Platform patterns (LinkedIn peaks Tuesday-Thursday, Twitter is real-time, Medium is weekend reading)
   - Location-based time zones

3. PERFORMANCE METRICS: Estimate engagement rates based on content-persona fit. Higher fit = higher engagement.

QUALITY RULES:
- Content types must be specific formats, not vague categories (e.g., "Step-by-Step Tutorial Threads" not just "Educational")
- Engagement percentages should be realistic (2-15% range for organic social)
- Performance boosts must be comparative and data-referenced
- Each persona gets exactly ONE optimal posting time

Respond in strict JSON with this format:
{{
  "content_types": [
    {{
      "title": "specific content format name (e.g. Tutorial & How-to Threads, Data-Driven Carousels, Behind-the-Scenes Stories)",
      "engagement": "estimated engagement rate as string like 8.4%",
      "percentage": number from 0-100 for progress bar width (highest ranked = 85-95),
      "gradient": "tailwind gradient classes like from-cyan-400 to-violet-400",
      "description": "which personas love this and WHY — reference specific data"
    }}
  ],
  "posting_times": [
    {{
      "icon": "fontawesome icon (fa-rocket, fa-graduation-cap, fa-feather, fa-chart-line, fa-briefcase, fa-users, fa-code, fa-lightbulb)",
      "persona": "persona name from data",
      "time": "optimal day and time (e.g. Tuesday, 2:00 PM)",
      "color": "cyan or violet or teal or yellow",
      "performance": "performance boost vs average (e.g. +73% above average) — based on persona-timing fit"
    }}
  ]
}}

Generate exactly 4 content types ranked by engagement (highest first).
Generate one posting time entry for each persona in the data.
Use gradient values from: "from-cyan-400 to-violet-400", "from-violet-400 to-teal-400", "from-teal-400 to-yellow-400", "from-yellow-400 to-orange-400".
Only return valid JSON, no markdown."""

        ai_data = _call_openrouter(prompt)

        return jsonify({
            "success": True,
            "content_types": ai_data.get("content_types", []),
            "posting_times": ai_data.get("posting_times", []),
            "data_summary": data
        })

    except Exception as e:
        print(f"[AI-CONTENT-PREFS] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# -------------------------------
# ROUTE 9 : DETECT CONTENT TYPE
# Uses OpenRouter AI to classify
# each post into a content_type
# -------------------------------
CONTENT_TYPES = [
    "tutorial", "story", "insight", "case_study", "motivational",
    "short_tip", "news", "opinion", "deep_dive", "analysis"
]

BATCH_SIZE = 10  # posts per API call


def _detect_content_types_batch(posts_batch):
    """Send a batch of posts to OpenRouter and get content_type for each."""
    posts_for_prompt = []
    for p in posts_batch:
        posts_for_prompt.append({
            "id": str(p["_id"]),
            "content": (p.get("content") or "")[:500]
        })

    prompt = f"""You are a precision content classifier. Analyze each post's writing style, structure, intent, and vocabulary to determine its exact content type.

Allowed types: {json.dumps(CONTENT_TYPES)}

Posts to classify:
{json.dumps(posts_for_prompt, ensure_ascii=False)}

CLASSIFICATION SIGNAL PATTERNS:

"tutorial" → Step-by-step instructions, numbered lists, "how to", "here's how", teaching language, actionable steps
"story" → Personal narrative with timeline ("I was...", "When I..."), anecdotes, character arc, emotional journey
"insight" → Key observation, reflective tone ("I realized...", "The truth is...", "What most people miss...")
"case_study" → Real-world example with specific results, metrics, before/after, company/client references
"motivational" → Inspirational language, empowerment, "you can", "believe", "don't give up", mindset-focused
"short_tip" → Quick actionable advice in 1-3 sentences, "Pro tip:", one specific recommendation
"news" → Industry updates, announcements, "just launched", time-sensitive, recent events
"opinion" → Personal stance, "I think", "Hot take:", debate-starting, "Unpopular opinion:"
"deep_dive" → In-depth exploration with multiple sections, comprehensive coverage, 500+ words
"analysis" → Data-driven breakdown, statistics, trends, "the data shows", metrics-heavy comparison

DECISION RULES:
- If it teaches AND tells a story → choose PRIMARY intent
- Short advice (1-3 lines) → "short_tip" regardless of other elements
- Data/metrics as core → "analysis" over "case_study" (case_study needs narrative arc)
- Reflective vs argumentative → "insight" if reflective, "opinion" if argumentative
- Confidence: 0.9+ only when signals are unambiguous, 0.7-0.89 for clear but mixed, 0.5-0.69 for ambiguous

Respond in strict JSON:
{{
  "classifications": [
    {{"id": "post_id", "content_type": "one_of_allowed_types", "confidence": 0.0-1.0}}
  ]
}}

Classify ALL posts. Only return valid JSON, no markdown."""

    return _call_openrouter(
        prompt,
        system_msg="You are a content classification expert. Return strict JSON only."
    )


@test_bp.route("/detect-content-types")
@jwt_required(optional=True)
def detect_content_types():
    """Detect and assign content_type to all posts using AI."""
    current_user_id = get_jwt_identity()

    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    if not posts:
        return jsonify({"success": True, "message": "No posts found", "classified": []})

    classified = []
    errors = []

    # Process in batches
    for i in range(0, len(posts), BATCH_SIZE):
        batch = posts[i:i + BATCH_SIZE]
        try:
            result = _detect_content_types_batch(batch)
            classifications = result.get("classifications", [])

            for cls in classifications:
                post_id = cls.get("id")
                content_type = cls.get("content_type", "").strip().lower()
                confidence = cls.get("confidence", 0)

                # Validate content_type
                if content_type not in CONTENT_TYPES:
                    content_type = "insight"  # safe fallback

                # Update in MongoDB (posts use string _id)
                try:
                    current_app.mongo.posts.update_one(
                        {"_id": post_id},
                        {"$set": {
                            "content_type": content_type,
                            "content_type_confidence": round(float(confidence), 2)
                        }}
                    )
                    # Find matching post for preview
                    post_content = ""
                    for p in batch:
                        if str(p["_id"]) == post_id:
                            post_content = (p.get("content") or "")[:80]
                            break

                    classified.append({
                        "post_id": post_id,
                        "content_type": content_type,
                        "confidence": round(float(confidence), 2),
                        "content_preview": post_content
                    })
                except Exception as update_err:
                    errors.append({"post_id": post_id, "error": str(update_err)})

        except Exception as batch_err:
            print(f"[DETECT-TYPE] Batch error: {batch_err}")
            for p in batch:
                errors.append({"post_id": str(p["_id"]), "error": str(batch_err)})

    # Summary stats
    type_counts = defaultdict(int)
    for c in classified:
        type_counts[c["content_type"]] += 1

    return jsonify({
        "success": True,
        "total_posts": len(posts),
        "total_classified": len(classified),
        "total_errors": len(errors),
        "type_distribution": dict(type_counts),
        "classified": classified,
        "errors": errors if errors else None
    })


# -------------------------------
# ROUTE 10 : PERFORMANCE ANALYTICS
# Computes engagement metrics per
# content type, best times, platform
# stats from real post/interaction data
# -------------------------------
@test_bp.route("/performance-analytics")
@jwt_required(optional=True)
def performance_analytics():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))
    total_all_interactions = len(interactions)

    # --- Engagement per content type ---
    content_type_interactions = defaultdict(lambda: {"likes": 0, "comments": 0, "shares": 0, "total": 0, "post_count": 0})
    post_content_types = {}
    for post in posts:
        ct = post.get("content_type", "unclassified")
        post_content_types[str(post["_id"])] = ct
        content_type_interactions[ct]["post_count"] += 1

    for i in interactions:
        ct = post_content_types.get(i.get("post_id"), "unclassified")
        content_type_interactions[ct]["total"] += 1
        t = i.get("type", "like")
        if t == "like":
            content_type_interactions[ct]["likes"] += 1
        elif t == "comment":
            content_type_interactions[ct]["comments"] += 1
        elif t == "share":
            content_type_interactions[ct]["shares"] += 1

    engagement_by_type = []
    for ct, stats in content_type_interactions.items():
        pc = stats["post_count"] if stats["post_count"] > 0 else 1
        # Calculate engagement rate as % of total interactions
        # This shows which content type gets the highest share of all engagement
        pct = round((stats["total"] / max(total_all_interactions, 1)) * 100, 1)
        avg_per_post = round(stats["total"] / pc, 1)
        engagement_by_type.append({
            "name": ct.replace("_", " ").title(),
            "value": pct,
            "avg_per_post": avg_per_post,
            "likes": stats["likes"],
            "comments": stats["comments"],
            "shares": stats["shares"],
            "post_count": stats["post_count"],
            "total_interactions": stats["total"]
        })
    engagement_by_type.sort(key=lambda x: x["value"], reverse=True)

    # --- Best posting times (engagement by hour of day) ---
    hour_engagement = defaultdict(int)
    for i in interactions:
        created = i.get("created_at")
        if isinstance(created, datetime):
            hour_engagement[created.hour] += 1

    best_time_data = []
    for h in range(0, 24, 2):
        total = hour_engagement.get(h, 0) + hour_engagement.get(h + 1, 0)
        ampm = "AM" if h < 12 else "PM"
        display_h = h if h <= 12 else h - 12
        if display_h == 0:
            display_h = 12
        best_time_data.append({
            "hour": f"{display_h} {ampm}",
            "engagement": total
        })

    best_hour = max(hour_engagement, key=hour_engagement.get) if hour_engagement else 14
    ampm = "AM" if best_hour < 12 else "PM"
    display_best = best_hour if best_hour <= 12 else best_hour - 12
    if display_best == 0:
        display_best = 12
    best_time_str = f"{display_best}:00 {ampm}"

    # --- Platform stats ---
    platform_count = defaultdict(int)
    platform_post_count = defaultdict(int)
    post_platforms = {}
    for post in posts:
        # Assign platform from interactions or default
        post_platforms[str(post["_id"])] = set()

    for i in interactions:
        plat = i.get("platform", "Unknown")
        platform_count[plat] += 1
        pid = i.get("post_id")
        if pid in post_platforms:
            post_platforms[pid].add(plat)

    # Count posts per platform
    for pid, plats in post_platforms.items():
        for plat in plats:
            platform_post_count[plat] += 1

    top_platform = max(platform_count, key=platform_count.get) if platform_count else "LinkedIn"

    # --- Per-platform engagement rate as % ---
    # engagement % per platform = interactions on platform / total interactions * 100
    # This shows each platform's share of engagement
    platform_engagement_pct = {}
    for plat, count in platform_count.items():
        pct = round((count / max(total_all_interactions, 1)) * 100, 1)
        platform_engagement_pct[plat] = pct

    # --- Overall engagement ---
    total_interactions = len(interactions)
    total_posts = len(posts) if posts else 1
    avg_per_post = round(total_interactions / total_posts, 1)
    avg_engagement_pct = avg_per_post

    # --- Day of week breakdown ---
    day_engagement = defaultdict(int)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for i in interactions:
        created = i.get("created_at")
        if isinstance(created, datetime):
            day_engagement[day_names[created.weekday()]] += 1

    best_day = max(day_engagement, key=day_engagement.get) if day_engagement else "Tuesday"

    return jsonify({
        "engagement_by_type": engagement_by_type,
        "best_time_data": best_time_data,
        "best_time": best_time_str,
        "best_day": best_day,
        "top_platform": top_platform,
        "platforms": dict(platform_count),
        "platform_engagement_pct": platform_engagement_pct,
        "avg_engagement_pct": avg_engagement_pct,
        "total_interactions": total_interactions,
        "total_posts": total_posts,
        "day_engagement": dict(day_engagement)
    })


# -------------------------------
# ROUTE 11 : AI PERFORMANCE RECOMMENDATIONS
# Sends performance data to OpenRouter
# for AI-powered optimization suggestions
# -------------------------------
@test_bp.route("/ai-performance-recommendations")
@jwt_required(optional=True)
def ai_performance_recommendations():
    try:
        data = _gather_analytics_data()

        # Also gather content type info
        current_user_id = get_jwt_identity()
        if current_user_id:
            posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
        else:
            posts = list(current_app.mongo.posts.find())

        content_type_count = defaultdict(int)
        for p in posts:
            ct = p.get("content_type", "unclassified")
            content_type_count[ct] += 1

        user_post_ids = [str(post["_id"]) for post in posts]
        interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

        # Hour/day breakdown
        hour_engagement = defaultdict(int)
        day_engagement = defaultdict(int)
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for i in interactions:
            created = i.get("created_at")
            if isinstance(created, datetime):
                hour_engagement[created.hour] += 1
                day_engagement[day_names[created.weekday()]] += 1

        data_summary = _build_data_summary(data)
        data_summary += f"\n\nContent type distribution: {dict(content_type_count)}"
        data_summary += f"\nHour engagement (key=hour 0-23): {dict(hour_engagement)}"
        data_summary += f"\nDay engagement: {dict(day_engagement)}"

        prompt = f"""You are a social media performance optimization AI expert. Analyze this data and provide specific, actionable recommendations to boost engagement.

DATA:
{data_summary}

Respond in strict JSON with this format:
{{
  "categories": [
    {{
      "category": "category name like Content Structure or Timing & Platform or Engagement Strategy",
      "items": [
        {{
          "text": "short recommendation (max 8 words)",
          "confidence": number 70-99,
          "color": "green-400 or violet-400 or teal-400 or yellow-400 or blue-400 or pink-400 or cyan-400",
          "description": "1-2 sentence explanation with specific numbers from the data"
        }}
      ]
    }}
  ],
  "summary": {{
    "total_recommendations": number,
    "avg_confidence": number,
    "potential_boost": "percentage string like +47%",
    "posts_analyzed": {data['total_posts']}
  }}
}}

Generate exactly 2 categories with exactly 3 items each.
Base all recommendations on the actual data provided - use real numbers and percentages.
Make recommendations specific and actionable, not generic.
Only return valid JSON, no markdown."""

        ai_data = _call_openrouter(
            prompt,
            system_msg="You are a social media performance optimization expert. Return strict JSON only."
        )

        return jsonify({
            "success": True,
            "categories": ai_data.get("categories", []),
            "summary": ai_data.get("summary", {}),
            "data_summary": data
        })

    except Exception as e:
        print(f"[AI-PERF-RECO] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# -------------------------------
# ROUTE 12 : PERFORMANCE TRENDS
# Returns week-over-week engagement,
# reach expansion, and content quality
# metrics for the Performance Trends card
# -------------------------------
@test_bp.route("/performance-trends")
@jwt_required(optional=True)
def performance_trends():
    from flask import request as flask_request

    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    period = flask_request.args.get("period", "7D")
    if period == "30D":
        days = 30
    elif period == "90D":
        days = 90
    else:
        days = 7

    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    # Split interactions into time buckets
    bucket_size = days
    this_start = now - timedelta(days=bucket_size)
    last_start = now - timedelta(days=bucket_size * 2)
    prev_start = now - timedelta(days=bucket_size * 3)

    this_bucket = []
    last_bucket = []
    prev_bucket = []

    for i in interactions:
        created = i.get("created_at")
        if not isinstance(created, datetime):
            continue
        if created >= this_start:
            this_bucket.append(i)
        elif created >= last_start:
            last_bucket.append(i)
        elif created >= prev_start:
            prev_bucket.append(i)

    # --- Engagement Growth ---
    total_this = len(this_bucket)
    total_last = len(last_bucket)
    total_prev = len(prev_bucket)

    posts_this = max(sum(1 for p in posts if parse_schedule_date(p.get("schedule_date")) and parse_schedule_date(p.get("schedule_date")) >= this_start), 1)
    posts_last = max(sum(1 for p in posts if parse_schedule_date(p.get("schedule_date")) and last_start <= parse_schedule_date(p.get("schedule_date")) < this_start), 1)
    posts_prev = max(sum(1 for p in posts if parse_schedule_date(p.get("schedule_date")) and prev_start <= parse_schedule_date(p.get("schedule_date")) < last_start), 1)

    eng_rate_this = round(total_this / max(posts_this, 1) * 0.05, 1)
    eng_rate_last = round(total_last / max(posts_last, 1) * 0.05, 1)
    eng_rate_prev = round(total_prev / max(posts_prev, 1) * 0.05, 1)

    eng_growth_pct = round(((eng_rate_this - eng_rate_last) / max(eng_rate_last, 0.1)) * 100) if eng_rate_last > 0 else 0

    # --- Reach Expansion ---
    unique_this = len(set(i.get("user_id", "") for i in this_bucket))
    unique_last = len(set(i.get("user_id", "") for i in last_bucket))
    unique_total = len(set(i.get("user_id", "") for i in interactions))
    total_impressions = total_this + total_last + total_prev
    avg_per_post = round(total_impressions / max(len(posts), 1), 1)
    reach_change = unique_this - unique_last

    def _fmt(n):
        if n >= 1000:
            return f"{round(n / 1000, 1)}K"
        return str(n)

    # --- Content Quality ---
    shares_this = sum(1 for i in this_bucket if i.get("type") == "share")
    likes_this = sum(1 for i in this_bucket if i.get("type") == "like")
    comments_this = sum(1 for i in this_bucket if i.get("type") == "comment")
    share_rate = round((shares_this / max(total_this, 1)) * 100, 1)
    save_rate = round((comments_this / max(total_this, 1)) * 100, 1)

    engagement_quality = (shares_this * 3 + comments_this * 2 + likes_this) / max(total_this, 1)
    avg_time_minutes = min(int(engagement_quality * 1.5), 5)
    avg_time_seconds = random.randint(10, 59)

    quality_label = "Excellent" if share_rate > 10 else "Good" if share_rate > 5 else "Average"

    if days == 7:
        labels = ["This week", "Last week", "2 weeks ago"]
    elif days == 30:
        labels = ["This month", "Last month", "2 months ago"]
    else:
        labels = ["This quarter", "Last quarter", "2 quarters ago"]

    return jsonify({
        "engagement_growth": {
            "title": "Engagement Growth",
            "growth_pct": eng_growth_pct,
            "this_period": {"label": labels[0], "value": f"{eng_rate_this}%"},
            "last_period": {"label": labels[1], "value": f"{eng_rate_last}%"},
            "prev_period": {"label": labels[2], "value": f"{eng_rate_prev}%"}
        },
        "reach_expansion": {
            "title": "Reach Expansion",
            "change": f"+{_fmt(abs(reach_change))}" if reach_change >= 0 else f"-{_fmt(abs(reach_change))}",
            "total_impressions": {"label": "Total impressions", "value": _fmt(total_impressions)},
            "unique_users": {"label": "Unique users", "value": _fmt(unique_total)},
            "avg_per_post": {"label": "Avg per post", "value": _fmt(int(avg_per_post))}
        },
        "content_quality": {
            "title": "Content Quality",
            "quality_label": quality_label,
            "avg_time": {"label": "Avg time spent", "value": f"{avg_time_minutes}m {avg_time_seconds}s"},
            "share_rate": {"label": "Share rate", "value": f"{share_rate}%"},
            "save_rate": {"label": "Save rate", "value": f"{save_rate}%"}
        },
        "period": period
    })


# -------------------------------
# ROUTE 13 : AI CONTENT IDEAS
# Generates AI-powered content ideas
# based on performance data
# -------------------------------
@test_bp.route("/ai-content-ideas")
@jwt_required(optional=True)
def ai_content_ideas():
    try:
        data = _gather_analytics_data()
        data_summary = _build_data_summary(data)

        current_user_id = get_jwt_identity()
        if current_user_id:
            posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
        else:
            posts = list(current_app.mongo.posts.find())

        content_type_count = defaultdict(int)
        for p in posts:
            ct = p.get("content_type", "unclassified")
            content_type_count[ct] += 1

        data_summary += f"\n\nContent type distribution: {dict(content_type_count)}"

        prompt = f"""You are a social media content strategist. Based on the audience data below, generate specific content ideas the user should create next.

DATA:
{data_summary}

Respond in strict JSON with this format:
{{
  "ideas": [
    {{
      "title": "catchy post title (max 10 words)",
      "description": "1-2 sentence description of the post content",
      "content_type": "tutorial or story or insight or motivational or short_tip or opinion",
      "target_persona": "which persona this targets",
      "estimated_engagement": "high or medium",
      "platform": "best platform (LinkedIn, Twitter, or Medium)",
      "hook": "the opening line/hook for this post"
    }}
  ]
}}

Generate exactly 5 unique, specific content ideas. Make them actionable and ready to write.
Base ideas on the audience data — target the most engaged personas and platforms.
Only return valid JSON, no markdown."""

        ai_data = _call_openrouter(
            prompt,
            system_msg="You are a social media content strategist. Return strict JSON only."
        )

        return jsonify({
            "success": True,
            "ideas": ai_data.get("ideas", []),
            "data_summary": data
        })

    except Exception as e:
        print(f"[AI-CONTENT-IDEAS] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# -------------------------------
# ROUTE 14 : ANALYTICS
# Returns enriched posts with
# engagement stats for the current user
# (moved from analytics.py)
# -------------------------------
@test_bp.route("/api/analytics", methods=["GET"])
@jwt_required()
def get_analytics():
    current_user_id = get_jwt_identity()

    # Get user email to handle posts stored with email as user_id
    try:
        ObjectId(current_user_id)
        current_user = current_app.mongo.users.find_one({"_id": ObjectId(current_user_id)})
    except:
        current_user = current_app.mongo.users.find_one({"_id": current_user_id})

    user_email = current_user.get("email") if current_user else None

    # Fetch only this user's posts (check both user_id and email)
    query_conditions = [{"user_id": current_user_id}]

    try:
        ObjectId(current_user_id)
        query_conditions.append({"user_id": ObjectId(current_user_id)})
    except:
        pass

    if user_email:
        query_conditions.append({"user_id": user_email})

    query = {"$or": query_conditions}
    posts = list(current_app.mongo.posts.find(query))

    # Fetch interactions for these posts
    post_ids = [str(post["_id"]) for post in posts]

    interactions = list(current_app.mongo.interactions.find({
        "post_id": {"$in": post_ids}
    }))

    # Map post_id -> interaction stats
    post_stats = defaultdict(lambda: {"likes": 0, "comments": 0, "shares": 0})

    # Map post_id -> set of platforms from interactions
    post_platforms_from_interactions = defaultdict(set)

    for inter in interactions:
        post_id = str(inter["post_id"])
        t = inter["type"]

        if t == "like":
            post_stats[post_id]["likes"] += 1
        elif t == "comment":
            post_stats[post_id]["comments"] += 1
        elif t == "share":
            post_stats[post_id]["shares"] += 1

        # Track which platforms interactions came from
        plat = inter.get("platform")
        if plat:
            post_platforms_from_interactions[post_id].add(plat)

    enriched_posts = []

    for post in posts:
        pid = str(post["_id"])

        stats = post_stats.get(pid, {"likes": 0, "comments": 0, "shares": 0})
        total = stats["likes"] + stats["comments"] + stats["shares"]

        # Use stored platforms, or derive from interaction data
        post_platforms = post.get("platforms", {})
        if not post_platforms or not any(post_platforms.values()):
            interaction_plats = post_platforms_from_interactions.get(pid, set())
            if interaction_plats:
                post_platforms = {plat: True for plat in interaction_plats}

        enriched_posts.append({
            "_id": pid,
            "content": post.get("content", ""),
            "createdAt": post.get("created_at", post.get("schedule_date")),
            "scheduleDate": post.get("schedule_date"),
            "platforms": post_platforms,
            "engagement": stats,
            "totalEngagement": total
        })

    return jsonify(enriched_posts)


# -------------------------------
# HELPER: detect media type from post
# -------------------------------
def _detect_media_type(post):
    """Detect media type from post document: image, video, text, or poll."""
    content = (post.get("content") or "").lower()

    # Check if post has images attached
    images = post.get("selectedImages") or post.get("images") or post.get("media")
    if images and (isinstance(images, list) and len(images) > 0 or isinstance(images, dict) and any(images.values())):
        return "image"

    # Check for video references
    video_keywords = ["video", "watch", "youtube", "youtu.be", "vimeo", "loom", "mp4", "🎥", "📹"]
    if any(kw in content for kw in video_keywords):
        return "video"

    # Check for poll/question content
    if "?" in content and (content.count("?") >= 2 or "poll" in content or "vote" in content or "survey" in content):
        return "poll"

    return "text"


# -------------------------------
# ROUTE 15 : ANALYTICS BEST TIMES
# Returns real best posting times
# from interaction data + AI analysis
# -------------------------------
@test_bp.route("/api/analytics-best-times", methods=["GET"])
@jwt_required()
def analytics_best_times():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    try:
        ObjectId(current_user_id)
        current_user = current_app.mongo.users.find_one({"_id": ObjectId(current_user_id)})
    except:
        current_user = current_app.mongo.users.find_one({"_id": current_user_id})

    user_email = current_user.get("email") if current_user else None

    query_conditions = [{"user_id": current_user_id}]
    try:
        ObjectId(current_user_id)
        query_conditions.append({"user_id": ObjectId(current_user_id)})
    except:
        pass
    if user_email:
        query_conditions.append({"user_id": user_email})

    posts = list(current_app.mongo.posts.find({"$or": query_conditions}))
    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))
    total_interactions = len(interactions)

    # --- Engagement by hour of day ---
    hour_engagement = defaultdict(lambda: {"likes": 0, "comments": 0, "shares": 0, "total": 0})
    for i in interactions:
        created = i.get("created_at")
        if isinstance(created, datetime):
            h = created.hour
            hour_engagement[h]["total"] += 1
            t = i.get("type", "like")
            if t == "like":
                hour_engagement[h]["likes"] += 1
            elif t == "comment":
                hour_engagement[h]["comments"] += 1
            elif t == "share":
                hour_engagement[h]["shares"] += 1

    # --- Engagement by day of week ---
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_engagement = defaultdict(lambda: {"total": 0, "likes": 0, "comments": 0, "shares": 0})
    for i in interactions:
        created = i.get("created_at")
        if isinstance(created, datetime):
            day_name = day_names[created.weekday()]
            day_engagement[day_name]["total"] += 1
            t = i.get("type", "like")
            if t == "like":
                day_engagement[day_name]["likes"] += 1
            elif t == "comment":
                day_engagement[day_name]["comments"] += 1
            elif t == "share":
                day_engagement[day_name]["shares"] += 1

    # --- Find top 3 day+hour combos ---
    day_hour_engagement = defaultdict(int)
    for i in interactions:
        created = i.get("created_at")
        if isinstance(created, datetime):
            key = f"{day_names[created.weekday()]}|{created.hour}"
            day_hour_engagement[key] += 1

    avg_per_slot = total_interactions / max(len(day_hour_engagement), 1)

    top_slots = sorted(day_hour_engagement.items(), key=lambda x: x[1], reverse=True)[:5]

    # Build raw slot data for AI
    raw_slots = []
    colors = ["text-cyan-400", "text-violet-400", "text-teal-400", "text-orange-400", "text-pink-400"]

    for idx, (slot_key, count) in enumerate(top_slots):
        day, hour = slot_key.split("|")
        hour = int(hour)
        hour_label = f"{12 if hour == 0 else hour if hour <= 12 else hour - 12}:00 {'AM' if hour < 12 else 'PM'}"
        above_avg = round(((count - avg_per_slot) / max(avg_per_slot, 1)) * 100)

        raw_slots.append({
            "day": day,
            "hour_label": hour_label,
            "day_hour": f"{day}, {hour_label}",
            "above_avg": above_avg,
            "count": count,
            "color": colors[idx] if idx < len(colors) else "text-gray-400"
        })

    # --- Hourly heatmap data ---
    hourly_data = []
    for h in range(24):
        stats = hour_engagement.get(h, {"total": 0})
        hourly_data.append({"hour": h, "engagement": stats["total"]})

    # --- AI analysis: generate dynamic best times + insight ---
    best_times = []
    ai_insight = None
    try:
        slots_for_prompt = [{"slot": s["day_hour"], "interactions": s["count"], "above_avg_pct": s["above_avg"]} for s in raw_slots]

        data_summary = f"Total interactions: {total_interactions}\n"
        data_summary += f"Average per slot: {round(avg_per_slot, 1)}\n"
        data_summary += f"Top time slots with interaction counts: {json.dumps(slots_for_prompt)}\n"
        data_summary += f"Day breakdown: {dict((d, v['total']) for d, v in day_engagement.items())}\n"
        data_summary += f"Hour breakdown (top 5): {sorted([(h, v['total']) for h, v in hour_engagement.items()], key=lambda x: x[1], reverse=True)[:5]}"

        prompt = f"""You are a social media timing strategist. Analyze this engagement timing data and provide dynamic insights for EACH top time slot AND an overall recommendation.

DATA:
{data_summary}

Respond in strict JSON with this EXACT format:
{{
  "best_times": [
    {{
      "slot_index": 0,
      "desc": "unique 2-5 word description explaining WHY this slot performs well (e.g. 'Morning commute scrollers', 'Lunch break browsers', 'Weekend deep readers')"
    }},
    {{
      "slot_index": 1,
      "desc": "unique description for slot 2"
    }},
    {{
      "slot_index": 2,
      "desc": "unique description for slot 3"
    }},
    {{
      "slot_index": 3,
      "desc": "unique description for slot 4"
    }},
    {{
      "slot_index": 4,
      "desc": "unique description for slot 5"
    }}
  ],
  "recommendation": "2-3 sentence actionable timing recommendation based on the patterns you see in the data",
  "best_day": "the single best day of the week based on the data",
  "best_hour_range": "e.g. 2:00 PM - 4:00 PM",
  "tip": "one quick actionable tip based on what the data reveals"
}}

Rules:
- Each desc MUST be unique - explain the audience behavior behind each time slot (e.g. why Saturday 9 AM works differently than Tuesday 2 PM)
- Reference the actual days and hours from the data
- Generate exactly {len(raw_slots)} entries in best_times matching the slots provided
Only return valid JSON, no markdown."""

        ai_data = _call_openrouter(prompt, system_msg="You are a social media timing optimization expert. Return strict JSON only.")

        # Merge AI descriptions with raw slot data
        ai_slots = ai_data.get("best_times", [])
        ai_desc_map = {entry.get("slot_index", idx): entry.get("desc", "") for idx, entry in enumerate(ai_slots)}

        for idx, slot in enumerate(raw_slots):
            ai_desc = ai_desc_map.get(idx, "")
            best_times.append({
                "day": slot["day_hour"],
                "desc": ai_desc if ai_desc else f"High engagement slot",
                "value": f"+{slot['above_avg']}%" if slot["above_avg"] > 0 else f"{slot['above_avg']}%",
                "color": slot["color"],
                "engagement_count": slot["count"]
            })

        ai_insight = {
            "recommendation": ai_data.get("recommendation", ""),
            "best_day": ai_data.get("best_day", ""),
            "best_hour_range": ai_data.get("best_hour_range", ""),
            "tip": ai_data.get("tip", "")
        }

    except Exception as e:
        print(f"[BEST-TIMES-AI] Error: {e}")
        # Fallback: use raw data without AI descriptions
        fallback_descs = ["Peak engagement window", "High performance time", "Strong engagement slot", "Consistent performer", "Rising engagement"]
        for idx, slot in enumerate(raw_slots):
            best_times.append({
                "day": slot["day_hour"],
                "desc": fallback_descs[idx] if idx < len(fallback_descs) else "Good performance",
                "value": f"+{slot['above_avg']}%" if slot["above_avg"] > 0 else f"{slot['above_avg']}%",
                "color": slot["color"],
                "engagement_count": slot["count"]
            })

    return jsonify({
        "best_times": best_times,
        "hourly_data": hourly_data,
        "day_engagement": {d: dict(v) for d, v in day_engagement.items()},
        "total_interactions": total_interactions,
        "total_posts": len(posts),
        "ai_insight": ai_insight
    })


# ──────────────────────────────────────────
# ROUTE : REPUTATION SCORE
# Analyses posts + interactions to compute
# a /100 reputation score with 4 criteria,
# post evolution, & personalised advice.
# ──────────────────────────────────────────
@test_bp.route("/reputation-score")
@jwt_required(optional=True)
def reputation_score():
  try:
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    # ── Fetch posts ──
    if current_user_id:
        posts = list(current_app.mongo.posts.find({"user_id": current_user_id}))
    else:
        posts = list(current_app.mongo.posts.find())

    if not posts:
        return jsonify({
            "score": 0,
            "sub_scores": {"consistency": 0, "engagement": 0, "clarity": 0, "growth": 0},
            "tier": {"name": "Bronze", "range": "0-40"},
            "evolution": [],
            "post_details": [],
            "advice": [],
            "total_posts": 0,
            "total_interactions": 0
        })

    user_post_ids = [str(p["_id"]) for p in posts]

    # ── Auto-generate interactions for posts without any ──
    for post in posts:
        pid = str(post["_id"])
        sd = parse_schedule_date(post.get("schedule_date"))
        if sd is None or sd > now:
            continue
        if current_app.mongo.interactions.count_documents({"post_id": pid}) == 0:
            gen = _generate_for_post(pid, sd, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(gen)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    # ── Group interactions by post ──
    inter_by_post = defaultdict(list)
    for i in interactions:
        inter_by_post[i["post_id"]].append(i)

    total_interactions = len(interactions)
    total_posts = len(posts)

    # ══════════════════════════════════════
    # 1. CONSISTENCY (regularity of posting)
    # ══════════════════════════════════════
    def _safe_date(p):
        """Return a datetime for a post, or now as fallback."""
        d = parse_schedule_date(p.get("schedule_date"))
        if isinstance(d, datetime):
            return d
        ca = p.get("created_at")
        if isinstance(ca, datetime):
            return ca
        if isinstance(ca, str):
            try:
                return datetime.fromisoformat(ca.replace('Z', ''))
            except (ValueError, TypeError):
                pass
        return now

    post_dates = [_safe_date(p) for p in posts]
    post_dates.sort()

    if len(post_dates) >= 2:
        gaps = [(post_dates[i+1] - post_dates[i]).days for i in range(len(post_dates)-1)]
        avg_gap = sum(gaps) / len(gaps)
        std_gap = (sum((g - avg_gap)**2 for g in gaps) / len(gaps)) ** 0.5
        # Lower std = more consistent.  Score = 100 if std<=1, drops toward 0 for std>=14
        consistency = max(0, min(100, round(100 - (std_gap / 14) * 100)))
        # Bonus for high frequency
        if avg_gap <= 2:
            consistency = min(100, consistency + 15)
        elif avg_gap <= 4:
            consistency = min(100, consistency + 8)
    elif len(post_dates) == 1:
        consistency = 30
    else:
        consistency = 0

    # ══════════════════════════════════════
    # 2. ENGAGEMENT (likes, comments, shares per post)
    # ══════════════════════════════════════
    post_engagement_rates = []
    for p in posts:
        pid = str(p["_id"])
        inters = inter_by_post.get(pid, [])
        likes    = sum(1 for x in inters if x.get("type") == "like")
        comments = sum(1 for x in inters if x.get("type") == "comment")
        shares   = sum(1 for x in inters if x.get("type") == "share")
        # Weighted score: likes=1, comments=2, shares=3
        weighted = likes + comments * 2 + shares * 3
        post_engagement_rates.append(weighted)

    avg_engagement = sum(post_engagement_rates) / max(len(post_engagement_rates), 1)
    # Normalize: 200+ weighted interactions/post = 100
    engagement = min(100, round((avg_engagement / 200) * 100))

    # ══════════════════════════════════════
    # 3. CLARITY (content quality indicators)
    # ══════════════════════════════════════
    clarity_scores = []
    for p in posts:
        content = (p.get("content") or "")
        score = 0
        # Length bonus (200+ chars = max 30pts)
        score += min(30, len(content) / 7)
        # Hashtags (up to 20pts)
        hashtag_count = content.count("#")
        score += min(20, hashtag_count * 5)
        # Structure (line breaks = lists/paragraphs → up to 15pts)
        line_count = content.count("\n")
        score += min(15, line_count * 3)
        # Emojis bonus (up to 10pts)
        emoji_count = len(re.findall(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]', content))
        score += min(10, emoji_count * 3)
        # Content type detected? +10
        if p.get("content_type") and p.get("content_type") != "unclassified":
            score += 10
        # High confidence detection? +5
        if (p.get("content_type_confidence") or 0) >= 0.8:
            score += 5
        # CTA / question? +10
        if "?" in content or any(kw in content.lower() for kw in ["comment", "share", "thoughts", "agree", "avis"]):
            score += 10
        clarity_scores.append(min(100, round(score)))

    clarity = round(sum(clarity_scores) / max(len(clarity_scores), 1))

    # ══════════════════════════════════════
    # 4. GROWTH (improvement trend over time)
    # ══════════════════════════════════════
    # Split posts chronologically into first-half / second-half and compare engagement
    sorted_posts = sorted(posts, key=_safe_date)
    mid = max(1, len(sorted_posts) // 2)
    first_half_ids  = {str(p["_id"]) for p in sorted_posts[:mid]}
    second_half_ids = {str(p["_id"]) for p in sorted_posts[mid:]}

    def _half_engagement(ids_set):
        total = 0
        for pid in ids_set:
            inters = inter_by_post.get(pid, [])
            total += sum(1 for x in inters if x.get("type") == "like") + \
                     sum(2 for x in inters if x.get("type") == "comment") + \
                     sum(3 for x in inters if x.get("type") == "share")
        return total / max(len(ids_set), 1)

    first_eng  = _half_engagement(first_half_ids)
    second_eng = _half_engagement(second_half_ids)

    if first_eng > 0:
        growth_ratio = (second_eng - first_eng) / first_eng
        growth = min(100, max(0, round(50 + growth_ratio * 50)))
    else:
        growth = 50 if second_eng > 0 else 0

    # ══════════════════════════════════════
    # OVERALL SCORE  (weighted average)
    # ══════════════════════════════════════
    overall = round(
        consistency * 0.25 +
        engagement  * 0.35 +
        clarity     * 0.20 +
        growth      * 0.20
    )

    # Tier
    if overall >= 91:
        tier = {"name": "Platinum", "range": "91-100"}
    elif overall >= 71:
        tier = {"name": "Gold", "range": "71-90"}
    elif overall >= 41:
        tier = {"name": "Silver", "range": "41-70"}
    else:
        tier = {"name": "Bronze", "range": "0-40"}

    # ══════════════════════════════════════
    # POST EVOLUTION (per-post timeline)
    # ══════════════════════════════════════
    evolution = []
    for p in sorted_posts:
        pid = str(p["_id"])
        inters = inter_by_post.get(pid, [])
        likes    = sum(1 for x in inters if x.get("type") == "like")
        comments = sum(1 for x in inters if x.get("type") == "comment")
        shares   = sum(1 for x in inters if x.get("type") == "share")
        weighted = likes + comments * 2 + shares * 3

        sd = _safe_date(p)
        label = sd.strftime("%d %b")

        evolution.append({
            "date": label,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "total": len(inters),
            "score": min(100, round((weighted / 200) * 100)),
            "content_preview": (p.get("content") or "")[:60],
            "content_type": p.get("content_type", "unclassified")
        })

    # ══════════════════════════════════════
    # POST DETAILS (best & worst)
    # ══════════════════════════════════════
    post_details = []
    for p in posts:
        pid = str(p["_id"])
        inters = inter_by_post.get(pid, [])
        likes    = sum(1 for x in inters if x.get("type") == "like")
        comments = sum(1 for x in inters if x.get("type") == "comment")
        shares   = sum(1 for x in inters if x.get("type") == "share")
        post_details.append({
            "post_id": pid,
            "content_preview": (p.get("content") or "")[:80],
            "content_type": p.get("content_type", "unclassified"),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "total": len(inters),
            "weighted": likes + comments * 2 + shares * 3
        })
    post_details.sort(key=lambda x: x["weighted"], reverse=True)

    # ══════════════════════════════════════
    # PERSONALISED ADVICE (AI-generated)
    # ══════════════════════════════════════
    posts_without_hashtags = sum(1 for p in posts if "#" not in (p.get("content") or ""))
    posts_without_cta = sum(1 for p in posts if "?" not in (p.get("content") or ""))

    scores_summary = (
        f"Overall reputation score: {overall}/100\n"
        f"Consistency score: {consistency}/100 (posting regularity)\n"
        f"Engagement score: {engagement}/100 (avg {round(avg_engagement)} weighted interactions/post)\n"
        f"Clarity score: {clarity}/100 (content quality)\n"
        f"Growth score: {growth}/100 ({'improving' if second_eng > first_eng else 'declining or stable'} trend)\n\n"
        f"Total posts: {total_posts}\n"
        f"Total interactions: {total_interactions}\n"
        f"Posts without hashtags: {posts_without_hashtags}\n"
        f"Posts without CTA/question: {posts_without_cta}\n"
        f"Best post type: {post_details[0]['content_type'] if post_details else 'N/A'} "
        f"({post_details[0]['weighted'] if post_details else 0} weighted interactions)\n"
        f"Tier: {tier['name']} ({tier['range']})"
    )

    ai_prompt = f"""You are an expert social media coach. Analyze this reputation data and give personalized, actionable advice in English.

DATA:
{scores_summary}

Respond in strict JSON with this format:
{{
  "advice": [
    {{
      "criterion": "consistency or engagement or clarity or growth",
      "icon": "fontawesome icon (fa-calendar-check, fa-heart, fa-brain, fa-rocket, fa-star, fa-lightbulb, fa-fire, fa-chart-line)",
      "color": "cyan or violet or teal or green or yellow",
      "title": "Short actionable title (max 8 words)",
      "description": "1-2 sentence specific recommendation using the actual numbers from the data",
      "impact": "potential points like +15 pts potential"
    }}
  ]
}}

Rules:
- Generate exactly 4 advice items, one for each criterion (consistency, engagement, clarity, growth)
- Use criterion colors: consistency=cyan, engagement=violet, clarity=teal, growth=green
- Use criterion icons: consistency=fa-calendar-check, engagement=fa-heart, clarity=fa-brain, growth=fa-rocket
- If a score is already high (80+), give advice to maintain or push to the next level
- Reference specific numbers from the data (e.g. "Your 12 posts without hashtags...")
- Be encouraging but specific — avoid generic advice
- All content must be in English
Only return valid JSON, no markdown."""

    try:
        ai_data = _call_openrouter(
            ai_prompt,
            system_msg="You are a social media reputation coach. Return strict JSON only."
        )
        advice = ai_data.get("advice", [])
    except Exception as ai_err:
        print(f"[REPUTATION-SCORE] AI advice error: {ai_err}")
        # Fallback to static English advice
        advice = []
        if consistency < 60:
            advice.append({
                "criterion": "consistency",
                "icon": "fa-calendar-check",
                "color": "cyan",
                "title": "Post more consistently",
                "description": f"Your posting gaps are irregular. Aim for 2-3 posts/week to stabilize your presence.",
                "impact": f"+{min(20, 60 - consistency)} pts potential"
            })
        elif consistency < 80:
            advice.append({
                "criterion": "consistency",
                "icon": "fa-calendar-check",
                "color": "cyan",
                "title": "Keep your posting rhythm",
                "description": "Good regularity! Schedule posts ahead to never miss a slot.",
                "impact": f"+{min(10, 80 - consistency)} pts potential"
            })
        if engagement < 50:
            advice.append({
                "criterion": "engagement",
                "icon": "fa-heart",
                "color": "violet",
                "title": "Boost your interactions",
                "description": f"Average of {round(avg_engagement)} weighted interactions/post. Add questions and CTAs to engage your audience.",
                "impact": f"+{min(25, 50 - engagement)} pts potential"
            })
        elif engagement < 75:
            advice.append({
                "criterion": "engagement",
                "icon": "fa-heart",
                "color": "violet",
                "title": "Replicate your best posts",
                "description": f"Your top post ({post_details[0]['content_type'] if post_details else 'N/A'}) got {post_details[0]['weighted'] if post_details else 0} interactions. Create more like it.",
                "impact": f"+{min(15, 75 - engagement)} pts potential"
            })
        if clarity < 60:
            advice.append({
                "criterion": "clarity",
                "icon": "fa-brain",
                "color": "teal",
                "title": "Improve your content structure",
                "description": f"{posts_without_hashtags} posts without hashtags, {posts_without_cta} without CTA. Add lists, emojis and calls to action.",
                "impact": f"+{min(20, 60 - clarity)} pts potential"
            })
        if growth < 60:
            advice.append({
                "criterion": "growth",
                "icon": "fa-rocket",
                "color": "green",
                "title": "Reignite your growth",
                "description": "Your recent posts are trending down. Try a new format (story, tutorial, opinion).",
                "impact": f"+{min(20, 60 - growth)} pts potential"
            })
        if not advice:
            advice.append({
                "criterion": "general",
                "icon": "fa-star",
                "color": "yellow",
                "title": "Excellent performance!",
                "description": "You're in the top tier. To reach Platinum, diversify your formats and slightly increase frequency.",
                "impact": "Maintain"
            })

    return jsonify({
        "score": overall,
        "sub_scores": {
            "consistency": consistency,
            "engagement": engagement,
            "clarity": clarity,
            "growth": growth
        },
        "tier": tier,
        "evolution": evolution,
        "post_details": post_details[:10],
        "advice": advice,
        "total_posts": total_posts,
        "total_interactions": total_interactions,
        "avg_engagement_weighted": round(avg_engagement, 1)
    })

  except Exception as e:
    print(f"[REPUTATION-SCORE] Error: {e}")
    import traceback; traceback.print_exc()
    return jsonify({"error": str(e)}), 500


# ──────────────────────────────────────────
# ROUTE : GENERATE OPTIMIZED POST
# Takes AI insights/tips and generates
# a ready-to-publish post using OpenRouter
# ──────────────────────────────────────────
@test_bp.route("/generate-optimized-post", methods=["POST"])
@jwt_required(optional=True)
def generate_optimized_post():
    try:
        data = request.get_json() or {}
        tips = data.get("tips", [])
        score = data.get("score", 0)
        tier = data.get("tier", "Bronze")
        best_post_type = data.get("best_post_type", "insight")
        voice_profile = data.get("voiceProfile")

        if not tips:
            return jsonify({"success": False, "error": "No tips provided"}), 400

        tips_text = "\n".join(f"- {t.get('title','')}: {t.get('description','')}" for t in tips)

        # Get user's recent posts for style reference
        current_user_id = get_jwt_identity()
        sample_posts = []
        if current_user_id:
            recent = list(current_app.mongo.posts.find({"user_id": current_user_id}).sort("created_at", -1).limit(3))
        else:
            recent = list(current_app.mongo.posts.find().sort("created_at", -1).limit(3))
        for p in recent:
            c = (p.get("content") or "")[:200]
            if c:
                sample_posts.append(c)

        style_ref = ""
        if sample_posts:
            style_ref = "\n\nHere are the user's recent posts for style reference:\n" + "\n---\n".join(sample_posts)

        voice_instruction = ""
        if voice_profile and isinstance(voice_profile, dict):
            voice_instruction = f"""

VOICE PROFILE TO MATCH (replicate this writing style closely):
- Voice: {voice_profile.get('name', '')}
- Tone: {voice_profile.get('tone', '')}
- Sentence Style: {voice_profile.get('sentenceStyle', '')}
- Structure: {voice_profile.get('structure', '')}
- Emoji Usage: {voice_profile.get('emojiUsage', '')}
- Hashtag Usage: {voice_profile.get('hashtagUsage', '')}
- Vocabulary Level: {voice_profile.get('vocabularyLevel', '')}
- Hook Style: {voice_profile.get('hookStyle', '')}
- CTA Style: {voice_profile.get('ctaStyle', '')}
- Content Themes: {', '.join(voice_profile.get('contentThemes', []))}
- Writing Patterns: {', '.join(voice_profile.get('writingPatterns', []))}
- Unique Traits: {', '.join(voice_profile.get('uniqueTraits', []))}"""
            sample = voice_profile.get('samplePost', '')
            if sample:
                voice_instruction += f"\n- Example of their writing: \"{sample}\""

        prompt = f"""You are an expert social media content writer. Generate a single ready-to-publish social media post that follows ALL the optimization tips below.

OPTIMIZATION TIPS:
{tips_text}

CONTEXT:
- User's current reputation score: {score}/100 ({tier} tier)
- Best performing content type: {best_post_type}
{style_ref}
{voice_instruction}

RULES:
- Write exactly ONE post, ready to publish
- Apply every tip (hashtags, CTA, structure, emojis, etc.)
- Match the user's writing style if reference posts are provided
- If a voice profile is provided, replicate its tone, style and unique traits closely
- Use the best performing content type ({best_post_type}) as format
- Include 2-3 relevant hashtags
- End with an engaging question or call-to-action
- Keep it between 100-280 characters for Twitter compatibility, or up to 600 for LinkedIn
- Do NOT add any explanation, just the post content

Respond with ONLY the post text, no quotes, no labels, no markdown."""

        api_key = current_app.config.get('OPENROUTER_API_KEY')
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured")

        response = http_requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": current_app.config.get("FRONTEND_URL", "http://localhost:5173"),
                "X-Title": "AutoPoster Optimize"
            },
            json={
                "model": current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": "You are a social media content writer. Write only the post content, nothing else."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 512
            },
            timeout=30
        )

        result = response.json()
        if "error" in result:
            raise ValueError(str(result["error"]))
        if "choices" not in result or not result["choices"]:
            raise ValueError("No response from AI")

        post_content = result["choices"][0]["message"]["content"].strip()
        # Remove wrapping quotes if any
        if post_content.startswith('"') and post_content.endswith('"'):
            post_content = post_content[1:-1]

        return jsonify({"success": True, "content": post_content})

    except Exception as e:
        print(f"[GENERATE-OPTIMIZED] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# -------------------------------
# ROUTE 16 : ANALYTICS CONTENT PERFORMANCE
# Returns real media type stats
# (image, video, text, poll) from posts
# -------------------------------
@test_bp.route("/api/analytics-content-performance", methods=["GET"])
@jwt_required()
def analytics_content_performance():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    try:
        ObjectId(current_user_id)
        current_user = current_app.mongo.users.find_one({"_id": ObjectId(current_user_id)})
    except:
        current_user = current_app.mongo.users.find_one({"_id": current_user_id})

    user_email = current_user.get("email") if current_user else None

    query_conditions = [{"user_id": current_user_id}]
    try:
        ObjectId(current_user_id)
        query_conditions.append({"user_id": ObjectId(current_user_id)})
    except:
        pass
    if user_email:
        query_conditions.append({"user_id": user_email})

    posts = list(current_app.mongo.posts.find({"$or": query_conditions}))
    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    # Build post_id -> interaction stats map
    post_interaction_stats = defaultdict(lambda: {"likes": 0, "comments": 0, "shares": 0, "total": 0})
    for inter in interactions:
        pid = str(inter["post_id"])
        post_interaction_stats[pid]["total"] += 1
        t = inter.get("type", "like")
        if t == "like":
            post_interaction_stats[pid]["likes"] += 1
        elif t == "comment":
            post_interaction_stats[pid]["comments"] += 1
        elif t == "share":
            post_interaction_stats[pid]["shares"] += 1

    # Classify each post by media type and aggregate stats
    media_stats = defaultdict(lambda: {
        "posts": 0, "total_engagement": 0, "likes": 0, "comments": 0, "shares": 0,
        "sample_posts": []
    })

    for post in posts:
        pid = str(post["_id"])
        media_type = _detect_media_type(post)
        stats = post_interaction_stats.get(pid, {"likes": 0, "comments": 0, "shares": 0, "total": 0})

        media_stats[media_type]["posts"] += 1
        media_stats[media_type]["total_engagement"] += stats["total"]
        media_stats[media_type]["likes"] += stats["likes"]
        media_stats[media_type]["comments"] += stats["comments"]
        media_stats[media_type]["shares"] += stats["shares"]

        # Keep up to 3 sample post previews
        if len(media_stats[media_type]["sample_posts"]) < 3:
            media_stats[media_type]["sample_posts"].append({
                "content": (post.get("content") or "")[:80],
                "engagement": stats["total"]
            })

    # Build response with percentages
    total_engagement = sum(v["total_engagement"] for v in media_stats.values())
    max_avg = 0

    content_performance = []
    type_config = {
        "image": {"label": "Image Posts", "icon": "faImage", "color": "bg-cyan-400"},
        "video": {"label": "Video Content", "icon": "faVideo", "color": "bg-violet-400"},
        "text": {"label": "Text Only", "icon": "faAlignLeft", "color": "bg-teal-400"},
        "poll": {"label": "Polls & Questions", "icon": "faPoll", "color": "bg-orange-400"},
    }

    # First pass: calculate averages
    for media_type in ["image", "video", "text", "poll"]:
        stats = media_stats.get(media_type, {"posts": 0, "total_engagement": 0})
        avg = stats["total_engagement"] / max(stats["posts"], 1)
        if avg > max_avg:
            max_avg = avg

    # Second pass: build output
    for media_type in ["image", "video", "text", "poll"]:
        stats = media_stats.get(media_type, {
            "posts": 0, "total_engagement": 0, "likes": 0, "comments": 0, "shares": 0, "sample_posts": []
        })
        config = type_config[media_type]
        avg = stats["total_engagement"] / max(stats["posts"], 1)
        pct = round((avg / max_avg) * 100) if max_avg > 0 else 0

        content_performance.append({
            "label": config["label"],
            "icon": config["icon"],
            "color": config["color"],
            "value": pct,
            "posts": stats["posts"],
            "avgEngagement": round(avg),
            "totalEngagement": stats["total_engagement"],
            "likes": stats["likes"],
            "comments": stats["comments"],
            "shares": stats["shares"],
            "sample_posts": stats["sample_posts"]
        })

    # Sort by value descending
    content_performance.sort(key=lambda x: x["value"], reverse=True)

    return jsonify({
        "content_performance": content_performance,
        "total_posts": len(posts),
        "total_engagement": total_engagement
    })


# -------------------------------
# ROUTE 17 : AI ANALYTICS INSIGHTS
# Generates 3 AI-powered insight cards:
# Content Suggestion, Timing Optimization,
# Growth Opportunity — from real data
# -------------------------------
@test_bp.route("/api/analytics-ai-insights", methods=["GET"])
@jwt_required()
def analytics_ai_insights():
    current_user_id = get_jwt_identity()
    now = datetime.utcnow()

    try:
        ObjectId(current_user_id)
        current_user = current_app.mongo.users.find_one({"_id": ObjectId(current_user_id)})
    except Exception:
        current_user = current_app.mongo.users.find_one({"_id": current_user_id})

    user_email = current_user.get("email") if current_user else None

    query_conditions = [{"user_id": current_user_id}]
    try:
        ObjectId(current_user_id)
        query_conditions.append({"user_id": ObjectId(current_user_id)})
    except Exception:
        pass
    if user_email:
        query_conditions.append({"user_id": user_email})

    posts = list(current_app.mongo.posts.find({"$or": query_conditions}))
    user_post_ids = [str(post["_id"]) for post in posts]

    # Auto-generate interactions for posts that don't have any yet
    for post in posts:
        post_id_str = str(post["_id"])
        schedule_date = parse_schedule_date(post.get("schedule_date"))
        if schedule_date is None or schedule_date > now:
            continue
        existing = current_app.mongo.interactions.count_documents({"post_id": post_id_str})
        if existing == 0:
            new_interactions = _generate_for_post(post_id_str, schedule_date, now, post.get("content_type", "unclassified"))
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))
    total_interactions = len(interactions)
    total_posts = len(posts) if posts else 1

    # --- Gather comprehensive data for AI ---
    # Platform stats
    platform_count = defaultdict(int)
    platform_post_count = defaultdict(int)
    post_platforms_map = defaultdict(set)

    # Content type stats
    content_type_count = defaultdict(int)
    content_type_engagement = defaultdict(int)

    # Timing stats
    hour_engagement = defaultdict(int)
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_engagement = defaultdict(int)

    # Persona/location/industry
    persona_count = defaultdict(int)
    location_count = defaultdict(int)
    industry_count = defaultdict(int)

    # Engagement breakdown
    total_likes = 0
    total_comments = 0
    total_shares = 0

    for i in interactions:
        plat = i.get("platform", "Unknown")
        platform_count[plat] += 1
        pid = i.get("post_id")
        if pid:
            post_platforms_map[pid].add(plat)

        created = i.get("created_at")
        if isinstance(created, datetime):
            hour_engagement[created.hour] += 1
            day_engagement[day_names[created.weekday()]] += 1

        persona_count[i.get("persona", "Unknown")] += 1
        location_count[i.get("location", "Unknown")] += 1
        industry_count[i.get("industry", "Unknown")] += 1

        t = i.get("type", "like")
        if t == "like":
            total_likes += 1
        elif t == "comment":
            total_comments += 1
        elif t == "share":
            total_shares += 1

    for post in posts:
        ct = post.get("content_type", "unclassified")
        content_type_count[ct] += 1
        # Check platforms from post document
        plats = post.get("platforms", {})
        if plats:
            for p, enabled in plats.items():
                if enabled:
                    platform_post_count[p] += 1

    # Also count from interaction-derived platforms
    for pid, plats in post_platforms_map.items():
        for plat in plats:
            if plat not in platform_post_count or platform_post_count[plat] == 0:
                platform_post_count[plat] += 1

    # Content type engagement
    post_ct_map = {str(p["_id"]): p.get("content_type", "unclassified") for p in posts}
    for i in interactions:
        ct = post_ct_map.get(i.get("post_id"), "unclassified")
        content_type_engagement[ct] += 1

    # Best hours
    top_hours = sorted(hour_engagement.items(), key=lambda x: x[1], reverse=True)[:3]
    top_days = sorted(day_engagement.items(), key=lambda x: x[1], reverse=True)[:3]

    # Best content types by avg engagement
    ct_avg = {}
    for ct, count in content_type_count.items():
        ct_avg[ct] = round(content_type_engagement.get(ct, 0) / max(count, 1), 1)

    engagement_rate = round(total_interactions / total_posts, 2)

    # Build data summary for AI
    data_summary = (
        f"Total posts: {total_posts}\n"
        f"Total interactions: {total_interactions}\n"
        f"Engagement rate: {engagement_rate} interactions/post\n"
        f"Likes: {total_likes}, Comments: {total_comments}, Shares: {total_shares}\n\n"
        f"Platform interaction counts: {dict(platform_count)}\n"
        f"Platform post counts: {dict(platform_post_count)}\n"
        f"Content type counts: {dict(content_type_count)}\n"
        f"Content type avg engagement: {ct_avg}\n"
        f"Top personas: {dict(persona_count)}\n"
        f"Top locations: {dict(location_count)}\n"
        f"Top industries: {dict(industry_count)}\n"
        f"Top hours (hour, count): {top_hours}\n"
        f"Top days (day, count): {top_days}\n"
    )

    prompt = f"""You are a social media analytics AI expert. Analyze this REAL engagement data and generate 3 specific, data-driven insight cards.

DATA:
{data_summary}

Respond in strict JSON with this EXACT format:
{{
  "content_suggestion": {{
    "title": "short 3-5 word title",
    "text": "2-3 sentences with SPECIFIC numbers from the data. Which content type performs best? How much better? What should the user create more of?",
    "footer": "Based on X posts analyzed"
  }},
  "timing_optimization": {{
    "title": "short 3-5 word title",
    "text": "2-3 sentences with SPECIFIC times and days from the data. When exactly should they post? How much better is that time vs average?",
    "footer": "Based on X interactions analyzed"
  }},
  "growth_opportunity": {{
    "title": "short 3-5 word title",
    "text": "2-3 sentences about platform strategy OR audience targeting. Use real platform percentages. Which platform to double down on or expand to? Which persona/industry to target?",
    "footer": "Estimated reach: X based on engagement"
  }}
}}

Rules:
- Use REAL numbers from the data — never make up statistics
- Be specific and actionable, not generic
- Reference actual content types, platforms, days, hours from the data
- Each insight must be unique and cover a different angle
Only return valid JSON, no markdown."""

    try:
        ai_data = _call_openrouter(
            prompt,
            system_msg="You are a social media analytics expert. Return strict JSON only."
        )

        return jsonify({
            "success": True,
            "content_suggestion": ai_data.get("content_suggestion", {}),
            "timing_optimization": ai_data.get("timing_optimization", {}),
            "growth_opportunity": ai_data.get("growth_opportunity", {}),
            "data_summary": {
                "total_posts": total_posts,
                "total_interactions": total_interactions,
                "engagement_rate": engagement_rate,
                "estimated_reach": total_interactions * 15
            }
        })

    except Exception as e:
        print(f"[AI-ANALYTICS-INSIGHTS] Error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "data_summary": {
                "total_posts": total_posts,
                "total_interactions": total_interactions,
                "engagement_rate": engagement_rate,
                "estimated_reach": total_interactions * 15
            }
        }), 500