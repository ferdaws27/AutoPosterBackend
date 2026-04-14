"""
Clone / Voice Analysis routes.
Uses Apify to scrape real posts from a profile URL,
then OpenRouter AI to analyze the writing voice.
All analyses and scraped data are persisted in MongoDB.
"""

import datetime
import json
import os
import re
import time

import requests
from bson import ObjectId
from flask import Blueprint, current_app, jsonify, request

clone_bp = Blueprint("clone", __name__)


# ─── Profile image fallback via SerpAPI ──────────────────────────

def _search_profile_image(name, platform, serpapi_key):
    """
    Search for a profile image using SerpAPI Google Images.
    Returns image URL or None.
    """
    if not serpapi_key or not name:
        return None
    try:
        query = f"{name} {platform} profile photo"
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_images",
                "q": query,
                "num": 3,
                "api_key": serpapi_key,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        images = resp.json().get("images_results", [])
        for img in images:
            url = img.get("original") or img.get("thumbnail")
            if url and url.startswith("http"):
                return url
    except Exception as e:
        current_app.logger.warning(f"SerpAPI image search failed: {e}")
    return None


# ─── Apify helpers ───────────────────────────────────────────────

def _scrape_with_apify(url, apify_key):
    """
    Use Apify scrapers to fetch real posts from a profile URL.
    Supports LinkedIn, Twitter/X, and Medium.
    Returns a list of post text strings.
    """
    url_lower = url.lower()

    # Determine actor and input based on platform
    if "linkedin.com" in url_lower:
        actor_id = "apifly/linkedin-scraper"
        actor_input = {
            "deepScrape": True,
            "limitPerSource": 10,
            "rawData": False,
            "urls": [url],
        }
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        # Extract handle from URL like https://twitter.com/username or https://x.com/username
        handle = url.rstrip("/").split("/")[-1].lstrip("@")
        actor_id = "apidojo/twitter-user-scraper"
        actor_input = {
            "startUrls": [{"url": url}],
            "handle": handle,
            "maxTweets": 15,
            "mode": "user",
        }
    elif "medium.com" in url_lower or url.startswith("@"):
        actor_id = "newrocknot/medium-scraper"
        actor_input = {
            "startUrls": [{"url": url}],
            "maxArticles": 10,
        }
    else:
        return [], None

    # Start the actor run
    run_resp = requests.post(
        f"https://api.apify.com/v2/acts/{actor_id}/runs",
        params={"token": apify_key},
        headers={"Content-Type": "application/json"},
        json=actor_input,
        timeout=30,
    )

    if run_resp.status_code not in (200, 201):
        current_app.logger.error(f"Apify run start failed: {run_resp.status_code} {run_resp.text[:300]}")
        return [], None

    run_data = run_resp.json().get("data", {})
    run_id = run_data.get("id")
    if not run_id:
        return [], None

    # Poll for completion (max ~90 seconds)
    dataset_id = None
    for _ in range(30):
        time.sleep(3)
        status_resp = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": apify_key},
            timeout=15,
        )
        if status_resp.status_code != 200:
            continue
        status_data = status_resp.json().get("data", {})
        run_status = status_data.get("status")

        if run_status == "SUCCEEDED":
            dataset_id = status_data.get("defaultDatasetId")
            break
        elif run_status in ("FAILED", "ABORTED", "TIMED-OUT"):
            current_app.logger.error(f"Apify run {run_status}")
            return [], None

    if not dataset_id:
        return [], None

    # Fetch dataset items
    items_resp = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": apify_key, "format": "json"},
        timeout=30,
    )
    if items_resp.status_code != 200:
        return [], None

    items = items_resp.json()
    posts = []
    profile_image = None
    for item in items:
        # Try to extract profile image
        if not profile_image:
            img = (
                item.get("profileImageUrl")
                or item.get("profilePicture")
                or item.get("profileImage")
                or item.get("avatar")
                or item.get("authorImage")
                or item.get("authorAvatar")
                or item.get("profile_image_url")
                or (item.get("user") or {}).get("profile_image_url_https")
                or (item.get("user") or {}).get("profileImageUrl")
                or ""
            )
            if img and isinstance(img, str) and img.startswith("http"):
                profile_image = img

        # Extract text from various possible fields (covers LinkedIn, Twitter, Medium)
        text = (
            item.get("text")           # Twitter tweets, LinkedIn
            or item.get("full_text")    # Twitter extended tweets
            or item.get("postText")    # LinkedIn posts
            or item.get("content")     # Medium articles
            or item.get("article")     # Medium article body
            or item.get("description") # General fallback
            or item.get("body")        # Medium body
            or item.get("tweet")       # Some Twitter scrapers
            or ""
        )
        # For Medium, also try the title + subtitle + paragraphs
        if not text and item.get("title"):
            paragraphs = item.get("paragraphs") or item.get("sections") or []
            if isinstance(paragraphs, list):
                text = item["title"] + "\n\n" + "\n".join(str(p) for p in paragraphs[:5])
            else:
                text = item["title"]

        if isinstance(text, str) and len(text.strip()) > 20:
            posts.append(text.strip())

    return posts[:15], profile_image  # Cap at 15 posts


# ─── OpenRouter helper ───────────────────────────────────────────

def _call_openrouter(api_key, messages, temperature=0.7, max_tokens=2000):
    """Call OpenRouter API."""
    model = current_app.config.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    resp = requests.post(
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
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"].strip()


# ─── Text analysis helpers ────────────────────────────────────────

def _compute_post_stats(posts):
    """Compute real statistics from scraped posts."""
    if not posts:
        return {}
    word_counts = [len(p.split()) for p in posts]
    total_words = sum(word_counts)
    avg_words = round(total_words / len(posts))
    char_counts = [len(p) for p in posts]
    avg_chars = round(sum(char_counts) / len(posts))

    # Estimate reading level (simple syllable-based Flesch-Kincaid approximation)
    total_sentences = sum(p.count('.') + p.count('!') + p.count('?') or 1 for p in posts)
    # Rough syllable count: count vowel groups
    total_syllables = 0
    for post in posts:
        words = re.findall(r'[a-zA-Z]+', post.lower())
        for w in words:
            syllables = len(re.findall(r'[aeiouy]+', w))
            total_syllables += max(syllables, 1)

    if total_sentences > 0 and total_words > 0:
        fk_grade = 0.39 * (total_words / total_sentences) + 11.8 * (total_syllables / total_words) - 15.59
        fk_grade = max(1, min(16, round(fk_grade)))
    else:
        fk_grade = 8

    # Emoji density
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
        "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
        "\U00002600-\U000026FF\U0000200D]+", flags=re.UNICODE
    )
    total_emojis = sum(len(emoji_pattern.findall(p)) for p in posts)
    emoji_per_post = round(total_emojis / len(posts), 1)

    # Hashtag density
    total_hashtags = sum(p.count('#') for p in posts)
    hashtag_per_post = round(total_hashtags / len(posts), 1)

    return {
        "postCount": len(posts),
        "avgWordCount": avg_words,
        "avgCharCount": avg_chars,
        "totalWords": total_words,
        "readingGrade": fk_grade,
        "emojiPerPost": emoji_per_post,
        "hashtagPerPost": hashtag_per_post,
        "shortestPost": min(word_counts),
        "longestPost": max(word_counts),
    }


# ─── Routes ──────────────────────────────────────────────────────

@clone_bp.route("/analyze", methods=["POST"])
def analyze_profile():
    """
    Analyze a creator's writing voice.
    1. Scrapes real posts via Apify
    2. Computes real word-level stats
    3. Feeds posts + stats to AI for deep voice analysis
    4. Saves everything to MongoDB (clone_analyses collection)
    
    Accepts: { url: string, user_id?: string }
    Returns: { success, profile, analysis, postStats, postsScraped, analysisId }
    """
    try:
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        user_id = data.get("user_id", "guest")
        if not url:
            return jsonify({"success": False, "error": "URL or handle is required"}), 400

        api_key = current_app.config.get("OPENROUTER_API_KEY")
        apify_key = current_app.config.get("APIFY_KEY")

        if not api_key:
            return jsonify({"success": False, "error": "AI API key not configured"}), 500

        # Detect platform
        platform = "unknown"
        if "linkedin.com" in url.lower():
            platform = "LinkedIn"
        elif "twitter.com" in url.lower() or "x.com" in url.lower():
            platform = "X (Twitter)"
        elif "medium.com" in url.lower():
            platform = "Medium"
        elif url.startswith("@"):
            platform = "X (Twitter)"
            url = f"https://x.com/{url.lstrip('@')}"

        # Step 1: Scrape real posts with Apify
        scraped_posts = []
        profile_image_url = None
        if apify_key and platform in ("LinkedIn", "X (Twitter)", "Medium"):
            try:
                scraped_posts, profile_image_url = _scrape_with_apify(url, apify_key)
            except Exception as e:
                current_app.logger.warning(f"Apify scrape failed, falling back to AI-only: {e}")

        # Step 2: Compute real stats from scraped posts
        post_stats = _compute_post_stats(scraped_posts) if scraped_posts else {}

        # Step 3: Build the AI analysis prompt
        if scraped_posts:
            posts_block = "\n\n---\n\n".join(
                f"POST {i+1}:\n{post}" for i, post in enumerate(scraped_posts)
            )
            stats_context = ""
            if post_stats:
                stats_context = f"""
COMPUTED STATISTICS (from actual posts - use these exact numbers, do NOT invent your own):
- Posts analyzed: {post_stats['postCount']}
- Average post length: {post_stats['avgWordCount']} words
- Shortest post: {post_stats['shortestPost']} words
- Longest post: {post_stats['longestPost']} words
- Flesch-Kincaid reading grade: Grade {post_stats['readingGrade']}
- Emoji per post: {post_stats['emojiPerPost']}
- Hashtags per post: {post_stats['hashtagPerPost']}
"""
            system_prompt = f"""You are an expert writing style analyst and voice profiling engine.
I will provide you with {len(scraped_posts)} REAL posts from a creator's {platform} profile, plus computed statistics.

Your job: perform a DEEP, PRECISE analysis of their writing voice. Be specific - not generic.
{stats_context}
IMPORTANT RULES:
- Use the EXACT statistics provided above for avgPostLength, readingLevel, emojiUsage, hashtagUsage
- For tone, be specific (e.g. "Conversational & Authoritative with subtle humor" not just "Professional")
- For structure, describe the actual pattern you see (e.g. "Bold statement hook -> 3-4 short paragraphs -> question CTA")
- For writingPatterns, list SPECIFIC patterns from the actual text (exact phrases they reuse, line break habits, list styles)
- For uniqueTraits, identify what makes this creator DIFFERENT from others
- For hookStyle and ctaStyle, give actual examples from their posts
- samplePost should perfectly mimic their voice - someone familiar with them should recognize it

Return ONLY a JSON object (no markdown, no backticks) with this exact structure:
{{
  "profile": {{
    "name": "Creator's name (extract from content or use handle)",
    "handle": "Their handle or profile identifier",
    "platform": "{platform}",
    "bio": "Inferred bio: what they write about and their likely role/expertise"
  }},
  "analysis": {{
    "tone": "Precise primary tone with nuance (2-4 descriptors)",
    "structure": "Actual post structure pattern with arrows (e.g. Hook -> Body -> CTA)",
    "sentenceStyle": "Short & Punchy / Medium & Clear / Long & Detailed / Mixed",
    "emojiUsage": "None / Minimal (0-1 per post) / Moderate (2-4 per post) / Heavy (5+ per post)",
    "hashtagUsage": "None / Minimal (0-1 per post) / Moderate (2-3 per post) / Heavy (4+ per post)",
    "vocabularyLevel": "Simple / Intermediate / Advanced / Expert / Mixed",
    "contentThemes": ["theme1", "theme2", "theme3", "theme4", "theme5"],
    "writingPatterns": ["Specific pattern 1", "Specific pattern 2", "Specific pattern 3", "Specific pattern 4"],
    "hookStyle": "Description of how they open posts, with a real example",
    "ctaStyle": "Description of how they end posts, with a real example",
    "uniqueTraits": ["Specific unique trait 1", "Specific unique trait 2", "Specific unique trait 3"],
    "engagementTactics": ["Specific tactic 1", "Specific tactic 2", "Specific tactic 3"],
    "confidenceScore": 85,
    "avgPostLength": "~{post_stats.get('avgWordCount', 120)} words",
    "readingLevel": "Grade {post_stats.get('readingGrade', 8)}",
    "styleSummary": "2-3 sentence summary capturing the essence of their writing voice, what makes it unique, and the feeling it gives readers",
    "sampleHook": "An exact-style hook they would write",
    "samplePost": "A full sample post (4-6 sentences) perfectly mimicking their voice, structure, and style"
  }}
}}

confidenceScore: 80-95 based on how much data you have."""

            user_prompt = f"Profile URL: {url}\n\nHere are the real posts to analyze:\n\n{posts_block}"
        else:
            # Fallback: AI-only analysis (no scraped data)
            system_prompt = f"""You are an expert writing style analyst.
Given a creator's {platform} profile URL or handle, analyze their public writing voice.
If you recognize them, provide accurate analysis. If not, give a reasonable estimate.
Be SPECIFIC and DETAILED in every field - avoid generic descriptions.

Return ONLY a JSON object (no markdown, no backticks) with this exact structure:
{{
  "profile": {{
    "name": "Creator's full name",
    "handle": "@handle or profile identifier",
    "platform": "{platform}",
    "bio": "Short bio if known"
  }},
  "analysis": {{
    "tone": "Precise primary tone with nuance",
    "structure": "Typical post structure pattern",
    "sentenceStyle": "Short & Punchy / Medium & Clear / Long & Detailed / Mixed",
    "emojiUsage": "None / Minimal / Moderate / Heavy",
    "hashtagUsage": "None / Minimal / Moderate / Heavy",
    "vocabularyLevel": "Simple / Intermediate / Advanced / Expert / Mixed",
    "contentThemes": ["theme1", "theme2", "theme3"],
    "writingPatterns": ["Pattern 1", "Pattern 2", "Pattern 3"],
    "hookStyle": "How they typically start posts with example",
    "ctaStyle": "How they typically end posts with example",
    "uniqueTraits": ["Unique trait 1", "Unique trait 2", "Unique trait 3"],
    "engagementTactics": ["Tactic 1", "Tactic 2"],
    "confidenceScore": 55,
    "avgPostLength": "~120 words",
    "readingLevel": "Grade 8",
    "styleSummary": "2-3 sentence summary of their writing voice",
    "sampleHook": "An example hook in their style",
    "samplePost": "A full sample post (4-6 sentences) in their style"
  }}
}}

confidenceScore: 70-95 for known creators, 40-60 for unknown."""

            user_prompt = f"Analyze the writing voice of: {url}\nPlatform: {platform}"

        raw = _call_openrouter(api_key, [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], temperature=0.5, max_tokens=2500)

        # Clean and parse JSON - be aggressive about extracting valid JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        # If AI wrapped with extra text, extract the first { ... } block
        brace_start = cleaned.find("{")
        brace_end = cleaned.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            cleaned = cleaned[brace_start:brace_end + 1]

        result = json.loads(cleaned)

        profile_data = result.get("profile", {})
        analysis_data = result.get("analysis", {})

        if profile_image_url:
            profile_data["imageUrl"] = profile_image_url
        elif not profile_data.get("imageUrl"):
            # Fallback 1: Search for a real profile image via SerpAPI
            serpapi_key = current_app.config.get("SERPAPI_KEY")
            searched_image = _search_profile_image(
                profile_data.get("name") or profile_data.get("handle", ""),
                platform,
                serpapi_key,
            )
            if searched_image:
                profile_data["imageUrl"] = searched_image
            else:
                # Fallback 2: Generate avatar from initials
                avatar_name = (
                    profile_data.get("name")
                    or profile_data.get("handle", "").lstrip("@")
                    or "User"
                )
                profile_data["imageUrl"] = (
                    f"https://ui-avatars.com/api/?name={requests.utils.quote(avatar_name)}"
                    f"&background=0891b2&color=fff&size=128&bold=true&format=png"
                )

        # Step 4: Save the full analysis to MongoDB
        analysis_doc = {
            "user_id": user_id,
            "url": url,
            "platform": platform,
            "profile": profile_data,
            "analysis": analysis_data,
            "postStats": post_stats,
            "scrapedPosts": scraped_posts,
            "postsScraped": len(scraped_posts),
            "created_at": datetime.datetime.utcnow(),
        }
        collection = current_app.mongo["clone_analyses"]
        insert_result = collection.insert_one(analysis_doc)
        analysis_id = str(insert_result.inserted_id)

        return jsonify({
            "success": True,
            "profile": profile_data,
            "analysis": analysis_data,
            "postStats": post_stats,
            "postsScraped": len(scraped_posts),
            "analysisId": analysis_id,
        })

    except json.JSONDecodeError as e:
        current_app.logger.error(f"JSON parse error: {e}\nRaw AI output: {raw[:500] if 'raw' in locals() else 'N/A'}")
        return jsonify({"success": False, "error": "AI returned invalid format, please retry"}), 502
    except Exception as e:
        current_app.logger.error(f"Clone analyze error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@clone_bp.route("/presets", methods=["GET"])
def get_presets():
    """Get all saved voice presets for the current user."""
    try:
        user_id = request.args.get("user_id", "guest")
        collection = current_app.mongo["voice_presets"]
        presets = list(collection.find({"user_id": user_id}).sort("created_at", -1))
        for p in presets:
            p["_id"] = str(p["_id"])
            # Ensure every preset has a profile image
            profile = p.get("profile") or {}
            if not profile.get("imageUrl"):
                avatar_name = (
                    profile.get("name")
                    or profile.get("handle", "").lstrip("@")
                    or p.get("name", "User")
                )
                profile["imageUrl"] = (
                    f"https://ui-avatars.com/api/?name={requests.utils.quote(avatar_name)}"
                    f"&background=0891b2&color=fff&size=128&bold=true&format=png"
                )
                p["profile"] = profile
        return jsonify({"success": True, "presets": presets})
    except Exception as e:
        current_app.logger.error(f"Get presets error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@clone_bp.route("/presets", methods=["POST"])
def save_preset():
    """Save a voice preset."""
    try:
        data = request.get_json() or {}
        user_id = data.get("user_id", "guest")
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "Name is required"}), 400

        collection = current_app.mongo["voice_presets"]
        doc = {
            "user_id": user_id,
            "name": name,
            "type": data.get("type", "cloned"),
            "profile": data.get("profile", {}),
            "analysis": data.get("analysis", {}),
            "postStats": data.get("postStats", {}),
            "url": data.get("url", ""),
            "active": False,
            "created_at": datetime.datetime.utcnow(),
        }
        result = collection.insert_one(doc)
        return jsonify({"success": True, "preset_id": str(result.inserted_id)})
    except Exception as e:
        current_app.logger.error(f"Save preset error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@clone_bp.route("/presets/<preset_id>", methods=["DELETE"])
def delete_preset(preset_id):
    """Delete a saved voice preset."""
    try:
        collection = current_app.mongo["voice_presets"]
        result = collection.delete_one({"_id": ObjectId(preset_id)})
        if result.deleted_count == 0:
            return jsonify({"success": False, "error": "Preset not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        current_app.logger.error(f"Delete preset error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@clone_bp.route("/presets/<preset_id>/activate", methods=["POST"])
def activate_preset(preset_id):
    """Set a preset as the active voice."""
    try:
        user_id = request.get_json().get("user_id", "guest") if request.is_json else "guest"
        collection = current_app.mongo["voice_presets"]
        # Deactivate all for user
        collection.update_many({"user_id": user_id}, {"$set": {"active": False}})
        # Activate selected
        result = collection.update_one({"_id": ObjectId(preset_id)}, {"$set": {"active": True}})
        if result.matched_count == 0:
            return jsonify({"success": False, "error": "Preset not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        current_app.logger.error(f"Activate preset error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@clone_bp.route("/analyses", methods=["GET"])
def get_analyses():
    """Get analysis history for the current user."""
    try:
        user_id = request.args.get("user_id", "guest")
        collection = current_app.mongo["clone_analyses"]
        analyses = list(
            collection.find(
                {"user_id": user_id},
                {"scrapedPosts": 0}  # Exclude raw posts from list (too large)
            ).sort("created_at", -1).limit(20)
        )
        for a in analyses:
            a["_id"] = str(a["_id"])
        return jsonify({"success": True, "analyses": analyses})
    except Exception as e:
        current_app.logger.error(f"Get analyses error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@clone_bp.route("/analyses/<analysis_id>", methods=["GET"])
def get_analysis_detail(analysis_id):
    """Get a single analysis with full scraped posts."""
    try:
        collection = current_app.mongo["clone_analyses"]
        doc = collection.find_one({"_id": ObjectId(analysis_id)})
        if not doc:
            return jsonify({"success": False, "error": "Analysis not found"}), 404
        doc["_id"] = str(doc["_id"])
        return jsonify({"success": True, "analysis": doc})
    except Exception as e:
        current_app.logger.error(f"Get analysis detail error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
