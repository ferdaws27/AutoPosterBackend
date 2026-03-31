from flask import Flask
from flask_cors import CORS
from .config import Config
from .extensions import db, jwt
from dotenv import load_dotenv
from pymongo import MongoClient
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

    @app.get("/api/health")
    def health():
        return {"status": "ok", "message": "AutoPoster Backend Running"}

    # ✅ IMPORTANT: import + register blueprint ici (les 2 lignes doivent être indentées)
    from .routes.oauth_linkedin import oauth_linkedin_bp
    from .routes.oauth_twitter import oauth_twitter_bp
    from .routes.oauth_medium import oauth_medium_bp
    from .routes.dashboard import dashboard_bp
    from .routes.quote_generator import quote_generator_bp
    from .routes.hook_generator import hook_generator_bp
    from .routes.ai_ideas import ai_ideas_bp

    app.register_blueprint(oauth_linkedin_bp)
    app.register_blueprint(oauth_twitter_bp)
    app.register_blueprint(oauth_medium_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(quote_generator_bp)
    app.register_blueprint(hook_generator_bp)
    app.register_blueprint(ai_ideas_bp)

    return app