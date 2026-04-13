"""
Video Builder Route — AI-generated images + TTS voiceover = real video.
Pipeline per scene:
  1. OpenRouter creates a photorealistic image prompt from visualDirection
  2. Kie AI z-image generates the image
  3. edge-tts generates voiceover from narration
  4. Pillow adds a subtle text overlay on the AI image
  5. moviepy assembles all scene clips into one MP4
"""

from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required
import requests as http_requests
import asyncio
import tempfile
import json
import time
import os
import io
import re
import concurrent.futures

import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import (
    ImageClip,
    AudioFileClip,
    concatenate_videoclips,
)

video_builder_bp = Blueprint(
    "video_builder_bp", __name__, url_prefix="/api/media"
)

# ── constants ────────────────────────────────────────────────────
WIDTH, HEIGHT = 1080, 1920  # 9:16 vertical
FPS = 24
TTS_VOICE = "en-US-GuyNeural"

KIE_AI_API_KEY = os.getenv("KIE_AI_API_KEY", "")
KIE_AI_BASE = "https://api.kie.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SCENE_ACCENTS = {
    "hook": (0, 194, 255), "problem": (255, 80, 100), "solution": (0, 220, 130),
    "results": (160, 100, 255), "insights": (220, 200, 50), "cta": (123, 97, 255),
    "default": (0, 194, 255),
}


def _get_accent(st: str):
    k = st.lower().strip()
    for key, v in SCENE_ACCENTS.items():
        if key in k:
            return v
    return SCENE_ACCENTS["default"]


# ══════════════════════════════════════════════════════════════════
#  AI IMAGE PROMPT GENERATION  (OpenRouter)
# ══════════════════════════════════════════════════════════════════


def _generate_image_prompts(scenes: list) -> list[str]:
    """Use OpenRouter to create photorealistic image prompts per scene."""
    api_key = OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return [s.get("visualDirection", "professional photo") for s in scenes]

    scenes_desc = "\n".join(
        f"Scene {s.get('sceneNumber', i+1)} ({s.get('type','')}):\n"
        f"  Narration: \"{s.get('narration', '')}\"\n"
        f"  Visual direction: \"{s.get('visualDirection', '')}\"\n"
        f"  Text overlay: \"{s.get('textOverlay', '')}\""
        for i, s in enumerate(scenes)
    )

    prompt = f"""For each video scene below, write ONE image prompt that shows EXACTLY what the narration is talking about.

THE #1 RULE: The image MUST directly illustrate the scene's specific topic. If the narration talks about "AI automating email marketing", the image must show something related to AI and email marketing — NOT a generic office photo. Read the narration carefully and pick the most visual concrete subject from it.

How to write each prompt (3-4 sentences):
1. First sentence: Describe the SPECIFIC SUBJECT that matches the narration content — real objects, people doing the exact activity mentioned, or the exact concept being discussed. Be concrete and literal.
2. Second sentence: Place it in a fitting environment with realistic details.
3. Third sentence: Add camera/lighting — "shot on 85mm lens, f/1.8, soft natural light, shallow depth of field, photorealistic."

Rules:
- Photorealistic only, no illustration/cartoon/3D. Portrait 9:16 vertical.
- No text, words, letters, logos in the image.
- Each scene gets a DIFFERENT image that matches ITS specific narration — not generic stock photos.
- If narration mentions data/stats → show real dashboards, charts on screens, analytics.
- If narration mentions a product → show that type of product in use.
- If narration mentions people → show people doing the EXACT activity described.
- If narration mentions emotions → show facial expressions and body language matching that emotion.

SCENES:
{scenes_desc}

Return ONLY a JSON array: ["prompt1", "prompt2", ...]"""

    try:
        resp = http_requests.post(
            OPENROUTER_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": OPENROUTER_MODEL or "openai/gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You create image prompts that directly match the content described. Always return valid JSON arrays only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5,
                "max_tokens": 2000,
            },
            timeout=25,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
            prompts = json.loads(raw.strip())
            if isinstance(prompts, list) and len(prompts) >= len(scenes):
                for i, p in enumerate(prompts[:len(scenes)]):
                    print(f"[img_prompt] Scene {i+1}: {p[:80]}...")
                return prompts[:len(scenes)]
    except Exception as e:
        print(f"[img_prompt] Generation failed: {e}")

    return [s.get("visualDirection", "professional cinematic photo") for s in scenes]


# ══════════════════════════════════════════════════════════════════
#  KIE AI — z-image Generation + Polling + Download
# ══════════════════════════════════════════════════════════════════


def _kie_generate_image(prompt: str) -> str | None:
    """Submit image generation to Kie AI z-image. Returns task_id."""
    api_key = KIE_AI_API_KEY or os.getenv("KIE_AI_API_KEY", "")
    if not api_key:
        return None

    try:
        resp = http_requests.post(
            f"{KIE_AI_BASE}/jobs/createTask",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "z-image",
                "input": {
                    "prompt": prompt,
                    "aspect_ratio": "9:16",
                    "nsfw_checker": True,
                },
            },
            timeout=30,
        )
        data = resp.json()
        print(f"[kie_img] Create response code={data.get('code')}")

        if data.get("code") == 200:
            d = data.get("data", {})
            if isinstance(d, dict) and d.get("taskId"):
                return d["taskId"]
            elif isinstance(d, str):
                return d

        print(f"[kie_img] Create failed: {data}")
        return None
    except Exception as e:
        print(f"[kie_img] Create error: {e}")
        return None


def _kie_poll_task(task_id: str, max_wait: int = 120) -> str | None:
    """Poll Kie AI task until success. Returns first result URL or None."""
    api_key = KIE_AI_API_KEY or os.getenv("KIE_AI_API_KEY", "")
    if not api_key:
        return None

    start = time.time()
    interval = 3

    while time.time() - start < max_wait:
        try:
            resp = http_requests.get(
                f"{KIE_AI_BASE}/jobs/recordInfo",
                params={"taskId": task_id},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            data = resp.json()

            if data.get("code") != 200:
                print(f"[kie_img] Poll error: {data}")
                time.sleep(interval)
                continue

            info = data.get("data", {})
            state = info.get("state", "")

            if state == "success":
                result_raw = info.get("resultJson", "{}")
                try:
                    result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                except json.JSONDecodeError:
                    result = {}

                urls = result.get("resultUrls", [])
                if urls:
                    print(f"[kie_img] Task {task_id} done: {urls[0][:60]}...")
                    return urls[0]

                print(f"[kie_img] Success but no URL: {result}")
                return None

            elif state == "fail":
                print(f"[kie_img] Task {task_id} failed: {info.get('failMsg', '?')}")
                return None

            time.sleep(interval)
            if interval < 10:
                interval += 1

        except Exception as e:
            print(f"[kie_img] Poll error: {e}")
            time.sleep(interval)

    print(f"[kie_img] Timeout for task {task_id}")
    return None


def _kie_download_file(url: str, dest: str) -> bool:
    """Download a file from Kie AI URL, optionally via download-url endpoint."""
    api_key = KIE_AI_API_KEY or os.getenv("KIE_AI_API_KEY", "")

    # Try getting a temp download link first
    try:
        resp = http_requests.post(
            f"{KIE_AI_BASE}/common/download-url",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"url": url},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            url = data["data"]
    except Exception:
        pass

    try:
        resp = http_requests.get(url, timeout=30, stream=True)
        if resp.status_code == 200:
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            size = os.path.getsize(dest)
            print(f"[kie_img] Downloaded: {size / 1024:.0f}KB -> {dest}")
            return size > 500
    except Exception as e:
        print(f"[kie_img] Download error: {e}")
    return False


def _generate_one_image(prompt: str, dest: str) -> bool:
    """Full pipeline: submit z-image task -> poll -> download. Returns True on success."""
    task_id = _kie_generate_image(prompt)
    if not task_id:
        return False

    url = _kie_poll_task(task_id, max_wait=120)
    if not url:
        return False

    return _kie_download_file(url, dest)


# ══════════════════════════════════════════════════════════════════
#  IMAGE PROCESSING + TEXT OVERLAY
# ══════════════════════════════════════════════════════════════════


def _load_font(size: int):
    for name in ("arial.ttf", "Arial.ttf", "arialbd.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_rounded_rect(draw, xy, radius, fill):
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.pieslice([x0, y0, x0 + 2 * radius, y0 + 2 * radius], 180, 270, fill=fill)
    draw.pieslice([x1 - 2 * radius, y0, x1, y0 + 2 * radius], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - 2 * radius, x0 + 2 * radius, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - 2 * radius, y1 - 2 * radius, x1, y1], 0, 90, fill=fill)


def _resize_to_frame(path: str):
    """Resize + center-crop an image to WIDTH x HEIGHT (9:16)."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return

    iw, ih = img.size
    target_ratio = WIDTH / HEIGHT
    img_ratio = iw / ih

    if img_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        left = (iw - new_w) // 2
        img = img.crop((left, 0, left + new_w, ih))
    else:
        new_h = int(iw / target_ratio)
        top = (ih - new_h) // 2
        img = img.crop((0, top, iw, top + new_h))

    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    img.save(path, "JPEG", quality=92)


def _add_overlay(path, scene_num, total, scene_type, narration, text_overlay, title=""):
    """Add subtle cinematic overlay on AI-generated image: gradient + badge + narration."""
    accent = _get_accent(scene_type)
    img = Image.open(path).convert("RGBA")

    # Dark gradient overlay (subtle at top, stronger at bottom for text readability)
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for y in range(300):
        alpha = int(140 * (1 - y / 300))
        draw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, alpha))
    for y in range(HEIGHT - 600, HEIGHT):
        t = (y - (HEIGHT - 600)) / 600
        alpha = int(180 * t)
        draw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, alpha))

    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    font_sm = _load_font(30)
    font_badge = _load_font(26)
    font_narr = _load_font(42)
    font_overlay = _load_font(54)

    # Scene counter (top-left)
    draw.text((50, 70), f"SCENE {scene_num}/{total}", fill=(220, 220, 220), font=font_sm)

    # Type badge (top-right)
    badge_text = scene_type.upper()
    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw, bh = bbox[2] - bbox[0] + 36, bbox[3] - bbox[1] + 20
    bx = WIDTH - 50 - bw
    _draw_rounded_rect(draw, (bx, 65, bx + bw, 65 + bh), bh // 2, accent)
    draw.text((bx + 18, 73), badge_text, fill=(255, 255, 255), font=font_badge)

    # Text overlay (center, if provided — big impactful text)
    if text_overlay:
        ov_lines = _wrap_text(text_overlay, font_overlay, WIDTH - 120)
        y_pos = HEIGHT // 3
        for line in ov_lines[:3]:
            bb = draw.textbbox((0, 0), line, font=font_overlay)
            tw = bb[2] - bb[0]
            draw.text(((WIDTH - tw) // 2 + 2, y_pos + 2), line, fill=(0, 0, 0), font=font_overlay)
            draw.text(((WIDTH - tw) // 2, y_pos), line, fill=(255, 255, 255), font=font_overlay)
            y_pos += 68

    # Narration text (bottom area with accent bar)
    narr_lines = _wrap_text(narration, font_narr, WIDTH - 110)
    y_narr = HEIGHT - 90 - len(narr_lines[:5]) * 54 - 40
    draw.rectangle([50, y_narr - 10, 54, y_narr - 10 + len(narr_lines[:5]) * 54], fill=accent)
    for line in narr_lines[:5]:
        draw.text((68, y_narr + 2), line, fill=(0, 0, 0), font=font_narr)
        draw.text((66, y_narr), line, fill=(255, 255, 255), font=font_narr)
        y_narr += 54

    # Progress bar
    bar_y = HEIGHT - 60
    draw.rectangle([50, bar_y, WIDTH - 50, bar_y + 4], fill=(80, 80, 80))
    pw = int((WIDTH - 100) * scene_num / total)
    draw.rectangle([50, bar_y, 50 + pw, bar_y + 4], fill=accent)

    img.save(path, "JPEG", quality=92)


# ══════════════════════════════════════════════════════════════════
#  FALLBACK GRADIENT FRAME (when Kie AI fails for a scene)
# ══════════════════════════════════════════════════════════════════


def _generate_fallback_frame(dest, num, total, stype, narration, overlay, title=""):
    accent = _get_accent(stype)
    img = Image.new("RGB", (WIDTH, HEIGHT), (14, 17, 22))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line([(0, y), (WIDTH, y)], fill=(int(14 + 12 * t), int(17 + 14 * t), int(22 + 16 * t)))
    for r in range(250, 0, -2):
        f = r / 250
        draw.ellipse([WIDTH // 2 - r, HEIGHT // 2 - r - 200, WIDTH // 2 + r, HEIGHT // 2 + r - 200],
                     fill=(min(14 + int(accent[0] * 0.12 * f), 255),
                           min(17 + int(accent[1] * 0.12 * f), 255),
                           min(22 + int(accent[2] * 0.12 * f), 255)))

    font_sm, font_badge, font_narr = _load_font(32), _load_font(28), _load_font(48)
    draw.text((60, 80), f"SCENE {num}/{total}", fill=(200, 200, 200), font=font_sm)
    bt = stype.upper()
    bb = draw.textbbox((0, 0), bt, font=font_badge)
    bw, bh = bb[2] - bb[0] + 40, bb[3] - bb[1] + 24
    bx = WIDTH - 60 - bw
    _draw_rounded_rect(draw, (bx, 75, bx + bw, 75 + bh), bh // 2, accent)
    draw.text((bx + 20, 85), bt, fill=(255, 255, 255), font=font_badge)

    narr_lines = _wrap_text(narration, font_narr, WIDTH - 120)
    y = (HEIGHT - len(narr_lines[:6]) * 62) // 2
    for line in narr_lines[:6]:
        bb = draw.textbbox((0, 0), line, font=font_narr)
        draw.text(((WIDTH - bb[2] + bb[0]) // 2, y), line, fill=(240, 240, 240), font=font_narr)
        y += 62

    bar_y = HEIGHT - 80
    draw.rectangle([60, bar_y, WIDTH - 60, bar_y + 5], fill=(50, 50, 60))
    draw.rectangle([60, bar_y, 60 + int((WIDTH - 120) * num / total), bar_y + 5], fill=accent)
    img.save(dest, "JPEG", quality=90)


# ══════════════════════════════════════════════════════════════════
#  TTS
# ══════════════════════════════════════════════════════════════════


async def _generate_tts(text, path, voice=TTS_VOICE):
    await edge_tts.Communicate(text, voice).save(path)


def _run_tts(text, path, voice=TTS_VOICE):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _generate_tts(text, path, voice)).result()
        else:
            loop.run_until_complete(_generate_tts(text, path, voice))
    except RuntimeError:
        asyncio.run(_generate_tts(text, path, voice))


# ══════════════════════════════════════════════════════════════════
#  MAIN ROUTE
# ══════════════════════════════════════════════════════════════════


@video_builder_bp.post("/build-video")
@jwt_required()
def build_video():
    """
    Build a real video from AI-generated scenes.

    Pipeline:
      1. OpenRouter generates photorealistic image prompts per scene
      2. Kie AI z-image generates AI images for each scene
      3. edge-tts generates voiceover audio per scene
      4. Pillow adds cinematic text overlay on each AI image
      5. moviepy assembles all clips into a single MP4

    Falls back to styled gradient frames if Kie AI image gen fails.

    Request: { title, scenes: [{sceneNumber, narration, visualDirection, textOverlay, type}] }
    Returns: MP4 file download.
    """
    data = request.get_json()
    scenes = data.get("scenes", [])
    title = data.get("title", "AutoPoster_Video")

    if not scenes:
        return jsonify({"success": False, "error": "No scenes provided"}), 400

    tmpdir = tempfile.mkdtemp(prefix="autoposter_video_")
    total = len(scenes)

    try:
        kie_key = KIE_AI_API_KEY or os.getenv("KIE_AI_API_KEY", "")

        # ── Step 1: Generate image prompts via OpenRouter ─────────
        print(f"[video] Generating image prompts for {total} scenes...")
        image_prompts = _generate_image_prompts(scenes)

        # ── Step 2: Submit ALL image generation tasks in parallel ──
        print(f"[video] Submitting {total} image tasks to Kie AI z-image...")
        task_ids = []
        for i, prompt in enumerate(image_prompts):
            if kie_key:
                tid = _kie_generate_image(prompt)
                task_ids.append(tid)
                print(f"[video] Scene {i+1} submitted: task={tid}")
            else:
                task_ids.append(None)

        # ── Step 3: Generate TTS for all scenes (while images generate) ──
        print(f"[video] Generating TTS audio for {total} scenes...")
        audio_paths = []
        for i, scene in enumerate(scenes):
            narr = scene.get("narration", "")
            audio_path = os.path.join(tmpdir, f"scene_{i}.mp3")
            _run_tts(narr, audio_path)
            audio_paths.append(audio_path)
            print(f"[video] TTS scene {i+1}/{total} done")

        # ── Step 4: Poll for images + download ────────────────────
        print(f"[video] Waiting for AI images...")
        clips = []

        for i, scene in enumerate(scenes):
            narration = scene.get("narration", "")
            text_overlay = scene.get("textOverlay", "")
            scene_type = scene.get("type", "")
            scene_num = scene.get("sceneNumber", i + 1)
            img_path = os.path.join(tmpdir, f"scene_{i}.jpg")

            image_ok = False

            # Poll and download AI image
            if task_ids[i]:
                url = _kie_poll_task(task_ids[i], max_wait=120)
                if url:
                    raw_path = os.path.join(tmpdir, f"scene_{i}_raw.png")
                    if _kie_download_file(url, raw_path):
                        # Resize to 9:16 frame
                        try:
                            img = Image.open(raw_path).convert("RGB")
                            img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
                            img.save(img_path, "JPEG", quality=92)
                            image_ok = True
                            print(f"[video] Scene {i+1}: AI image ready!")
                        except Exception as e:
                            print(f"[video] Scene {i+1}: Image processing failed: {e}")

            # Fallback to gradient frame
            if not image_ok:
                print(f"[video] Scene {i+1}: Using fallback frame")
                _generate_fallback_frame(img_path, scene_num, total, scene_type,
                                         narration, text_overlay, title)

            # Add text overlay on top of AI image
            if image_ok:
                _add_overlay(img_path, scene_num, total, scene_type,
                             narration, text_overlay, title)

            # ── Build clip: image + audio ─────────────────────────
            audio_clip = AudioFileClip(audio_paths[i])
            duration = audio_clip.duration + 0.5
            clip = ImageClip(img_path).with_duration(duration).with_audio(audio_clip)
            clips.append(clip)
            print(f"[video] Scene {i+1}/{total} clip ready ({duration:.1f}s)")

        # ── Step 5: Assemble final video ──────────────────────────
        print(f"[video] Assembling {len(clips)} scenes into MP4...")
        final = concatenate_videoclips(clips, method="compose")
        output_path = os.path.join(tmpdir, "output.mp4")
        final.write_videofile(output_path, fps=FPS, codec="libx264",
                              audio_codec="aac", logger=None)

        with open(output_path, "rb") as f:
            video_bytes = io.BytesIO(f.read())

        for c in clips:
            try: c.close()
            except: pass
        try: final.close()
        except: pass

        safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:60]
        video_bytes.seek(0)

        return send_file(
            video_bytes,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=f"{safe_title}.mp4",
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  CAROUSEL BUILDER — AI images + text overlay = slide images
# ══════════════════════════════════════════════════════════════════

CAROUSEL_W, CAROUSEL_H = 1080, 1080  # square for LinkedIn/Instagram

# Color themes per slide position
SLIDE_THEMES = [
    {"bg": (15, 23, 42), "accent": (0, 194, 255), "badge": "HOOK"},
    {"bg": (20, 15, 42), "accent": (139, 92, 246), "badge": "KEY POINT"},
    {"bg": (15, 30, 30), "accent": (0, 220, 160), "badge": "INSIGHT"},
    {"bg": (30, 15, 25), "accent": (244, 63, 94), "badge": "DATA"},
    {"bg": (25, 25, 15), "accent": (250, 204, 21), "badge": "TIP"},
    {"bg": (15, 25, 35), "accent": (56, 189, 248), "badge": "TAKEAWAY"},
    {"bg": (25, 15, 35), "accent": (168, 85, 247), "badge": "SUMMARY"},
    {"bg": (15, 20, 40), "accent": (99, 102, 241), "badge": "CTA"},
]


def _generate_slide_image_prompts(slides: list) -> list[str]:
    """Generate photorealistic image prompts for carousel slides."""
    api_key = OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return [s.get("imageQuery", "professional photo") for s in slides]

    slides_desc = "\n".join(
        f"Slide {s.get('slideNumber', i+1)}:\n"
        f"  Headline: \"{s.get('headline', '')}\"\n"
        f"  Body: \"{s.get('body', '')}\"\n"
        f"  Design note: \"{s.get('designNote', '')}\""
        for i, s in enumerate(slides)
    )

    prompt = f"""For each carousel slide below, write ONE image prompt for a background image that matches the slide's specific topic.

THE #1 RULE: The background image MUST relate to what the slide is actually about. Read the headline and body text carefully. If the slide talks about "email open rates", show a phone with email notifications — NOT a random sunset. The image should make someone immediately understand the slide's topic even before reading the text.

How to write each prompt (2-3 sentences):
1. First sentence: Describe a SPECIFIC visual subject directly related to the slide's headline/body content. Be concrete — real objects, real scenes, real activities mentioned in the text.
2. Second sentence: Make it slightly blurred or dark enough to work as a text BACKGROUND — use shallow depth of field (f/1.4) or soft dark tones so white text is readable on top.
3. Add: "photorealistic, shot on professional camera, square 1:1 format, soft diffused lighting."

Rules:
- No text, words, letters, logos in the image.
- Photorealistic only, no illustration/cartoon/3D.
- Each slide gets a DIFFERENT image matching ITS specific content.
- The image should be slightly dark or blurred so headline text is readable on top.
- If slide mentions tech → show real tech (laptops, phones, code screens blurred).
- If slide mentions growth → show graphs going up, plants growing, arrows.
- If slide mentions people → show people doing what the slide describes.
- If slide mentions a problem → show visual metaphor of that problem.

SLIDES:
{slides_desc}

Return ONLY a JSON array: ["prompt1", "prompt2", ...]"""

    try:
        resp = http_requests.post(
            OPENROUTER_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "model": OPENROUTER_MODEL or "openai/gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You create background image prompts that directly match the slide's topic. Always return valid JSON arrays only."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.5,
                "max_tokens": 2000,
            },
            timeout=25,
        )
        if resp.status_code == 200:
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
            raw = re.sub(r'\n?```\s*$', '', raw)
            prompts = json.loads(raw.strip())
            if isinstance(prompts, list) and len(prompts) >= len(slides):
                return prompts[:len(slides)]
    except Exception as e:
        print(f"[carousel] Prompt gen failed: {e}")

    return [s.get("imageQuery", "abstract professional background") for s in slides]


def _build_carousel_slide(
    dest: str,
    slide: dict,
    slide_idx: int,
    total: int,
    bg_image_path: str | None,
    title: str = "",
):
    """Build one carousel slide image with AI background + text overlay."""
    theme = SLIDE_THEMES[slide_idx % len(SLIDE_THEMES)]
    accent = theme["accent"]
    bg_color = theme["bg"]

    headline = slide.get("headline", "")
    body = slide.get("body", "")
    slide_num = slide.get("slideNumber", slide_idx + 1)

    # Start with AI background or gradient
    if bg_image_path and os.path.exists(bg_image_path):
        try:
            img = Image.open(bg_image_path).convert("RGBA")
            # Resize to square
            iw, ih = img.size
            side = min(iw, ih)
            left = (iw - side) // 2
            top = (ih - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((CAROUSEL_W, CAROUSEL_H), Image.LANCZOS)

            # Heavy dark overlay so text is readable
            overlay = Image.new("RGBA", (CAROUSEL_W, CAROUSEL_H), (0, 0, 0, 0))
            draw_ov = ImageDraw.Draw(overlay)
            for y in range(CAROUSEL_H):
                alpha = int(160 + 40 * (y / CAROUSEL_H))
                draw_ov.line([(0, y), (CAROUSEL_W, y)], fill=(bg_color[0], bg_color[1], bg_color[2], alpha))
            img = Image.alpha_composite(img, overlay).convert("RGB")
        except Exception:
            img = Image.new("RGB", (CAROUSEL_W, CAROUSEL_H), bg_color)
    else:
        img = Image.new("RGB", (CAROUSEL_W, CAROUSEL_H), bg_color)

    draw = ImageDraw.Draw(img)

    # Subtle gradient overlay
    for y in range(CAROUSEL_H):
        t = y / CAROUSEL_H
        r = int(bg_color[0] * (1 - 0.3 * t))
        g = int(bg_color[1] * (1 - 0.3 * t))
        b = int(bg_color[2] * (1 - 0.3 * t))
        alpha_line = Image.new("RGBA", (CAROUSEL_W, 1), (r, g, b, 30))
        img.paste(Image.new("RGB", (CAROUSEL_W, 1), (r, g, b)), (0, y), alpha_line.split()[3])

    draw = ImageDraw.Draw(img)

    # Accent decoration — top bar
    draw.rectangle([0, 0, CAROUSEL_W, 6], fill=accent)

    # Accent glow circle (decorative)
    for r_radius in range(120, 0, -2):
        f = r_radius / 120
        cr = min(bg_color[0] + int(accent[0] * 0.08 * f), 255)
        cg = min(bg_color[1] + int(accent[1] * 0.08 * f), 255)
        cb = min(bg_color[2] + int(accent[2] * 0.08 * f), 255)
        draw.ellipse(
            [CAROUSEL_W - 180 - r_radius, 60 - r_radius,
             CAROUSEL_W - 180 + r_radius, 60 + r_radius],
            fill=(cr, cg, cb),
        )

    # Fonts
    font_slide_num = _load_font(22)
    font_headline = _load_font(52)
    font_body = _load_font(28)
    font_footer = _load_font(18)

    # Slide number badge (top-left)
    badge_text = f"  {slide_num}/{total}  "
    bb = draw.textbbox((0, 0), badge_text, font=font_slide_num)
    bw, bh = bb[2] - bb[0] + 20, bb[3] - bb[1] + 16
    _draw_rounded_rect(draw, (50, 50, 50 + bw, 50 + bh), bh // 2, accent)
    draw.text((60, 56), badge_text, fill=(255, 255, 255), font=font_slide_num)

    # Headline (centered, upper area)
    headline_lines = _wrap_text(headline, font_headline, CAROUSEL_W - 120)
    total_headline_h = len(headline_lines[:4]) * 66

    # Position headline starting at ~30% from top
    hy = max(200, (CAROUSEL_H - total_headline_h - 200) // 3)
    for line in headline_lines[:4]:
        bb = draw.textbbox((0, 0), line, font=font_headline)
        tw = bb[2] - bb[0]
        # Shadow
        draw.text(((CAROUSEL_W - tw) // 2 + 2, hy + 2), line, fill=(0, 0, 0), font=font_headline)
        draw.text(((CAROUSEL_W - tw) // 2, hy), line, fill=(255, 255, 255), font=font_headline)
        hy += 66

    # Accent divider line
    div_y = hy + 20
    div_w = 80
    draw.rectangle([(CAROUSEL_W - div_w) // 2, div_y, (CAROUSEL_W + div_w) // 2, div_y + 4], fill=accent)

    # Body text (centered, below divider)
    body_lines = _wrap_text(body, font_body, CAROUSEL_W - 120)
    by = div_y + 30
    for line in body_lines[:6]:
        bb = draw.textbbox((0, 0), line, font=font_body)
        tw = bb[2] - bb[0]
        draw.text(((CAROUSEL_W - tw) // 2, by), line, fill=(200, 200, 210), font=font_body)
        by += 40

    # Footer — swipe indicator
    footer_y = CAROUSEL_H - 60
    if slide_idx < total - 1:
        swipe_text = "Swipe →"
    else:
        swipe_text = title[:40] if title else "AutoPoster"
    bb = draw.textbbox((0, 0), swipe_text, font=font_footer)
    tw = bb[2] - bb[0]
    draw.text(((CAROUSEL_W - tw) // 2, footer_y), swipe_text, fill=(*accent, ), font=font_footer)

    # Bottom accent bar
    draw.rectangle([0, CAROUSEL_H - 6, CAROUSEL_W, CAROUSEL_H], fill=accent)

    # Slide position dots
    dot_y = CAROUSEL_H - 30
    dot_total_w = total * 16 + (total - 1) * 8
    dot_start_x = (CAROUSEL_W - dot_total_w) // 2
    for d in range(total):
        dx = dot_start_x + d * 24
        color = accent if d == slide_idx else (80, 80, 90)
        draw.ellipse([dx, dot_y, dx + 10, dot_y + 10], fill=color)

    img.save(dest, "JPEG", quality=95)


def _build_gradient_slide(dest, slide, slide_idx, total, title=""):
    """Build a carousel slide with gradient background (no AI image)."""
    _build_carousel_slide(dest, slide, slide_idx, total, None, title)


@video_builder_bp.post("/build-carousel")
@jwt_required()
def build_carousel():
    """
    Build real carousel slide images from AI-generated slide data.

    Pipeline per slide:
      1. OpenRouter generates a background image prompt
      2. Kie AI z-image creates the background
      3. Pillow overlays headline + body text + branding
      4. Returns ZIP of all slide JPEGs

    Request: { title, slides: [{slideNumber, headline, body, designNote, imageQuery}] }
    Returns: ZIP file with slide_1.jpg, slide_2.jpg, etc.
    """
    data = request.get_json()
    slides = data.get("slides", [])
    title = data.get("title", "Carousel")

    if not slides:
        return jsonify({"success": False, "error": "No slides provided"}), 400

    tmpdir = tempfile.mkdtemp(prefix="autoposter_carousel_")
    total = len(slides)

    try:
        kie_key = KIE_AI_API_KEY or os.getenv("KIE_AI_API_KEY", "")

        # Step 1: Generate image prompts
        print(f"[carousel] Generating image prompts for {total} slides...")
        image_prompts = _generate_slide_image_prompts(slides)

        # Step 2: Submit all image tasks
        task_ids = []
        for i, prompt in enumerate(image_prompts):
            if kie_key:
                tid = _kie_generate_image(prompt)
                task_ids.append(tid)
                print(f"[carousel] Slide {i+1} submitted: task={tid}")
            else:
                task_ids.append(None)

        # Step 3: Poll + download + build slides
        slide_paths = []
        for i, slide in enumerate(slides):
            img_path = os.path.join(tmpdir, f"slide_{i+1}.jpg")
            bg_path = None

            # Try to get AI background
            if i < len(task_ids) and task_ids[i]:
                url = _kie_poll_task(task_ids[i], max_wait=120)
                if url:
                    raw_path = os.path.join(tmpdir, f"bg_{i}.png")
                    if _kie_download_file(url, raw_path):
                        bg_path = raw_path
                        print(f"[carousel] Slide {i+1}: AI background ready")

            if not bg_path:
                print(f"[carousel] Slide {i+1}: Using gradient background")

            _build_carousel_slide(img_path, slide, i, total, bg_path, title)
            slide_paths.append(img_path)
            print(f"[carousel] Slide {i+1}/{total} built")

        # Step 4: Create ZIP
        import zipfile
        zip_path = os.path.join(tmpdir, "carousel.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in slide_paths:
                zf.write(path, os.path.basename(path))

        with open(zip_path, "rb") as f:
            zip_bytes = io.BytesIO(f.read())

        safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)[:60]
        zip_bytes.seek(0)

        return send_file(
            zip_bytes,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{safe_title}_carousel.zip",
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
