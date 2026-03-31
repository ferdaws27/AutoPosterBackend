from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
import requests
import json

quote_generator_bp = Blueprint("quote_generator", __name__, url_prefix="/api/quote-generator")

@quote_generator_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_quote_variations():
    """
    Generate AI-powered quote variations for different platforms using OpenRouter
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data or "quote" not in data:
            return jsonify({"error": "Quote is required"}), 400
        
        quote = data["quote"].strip()
        platforms = data.get("platforms", ["twitter", "linkedin", "medium"])
        brand_signature = data.get("brand_signature", False)
        
        if len(quote) < 10:
            return jsonify({"error": "Quote too short. Minimum 10 characters."}), 400
        
        if len(quote) > 500:
            return jsonify({"error": "Quote too long. Maximum 500 characters."}), 400
        
        # Get OpenRouter API key
        openrouter_api_key = current_app.config.get("OPENROUTER_API_KEY")
        
        if not openrouter_api_key:
            return jsonify({"error": "OpenRouter API key not configured"}), 500
        
        # Create platform-specific prompts
        platform_instructions = {
            "twitter": "Create a Twitter variation (max 280 characters, concise, engaging, include relevant hashtags)",
            "linkedin": "Create a LinkedIn variation (professional tone, business context, 2-3 sentences, include relevant insights)",
            "medium": "Create a Medium variation (longer form, thoughtful, 3-4 sentences, suitable for article excerpt)"
        }
        
        variations = []
        
        for platform in platforms:
            if platform not in platform_instructions:
                continue
                
            try:
                # Create the prompt for this platform
                prompt = f"""
                Original quote: "{quote}"
                
                {platform_instructions[platform]}
                
                Guidelines:
                - Keep the core meaning intact
                - Adapt the tone and style for the platform
                - Make it engaging and shareable
                - Add appropriate formatting
                - {"" if not brand_signature else 'Add signature "— @EtkanAI" at the end'}
                
                Return only the variation text, no explanations.
                """
                
                # Call OpenRouter API
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "anthropic/claude-3-haiku",  # Fast and cost-effective model
                        "messages": [
                            {"role": "system", "content": "You are a skilled social media content creator who excels at adapting quotes for different platforms."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 200,
                        "temperature": 0.7
                    }
                )
                
                if response.status_code != 200:
                    print(f"OpenRouter API error for {platform}: {response.status_code}")
                    raise Exception(f"API call failed with status {response.status_code}")
                
                response_data = response.json()
                variation_text = response_data["choices"][0]["message"]["content"].strip()
                
                # Add brand signature if requested and not already included
                if brand_signature and "@EtkanAI" not in variation_text:
                    variation_text += "\n\n— @EtkanAI"
                
                variations.append({
                    "platform": platform.capitalize(),
                    "text": variation_text,
                    "tone": get_platform_tone(platform),
                    "engagement": estimate_engagement(platform)
                })
                
            except Exception as e:
                print(f"Error generating variation for {platform}: {str(e)}")
                # Add a fallback variation
                fallback_text = quote
                if brand_signature:
                    fallback_text += "\n\n— @EtkanAI"
                
                variations.append({
                    "platform": platform.capitalize(),
                    "text": fallback_text,
                    "tone": "neutral",
                    "engagement": "Medium"
                })
        
        return jsonify({
            "variations": variations,
            "original_quote": quote,
            "platforms": platforms
        }), 200
        
    except Exception as e:
        print(f"Error in quote generation: {str(e)}")
        return jsonify({"error": "Failed to generate quote variations"}), 500

def get_platform_tone(platform):
    """Get the characteristic tone for each platform"""
    tones = {
        "twitter": "witty",
        "linkedin": "professional",
        "medium": "thoughtful"
    }
    return tones.get(platform, "neutral")

def estimate_engagement(platform):
    """Estimate engagement level for each platform"""
    engagement = {
        "twitter": "High",
        "linkedin": "Medium",
        "medium": "Medium"
    }
    return engagement.get(platform, "Medium")

@quote_generator_bp.route("/templates", methods=["GET"])
@jwt_required()
def get_quote_templates():
    """
    Get predefined quote templates for inspiration
    """
    templates = [
        {
            "category": "motivational",
            "template": "The only way to do great work is to love what you do.",
            "variations": ["Keep pushing forward!", "Stay focused on your goals."]
        },
        {
            "category": "business",
            "template": "Innovation distinguishes between a leader and a follower.",
            "variations": ["Lead with creativity!", "Think different, act bold."]
        },
        {
            "category": "wisdom",
            "template": "The future belongs to those who believe in the beauty of their dreams.",
            "variations": ["Dream big, achieve bigger!", "Your dreams shape your reality."]
        }
    ]
    
    return jsonify({"templates": templates}), 200

@quote_generator_bp.route("/health", methods=["GET"])
def health_check():
    """Check if the quote generator service is healthy"""
    return jsonify({
        "status": "healthy",
        "openrouter_configured": bool(current_app.config.get("OPENROUTER_API_KEY")),
        "openai_configured": bool(current_app.config.get("OPENAI_API_KEY"))
    }), 200
