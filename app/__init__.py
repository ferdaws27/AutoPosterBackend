# app/__init__.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from pymongo import MongoClient
from openai import OpenAI
import os

from .config import Config
from .extensions import db, jwt

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # CORS pour le frontend React
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": [
                    os.getenv("FRONTEND_URL", "http://localhost:5173"),
                    "http://127.0.0.1:5173",
                    "http://localhost:5173",
                ],
                "allow_headers": ["Content-Type", "Authorization"],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "supports_credentials": True,
            }
        },
    )

    print("DATABASE_URL =", os.getenv("DATABASE_URL"))

    @app.before_request
    def log_request():
        print(f"Incoming request: {request.method} {request.url}")
        print(f"Headers: {dict(request.headers)}")
        if request.method in ['POST', 'PUT', 'PATCH'] and request.is_json:
            try:
                print(f"Body: {request.get_json()}")
            except:
                pass

    # Initialisation SQLAlchemy + JWT
    db.init_app(app)
    jwt.init_app(app)

    # Initialisation MongoDB
    mongo_uri = os.getenv("MONGO_URI")
    mongo_db_name = os.getenv("MONGO_DB")

    if not mongo_uri or not mongo_db_name:
        raise ValueError("MONGO_URI ou MONGO_DB non défini dans .env")

    mongo_client = MongoClient(mongo_uri)
    app.mongo_client = mongo_client
    app.mongo = mongo_client[mongo_db_name]

    # Test connexion Mongo
    try:
        mongo_client.admin.command("ping")
        print("MongoDB connected successfully")
    except Exception as e:
        print(f"MongoDB connection error: {e}")
        raise

    # Initialize guest user if not exists
    try:
        from werkzeug.security import generate_password_hash
        from .models.user import User
        users_collection = app.mongo["users"]
        
        guest_user = users_collection.find_one({"email": "guest@autoposter.tn"})
        if not guest_user:
            print("Creating guest user...")
            guest = User(
                email="guest@autoposter.tn",
                password=generate_password_hash("guest"),  # Hash the password
                first_name="Guest",
                last_name="User",
                role="FREE"
            )
            result = users_collection.insert_one(guest.to_dict())
            print(f"✅ Guest user created with ID: {result.inserted_id}")
        else:
            print(f"✅ Guest user already exists: {guest_user.get('_id')}")
    except Exception as e:
        print(f"⚠️  Could not initialize guest user: {e}")

    # OpenRouter client
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )
    model_name = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")

    # Routes API de test et blueprints existants
    from .routes.oauth_linkedin import oauth_linkedin_bp
    from .routes.oauth import oauth_twitter_bp
    from .routes.hook_generator import hook_generator_bp
    from .routes.quote_generator import quote_generator_bp
    from .routes.auth import auth_bp
    from .routes.posts import posts_bp
    from .routes.voice import voice_bp
    from .routes.test_route import test_bp  # <-- note bien le dossier routes et le s  # <-- Import ici AVANT register
    from .routes.analytics import analytics_bp
    # 🔹 Register Blueprints
    from .routes.trends import trends_bp

    
    app.register_blueprint(oauth_linkedin_bp)
    app.register_blueprint(oauth_twitter_bp)
    app.register_blueprint(hook_generator_bp, url_prefix="/api/hook-generator")
    app.register_blueprint(quote_generator_bp, url_prefix="/api/quote-generator")
    app.register_blueprint(auth_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(voice_bp)
    app.register_blueprint(test_bp)  # <-- Register ici
    app.register_blueprint(analytics_bp, url_prefix="/api")
    # Route health
    @app.get("/api/health")
    def health():
        return {"status": "ok", "message": "AutoPoster Backend Running"}
    app.register_blueprint(trends_bp)
    # 🔹 ROUTE IA
    @app.post("/api/ai/chat")
    def ai_chat():
        try:
            data = request.get_json()

            messages = data.get("messages", [])
            enable_reasoning = data.get("enable_reasoning", True)

            extra_body = {}
            if enable_reasoning:
                extra_body["reasoning"] = {"enabled": True}

            response = openrouter_client.chat.completions.create(
                model=model_name,
                messages=messages,
                extra_body=extra_body
            )

            message = response.choices[0].message

            return jsonify({
                "success": True,
                "data": {
                    "role": message.role,
                    "content": message.content,
                    "reasoning_details": getattr(message, "reasoning_details", None)
                }
            })

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    # ✅ IMPORTANT: import + register blueprint ici
    
    from .routes.auth import auth_bp
    from .routes.posts import posts_bp
    from .routes.voice import voice_bp
    from .routes.news import news_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(voice_bp)
    app.register_blueprint(news_bp)

    return app  # <-- RETURN à la fin