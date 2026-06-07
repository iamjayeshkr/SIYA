import re


# Rotating wake replies — JARVIS energy, Hinglish
_WAKE_REPLIES = [
    "Haan, bol.",
    "Online. Bol kya hai.",
    "Ready hoon. Chal.",
    "Haan?",
    "Bata.",
    "Sun rahi hoon.",
    "Hmm?",
    "Bol bhai.",
    "Systems up. Bol.",
    "Present. Kya scene hai.",
]

_ALREADY_ACTIVE_REPLIES = [
    "Pehle se chal rahi hoon yaar.",
    "Already active hoon, bol seedha.",
    "Main yahin hoon, dobara wake mat kar.",
]

import random as _random

def get_wake_reply() -> str:
    return _random.choice(_WAKE_REPLIES)

def get_already_active_reply() -> str:
    return _random.choice(_ALREADY_ACTIVE_REPLIES)

ALREADY_ACTIVE_REPLY = _ALREADY_ACTIVE_REPLIES[0]
WAKE_ACK_REPLY = _WAKE_REPLIES[0]
STARTING_REPLY = WAKE_ACK_REPLY


_WAKE_PHRASES = (
    # ── Single-word triggers (highest priority — just say "siya") ──────────
    "siya",
    "shiya",
    "seeya",
    # ── Short triggers ─────────────────────────────────────────────────────
    "hey siya",
    "hey shiya",
    "hey seeya",
    "ok siya",
    "okay siya",
    "ok shiya",
    "ok seeya",
    "hello siya",
    "hello shiya",
    "hello seeya",
    "siya sun",
    "shiya sun",
    "seeya sun",
    # ── Full wake phrases ──────────────────────────────────────────────────
    "wake up siya",
    "wake up shiya",
    "wake up seeya",
    "wake siya",
    "wake shiya",
    "wake seeya",
    "activate siya",
    "activate shiya",
    "activate seeya",
    "siya activate",
    "shiya activate",
    "seeya activate",
    "siya ko activate",
    "shiya ko activate",
    "seeya ko activate",
    "utho siya",
    "utho shiya",
    "utho seeya",
    "uth ja siya",
    "uth ja shiya",
    "uth ja seeya",
    "siya uth ja",
    "shiya uth ja",
    "seeya uth ja",
)


def _normalize(text: str) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def is_wake_command(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    
    for phrase in _WAKE_PHRASES:
        if phrase in ("siya", "shiya", "seeya"):
            if normalized == phrase:
                return True
        else:
            if phrase in normalized:
                # Specific allow-list for common variations like "kar do"
                if phrase in ("siya ko activate", "shiya ko activate", "seeya ko activate") and "kar do" in normalized:
                    return True
                # Ensure it's a clean activation rather than a compound query
                if normalized == phrase or normalized.startswith(phrase + " ") or normalized.endswith(" " + phrase):
                    query_words = {"search", "google", "weather", "bata", "batao", "play", "music", "song", "open", "close", "karo", "kar"}
                    words = normalized.split()
                    if not any(qw in words for qw in query_words):
                        return True
    return False

