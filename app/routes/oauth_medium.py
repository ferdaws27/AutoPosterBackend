"""Medium OAuth 2 (browser flow)."""
import secrets
from datetime import datetime
from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, jsonify, redirect, request
from flask_jwt_extended import decode_token, get_jwt_identity, jwt_required

from app.oauth_state import sign_oauth_payload, verify_oauth_payload

oauth_medium_bp = Blueprint(
    "oauth_medium_bp",
    __name__,
    url_prefix="/api/oauth/medium",
)


def _frontend_url():
    return current_app.config.get("FRONTEND_URL", "http://localhost:5173")


def _backend_url():
    return current_app.config.get("BACKEND_URL", "http://127.0.0.1:5000")


def _settings_redirect(**query_parts):
    base = f"{_frontend_url()}/dashboard/settings"
    q = urlencode([(k, v) for k, v in query_parts.items() if v is not None])
    return redirect(f"{base}?{q}" if q else base)


@oauth_medium_bp.get("/start")
def start():
    token = request.args.get("token")
    if not token:
        return _settings_redirect(oauth_error="medium_missing_token")

    try:
        decoded = decode_token(token)
        email = decoded["sub"]
    except Exception as e:
        print("medium /start decode_token:", e)
        return _settings_redirect(oauth_error="medium_invalid_token")

    client_id = current_app.config.get("MEDIUM_CLIENT_ID")
    if not client_id:
        return _settings_redirect(oauth_error="medium_not_configured")

    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY")
    signed_state = sign_oauth_payload(
        {"email": email, "p": "md", "n": secrets.token_urlsafe(8)},
        secret,
    )

    redirect_uri = f"{_backend_url()}/api/oauth/medium/callback"
    params = {
        "client_id": client_id,
        "scope": "basicProfile,publishPost",
        "state": signed_state,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    auth_url = "https://medium.com/m/oauth/authorize?" + urlencode(params)
    return redirect(auth_url)


@oauth_medium_bp.get("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return _settings_redirect(oauth_error=f"medium_{error}")

    state_param = request.args.get("state")
    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY")
    st = verify_oauth_payload(state_param, secret) if state_param else None
    if not st or st.get("p") != "md":
        return _settings_redirect(oauth_error="medium_state_invalid")

    email = st.get("email")
    code = request.args.get("code")
    if not code or not email:
        return _settings_redirect(oauth_error="medium_missing_params")

    client_id = current_app.config.get("MEDIUM_CLIENT_ID")
    client_secret = current_app.config.get("MEDIUM_CLIENT_SECRET")
    if not client_id or not client_secret:
        return _settings_redirect(oauth_error="medium_not_configured")

    redirect_uri = f"{_backend_url()}/api/oauth/medium/callback"

    token_urls = [
        "https://api.medium.com/v1/tokens",
        "https://medium.com/v1/tokens",
    ]
    token_json = None
    for turl in token_urls:
        tr = requests.post(
            turl,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data=urlencode(
                {
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                }
            ),
            timeout=20,
        )
        if tr.status_code == 200:
            token_json = tr.json()
            break
        print("Medium token attempt", turl, tr.status_code, tr.text[:500])

    if not token_json:
        return _settings_redirect(oauth_error="medium_token_exchange")

    access_token = token_json.get("access_token")
    refresh_token = token_json.get("refresh_token")
    if not access_token:
        return _settings_redirect(oauth_error="medium_no_access_token")

    mr = requests.get(
        "https://api.medium.com/v1/me",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=20,
    )
    if mr.status_code != 200:
        print("Medium /me error:", mr.status_code, mr.text)
        return _settings_redirect(oauth_error="medium_userinfo")

    payload = mr.json()
    data = payload.get("data") or payload

    collection = current_app.mongo["users"]
    result = collection.update_one(
        {"email": email},
        {
            "$set": {
                "medium_id": data.get("id"),
                "medium_username": data.get("username"),
                "medium_name": data.get("name"),
                "medium_image_url": data.get("imageUrl"),
                "medium_url": data.get("url"),
                "medium_access_token": access_token,
                "medium_refresh_token": refresh_token,
                "updated_at": datetime.utcnow(),
            }
        },
    )
    if result.matched_count == 0:
        return _settings_redirect(oauth_error="medium_user_not_found")

    return _settings_redirect(integration="medium", result="connected")


@oauth_medium_bp.post("/unlink")
@jwt_required()
def unlink():
    email = get_jwt_identity()
    current_app.mongo["users"].update_one(
        {"email": email},
        {
            "$unset": {
                "medium_id": "",
                "medium_username": "",
                "medium_name": "",
                "medium_image_url": "",
                "medium_url": "",
                "medium_access_token": "",
                "medium_refresh_token": "",
            },
            "$set": {"updated_at": datetime.utcnow()},
        },
    )
    return jsonify({"ok": True}), 200
