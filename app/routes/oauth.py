from flask import Blueprint, current_app, redirect, request, jsonify, session
import requests
from flask_jwt_extended import create_access_token
from urllib.parse import urlencode, quote
from datetime import datetime, timedelta
import base64
import secrets
import hashlib

oauth_twitter_bp = Blueprint(
    "oauth_twitter_bp",
    __name__,
    url_prefix="/api/oauth/twitter"
)


@oauth_twitter_bp.get("/start")
def start():
    client_id = current_app.config.get("TWITTER_CLIENT_ID")
    backend_url = current_app.config.get("BACKEND_URL")

    print("=== TWITTER START DEBUG ===")
    print(f"Client ID exists: {bool(client_id)}")
    print(f"Backend URL: {backend_url}")

    if not client_id:
        return jsonify(message="TWITTER_CLIENT_ID manquant"), 500

    redirect_uri = f"{backend_url}/api/oauth/twitter/callback"

    # PKCE (obligatoire pour Twitter)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")

    print(f"Code verifier length: {len(code_verifier)}")
    print(f"Code challenge length: {len(code_challenge)}")

    # store verifier en session
    session['twitter_code_verifier'] = code_verifier
    print(f"Code verifier stored in session")

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "tweet.read users.read offline.access",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = "https://twitter.com/i/oauth2/authorize?" + urlencode(params)
    print(f"Redirecting to: {auth_url}")
    return redirect(auth_url)



@oauth_twitter_bp.get("/callback")
def callback():
    frontend_url = current_app.config.get("FRONTEND_URL")
    backend_url = current_app.config.get("BACKEND_URL")

    print("=== TWITTER CALLBACK DEBUG ===")
    print(f"Frontend URL: {frontend_url}")
    print(f"Backend URL: {backend_url}")
    print(f"Request args: {dict(request.args)}")
    print(f"Session data: {dict(session)}")
    
    error = request.args.get("error")
    if error:
        print("Twitter error:", error)
        return redirect(f"{frontend_url}/login?oauth_error={error}")

    code = request.args.get("code")
    if not code:
        print("No code received")
        return redirect(f"{frontend_url}/login?oauth_error=no_code")

    client_id = current_app.config.get("TWITTER_CLIENT_ID")
    client_secret = current_app.config.get("TWITTER_CLIENT_SECRET")
    
    print(f"Client ID exists: {bool(client_id)}")
    print(f"Client Secret exists: {bool(client_secret)}")

    redirect_uri = f"{backend_url}/api/oauth/twitter/callback"
    print(f"Redirect URI: {redirect_uri}")

    # récupérer verifier depuis session
    code_verifier = session.get('twitter_code_verifier')
    
    if not code_verifier:
        print("Code verifier not found in session")
        return redirect(f"{frontend_url}/login?oauth_error=no_verifier")
    
    print(f"Code verifier exists: {bool(code_verifier)}")
    print(f"Code length: {len(code) if code else 0}")
    print(f"Verifier length: {len(code_verifier) if code_verifier else 0}")

    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    
    print(f"Token request data: {token_data}")

    token_response = requests.post(
        "https://api.twitter.com/2/oauth2/token",
        data=token_data,
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )

    print(f"Token response status: {token_response.status_code}")
    print(f"Token response body: {token_response.text}")

    if token_response.status_code != 200:
        print("Token error:", token_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=token_error")

    access_token = token_response.json().get("access_token")

   
    user_response = requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )

    if user_response.status_code != 200:
        print("User error:", user_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=user_error")

    userinfo = user_response.json()["data"]

    twitter_id = userinfo.get("id")
    username = userinfo.get("username")

    
    try:
        collection = current_app.mongo["users"]

        existing_user = collection.find_one({"twitter_id": twitter_id})

        if existing_user:
            collection.update_one(
                {"twitter_id": twitter_id},
                {"$set": {
                    "username": username,
                    "oauth_provider": "twitter",
                    "updated_at": datetime.utcnow()
                }}
            )
        else:
            collection.insert_one({
                "twitter_id": twitter_id,
                "username": username,
                "oauth_provider": "twitter",
                "role": "FREE",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })

    except Exception as e:
        print("Mongo error:", str(e))
        return redirect(f"{frontend_url}/login?oauth_error=db_error")

   
    jwt_token = create_access_token(identity=twitter_id, expires_delta=timedelta(days=7))
    token_encoded = quote(jwt_token)

    return redirect(f"{frontend_url}/oauth/callback#token={token_encoded}")
