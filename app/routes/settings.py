from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime

settings_bp = Blueprint("settings_bp", __name__, url_prefix="/api/user")


@settings_bp.route("/settings", methods=["GET", "OPTIONS"])
@jwt_required(optional=True)
def get_settings():
    if request.method == "OPTIONS":
        return "", 200
    """Get user settings from MongoDB"""
    user_id = get_jwt_identity()
    if not user_id:
        return jsonify({"success": False, "error": "Authentication required"}), 401
    collection = current_app.mongo["user_settings"]

    doc = collection.find_one({"user_id": user_id})
    if not doc:
        return jsonify({"success": True, "data": {}}), 200

    doc.pop("_id", None)
    doc.pop("user_id", None)
    return jsonify({"success": True, "data": doc.get("settings", {})}), 200


@settings_bp.route("/settings", methods=["POST", "OPTIONS"])
@jwt_required(optional=True)
def save_settings():
    if request.method == "OPTIONS":
        return "", 200
    """Save user settings to MongoDB (upsert)"""
    user_id = get_jwt_identity()
    if not user_id:
        return jsonify({"success": False, "error": "Authentication required"}), 401
    collection = current_app.mongo["user_settings"]

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    # Remove sensitive fields that shouldn't be stored as-is
    settings = {
        "ai": data.get("ai"),
        "posting": data.get("posting"),
        "integrations": data.get("integrations"),
        "danger": data.get("danger"),
        "lastUpdated": data.get("lastUpdated", datetime.utcnow().isoformat()),
    }

    # Store API keys separately (don't overwrite if not provided)
    api_data = data.get("api")
    if api_data:
        settings["api"] = {
            "keys": api_data.get("keys", {}),
            "dataRetention": api_data.get("dataRetention"),
            "backupFrequency": api_data.get("backupFrequency"),
        }

    collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "settings": settings,
                "updated_at": datetime.utcnow(),
            },
            "$setOnInsert": {
                "created_at": datetime.utcnow(),
            },
        },
        upsert=True,
    )

    return jsonify({"success": True, "message": "Settings saved"}), 200


@settings_bp.route("/linkedin-profile-url", methods=["GET", "POST", "OPTIONS"])
@jwt_required()
def linkedin_profile_url():
    if request.method == "OPTIONS":
        return "", 200

    user_id = get_jwt_identity()
    users_collection = current_app.mongo["users"]

    if request.method == "GET":
        user = users_collection.find_one({"email": user_id}, {"linkedin_profile_url": 1})
        return jsonify({"success": True, "linkedin_profile_url": (user or {}).get("linkedin_profile_url", "")})

    # POST
    data = request.get_json()
    url = (data.get("linkedin_profile_url") or "").strip()

    # Basic validation
    if url and not url.startswith("https://www.linkedin.com/in/"):
        return jsonify({"success": False, "error": "URL must start with https://www.linkedin.com/in/"}), 400

    users_collection.update_one(
        {"email": user_id},
        {"$set": {"linkedin_profile_url": url, "updated_at": datetime.utcnow()}}
    )
    return jsonify({"success": True, "message": "LinkedIn profile URL saved"})


@settings_bp.route("/auto-post", methods=["GET", "POST", "OPTIONS"])
@jwt_required()
def auto_post_settings():
    if request.method == "OPTIONS":
        return "", 200

    user_id = get_jwt_identity()
    users_collection = current_app.mongo["users"]

    if request.method == "GET":
        user = users_collection.find_one({"email": user_id}, {"auto_post": 1})
        return jsonify({"success": True, "auto_post": (user or {}).get("auto_post", {})})

    # POST
    data = request.get_json()
    auto_post = {
        "linkedin": bool(data.get("linkedin", False)),
        "twitter": bool(data.get("twitter", False)),
        "medium": bool(data.get("medium", False)),
    }

    users_collection.update_one(
        {"email": user_id},
        {"$set": {"auto_post": auto_post, "updated_at": datetime.utcnow()}}
    )
    return jsonify({"success": True, "message": "Auto-post settings saved"})
