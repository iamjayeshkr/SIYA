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
    return any(phrase in normalized for phrase in _WAKE_PHRASES)
