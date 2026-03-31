"""Twitter / X OAuth 2.0 (authorization code + PKCE, confidential client)."""
import base64
import hashlib
import secrets
from datetime import datetime
from urllib.parse import quote, urlencode

import requests
from flask import Blueprint, current_app, jsonify, redirect, request
from flask_jwt_extended import decode_token, get_jwt_identity, jwt_required

from app.oauth_state import sign_oauth_payload, verify_oauth_payload

oauth_twitter_bp = Blueprint(
    "oauth_twitter_bp",
    __name__,
    url_prefix="/api/oauth/twitter",
)


def _pkce_pair():
    code_verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").replace("=", "")
    )
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")
    return code_verifier, code_challenge


def _frontend_url():
    return current_app.config.get("FRONTEND_URL", "http://localhost:5173")


def _backend_url():
    return current_app.config.get("BACKEND_URL", "http://127.0.0.1:5000")


def _settings_redirect(**query_parts):
    base = f"{_frontend_url()}/dashboard/settings"
    q = urlencode([(k, v) for k, v in query_parts.items() if v is not None])
    return redirect(f"{base}?{q}" if q else base)


@oauth_twitter_bp.get("/start")
def start():
    token = request.args.get("token")
    if not token:
        return _settings_redirect(oauth_error="twitter_missing_token")

    try:
        decoded = decode_token(token)
        email = decoded["sub"]
    except Exception as e:
        print("twitter /start decode_token:", e)
        return _settings_redirect(oauth_error="twitter_invalid_token")

    client_id = current_app.config.get("TWITTER_CLIENT_ID")
    if not client_id:
        return _settings_redirect(oauth_error="twitter_not_configured")

    verifier, challenge = _pkce_pair()
    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY")
    signed_state = sign_oauth_payload(
        {"email": email, "v": verifier, "p": "tw"},
        secret,
    )

    redirect_uri = f"{_backend_url()}/api/oauth/twitter/callback"
    scope = "tweet.read tweet.write users.read offline.access"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": signed_state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = "https://twitter.com/i/oauth2/authorize?" + urlencode(params, quote_via=quote)
    return redirect(auth_url)


@oauth_twitter_bp.get("/callback")
def callback():
    frontend_err = request.args.get("error")
    if frontend_err:
        return _settings_redirect(oauth_error=f"twitter_{frontend_err}")

    state_param = request.args.get("state")
    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY")
    st = verify_oauth_payload(state_param, secret) if state_param else None
    if not st or st.get("p") != "tw":
        return _settings_redirect(oauth_error="twitter_state_invalid")

    email = st.get("email")
    code_verifier = st.get("v")
    code = request.args.get("code")
    if not code or not email or not code_verifier:
        return _settings_redirect(oauth_error="twitter_missing_params")

    client_id = current_app.config.get("TWITTER_CLIENT_ID")
    client_secret = current_app.config.get("TWITTER_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _settings_redirect(oauth_error="twitter_not_configured")

    redirect_uri = f"{_backend_url()}/api/oauth/twitter/callback"
    token_url = "https://api.twitter.com/2/oauth2/token"
    tr = requests.post(
        token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(client_id, client_secret),
        timeout=20,
    )
    if tr.status_code != 200:
        print("Twitter token error:", tr.status_code, tr.text)
        return _settings_redirect(oauth_error="twitter_token_exchange")

    tj = tr.json()
    access_token = tj.get("access_token")
    refresh_token = tj.get("refresh_token")
    if not access_token:
        print("Twitter token JSON:", tj)
        return _settings_redirect(oauth_error="twitter_no_access_token")

    ur = requests.get(
        "https://api.twitter.com/2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"user.fields": "profile_image_url,name,username"},
        timeout=20,
    )
    if ur.status_code != 200:
        print("Twitter user/me error:", ur.status_code, ur.text)
        return _settings_redirect(oauth_error="twitter_userinfo")

    ud = ur.json().get("data") or {}

    collection = current_app.mongo["users"]
    result = collection.update_one(
        {"email": email},
        {
            "$set": {
                "twitter_id": ud.get("id"),
                "twitter_username": ud.get("username"),
                "twitter_name": ud.get("name"),
                "twitter_profile_image_url": ud.get("profile_image_url"),
                "twitter_access_token": access_token,
                "twitter_refresh_token": refresh_token,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    if result.matched_count == 0:
        return _settings_redirect(oauth_error="twitter_user_not_found")

    return _settings_redirect(integration="twitter", result="connected")


@oauth_twitter_bp.post("/unlink")
@jwt_required()
def unlink():
    """Retire le compte X / Twitter du profil AutoPoster (tokens inclus)."""
    email = get_jwt_identity()
    current_app.mongo["users"].update_one(
        {"email": email},
        {
            "$unset": {
                "twitter_id": "",
                "twitter_username": "",
                "twitter_name": "",
                "twitter_profile_image_url": "",
                "twitter_access_token": "",
                "twitter_refresh_token": "",
            },
            "$set": {"updated_at": datetime.utcnow()},
        },
    )
    return jsonify({"ok": True}), 200
