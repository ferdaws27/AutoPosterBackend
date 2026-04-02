from flask import Flask, request, jsonify
from flask_cors import CORS
from .config import Config
from .extensions import db, jwt
from dotenv import load_dotenv
from pymongo import MongoClient
from openai import OpenAI
import os

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # CORS (React Vite)
    CORS(app, resources={r"/api/*": {"origins": ["http://localhost:5173"]}})
    print("DATABASE_URL =", os.getenv("DATABASE_URL"))

    db.init_app(app)
    jwt.init_app(app)

    mongo_uri = os.getenv("MONGO_URI")
    mongo_db_name = os.getenv("MONGO_DB")
    if not mongo_uri or not mongo_db_name:
        raise ValueError("MONGO_URI ou MONGO_DB non défini dans .env")

    mongo_client = MongoClient(mongo_uri)
    app.mongo = mongo_client[mongo_db_name]

    # 🔹 OpenRouter client
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    model_name = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "message": "AutoPoster Backend Running"}

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