"""
vani/reasoning/tools/media.py
Media playback control (play/pause/next/previous) and intent classifier.
"""

import subprocess
import logging
from langchain_core.tools import tool

from vani.reasoning.shared import (
    IS_MAC,
    logger,
    _frontmost_app_name,
    _mac_keystroke,
    _mac_key_code,
)

_MEDIA_HINTS = {
    "pause": [
        "gana stop kar", "music band kar", "gaana rok do", "pause kar",
        "song stop kar", "music pause kar", "stop music", "rok do", "band kar",
        "pause video", "video pause", "pause youtube", "youtube pause",
        "youtube rok", "youtube band", "video rok", "video stop"
    ],
    "play": [
        "play karo", "resume karo", "music chalu karo", "resume music",
        "chalu kar", "gana chalao", "song chalao",
        "play video", "resume video", "youtube play", "youtube resume"
    ],
    "next": [
        "agla gana", "next song", "next kar", "pudcha gana",
        "next video", "youtube next"
    ],
    "previous": [
        "pichla gana", "previous song", "prev song", "peeche wala gana",
        "previous video", "youtube previous", "prev video"
    ]
}


def _classify_media_intent(query: str):
    """
    Classifies media control intent using fuzzy/substring matching.
    Returns: 'play', 'pause', 'next', 'previous' or None.
    """
    q = query.lower().strip()

    for action, hints in _MEDIA_HINTS.items():
        for hint in hints:
            if hint in q:
                return action

    media_words = {"gana", "music", "song", "audio", "gaana", "video", "youtube"}
    action_words = {
        "pause": {"pause", "stop", "rok", "band"},
        "play": {"play", "resume", "chalu", "start"},
        "next": {"next", "agla", "forward"},
        "previous": {"previous", "pichla", "back", "prev"}
    }

    generic_words = {
        "kar", "karo", "please", "kardena", "kardo", "do", "de", "na", "pe", "par", "ko", "se",
        "me", "mein", "on", "in", "at", "the", "a", "an"
    }

    tokens = set(q.split())

    all_allowed = media_words | generic_words
    for words in action_words.values():
        all_allowed |= words

    specific_words = tokens - all_allowed
    if specific_words:
        return None

    has_media = bool(tokens & media_words)

    for action, words in action_words.items():
        if tokens & words:
            if has_media:
                return action
            if (q.endswith(" kar") or q.endswith(" karo") or
                    q.startswith("pause") or q.startswith("play") or
                    q.startswith("resume") or q.startswith("stop")):
                return action

    return None


@tool
async def media_control(action: str, query: str = "") -> str:
    """
    Media playback control (Play, Pause, Next, Previous) on Mac.
    action: 'play', 'pause', 'next', 'previous'
    """
    if not IS_MAC:
        return "❌ Media control sirf Mac par supported hai currently."

    action = action.lower().strip()
    action_map = {
        "play": 16,
        "pause": 16,
        "next": 19,
        "previous": 20
    }

    code = action_map.get(action)
    if not code:
        return f"❌ Unknown action: {action}"

    logger.info(f"[MEDIA] Command: {query}")
    logger.info(f"[MEDIA] Action: {action}")

    q = (query or "").lower()
    app = _frontmost_app_name().lower()
    if any(word in q for word in ["youtube", "video"]) or any(
        browser in app for browser in ["chrome", "safari", "firefox", "brave", "edge"]
    ):
        if action in {"play", "pause"}:
            ok = _mac_keystroke(" ")
        elif action == "next":
            ok = _mac_keystroke("n", ["shift"])
        else:
            ok = _mac_keystroke("p", ["shift"])
        if ok:
            return f"✅ YouTube/video {action} ho gaya."

    target = "Unknown / System"
    try:
        r = subprocess.run(
            ["osascript", "-e", 'if application "Spotify" is running then "Spotify"'],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and "Spotify" in r.stdout:
            target = "Spotify"
        else:
            r = subprocess.run(
                ["osascript", "-e", 'if application "Music" is running then "Music"'],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0 and "Music" in r.stdout:
                target = "Music"
            else:
                script = (
                    'tell application "System Events" to get name of every process '
                    'whose name contains "Chrome" or name contains "Safari" or name contains "Firefox"'
                )
                r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
                if r.returncode == 0 and r.stdout.strip():
                    target = f"Browser ({r.stdout.strip().split(',')[0]})"
    except Exception:
        pass

    logger.info(f"[MEDIA] Target: {target}")

    try:
        if not _mac_key_code(code):
            return f"❌ Media {action} nahi hua."
        logger.info(f"[MEDIA] Result: Success")
        return f"✅ Media {action} ho gaya."
    except Exception as e:
        logger.error(f"[MEDIA] Result: Failed - {e}")
        return f"❌ Media control failed: {e}"
