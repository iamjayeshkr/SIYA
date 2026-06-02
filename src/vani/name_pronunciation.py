"""
vani_name_pronunciation.py — Natural Name Pronunciation System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vani pronounces Indian/English names naturally — never robotic.

Flow:
  Name encountered → check cache → infer if missing → store → inject into prompt
  Cache persists across sessions via JSON file (same dir as memory).

Usage:
  from vani.name_pronunciation import get_pronunciation_block, cache_name

  # In vani_prompts.py:
  from vani.name_pronunciation import get_pronunciation_block
  instructions_prompt += get_pronunciation_block()

  # When a new name is learned:
  cache_name("Harshit", lang_hint="hindi")
"""

import json
import os
import re
import logging
from pathlib import Path
from typing import Optional

from vani.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# ── Storage ──────────────────────────────────────────────────────────────────

_CACHE_FILE = PROJECT_ROOT / "conversations" / "pronunciation_cache.json"

# In-memory dict: { "harshit": {"display": "Harshit", "phonetic": "HUR-shit", "native": "हर्षित", "lang": "hindi"} }
_cache: dict = {}
_cache_loaded: bool = False


def _ensure_dir():
    """Ensure parent directory for cache exists."""
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_cache():
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _ensure_dir()
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
            logger.info(f"[PRONOUNCE] Cache loaded — {len(_cache)} names")
        except Exception as e:
            logger.warning(f"[PRONOUNCE] Cache load failed: {e}")
            _cache = {}
    else:
        _cache = {}
    _cache_loaded = True


def _save_cache():
    _ensure_dir()
    tmp = str(_CACHE_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CACHE_FILE)
        logger.info(f"[PRONOUNCE] Cache saved — {len(_cache)} names")
    except Exception as e:
        logger.error(f"[PRONOUNCE] Cache save failed: {e}")


# ── Built-in Indian name table ────────────────────────────────────────────────
# Format: display_name → (phonetic, native_script, lang)

_BUILTIN: dict[str, tuple[str, str, str]] = {
    # User
    "Rudra":    ("ROOD-ruh",    "रूद्र",     "hindi"),
    # Common contacts — add more as needed
    "Harshit":  ("HUR-shit",    "हर्षित",    "hindi"),
    "Divya":    ("DIV-yah",     "दिव्या",    "hindi"),
    "Priya":    ("PREE-yah",    "प्रिया",    "hindi"),
    "Ananya":   ("uh-NUN-yah",  "अनन्या",   "hindi"),
    "Rohan":    ("ROH-hun",     "रोहन",      "hindi"),
    "Arjun":    ("UR-jun",      "अर्जुन",    "hindi"),
    "Neha":     ("NAY-hah",     "नेहा",      "hindi"),
    "Ranbir":   ("RUN-beer",    "रणबीर",     "hindi"),
    "Shrey":    ("SHRAY",       "श्रेय",     "hindi"),
    "Aditya":   ("uh-DIT-yah",  "आदित्य",   "hindi"),
    "Pooja":    ("POO-jah",     "पूजा",      "hindi"),
    "Rahul":    ("RAH-hul",     "राहुल",     "hindi"),
    "Aarav":    ("AH-ruv",      "आरव",       "hindi"),
    "Ishaan":   ("ee-SHAAN",    "ईशान",      "hindi"),
    "Karan":    ("KUH-run",     "करण",       "hindi"),
    "Siddharth":("SID-harth",   "सिद्धार्थ","hindi"),
    "Tanvi":    ("TUN-vee",     "तन्वी",     "hindi"),
    "Vikram":   ("VIK-rum",     "विक्रम",    "hindi"),
    "Meera":    ("MEE-rah",     "मीरा",      "hindi"),
    "Kabir":    ("kuh-BEER",    "कबीर",      "hindi"),
    "Ayaan":    ("AY-yaan",     "आयान",      "hindi"),
    "Riya":     ("REE-yah",     "रिया",      "hindi"),
    "Shreya":   ("SHRAY-ah",    "श्रेया",    "hindi"),
    "Gaurav":   ("GOW-ruv",     "गौरव",      "hindi"),
    "Yash":     ("YUSH",        "यश",        "hindi"),
    "Varun":    ("VUH-run",     "वरुण",      "hindi"),
    "Nisha":    ("NEE-shah",    "निशा",      "hindi"),
    "Akash":    ("AH-kash",     "आकाश",     "hindi"),
    "Manav":    ("MUH-nuv",     "मानव",      "hindi"),
    "Deepak":   ("DEE-puk",     "दीपक",      "hindi"),
}


# ── Phonetic inference rules for unknown Indian names ─────────────────────────

def _infer_phonetic(name: str, lang_hint: str = "") -> tuple[str, str, str]:
    """
    Infer phonetic pronunciation for an unknown name.
    Returns (phonetic, native_guess, lang).
    Rule-based — avoids robotic letter-by-letter reading.
    """
    n = name.strip()
    lang = lang_hint.lower() if lang_hint else "hindi"

    # Common suffix → sound mappings (Indian names)
    suffix_map = [
        ("ita",  "ee-tah"),  ("ita", "ee-tah"),
        ("ita",  "ee-tah"),
        ("arth", "arth"),
        ("esh",  "aysh"),
        ("ish",  "ish"),
        ("esh",  "aysh"),
        ("aan",  "aan"),
        ("aan",  "aan"),
        ("yan",  "yun"),
        ("raj",  "raaj"),
        ("dev",  "dev"),
        ("ika",  "ee-kah"),
        ("ika",  "ee-kah"),
        ("ini",  "ee-nee"),
        ("ani",  "uh-nee"),
        ("avi",  "uh-vee"),
        ("avi",  "AH-vee"),
    ]

    # Vowel-ending patterns
    phonetic_parts = []
    i = 0
    s = n.lower()

    # Simple syllable chunker: consonant clusters + vowels
    vowels = set("aeiou")
    chunks = re.findall(r'[^aeiou]*[aeiou]+|[^aeiou]+$', s)
    if not chunks:
        chunks = [s]

    def _syllable_to_sound(syl: str) -> str:
        # Known mappings
        replacements = [
            ("sh", "SH"), ("th", "T"), ("ph", "F"),
            ("kh", "KH"), ("gh", "G"), ("ch", "CH"),
            ("aa", "AA"), ("ee", "EE"), ("oo", "OO"),
            ("ai", "AY"), ("au", "OW"),
            ("a",  "uh"), ("e", "ay"), ("i", "ih"),
            ("o",  "oh"), ("u", "oo"),
        ]
        r = syl
        for old, new in replacements:
            r = r.replace(old, new)
        return r.upper()

    phonetic = "-".join(_syllable_to_sound(c) for c in chunks if c)
    if not phonetic:
        phonetic = n.upper()

    native = ""  # Can't generate Devanagari without lookup
    return phonetic, native, lang


# ── Public API ────────────────────────────────────────────────────────────────

def cache_name(name: str, phonetic: str = "", native: str = "", lang_hint: str = "") -> dict:
    """
    Add/update a name in the pronunciation cache.
    If phonetic not provided, infer from rules.
    Returns the stored entry.
    """
    _load_cache()
    key = name.strip().lower()
    display = name.strip().title()

    if not phonetic:
        # Check builtin table first
        builtin = _BUILTIN.get(display)
        if builtin:
            phonetic, native, lang = builtin
        else:
            phonetic, native_inf, lang = _infer_phonetic(display, lang_hint)
            if not native:
                native = native_inf
    else:
        lang = lang_hint or "unknown"

    entry = {
        "display":  display,
        "phonetic": phonetic,
        "native":   native,
        "lang":     lang,
    }
    _cache[key] = entry
    _save_cache()
    logger.info(f"[PRONOUNCE] Cached: {display} → {phonetic}")
    return entry


def get_phonetic(name: str) -> Optional[str]:
    """Return phonetic string for a name, or None if not cached."""
    _load_cache()
    return (_cache.get(name.strip().lower()) or {}).get("phonetic")


def ensure_name(name: str, lang_hint: str = "hindi") -> dict:
    """
    Return cached entry for name. Auto-populate if missing.
    """
    _load_cache()
    key = name.strip().lower()
    if key not in _cache:
        return cache_name(name, lang_hint=lang_hint)
    return _cache[key]


def get_all_cached() -> dict:
    """Return full cache dict (display_name → entry)."""
    _load_cache()
    return {v["display"]: v for v in _cache.values()}


def get_pronunciation_block() -> str:
    """
    Returns a prompt block to inject into instructions_prompt.
    Tells Gemini exactly how to pronounce each known name.
    """
    _load_cache()

    # Seed builtins that aren't in cache yet (non-destructive)
    for display, (phonetic, native, lang) in _BUILTIN.items():
        key = display.lower()
        if key not in _cache:
            _cache[key] = {"display": display, "phonetic": phonetic, "native": native, "lang": lang}

    if not _cache:
        return ""

    lines = []
    for entry in sorted(_cache.values(), key=lambda x: x["display"]):
        native_part = f" ({entry['native']})" if entry.get("native") else ""
        lines.append(f"  • {entry['display']}{native_part} → say: {entry['phonetic']}")

    block = (
        "\n\nNAME PRONUNCIATION (follow exactly — never say names robotically or letter-by-letter):\n"
        + "\n".join(lines)
        + "\n"
        "Rules: Pronounce names as a native Hindi/English speaker would. "
        "Never spell out: R-U-D-R-A. Never say 'Roo-draa' for Rudra. "
        "Use the phonetic guide above every time you say a name.\n"
    )
    return block


# ── Seed on import ────────────────────────────────────────────────────────────
# Pre-populate cache with builtins silently at import time
def _seed_builtins():
    _load_cache()
    changed = False
    for display, (phonetic, native, lang) in _BUILTIN.items():
        key = display.lower()
        if key not in _cache:
            _cache[key] = {"display": display, "phonetic": phonetic, "native": native, "lang": lang}
            changed = True
    if changed:
        _save_cache()

_seed_builtins()
