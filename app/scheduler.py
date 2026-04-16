"""
Background scheduler that auto-publishes scheduled posts when their date/time arrives,
and fetches LinkedIn engagement (likes, comments, shares) for published posts.
"""
import threading
import time
from datetime import datetime
from urllib.parse import quote
import requests as http_requests


def _publish_to_linkedin(post_doc, user_doc):
    """Publish a single post to LinkedIn. Returns (success, error_msg)."""
    linkedin_token = user_doc.get("linkedin_access_token")
    linkedin_id = user_doc.get("linkedin_id")

    if not linkedin_token or not linkedin_id:
        return False, "LinkedIn not connected"

    token_expires = user_doc.get("linkedin_token_expires_at")
    if token_expires and datetime.utcnow() > token_expires:
        return False, "LinkedIn token expired"

    content = post_doc.get("content", "")
    if not content:
        return False, "Post has no content"

    author_urn = f"urn:li:person:{linkedin_id}"

    ugc_payload = {
        "author": author_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": content
                },
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    try:
        li_response = http_requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {linkedin_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=ugc_payload,
            timeout=15,
        )

        if li_response.status_code in (200, 201):
            linkedin_post_id = li_response.headers.get("X-RestLi-Id", "")
            return True, linkedin_post_id
        else:
            return False, f"LinkedIn API {li_response.status_code}: {li_response.text[:200]}"
    except Exception as e:
        return False, str(e)


def _check_scheduled_posts(app):
    """Check for scheduled posts that are due and publish them."""
    with app.app_context():
        try:
            mongo = app.mongo
            posts_collection = mongo["posts"]
            users_collection = mongo["users"]

            now = datetime.utcnow()
            today_str = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")

            # Find all scheduled posts where date <= today
            scheduled_posts = list(posts_collection.find({
                "status": "scheduled",
                "schedule_date": {"$lte": today_str}
            }))

            for post in scheduled_posts:
                post_date = post.get("schedule_date", "")
                post_time = post.get("schedule_time", "00:00")

                # Check if the scheduled time has passed
                if post_date < today_str:
                    # Past date — publish immediately
                    is_due = True
                elif post_date == today_str:
                    # Today — check if time has passed
                    is_due = (post_time or "00:00") <= current_time_str
                else:
                    is_due = False

                if not is_due:
                    continue

                post_id = post["_id"]
                user_email = post.get("user_id")
                platforms = post.get("platforms", {})

                # Get user
                user = users_collection.find_one({"email": user_email})
                if not user:
                    print(f"[SCHEDULER] User {user_email} not found, skipping post {post_id}")
                    continue

                # If no schedule_time, use optimal posting times from settings
                if not post_time or post_time == "00:00":
                    settings_doc = mongo["user_settings"].find_one({"user_id": user_email})
                    if settings_doc:
                        posting_prefs = (settings_doc.get("settings") or {}).get("posting") or {}
                        pt = posting_prefs.get("platformTimes", {})
                        # Pick the first valid time from the first selected platform
                        for plat_key in ["linkedin", "twitter", "medium"]:
                            cap_key = plat_key.capitalize() if plat_key != "linkedin" else "LinkedIn"
                            if platforms.get(cap_key):
                                plat_times = pt.get(plat_key, [])
                                valid = [t for t in plat_times if t and len(t) >= 4]
                                if valid:
                                    # Find the next upcoming time today
                                    upcoming = [t for t in valid if t > current_time_str]
                                    if upcoming:
                                        post_time = upcoming[0]
                                    else:
                                        post_time = valid[0]  # Use first time (already passed)
                                    break

                    # Re-check if time has passed after optimal time assignment
                    if post_date == today_str and post_time > current_time_str:
                        is_due = False
                        continue

                print(f"[SCHEDULER] Publishing post {post_id} for {user_email} (scheduled: {post_date} {post_time})")


                published = False
                errors = []

                # Check if auto-post is enabled for LinkedIn
                auto_post = user.get("auto_post", {})

                # Publish to LinkedIn if selected AND auto-post enabled
                if platforms.get("LinkedIn") and auto_post.get("linkedin", False):
                    success, result = _publish_to_linkedin(post, user)
                    if success:
                        print(f"[SCHEDULER] ✅ LinkedIn published: {result}")
                        posts_collection.update_one(
                            {"_id": post_id},
                            {"$set": {"linkedin_post_id": result}}
                        )
                        published = True
                    else:
                        print(f"[SCHEDULER] ❌ LinkedIn failed: {result}")
                        errors.append(f"LinkedIn: {result}")

                # Update post status
                update_data = {
                    "status": "posted",
                    "published_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }

                if errors:
                    update_data["publish_errors"] = errors

                posts_collection.update_one(
                    {"_id": post_id},
                    {"$set": update_data}
                )

                print(f"[SCHEDULER] Post {post_id} marked as posted")

        except Exception as e:
            print(f"[SCHEDULER] Error: {e}")


def _fetch_linkedin_engagement(app):
    """Fetch likes, comments, shares for all published LinkedIn posts."""
    with app.app_context():
        try:
            mongo = app.mongo
            posts_collection = mongo["posts"]
            users_collection = mongo["users"]

            # Find all posted posts that have a linkedin_post_id
            posted = list(posts_collection.find({
                "status": "posted",
                "linkedin_post_id": {"$exists": True, "$ne": ""}
            }))

            if not posted:
                return

            # Group posts by user to avoid repeated user lookups
            user_cache = {}

            for post in posted:
                user_email = post.get("user_id")
                linkedin_post_id = post.get("linkedin_post_id")
                post_id = post["_id"]

                if not linkedin_post_id:
                    continue

                # Get user token (cached)
                if user_email not in user_cache:
                    user = users_collection.find_one({"email": user_email})
                    user_cache[user_email] = user
                else:
                    user = user_cache[user_email]

                if not user:
                    continue

                linkedin_token = user.get("linkedin_access_token")
                if not linkedin_token:
                    continue

                # Check token expiration
                token_expires = user.get("linkedin_token_expires_at")
                if token_expires and datetime.utcnow() > token_expires:
                    continue

                # Use the stored URN directly (already in urn:li:share:xxx format)
                share_urn = linkedin_post_id
                encoded_urn = quote(share_urn, safe='')

                try:
                    # Fetch social actions (likes count, comments count)
                    resp = http_requests.get(
                        f"https://api.linkedin.com/v2/socialActions/{encoded_urn}",
                        headers={
                            "Authorization": f"Bearer {linkedin_token}",
                            "X-Restli-Protocol-Version": "2.0.0",
                        },
                        timeout=10,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        likes_count = data.get("likesSummary", {}).get("totalLikes", 0)
                        comments_count = data.get("commentsSummary", {}).get("totalFirstLevelComments", 0)

                        # LinkedIn socialActions doesn't return shares directly,
                        # try the shares count from the aggregatedTotalShareStatistics
                        shares_count = data.get("sharesSummary", {}).get("totalShares", 0) if "sharesSummary" in data else 0

                        engagement = {
                            "likes": likes_count,
                            "comments": comments_count,
                            "shares": shares_count,
                        }

                        posts_collection.update_one(
                            {"_id": post_id},
                            {"$set": {
                                "engagement": engagement,
                                "engagement_updated_at": datetime.utcnow(),
                            }}
                        )

                        if likes_count > 0 or comments_count > 0 or shares_count > 0:
                            print(f"[ENGAGEMENT] Post {post_id}: {likes_count} likes, {comments_count} comments, {shares_count} shares")
                    elif resp.status_code == 403:
                        # Missing r_member_social scope — don't spam logs
                        pass
                    else:
                        print(f"[ENGAGEMENT] Failed for {post_id}: {resp.status_code} - {resp.text[:200]}")

                except Exception as e:
                    print(f"[ENGAGEMENT] Error for post {post_id}: {e}")

        except Exception as e:
            print(f"[ENGAGEMENT] Global error: {e}")


def start_scheduler(app):
    """Start the background scheduler thread."""
    def run_loop():
        print("[SCHEDULER] Auto-publish scheduler started (checking every 60s)")
        while True:
            try:
                _check_scheduled_posts(app)
                # Engagement fetching requires LinkedIn app verification
                # (Community Management API product). Uncomment when verified:
                # if cycle % 5 == 0:
                #     _fetch_linkedin_engagement(app)
            except Exception as e:
                print(f"[SCHEDULER] Loop error: {e}")
            time.sleep(60)

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
