from flask import Blueprint, current_app, redirect, request, jsonify
import requests
from flask_jwt_extended import create_access_token
from urllib.parse import urlencode, quote

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
    if not email:
        return redirect(f"{frontend_url}/login?oauth_error=no_email")

    # 5) créer JWT puis rediriger vers React (✅ HASH)
    jwt_token = create_access_token(identity=email)
    token_encoded = quote(jwt_token)

    redirect_to = f"{frontend_url}/oauth/callback#token={token_encoded}"
    print("Redirecting to:", redirect_to)

    return redirect(redirect_to)