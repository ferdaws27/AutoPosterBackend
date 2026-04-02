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
        if request.is_json:
            print(f"Body: {request.get_json()}")

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

    # Route test backend
    # 🔹 OpenRouter client
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    model_name = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "message": "AutoPoster Backend Running"}

    # Blueprints
    from .routes.oauth_linkedin import oauth_linkedin_bp
    from .routes.hook_generator import hook_generator_bp
    from .routes.quote_generator import quote_generator_bp

    app.register_blueprint(oauth_linkedin_bp)
    app.register_blueprint(hook_generator_bp, url_prefix="/api/hook-generator")
    app.register_blueprint(quote_generator_bp, url_prefix="/api/quote-generator")
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
    from .routes.oauth_linkedin import oauth_linkedin_bp
    from .routes.posts import posts_bp
    app.register_blueprint(oauth_linkedin_bp)
    app.register_blueprint(posts_bp)

    return app