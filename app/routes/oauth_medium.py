from flask import Blueprint, current_app, redirect, request, jsonify, session
import requests
from flask_jwt_extended import create_access_token
from urllib.parse import urlencode, quote
from datetime import datetime, timedelta
import secrets

oauth_medium_bp = Blueprint(
    "oauth_medium_bp",
    __name__,
    url_prefix="/api/oauth/medium"
)


@oauth_medium_bp.get("/start")
def start():
    """Redirect user to Medium OAuth2 authorization page."""
    client_id = current_app.config.get("MEDIUM_CLIENT_ID")
    backend_url = current_app.config.get("BACKEND_URL")

    if not client_id:
        return jsonify(message="MEDIUM_CLIENT_ID manquant"), 500

    redirect_uri = f"{backend_url}/api/oauth/medium/callback"

    # CSRF state
    state = secrets.token_urlsafe(32)
    session["medium_oauth_state"] = state

    params = {
        "client_id": client_id,
        "scope": "basicProfile,listPublications,publishPost",
        "state": state,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }

    auth_url = "https://medium.com/m/oauth/authorize?" + urlencode(params)
    return redirect(auth_url)


@oauth_medium_bp.get("/callback")
def callback():
    """Handle Medium OAuth2 callback: exchange code for token, fetch user, save to DB."""
    frontend_url = current_app.config.get("FRONTEND_URL")
    backend_url = current_app.config.get("BACKEND_URL")

    error = request.args.get("error")
    if error:
        return redirect(f"{frontend_url}/login?oauth_error={error}")

    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return redirect(f"{frontend_url}/login?oauth_error=no_code")

    # Verify state
    saved_state = session.pop("medium_oauth_state", None)
    if not saved_state or saved_state != state:
        return redirect(f"{frontend_url}/login?oauth_error=invalid_state")

    client_id = current_app.config.get("MEDIUM_CLIENT_ID")
    client_secret = current_app.config.get("MEDIUM_CLIENT_SECRET")
    redirect_uri = f"{backend_url}/api/oauth/medium/callback"

    # Exchange code for access token
    token_response = requests.post(
        "https://api.medium.com/v1/tokens",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=10,
    )

    if token_response.status_code != 200 and token_response.status_code != 201:
        print("Medium token error:", token_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=token_error")

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return redirect(f"{frontend_url}/login?oauth_error=no_access_token")

    # Fetch user profile
    user_response = requests.get(
        "https://api.medium.com/v1/me",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=10,
    )

    if user_response.status_code != 200:
        print("Medium user error:", user_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=user_error")

    userinfo = user_response.json().get("data", {})
    medium_id = userinfo.get("id")
    username = userinfo.get("username")
    name = userinfo.get("name")
    image_url = userinfo.get("imageUrl")

    # Save / update in MongoDB
    try:
        collection = current_app.mongo["users"]
        existing = collection.find_one({"medium_id": medium_id})

        user_data = {
            "medium_id": medium_id,
            "username": username,
            "name": name,
            "profile_picture": image_url,
            "oauth_provider": "medium",
            "medium_access_token": access_token,
            "updated_at": datetime.utcnow(),
        }

        if existing:
            collection.update_one({"medium_id": medium_id}, {"$set": user_data})
            user_id = str(existing["_id"])
        else:
            user_data["role"] = "FREE"
            user_data["created_at"] = datetime.utcnow()
            result = collection.insert_one(user_data)
            user_id = str(result.inserted_id)

    except Exception as e:
        print("Medium Mongo error:", str(e))
        return redirect(f"{frontend_url}/login?oauth_error=db_error")

    # Create JWT and redirect to frontend
    jwt_token = create_access_token(identity=user_id, expires_delta=timedelta(days=7))
    token_encoded = quote(jwt_token)

    # Pass user info in URL for frontend to store
    user_encoded = quote(f"{username}||{name}||{image_url or ''}")

    return redirect(f"{frontend_url}/oauth/callback#token={token_encoded}&provider=medium&user={user_encoded}")
