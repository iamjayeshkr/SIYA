import base64
import os
from typing import Tuple


SUPPORTED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

_VISION_MODELS = (
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
)


def _detect_mime(filename: str, data: bytes, browser_mime: str = "") -> str:
    mime = (browser_mime or "").strip().lower()
    if mime in SUPPORTED_IMAGE_MIMES:
        return mime

    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"hevc", b"hevx"}:
        return "image/heic"
    if len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in {b"mif1", b"msf1"}:
        return "image/heif"

    ext = os.path.splitext(filename or "")[1].lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".heic":
        return "image/heic"
    if ext == ".heif":
        return "image/heif"
    return mime


def _make_prompt(user_prompt: str, filename: str) -> str:
    user_prompt = (user_prompt or "").strip()
    context = user_prompt or "Image ko dekho aur useful, honest review do."
    return f"""You are Vani, Rudra's personal assistant. Analyze the attached image.

User context/request:
{context}

Image filename: {filename or "uploaded image"}

Rules:
- First identify what kind of image this is: personal/photo, code screenshot, document, UI/design, object/product, place, meme, or something else.
- If it contains code, do a practical code review: bugs, edge cases, readability, performance, and a better version only when useful.
- If it is a personal photo, be warm but honest. Do not fake praise. Give a reality-check style review of the photo quality, pose, framing, lighting, expression/vibe, outfit/color coordination, background, and what can be improved.
- If the user asks for harsh feedback, be direct but not insulting. No "sab accha hai" unless it is genuinely strong.
- You may rate the image from 1 to 10 when helpful. Rate the image/photo/presentation, not the person's worth.
- Do not identify who a person is, confirm relationships, guess sensitive traits, or make sexual comments.
- If the image is about something else, answer according to that content.
- Reply naturally in Hinglish by default. Keep it useful and concrete."""


def _extract_text(data: dict) -> str:
    parts = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()


def analyze_image(filename: str, data: bytes, user_prompt: str = "", browser_mime: str = "") -> Tuple[bool, str]:
    if not data:
        return False, "Image empty hai."

    mime_type = _detect_mime(filename, data, browser_mime)
    if mime_type not in SUPPORTED_IMAGE_MIMES:
        return False, "Ye image format supported nahi hai. JPG, PNG, WebP, HEIC ya HEIF bhejo."

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return False, "GOOGLE_API_KEY/GEMINI_API_KEY missing hai, isliye image analyze nahi kar pa rahi."

    try:
        import requests
    except ImportError:
        return False, "Python dependency `requests` missing hai. Project requirements install karo, phir image review chalega."

    img_b64 = base64.b64encode(data).decode("utf-8")
    payload = {
        "contents": [{
            "parts": [
                {"text": _make_prompt(user_prompt, filename)},
                {"inline_data": {"mime_type": mime_type, "data": img_b64}},
            ]
        }]
    }

    last_error = None
    for model in _VISION_MODELS:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            resp = requests.post(url, json=payload, timeout=40)
            if resp.status_code == 429:
                last_error = f"{model}: rate limit"
                continue
            resp.raise_for_status()
            text = _extract_text(resp.json())
            if text:
                return True, text
            last_error = f"{model}: empty response"
        except Exception as exc:
            last_error = f"{model}: {exc}"

    return False, f"Image analyze nahi ho paayi. Last error: {last_error}"
