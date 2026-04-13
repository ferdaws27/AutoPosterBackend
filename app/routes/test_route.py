from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from collections import defaultdict
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


# -------------------------------
# GENERATE INTERACTIONS POUR 1 POST
# -------------------------------
def _generate_for_post(post_id_str, schedule_date, now):
    delta_seconds = int((now - schedule_date).total_seconds())
    followers_count = random.randint(1000, 6000)
    audience = [f"follower_{i}" for i in range(followers_count)]
    sample = random.sample(audience, k=min(300, len(audience)))

    interactions = []

    for user_id in sample:
        prob = random.random()
        random_seconds = random.randint(0, max(delta_seconds, 1))
        interaction_time = schedule_date + timedelta(seconds=random_seconds)

        if prob < 0.6:
            interaction = {"type": "like"}
        elif prob < 0.8:
            interaction = {"type": "comment", "content": random.choice(COMMENTS)}
        elif prob < 0.9:
            interaction = {"type": "share"}
        else:
            continue  # 10% ne font rien

        interaction.update({
            "post_id": post_id_str,
            "user_id": user_id,
            "created_at": interaction_time,
            "persona": random.choice(PERSONAS),
            "platform": random.choice(PLATFORMS),
            "location": random.choice(LOCATIONS),
            "industry": random.choice(INDUSTRIES)
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

        interactions = _generate_for_post(post_id_str, schedule_date, now)
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

        interactions = _generate_for_post(post_id_str, schedule_date, now)
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
            new_interactions = _generate_for_post(post_id_str, schedule_date, now)
            current_app.mongo.interactions.insert_many(new_interactions)

    interactions = list(current_app.mongo.interactions.find({"post_id": {"$in": user_post_ids}}))

    persona_count = defaultdict(int)
    platform_count = defaultdict(int)
    location_count = defaultdict(int)
    industry_count = defaultdict(int)
    unique_users = set()

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

        persona_count[i["persona"]] += 1
        platform_count[i["platform"]] += 1
        location_count[i["location"]] += 1
        industry_count[i["industry"]] += 1
        unique_users.add(i.get("user_id", ""))

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

    return jsonify({
        "personas": dict(persona_count),
        "platforms": dict(platform_count),
        "locations": dict(location_count),
        "industries": dict(industry_count),
        "engagement_rate": engagement_rate,
        "active_users": len(unique_users),
        "total_interactions": total_interactions,
        "total_posts": total_posts,
        "insights": insights
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
            new_interactions = _generate_for_post(post_id_str, schedule_date, now)
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
        response = http_requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {current_app.config['OPENROUTER_API_KEY']}",
                "Content-Type": "application/json",
                "HTTP-Referer": current_app.config.get("FRONTEND_URL", "http://localhost:5173"),
                "X-Title": "AutoPoster Audience Analyzer"
            },
            json={
                "model": current_app.config["OPENROUTER_MODEL"],
                "messages": [
                    {"role": "system", "content": "You are a senior audience intelligence analyst. Decode engagement patterns, identify growth opportunities, and provide data-backed persona insights. Return strict JSON only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            },
            timeout=30
        )

        result = response.json()
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
            new_interactions = _generate_for_post(post_id_str, schedule_date, now)
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


def _call_openrouter(prompt, system_msg="You are a senior social media analytics expert. Analyze data precisely, reference specific numbers, and provide actionable recommendations. Return strict JSON only — no markdown, no explanation."):
    response = http_requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {current_app.config['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": current_app.config.get("FRONTEND_URL", "http://localhost:5173"),
            "X-Title": "AutoPoster Audience Analyzer"
        },
        json={
            "model": current_app.config["OPENROUTER_MODEL"],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        },
        timeout=30
    )
    result = response.json()
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