from flask import Blueprint, current_app, redirect, request, jsonify, session
import requests
from flask_jwt_extended import create_access_token, decode_token
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
    state = secrets.token_urlsafe(16)

    print(f"Code verifier length: {len(code_verifier)}")
    print(f"Code challenge length: {len(code_challenge)}")
    print(f"OAuth state length: {len(state)}")

    # store verifier and state in session
    session['twitter_code_verifier'] = code_verifier
    session['twitter_oauth_state'] = state
    print(f"Code verifier stored in session")
    print(f"State stored in session")

    # Handle account linking: encode user_id in state and session
    link_token = request.args.get("link_token")
    link_user_id = None
    if link_token:
        try:
            decoded = decode_token(link_token)
            link_identity = decoded.get("sub") or decoded.get("identity")
            if link_identity:
                link_user_id = link_identity
                session["oauth_linking_user_id"] = link_user_id
                print(f"Linking OAuth to user: {link_user_id}")
        except Exception as e:
            print("Invalid Twitter link_token:", str(e))

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "tweet.read users.read offline.access",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = "https://twitter.com/i/oauth2/authorize?" + urlencode(params, quote_via=quote)
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

    # vérifier l'état et récupérer le vérificateur depuis la session
    request_state = request.args.get('state')
    session_state = session.pop('twitter_oauth_state', None)
    code_verifier = session.pop('twitter_code_verifier', None)

    if not request_state or not session_state or request_state != session_state:
        print("Invalid or missing OAuth state:", request_state, session_state)
        return redirect(f"{frontend_url}/login?oauth_error=invalid_state")

    if not code_verifier:
        print("Code verifier not found in session")
        return redirect(f"{frontend_url}/login?oauth_error=no_verifier")
    
    print(f"OAuth state verified")
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
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=10
    )

    print(f"Token response status: {token_response.status_code}")
    print(f"Token response body: {token_response.text}")

    if token_response.status_code != 200:
        print("Token error:", token_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=token_error")

    access_token = token_response.json().get("access_token")

   
    user_response = requests.get(
        "https://api.twitter.com/2/users/me?user.fields=name,username,profile_image_url",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )

    if user_response.status_code != 200:
        print("User error:", user_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=user_error")

    userinfo = user_response.json().get("data", {})

    twitter_id = userinfo.get("id")
    username = userinfo.get("username")
    full_name = userinfo.get("name")
    profile_picture = userinfo.get("profile_image_url")

    if not twitter_id:
        print("Twitter user info missing id:", user_response.text)
        return redirect(f"{frontend_url}/login?oauth_error=user_error")

    try:
        collection = current_app.mongo["users"]
        link_user_id = session.pop("oauth_linking_user_id", None)
        link_user_doc = None

        if link_user_id:
            try:
                from bson.objectid import ObjectId
                link_user_doc = collection.find_one({"_id": ObjectId(link_user_id)})
            except Exception as e:
                print("Invalid Twitter link user id:", str(e))

        provider_owner = collection.find_one({
            "social_accounts": {
                "$elemMatch": {
                    "provider": "twitter",
                    "provider_user_id": twitter_id
                }
            }
        })
        if provider_owner:
            existing_user = provider_owner
        elif link_user_doc:
            existing_user = link_user_doc
        else:
            existing_user = None

        account_data = {
            "provider": "twitter",
            "provider_user_id": twitter_id,
            "username": username,
            "name": full_name,
            "profile_picture": profile_picture,
            "access_token": access_token,
            "updated_at": datetime.utcnow()
        }

        if existing_user:
            if not existing_user.get("oauth_provider"):
                account_data["oauth_provider"] = "twitter"

            existing_accounts = existing_user.get("social_accounts", [])
            twitter_account = next((a for a in existing_accounts if a.get("provider") == "twitter"), None)
            if twitter_account:
                collection.update_one(
                    {"_id": existing_user["_id"], "social_accounts.provider": "twitter"},
                    {"$set": {"social_accounts.$": account_data, "updated_at": datetime.utcnow()}}
                )
            else:
                collection.update_one(
                    {"_id": existing_user["_id"]},
                    {"$push": {"social_accounts": account_data}, "$set": {"updated_at": datetime.utcnow()}}
                )

            if not existing_user.get("twitter_id"):
                collection.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": {"twitter_id": twitter_id, "oauth_provider": existing_user.get("oauth_provider", "twitter"), "updated_at": datetime.utcnow()}}
                )
            user_id = str(existing_user["_id"])
        else:
            result = collection.insert_one({
                **account_data,
                "twitter_id": twitter_id,
                "oauth_provider": "twitter",
                "twitter_access_token": access_token,
                "role": "FREE",
                "created_at": datetime.utcnow()
            })
            user_id = str(result.inserted_id)

    except Exception as e:
        print("Mongo error:", str(e))
        return redirect(f"{frontend_url}/login?oauth_error=db_error")

    jwt_token = create_access_token(identity=user_id, expires_delta=timedelta(days=7))
    token_encoded = quote(jwt_token)
    user_info_encoded = quote(f"{username or ''}||{full_name or ''}||{profile_picture or ''}")

    return redirect(f"{frontend_url}/oauth/callback#token={token_encoded}&provider=twitter&user={user_info_encoded}")
