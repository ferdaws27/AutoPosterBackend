from flask import Blueprint, current_app, redirect, request, jsonify, g
import requests
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from urllib.parse import urlencode, quote
from app.models.user import User
from datetime import datetime

oauth_linkedin_bp = Blueprint(
    "oauth_linkedin_bp",
    __name__,
    url_prefix="/api/oauth/linkedin"
)

@oauth_linkedin_bp.get("/start")
def start():
    client_id = current_app.config.get("LINKEDIN_CLIENT_ID")
    backend_url = current_app.config.get("BACKEND_URL", "http://127.0.0.1:5000")

    if not client_id:
        return jsonify(message="LINKEDIN_CLIENT_ID manquant dans .env"), 500

    redirect_uri = f"{backend_url}/api/oauth/linkedin/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        # ✅ décommente si tu veux forcer l'écran login à chaque fois
        # "prompt": "login",
    }

    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(params)
    return redirect(auth_url)


@oauth_linkedin_bp.get("/callback")
def callback():
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5173")
    backend_url = current_app.config.get("BACKEND_URL", "http://127.0.0.1:5000")

    # 0) gérer erreur LinkedIn (cancel, etc.)
    error = request.args.get("error")
    if error:
        print("LinkedIn error:", error, request.args.get("error_description"))
        return redirect(f"{frontend_url}/login?oauth_error={error}")

    # 1) récupérer code
    code = request.args.get("code")
    if not code:
        print("No code in callback")
        return redirect(f"{frontend_url}/login?oauth_error=no_code")

    # 2) récupérer credentials
    client_id = current_app.config.get("LINKEDIN_CLIENT_ID")
    client_secret = current_app.config.get("LINKEDIN_CLIENT_SECRET")
    if not client_id or not client_secret:
        return jsonify(message="LINKEDIN_CLIENT_ID ou LINKEDIN_CLIENT_SECRET manquant dans .env"), 500

    redirect_uri = f"{backend_url}/api/oauth/linkedin/callback"

    # 3) échanger code -> access_token
    token_response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )

    if token_response.status_code != 200:
        print("Token error:", token_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=token_error")

    access_token_li = token_response.json().get("access_token")
    if not access_token_li:
        print("No access_token in token response:", token_response.json())
        return redirect(f"{frontend_url}/login?oauth_error=no_access_token")

    # 4) récupérer user info
    userinfo_response = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token_li}"},
        timeout=10,
    )

    if userinfo_response.status_code != 200:
        print("Userinfo error:", userinfo_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=userinfo_error")

    userinfo = userinfo_response.json()
    print("LinkedIn userinfo:", userinfo)

    email = userinfo.get("email")
    user_email = userinfo.get("email")  # Global user email for current session
    g.user_email = user_email  # Store in Flask application context
    
    if not email:
        return redirect(f"{frontend_url}/login?oauth_error=no_email")

    # 5) Save or update user in MongoDB
    try:
        collection = current_app.mongo["users"]
        
        # Check if user exists
        existing_user = collection.find_one({"email": email})
        
        if existing_user:
            # Update existing user
            update_data = {
                "linkedin_id": userinfo.get("sub"),
                "first_name": userinfo.get("given_name"),
                "last_name": userinfo.get("family_name"),
                "profile_picture": userinfo.get("picture"),
                "locale": userinfo.get("locale"),
                "linkedin_data": userinfo,
                "oauth_provider": "linkedin",
                "updated_at": datetime.utcnow()
            }
            result = collection.update_one(
                {"email": email},
                {"$set": update_data}
            )
            print(f"User updated in MongoDB: {email}")
        else:
            # Create new user
            new_user = {
                "email": email,
                "password": None,
                "linkedin_id": userinfo.get("sub"),
                "first_name": userinfo.get("given_name"),
                "last_name": userinfo.get("family_name"),
                "profile_picture": userinfo.get("picture"),
                "locale": userinfo.get("locale"),
                "linkedin_data": userinfo,
                "oauth_provider": "linkedin",
                "role": "FREE",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            result = collection.insert_one(new_user)
            print(f"New user created in MongoDB: {email} (ID: {result.inserted_id})")
    except Exception as e:
        print(f"Error saving user to MongoDB: {str(e)}")
        return redirect(f"{frontend_url}/login?oauth_error=db_error")

    # 6) créer JWT puis rediriger vers React (✅ HASH)
    jwt_token = create_access_token(identity=email)
    token_encoded = quote(jwt_token)

    redirect_to = f"{frontend_url}/oauth/callback#token={token_encoded}"
    print("Redirecting to:", redirect_to)

    return redirect(redirect_to)


@oauth_linkedin_bp.get("/me")
@jwt_required()
def n():
    """
    Get the currently logged-in user's information.
    Requires valid JWT token in Authorization header.
    """
    try:
        # Get email from JWT identity or global user_email
        email = getattr(g, 'user_email', None) or get_jwt_identity()
        
        # Query MongoDB for user
        collection = current_app.mongo["users"]
        user_doc = collection.find_one({"email": email})
        
        if not user_doc:
            return jsonify(message="User not found"), 404
        
        # Convert MongoDB ObjectId to string for JSON serialization
        user_data = {
            "id": str(user_doc.get("_id")),
            "email": user_doc.get("email"),
            "first_name": user_doc.get("first_name"),
            "last_name": user_doc.get("last_name"),
            "full_name": f"{user_doc.get('first_name') or ''} {user_doc.get('last_name') or ''}".strip() or user_doc.get("email"),
            "profile_picture": user_doc.get("profile_picture"),
            "linkedin_id": user_doc.get("linkedin_id"),
            "locale": user_doc.get("locale"),
            "oauth_provider": user_doc.get("oauth_provider"),
            "role": user_doc.get("role"),
            "created_at": user_doc.get("created_at").isoformat() if user_doc.get("created_at") else None,
            "updated_at": user_doc.get("updated_at").isoformat() if user_doc.get("updated_at") else None,
            # Other social accounts (connected in Settings → Integrations)
            "twitter_id": user_doc.get("twitter_id"),
            "twitter_username": user_doc.get("twitter_username"),
            "twitter_name": user_doc.get("twitter_name"),
            "twitter_profile_image_url": user_doc.get("twitter_profile_image_url"),
            "twitter_connected": bool(user_doc.get("twitter_id")),
            "medium_id": user_doc.get("medium_id"),
            "medium_username": user_doc.get("medium_username"),
            "medium_name": user_doc.get("medium_name"),
            "medium_image_url": user_doc.get("medium_image_url"),
            "medium_connected": bool(user_doc.get("medium_id")),
        }
        
        return jsonify(user_data), 200
        
    except Exception as e:
        print(f"Error retrieving user: {str(e)}")
        return jsonify(message="Error retrieving user information"), 500