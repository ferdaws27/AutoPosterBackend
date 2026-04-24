from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import requests as http_requests
import json
import os
from datetime import datetime
from bson.objectid import ObjectId

media_bp = Blueprint("media_bp", __name__, url_prefix="/api/media")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@media_bp.post("/generate")
@jwt_required()
def generate_media():
    """Generate carousel slides or video script using Gemini AI."""
    data = request.get_json()
    text = (data.get("text") or "").strip()
    media_type = data.get("type", "carousel")  # carousel | video
    voice_profile = data.get("voiceProfile")

    voice_context = ""
    if voice_profile:
        voice_context = f"""\n\nWRITING VOICE PROFILE (adapt all content to match this style):
- Tone: {voice_profile.get('tone', 'Neutral')}
- Sentence Style: {voice_profile.get('sentenceStyle', 'Medium')}
- Structure: {voice_profile.get('structure', '')}
- Hook Style: {voice_profile.get('hookStyle', '')}
- Emoji Usage: {voice_profile.get('emojiUsage', 'Minimal')}
- Writing Patterns: {', '.join(voice_profile.get('writingPatterns', []))}
- Unique Traits: {', '.join(voice_profile.get('uniqueTraits', []))}
Make sure headlines, body text, narration, and CTAs all reflect this voice."""

    if not text:
        return jsonify({"success": False, "error": "Text content is required"}), 400

    api_key = OPENROUTER_API_KEY
    if not api_key:
        return jsonify({"success": False, "error": "OpenRouter API key not configured"}), 500

    try:
        if media_type == "carousel":
            prompt = f"""You are a world-class social media strategist and copywriter who has grown 50+ LinkedIn and Instagram accounts to 100K+ followers. You specialize in creating viral carousel posts that generate massive engagement.

Your task: Transform the following content into a high-converting LinkedIn/Instagram carousel with 6-8 slides.

CONTENT TO TRANSFORM:
---
{text}
---
{voice_context}

STRATEGIC FRAMEWORK:
1. HOOK SLIDE (Slide 1): Use a pattern-interrupt headline — a bold claim, surprising statistic, contrarian take, or curiosity gap that makes people STOP scrolling. This is the most critical slide.
2. PROBLEM/CONTEXT (Slide 2): Establish relatability — describe the pain point or situation your audience faces. Use "you" language.
3. CORE CONTENT (Slides 3-6): One key insight per slide. Each must be self-contained and valuable. Use concrete numbers, examples, or frameworks instead of vague advice.
4. SUMMARY/PROOF (Slide 7): Reinforce the value with a quick recap, result, or social proof.
5. CTA SLIDE (Final): Clear, specific call to action. Tell them EXACTLY what to do next (follow, comment, save, share, link in bio).

COPYWRITING RULES:
- Headlines: Max 8 words. Use power words (secret, proven, mistake, actually, instead)
- Body: 2-3 punchy sentences. Write at a 6th-grade reading level
- Use line breaks between sentences for readability
- Each slide must deliver ONE clear takeaway
- Avoid jargon, clichés, and filler words ("In today's world...", "It's important to...")
- Use specific numbers over vague claims ("3x faster" not "much faster")
- Write in active voice, present tense

Return ONLY valid JSON (no markdown, no code blocks) in this exact format:
{{
  "title": "Compelling carousel title that teases the value",
  "slides": [
    {{
      "slideNumber": 1,
      "headline": "Short, punchy, scroll-stopping headline (max 8 words)",
      "body": "Supporting text that expands on the headline. Keep it concise and impactful.",
      "designNote": "Specific visual direction: dominant color, layout style (centered/left-aligned), icon or illustration idea, typography weight",
      "imageQuery": "3-4 word visual concept for AI image background"
    }}
  ],
  "hashtags": ["relevant", "niche-specific", "hashtags", "mix-of-broad-and-specific"],
  "estimatedEngagement": "High/Medium/Low — with specific reason based on content virality factors"
}}"""

        else:  # video
            prompt = f"""You are an elite short-form video producer who has created viral content for top creators on TikTok, Instagram Reels, and YouTube Shorts. Your videos consistently get 1M+ views because of your mastery of pacing, hooks, and storytelling.

Your task: Transform the following content into a compelling 30-60 second vertical video script.

CONTENT TO TRANSFORM:
---
{text}
---
{voice_context}

VIDEO STRUCTURE FRAMEWORK:
1. THE HOOK (0-3s): The first 3 seconds decide everything. Use one of these proven patterns:
   - "Stop scrolling if you..." + relatable situation
   - Shocking stat or claim shown on screen
   - Quick visual that creates curiosity
   - Direct question to the viewer
2. THE SETUP (3-10s): Establish context quickly. Why should they care? What problem are you solving?
3. THE MEAT (10-40s): Deliver value in 2-4 punchy scenes. Each scene = one key point. Use concrete examples, numbers, or demonstrations.
4. THE PAYOFF (40-50s): The "aha moment" — the main insight, result, or transformation.
5. THE CTA (50-60s): Tell viewers exactly what to do: follow, comment a specific word, share, save, or visit link.

SCRIPT RULES:
- Narration: Write exactly how someone TALKS, not how they write. Use contractions ("don't", "you're"), rhetorical questions, and conversational pauses ("...and here's the thing")
- Pacing: Vary sentence length. Short punchy lines for impact. Slightly longer for explanation. Never more than 2 sentences per scene
- Visual Direction: Be SPECIFIC — describe exact camera angles (close-up hands, medium shot, over-shoulder), movements (slow zoom in, quick pan), and what's literally on screen
- Text Overlay: Use for key stats, lists, or emphasis. Max 5-7 words per overlay. Not every scene needs one
- Emotional arc: Start with curiosity/shock → build tension → deliver satisfaction
- Total word count for all narration combined: 80-150 words (average speaking pace)

Return ONLY valid JSON (no markdown, no code blocks) in this exact format:
{{
  "title": "Compelling video title that hooks viewers",
  "duration": "45 seconds",
  "format": "9:16 vertical",
  "scenes": [
    {{
      "sceneNumber": 1,
      "duration": "3s",
      "type": "Hook",
      "narration": "Exactly what the speaker says — written conversationally",
      "visualDirection": "Specific visual: camera angle, what's on screen, movement, lighting mood",
      "textOverlay": "Bold text shown on screen (or empty string if none)",
      "transition": "cut/fade/zoom/swipe"
    }}
  ],
  "musicSuggestion": "Specific music mood and tempo (e.g. 'upbeat lo-fi hip hop, 90 BPM' or 'dramatic orchestral build')",
  "hashtags": ["relevant", "trending", "niche-specific", "hashtags"],
  "estimatedEngagement": "High/Medium/Low — with specific reason"
}}"""

        resp = http_requests.post(
            OPENROUTER_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an expert content strategist. You ALWAYS return valid JSON with no markdown formatting, no code blocks, and no extra text. Your output is parsed directly by a JSON parser."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.75,
                "max_tokens": 3000,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            error_detail = resp.text[:500]
            return jsonify({
                "success": False,
                "error": f"OpenRouter API error ({resp.status_code}): {error_detail}"
            }), 502

        or_data = resp.json()
        raw_text = or_data["choices"][0]["message"]["content"]

        # Clean markdown code blocks if present
        import re
        cleaned = raw_text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        result = json.loads(cleaned)

        return jsonify({
            "success": True,
            "type": media_type,
            "data": result
        })

    except json.JSONDecodeError:
        return jsonify({
            "success": False,
            "error": "AI returned invalid JSON. Please try again.",
            "raw": raw_text[:500] if 'raw_text' in dir() else None
        }), 500
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@media_bp.get("/test")
def test_endpoint():
    """Test endpoint to verify media_bp is loaded."""
    return jsonify({
        "success": True,
        "message": "Media blueprint is working",
        "timestamp": datetime.utcnow().isoformat()
    })

@media_bp.post("/save-carousel")
@jwt_required()
def save_carousel():
    """Save carousel to MongoDB."""
    try:
        print("=== SAVE CAROUSEL ENDPOINT CALLED ===")
        data = request.get_json()
        print(f"Received data keys: {data.keys() if data else 'No data'}")
        
        # Get user ID from JWT
        user_id = get_jwt_identity()
        print(f"User ID from JWT: {user_id}")
        
        # If user is guest, try to get real user from database
        if user_id == "guest" or not user_id:
            print("Guest user detected, trying to get real user ID...")
            # Try to get user from JWT token or session
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
                # You could decode the token here to get the real user ID
                # For now, we'll use the guest ID
                user_id = "guest"
        
        # Try to get MongoDB connection
        try:
            saved_carousels = current_app.mongo["saved_carousels"]
            print(f"MongoDB collection accessed successfully")
        except Exception as mongo_err:
            print(f"MongoDB access error: {mongo_err}")
            return jsonify({
                "success": False,
                "error": f"MongoDB access failed: {str(mongo_err)}"
            }), 500
        
        carousel_data = {
            "title": data.get("title", "Untitled Carousel"),
            "slides": data.get("slides", []),
            "slideImages": data.get("slideImages", []),
            "image": data.get("image", ""),
            "createdAt": datetime.utcnow(),
            "userId": user_id,
            "userEmail": None  # Will be populated if we have user info
        }
        
        # Try to get user email if user_id is not guest
        if user_id and user_id != "guest":
            try:
                from bson.objectid import ObjectId
                user = current_app.mongo["users"].find_one({"_id": ObjectId(user_id)})
                if user:
                    carousel_data["userEmail"] = user.get("email")
            except:
                pass
        
        print(f"Carousel data to save: {carousel_data}")
        
        # Insert into MongoDB
        result = saved_carousels.insert_one(carousel_data)
        print(f"Insert result: {result}")
        print(f"Inserted ID: {result.inserted_id}")
        
        print("=== CAROUSEL SAVED SUCCESSFULLY ===")
        return jsonify({
            "success": True,
            "message": "Carousel saved successfully",
            "carouselId": str(result.inserted_id)
        }), 201
        
    except Exception as e:
        print(f"=== ERROR SAVING CAROUSEL: {e} ===")
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@media_bp.get("/saved-carousels")
@jwt_required()
def get_saved_carousels():
    """Get user's saved carousels from MongoDB."""
    try:
        # Use app's MongoDB connection
        saved_carousels = current_app.mongo["saved_carousels"]
        user_id = get_jwt_identity()
        carousels = list(saved_carousels.find(
            {"userId": user_id}
        ).sort("createdAt", -1).limit(10))
        
        # Convert ObjectId to string for JSON serialization
        for carousel in carousels:
            carousel["_id"] = str(carousel["_id"])
            del carousel["userId"]  # Don't return user ID to frontend
            
        return jsonify({
            "success": True,
            "carousels": carousels
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@media_bp.delete("/saved-carousels/<carousel_id>")
@jwt_required()
def delete_saved_carousel(carousel_id):
    """Delete saved carousel from MongoDB."""
    try:
        print(f"=== DELETE CAROUSEL CALLED ===")
        print(f"Carousel ID: {carousel_id}")
        
        # Use app's MongoDB connection
        saved_carousels = current_app.mongo["saved_carousels"]
        user_id = get_jwt_identity()
        print(f"User ID: {user_id}")
        
        # First check if carousel exists
        try:
            carousel = saved_carousels.find_one({"_id": ObjectId(carousel_id)})
            print(f"Carousel found: {carousel is not None}")
            if carousel:
                print(f"Carousel userId: {carousel.get('userId')}")
        except Exception as e:
            print(f"Error finding carousel: {e}")
        
        result = saved_carousels.delete_one({
            "_id": ObjectId(carousel_id),
            "userId": user_id
        })
        
        print(f"Deleted count: {result.deleted_count}")
        
        if result.deleted_count == 0:
            print("Carousel not found or user ID mismatch")
            return jsonify({
                "success": False,
                "error": "Carousel not found"
            }), 404
            
        print("✓ Carousel deleted successfully")
        return jsonify({
            "success": True,
            "message": "Carousel deleted successfully"
        }), 200
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
