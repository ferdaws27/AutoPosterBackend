import os
from dotenv import load_dotenv

# Charge .env (doit être dans le même dossier que run.py)
load_dotenv()

class Config:
    # PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT - Long expiration for user session (7 days)
    JWT_SECRET_KEY = os.getenv("JWT_SECRET")
    JWT_ACCESS_TOKEN_EXPIRES = 7 * 24 * 60 * 60  # ✅ 7 days in seconds

    # Session
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI")
    MONGO_DB = os.getenv("MONGO_DB")

    # LinkedIn OAuth
    LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
    LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")

    # Twitter OAuth
    TWITTER_CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")
    TWITTER_CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")

    # URLs
    BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000")
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")