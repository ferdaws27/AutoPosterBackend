from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
import requests
import json

hook_generator_bp = Blueprint("hook_generator", __name__, url_prefix="/api/hook-generator")

@hook_generator_bp.route("/test-generate", methods=["POST"])
def test_generate_hooks():
    """
    Test endpoint without JWT for debugging
    """
    try:
        data = request.get_json()
        
        if not data or "topic" not in data:
            return jsonify({"error": "Topic is required"}), 400
        
        topic = data["topic"].strip()
        platforms = data.get("platforms", ["twitter", "linkedin"])
        
        if len(topic) < 5:
            return jsonify({"error": "Topic too short. Minimum 5 characters."}), 400
        
        # Get OpenRouter API key
        openrouter_api_key = current_app.config.get("OPENROUTER_API_KEY")
        
        if not openrouter_api_key:
            return jsonify({"error": "OpenRouter API key not configured"}), 500
        
        # Simple test with one platform
        platform = platforms[0] if platforms else "twitter"
        
        try:
            prompt = f"""
            Topic: "{topic}"
            
            Generate 3 compelling hooks for {platform} about this topic.
            Make them catchy and engaging.
            Return each hook on a separate line, starting with •.
            """
            
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "anthropic/claude-3-haiku",
                    "messages": [
                        {"role": "system", "content": "You are a master copywriter specializing in creating viral hooks."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 300,
                    "temperature": 0.8
                }
            )
            
            if response.status_code != 200:
                return jsonify({"error": f"OpenRouter API error: {response.status_code}"}), 500
            
            response_data = response.json()
            hooks_text = response_data["choices"][0]["message"]["content"].strip()
            
            # Parse hooks from bullet points
            hooks = []
            for line in hooks_text.split('\n'):
                if line.strip().startswith('•'):
                    hook_text = line.strip().replace('•', '').strip()
                    if hook_text:
                        hooks.append({
                            "text": hook_text,
                            "type": "bold-statement",
                            "score": 85
                        })
            
            # If no bullet points found, use the whole text
            if not hooks:
                hooks = [{"text": hooks_text, "type": "bold-statement", "score": 85}]
            
            return jsonify({
                "hooks": hooks,
                "topic": topic,
                "platforms": platforms,
                "message": "Test successful - OpenRouter working"
            }), 200
            
        except Exception as e:
            return jsonify({"error": f"OpenRouter call failed: {str(e)}"}), 500
        
    except Exception as e:
        return jsonify({"error": f"Test endpoint error: {str(e)}"}), 500

@hook_generator_bp.route("/generate", methods=["POST"])
@jwt_required()
def generate_hooks():
    """
    Generate AI-powered hooks for different platforms using OpenRouter
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data or "topic" not in data:
            return jsonify({"error": "Topic is required"}), 400
        
        topic = data["topic"].strip()
        platforms = data.get("platforms", ["twitter", "linkedin", "medium"])
        
        if len(topic) < 5:
            return jsonify({"error": "Topic too short. Minimum 5 characters."}), 400
        
        if len(topic) > 200:
            return jsonify({"error": "Topic too long. Maximum 200 characters."}), 400
        
        # Get OpenRouter API key
        openrouter_api_key = current_app.config.get("OPENROUTER_API_KEY")
        
        if not openrouter_api_key:
            return jsonify({"error": "OpenRouter API key not configured"}), 500
        
        # Create platform-specific hook prompts
        platform_instructions = {
            "twitter": "Generate Twitter hooks (max 280 characters, catchy, engaging, include hashtags)",
            "linkedin": "Generate LinkedIn hooks (professional tone, business-focused, 2-3 sentences)",
            "medium": "Generate Medium hooks (thoughtful, article-style, 3-4 sentences, intriguing)"
        }
        
        hooks = []
        
        for platform in platforms:
            if platform not in platform_instructions:
                continue
                
            try:
                # Create the prompt for this platform
                prompt = f"""
                Topic: "{topic}"
                
                Generate 5 different types of hooks for {platform} about this topic:
                1. Bold statement hook
                2. Personal story hook  
                3. Question hook
                4. Statistic hook
                5. Urgency hook
                
                Return each hook on a separate line, starting with •.
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
                            {"role": "system", "content": "You are a master copywriter specializing in creating viral hooks for social media content."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 500,
                        "temperature": 0.8
                    }
                )
                
                if response.status_code != 200:
                    print(f"OpenRouter API error for {platform}: {response.status_code}")
                    raise Exception(f"API call failed with status {response.status_code}")
                
                response_data = response.json()
                hooks_text = response_data["choices"][0]["message"]["content"].strip()
                
                # Parse hooks from bullet points
                hook_types = ["bold-statement", "personal-story", "question", "statistic", "urgency"]
                platform_hooks = []
                
                for i, line in enumerate(hooks_text.split('\n')):
                    if line.strip().startswith('•'):
                        hook_text = line.strip().replace('•', '').strip()
                        if hook_text:
                            platform_hooks.append({
                                "text": hook_text,
                                "score": 85 + i,
                                "type": hook_types[i % len(hook_types)],
                                "platform": platform.capitalize()
                            })
                
                # If no bullet points found, create fallback hooks
                if not platform_hooks:
                    fallback_hooks = [
                        f"The truth about {topic} that nobody talks about",
                        f"I studied {topic} for years, and this shocked me",
                        f"What if everything you know about {topic} is wrong?",
                        f"Most people get {topic} completely wrong. Here's why:",
                        f"The {topic} revolution is happening now. Are you ready?"
                    ]
                    
                    for i, hook_text in enumerate(fallback_hooks):
                        platform_hooks.append({
                            "text": hook_text,
                            "score": 80 + i,
                            "type": hook_types[i],
                            "platform": platform.capitalize()
                        })
                
                hooks.extend(platform_hooks)
                
            except Exception as e:
                print(f"Error generating hooks for {platform}: {str(e)}")
                # Add fallback hooks
                fallback_hooks = [
                    f"The truth about {topic} that nobody talks about",
                    f"I studied {topic} for years, and this shocked me",
                    f"What if everything you know about {topic} is wrong?",
                    f"Most people get {topic} completely wrong. Here's why:",
                    f"The {topic} revolution is happening now. Are you ready?"
                ]
                
                for i, hook_text in enumerate(fallback_hooks):
                    hooks.append({
                        "text": hook_text,
                        "score": 80 + i,
                        "type": ["bold-statement", "personal-story", "question", "statistic", "urgency"][i],
                        "platform": platform.capitalize()
                    })
        
        return jsonify({
            "hooks": hooks,
            "topic": topic,
            "platforms": platforms,
            "total_generated": len(hooks)
        }), 200
        
    except Exception as e:
        print(f"Error in hook generation: {str(e)}")
        return jsonify({"error": "Failed to generate hooks"}), 500

@hook_generator_bp.route("/templates", methods=["GET"])
@jwt_required()
def get_hook_templates():
    """
    Get predefined hook templates for inspiration
    """
    templates = [
        {
            "category": "business",
            "topic": "AI implementation",
            "hooks": [
                "73% of businesses fail at AI implementation. Here's why:",
                "The AI revolution isn't coming. It's already here.",
                "What if your competitors are using AI and you're not?"
            ]
        },
        {
            "category": "technology",
            "topic": "machine learning",
            "hooks": [
                "Machine learning will change everything. Here's how:",
                "The truth about ML that nobody tells you:",
                "I spent 5 years studying ML. This one thing shocked me:"
            ]
        },
        {
            "category": "productivity",
            "topic": "time management",
            "hooks": [
                "Most productivity advice is wrong. Here's what works:",
                "The time management secret nobody shares:",
                "What if you could double your productivity overnight?"
            ]
        }
    ]
    
    return jsonify({"templates": templates}), 200

@hook_generator_bp.route("/health", methods=["GET"])
def health_check():
    """Check if the hook generator service is healthy"""
    return jsonify({
        "status": "healthy",
        "openrouter_configured": bool(current_app.config.get("OPENROUTER_API_KEY"))
    }), 200
