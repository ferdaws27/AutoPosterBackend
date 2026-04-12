from flask import Blueprint, current_app, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from app.models.user import User
from bson.objectid import ObjectId

auth_bp = Blueprint("auth_bp", __name__, url_prefix="/api/auth")


# =========================
# ✅ LOGIN
# =========================
@auth_bp.post("/login")
def login():
    try:
        data = request.get_json()
        
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            return jsonify({
                "success": False,
                "error": "Email and password are required"
            }), 400
        
        mongo = current_app.mongo
        users_collection = mongo["users"]
        
        # Find user by email
        user_doc = users_collection.find_one({"email": email})
        
        if not user_doc:
            return jsonify({
                "success": False,
                "error": "Invalid email or password"
            }), 401
        
        # Check password (handle both hashed and plain passwords for compatibility)
        stored_password = user_doc.get("password", "")
        password_valid = False
        
        # Try checking as hashed password first
        try:
            password_valid = check_password_hash(stored_password, password)
        except:
            # Fallback to plain text comparison (for development/testing)
            password_valid = stored_password == password
        
        if not password_valid:
            return jsonify({
                "success": False,
                "error": "Invalid email or password"
            }), 401
        
        # Generate JWT token with 7 days expiration
        user_id = str(user_doc["_id"])
        access_token = create_access_token(identity=user_id, expires_delta=timedelta(days=7))
        
        # Return user info and token
        return jsonify({
            "success": True,
            "access_token": access_token,
            "user": {
                "id": user_id,
                "email": user_doc.get("email"),
                "first_name": user_doc.get("first_name"),
                "last_name": user_doc.get("last_name"),
                "profile_picture": user_doc.get("profile_picture"),
                "role": user_doc.get("role", "FREE")
            }
        }), 200
        
    except Exception as e:
        print(f"Login error: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ REGISTER
# =========================
@auth_bp.post("/register")
def register():
    try:
        data = request.get_json()
        
        email = data.get("email")
        password = data.get("password")
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        
        if not email or not password:
            return jsonify({
                "success": False,
                "error": "Email and password are required"
            }), 400
        
        mongo = current_app.mongo
        users_collection = mongo["users"]
        
        # Check if user already exists
        if users_collection.find_one({"email": email}):
            return jsonify({
                "success": False,
                "error": "User already exists with this email"
            }), 409
        
        # Hash password
        hashed_password = generate_password_hash(password)
        
        # Create new user
        user = User(
            email=email,
            password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            role="FREE"
        )
        
        result = users_collection.insert_one(user.to_dict())
        user._id = result.inserted_id
        
        # Generate JWT token with 7 days expiration
        access_token = create_access_token(identity=str(user._id), expires_delta=timedelta(days=7))
        
        return jsonify({
            "success": True,
            "access_token": access_token,
            "user": {
                "id": str(user._id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role
            }
        }), 201
        
    except Exception as e:
        print(f"Register error: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================
# ✅ GET CURRENT USER
# =========================
@auth_bp.get("/me")
@jwt_required()
def me():
    try:
        identity = get_jwt_identity()
        mongo = current_app.mongo
        users_collection = mongo["users"]

        user_doc = None
        try:
            user_doc = users_collection.find_one({"_id": ObjectId(identity)})
        except:
            user_doc = users_collection.find_one({"twitter_id": identity})

        if not user_doc:
            return jsonify({"success": False, "error": "User not found"}), 404

        return jsonify({
            "success": True,
            "user": {
                "id": str(user_doc["_id"]),
                "email": user_doc.get("email"),
                "username": user_doc.get("username"),
                "first_name": user_doc.get("first_name"),
                "last_name": user_doc.get("last_name"),
                "full_name": f"{user_doc.get('first_name') or ''} {user_doc.get('last_name') or ''}".strip() or user_doc.get("username") or user_doc.get("email"),
                "name": user_doc.get("name"),
                "profile_picture": user_doc.get("profile_picture"),
                "bio": user_doc.get("bio"),
                "followers": user_doc.get("followers"),
                "following": user_doc.get("following"),
                "role": user_doc.get("role", "FREE"),
                "oauth_provider": user_doc.get("oauth_provider"),
            }
        }), 200

    except Exception as e:
        print(f"Me error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
