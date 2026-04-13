from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
import requests as http_requests
import os

images_bp = Blueprint("images_bp", __name__, url_prefix="/api/images")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")


@images_bp.get("/search")
@jwt_required()
def search_images():
    """Search Google Images via SerpAPI proxy."""
    query = request.args.get("q", "").strip()
    num = min(int(request.args.get("num", 6)), 10)
    page = int(request.args.get("page", 0))

    if not query:
        return jsonify({"success": False, "error": "Missing query parameter 'q'"}), 400

    api_key = SERPAPI_KEY
    if not api_key:
        return jsonify({"success": False, "error": "SerpAPI key not configured"}), 500

    try:
        resp = http_requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_images",
                "q": query,
                "api_key": api_key,
                "num": num,
                "ijn": str(page),
                "safe": "active",
            },
            timeout=15,
        )

        if resp.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"SerpAPI returned {resp.status_code}",
            }), resp.status_code

        data = resp.json()
        results = data.get("images_results", [])[:num]

        images = []
        for item in results:
            images.append({
                "url": item.get("original", ""),
                "thumbnail": item.get("thumbnail", ""),
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "width": item.get("original_width"),
                "height": item.get("original_height"),
            })

        return jsonify({"success": True, "images": images})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
