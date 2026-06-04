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
    # ── Single-word triggers (highest priority — just say "vani") ──────────
    "vani",
    "vaani",
    # ── Short triggers ─────────────────────────────────────────────────────
    "hey vani",
    "hey vaani",
    "ok vani",
    "okay vani",
    "ok vaani",
    "hello vani",
    "hello vaani",
    "vani sun",
    "vaani sun",
    # ── Full wake phrases ──────────────────────────────────────────────────
    "wake up vani",
    "wake up vaani",
    "wake vani",
    "wake vaani",
    "activate vani",
    "activate vaani",
    "vani activate",
    "vaani activate",
    "vani ko activate",
    "vaani ko activate",
    "utho vani",
    "utho vaani",
    "uth ja vani",
    "uth ja vaani",
    "vani uth ja",
    "vaani uth ja",
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
        if phrase in ("vani", "vaani"):
            if normalized == phrase:
                return True
        else:
            if phrase in normalized:
                # Specific allow-list for common variations like "kar do"
                if phrase in ("vani ko activate", "vaani ko activate") and "kar do" in normalized:
                    return True
                # Ensure it's a clean activation rather than a compound query
                if normalized == phrase or normalized.startswith(phrase + " ") or normalized.endswith(" " + phrase):
                    query_words = {"search", "google", "weather", "bata", "batao", "play", "music", "song", "open", "close", "karo", "kar"}
                    words = normalized.split()
                    if not any(qw in words for qw in query_words):
                        return True
    return False
