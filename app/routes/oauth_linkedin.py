from flask import Blueprint, current_app, redirect, request, jsonify, g, session
import requests
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, decode_token
from urllib.parse import urlencode, quote
from app.models.user import User
from datetime import datetime, timedelta
from bson.objectid import ObjectId

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
        "scope": "openid profile email w_member_social",
        # ✅ décommente si tu veux forcer l'écran login à chaque fois
        # "prompt": "login",
    }

    # Handle account linking
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
            print("Invalid LinkedIn link_token:", str(e))

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

    token_data = token_response.json()
    access_token_li = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 5184000)  # default 60 days
    if not access_token_li:
        print("No access_token in token response:", token_data)
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
        link_user_id = session.pop("oauth_linking_user_id", None)
        link_user_doc = None

        if link_user_id:
            try:
                link_user_doc = collection.find_one({"_id": ObjectId(link_user_id)})
            except Exception as e:
                print("Invalid LinkedIn link user id:", str(e))

        provider_owner = collection.find_one({
            "social_accounts": {
                "$elemMatch": {
                    "provider": "linkedin",
                    "provider_user_id": userinfo.get("sub")
                }
            }
        })
        if provider_owner:
            existing_user = provider_owner
        elif link_user_doc:
            existing_user = link_user_doc
        else:
            existing_user = collection.find_one({"email": email})

        account_data = {
            "provider": "linkedin",
            "provider_user_id": userinfo.get("sub"),
            "first_name": userinfo.get("given_name"),
            "last_name": userinfo.get("family_name"),
            "profile_picture": userinfo.get("picture"),
            "locale": userinfo.get("locale"),
            "profile": userinfo,
            "access_token": access_token_li,
            "token_expires_at": datetime.utcnow() + timedelta(seconds=expires_in),
            "updated_at": datetime.utcnow()
        }

        if existing_user:
            if not existing_user.get("oauth_provider"):
                account_data["oauth_provider"] = "linkedin"

            # Update existing LinkedIn account or append if missing
            existing_accounts = existing_user.get("social_accounts", [])
            linkedin_account = next((a for a in existing_accounts if a.get("provider") == "linkedin"), None)
            if linkedin_account:
                collection.update_one(
                    {"_id": existing_user["_id"], "social_accounts.provider": "linkedin"},
                    {"$set": {"social_accounts.$": account_data, "updated_at": datetime.utcnow()}}
                )
            else:
                collection.update_one(
                    {"_id": existing_user["_id"]},
                    {"$push": {"social_accounts": account_data}, "$set": {"updated_at": datetime.utcnow()}}
                )

            # Keep a top-level linkedin_id for compatibility when only one LinkedIn account exists
            if not existing_user.get("linkedin_id"):
                collection.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": {"linkedin_id": userinfo.get("sub"), "oauth_provider": existing_user.get("oauth_provider", "linkedin"), "updated_at": datetime.utcnow()}}
                )
            user_id = str(existing_user["_id"])
            print(f"User updated in MongoDB: {email}")
        else:
            new_user = {
                "email": email,
                "password": None,
                "linkedin_id": userinfo.get("sub"),
                "first_name": userinfo.get("given_name"),
                "last_name": userinfo.get("family_name"),
                "profile_picture": userinfo.get("picture"),
                "locale": userinfo.get("locale"),
                "linkedin_data": userinfo,
                "linkedin_access_token": access_token_li,
                "linkedin_token_expires_at": datetime.utcnow() + timedelta(seconds=expires_in),
                "oauth_provider": "linkedin",
                "social_accounts": [account_data],
                "role": "FREE",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            result = collection.insert_one(new_user)
            user_id = str(result.inserted_id)
            print(f"New user created in MongoDB: {email} (ID: {result.inserted_id})")
    except Exception as e:
        print(f"Error saving user to MongoDB: {str(e)}")
        return redirect(f"{frontend_url}/login?oauth_error=db_error")

    # 6) créer JWT puis rediriger vers React (✅ HASH)
    jwt_token = create_access_token(identity=user_id, expires_delta=timedelta(days=7))
    token_encoded = quote(jwt_token)

    full_name = f"{userinfo.get('given_name','') or userinfo.get('localizedFirstName','')} {userinfo.get('family_name','') or userinfo.get('localizedLastName','') or ''}".strip()
    profile_picture = userinfo.get('picture') or ""
    user_info_encoded = quote(f"{full_name}||{full_name}||{profile_picture}")
    redirect_to = f"{frontend_url}/oauth/callback#token={token_encoded}&provider=linkedin&user={user_info_encoded}"
    print("Redirecting to:", redirect_to)

    return redirect(redirect_to)


@oauth_linkedin_bp.get("/me")
@jwt_required()
def get_current_user():
    """
    Get the currently logged-in user's information.
    Requires valid JWT token in Authorization header.
    """
    try:
        # Get user id from JWT identity or global user_email
        identity = get_jwt_identity()
        collection = current_app.mongo["users"]
        user_doc = None

        try:
            user_doc = collection.find_one({"_id": ObjectId(identity)})
        except Exception:
            pass

        if not user_doc:
            email = getattr(g, 'user_email', None) or identity
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
        }
        
        return jsonify(user_data), 200
        
    except Exception as e:
        print(f"Error retrieving user: {str(e)}")
        return jsonify(message="Error retrieving user information"), 500