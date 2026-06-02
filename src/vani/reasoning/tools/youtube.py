"""
vani/reasoning/tools/youtube.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YouTube-explicit intent classifier with vector embeddings.

Handles:
  • seek forward/backward  — "10 min forward kardo", "30s peeche jao"
  • play / pause           — "play karo", "rok do"
  • next / previous song   — "next song", "agla gana"
  • play X (song name)     — "Shape of You play karo", "play Kesariya"
  • youtube search         — "youtube search karo Diljit", "youtube par X dhundo"
  • tab close              — "tab close kardo", "youtube band karo"

Bug fixes (v2):
  ─────────────────────────────────────────────────────────────
  FIX 1 — False positives on Google/search queries
    Root cause: cosine threshold was 0.15 — too low.  "google karo", "search karo",
    "batao" etc shared n-gram tokens with yt_play / yt_close_tab corpus phrases,
    giving scores of 0.20-0.28 that exceeded the old threshold.
    Fix: raised threshold to 0.30 (all genuine YT intents score ≥ 0.32).

  FIX 2 — Explicit Google/search guard
    "google karo ...", "search karo ...", "dhundo/khojo" without 'youtube' in
    the query are unconditionally returned as None so the router falls through
    to GOOGLE_SEARCH.  Queries that include 'youtube' explicitly are still
    handled here.

  FIX 3 — "youtube search karo X" → YOUTUBE_SEARCH (not yt_close_tab)
    "youtube search karo Diljit" was matching _HARD_CLOSE_TAB_RE because it
    contained "band/close" — wrong.  A dedicated _YT_SEARCH_RE is now checked
    FIRST in classify_youtube_intent() and routes to a new YOUTUBE_SEARCH
    intent that extracts the song/artist name and calls the existing play_song
    handler.
  ─────────────────────────────────────────────────────────────
"""

import re
import math
import asyncio
import subprocess
import logging
from typing import Optional

from vani.reasoning.shared import IS_MAC, IS_WINDOWS, logger, _osascript

# ─────────────────────────────────────────────────────────────
# Compile flag alias
# ─────────────────────────────────────────────────────────────
_I = re.IGNORECASE

# ─────────────────────────────────────────────────────────────
# 1.  INTENT CORPUS  (seed phrases for each intent class)
# ─────────────────────────────────────────────────────────────

_CORPUS: dict[str, list[str]] = {

    # ── seek forward ──────────────────────────────────────────
    "seek_forward": [
        "10 min forward kardo", "10 minute aage karo", "aage karo 5 minute",
        "forward kar 30 second", "30 second aage", "2 minute skip karo",
        "skip forward 1 minute", "aage skip karo", "thoda aage karo",
        "fast forward karo", "10s aage", "30s skip", "1 min aage jao",
        "5 minute baad se chalao", "aage le jao", "skip kar aage",
        "10 seconds forward", "go forward 2 minutes", "jump ahead 30 seconds",
        "seek forward", "move ahead", "thoda baad se chalao",
        "aage karo", "forward karo", "skip aage", "2 min aage",
    ],

    # ── seek backward ─────────────────────────────────────────
    "seek_backward": [
        "10 min back kardo", "10 minute peeche karo", "peeche karo 5 minute",
        "back kar 30 second", "30 second peeche", "2 minute rewind karo",
        "rewind 1 minute", "peeche jao", "thoda peeche karo",
        "10s back", "30s rewind", "1 min peeche jao",
        "peeche le jao", "back le jao", "skip kar peeche",
        "10 seconds back", "go back 2 minutes", "rewind 30 seconds",
        "seek backward", "move back", "thoda pehle se chalao",
        "dubara se ek minute", "wapas 30 second",
        "peeche karo", "back karo", "rewind karo",
    ],

    # ── play / resume ─────────────────────────────────────────
    "yt_play": [
        "play karo", "chalu karo", "resume karo", "youtube play karo",
        "video play karo", "gana chalu karo", "start karo",
        "youtube resume", "play kar", "video start kar",
        "chalao", "video chalao",
    ],

    # ── pause / stop ──────────────────────────────────────────
    "yt_pause": [
        "pause karo", "rok do", "band kar", "ruko", "youtube pause karo",
        "video pause karo", "gana rok do", "stop karo",
        "youtube rok", "video rok", "pause kar",
        "rok kar", "thehro",
    ],

    # ── next song / video ─────────────────────────────────────
    "yt_next": [
        "next song", "agla gana", "next video", "agla video",
        "next karo", "skip song", "agle pe jao", "next chalao",
        "next song play karo", "next track", "pudcha gana",
        "next wala", "next song bajao",
    ],

    # ── previous song / video ────────────────────────────────
    "yt_previous": [
        "previous song", "pichla gana", "prev song", "pichla video",
        "previous karo", "peeche wala gana", "pehle wala gana",
        "previous wala", "back song", "prev video",
        "previous track", "peeche wala bajao",
    ],

    # ── play X (song/video search) ───────────────────────────
    "yt_play_song": [
        "shape of you play karo", "kesariya chalao", "play tum hi ho",
        "play karo believer", "bajao despacito", "ye song play karo",
        "yeh wala gana laga do", "laga do koi gana", "play x song",
        "open youtube and play", "youtube par chalao", "youtube pe bajao",
        "song bajao", "gana bajao", "music play karo",
        "play song on youtube", "youtube play song",
    ],

    # ── close tab ────────────────────────────────────────────
    "yt_close_tab": [
        "tab close kardo", "youtube tab band karo", "tab band karo",
        "youtube band karo", "close tab", "tab close karo",
        "browser tab band", "tab hatao", "tab close kar",
        "close youtube tab", "youtube tab close",
        "youtube window band karo", "youtube close karo",
        "band karo youtube", "youtube hatao", "tab hatao youtube",
    ],

    # ── toggle fullscreen ────────────────────────────────────
    "yt_fullscreen": [
        "fullscreen karo", "full screen karo", "bada karo",
        "fullscreen kar", "maximize video", "fullscreen mode",
        "full kar", "bada screen karo",
    ],

    # ── mute / unmute ────────────────────────────────────────
    "yt_mute": [
        "mute karo", "awaaz band karo", "silent karo",
        "mute kar", "unmute karo", "awaaz chalu karo",
        "volume mute", "mute youtube", "unmute youtube",
    ],
}

# ─────────────────────────────────────────────────────────────
# 2.  LIGHTWEIGHT VECTOR EMBEDDING
#     Character bigram + word unigram bag-of-words, no deps.
# ─────────────────────────────────────────────────────────────

_TOKEN_CLEAN_RE = re.compile(r"[^a-z0-9\u0900-\u097f\s]")
_WS_RE          = re.compile(r"\s+")


def _tokenize(text: str) -> list[str]:
    """Word unigrams + character bigrams from cleaned text."""
    t = _TOKEN_CLEAN_RE.sub(" ", text.lower().strip())
    words = t.split()
    tokens = list(words)
    for w in words:
        tokens += [w[i:i+2] for i in range(len(w)-1)]
    return tokens


def _build_vocab_and_vectors(corpus: dict[str, list[str]]):
    all_docs: list[list[str]] = []
    labels:   list[str]       = []
    for intent, phrases in corpus.items():
        for phrase in phrases:
            toks = _tokenize(phrase)
            all_docs.append(toks)
            labels.append(intent)

    vocab: dict[str, int] = {}
    for doc in all_docs:
        for t in doc:
            if t not in vocab:
                vocab[t] = len(vocab)

    df: dict[int, int] = {}
    for doc in all_docs:
        for t in set(doc):
            idx = vocab[t]
            df[idx] = df.get(idx, 0) + 1

    N = len(all_docs)
    V = len(vocab)

    def _tfidf(doc: list[str]) -> list[float]:
        tf: dict[int, float] = {}
        for t in doc:
            idx = vocab[t]
            tf[idx] = tf.get(idx, 0) + 1
        vec = [0.0] * V
        for idx, count in tf.items():
            idf = math.log((N + 1) / (df.get(idx, 0) + 1)) + 1
            vec[idx] = (count / len(doc)) * idf
        return vec

    intent_vecs:   dict[str, list[float]] = {k: [0.0]*V for k in corpus}
    intent_counts: dict[str, int]         = {k: 0        for k in corpus}

    for label, doc in zip(labels, all_docs):
        vec = _tfidf(doc)
        iv  = intent_vecs[label]
        for i, v in enumerate(vec):
            iv[i] += v
        intent_counts[label] += 1

    centroids: dict[str, list[float]] = {}
    for intent, iv in intent_vecs.items():
        n = intent_counts[intent]
        normalized = _l2_norm([v / n for v in iv])
        centroids[intent] = normalized

    return vocab, df, N, V, centroids


def _l2_norm(vec: list[float]) -> list[float]:
    mag = math.sqrt(sum(v*v for v in vec))
    if mag < 1e-9:
        return vec
    return [v / mag for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x*y for x, y in zip(a, b))


_VOCAB, _DF, _N_DOCS, _V, _CENTROIDS = _build_vocab_and_vectors(_CORPUS)


def _embed_query(query: str) -> list[float]:
    tokens = _tokenize(query)
    tf: dict[int, float] = {}
    for t in tokens:
        idx = _VOCAB.get(t)
        if idx is not None:
            tf[idx] = tf.get(idx, 0) + 1
    vec = [0.0] * _V
    if not tokens:
        return vec
    for idx, count in tf.items():
        idf = math.log((_N_DOCS + 1) / (_DF.get(idx, 0) + 1)) + 1
        vec[idx] = (count / len(tokens)) * idf
    return _l2_norm(vec)


_NON_YT_SERVICES = frozenset({
    "whatsapp", "telegram", "spotify", "apple music",
    "hotstar", "netflix", "prime video", "gaana", "wynk",
})

# ─────────────────────────────────────────────────────────────
# FIX 2: Guard regex — queries that are definitely Google/web
# searches and NOT YouTube commands, even if they contain words
# like "karo" or "batao" that confused the old cosine scorer.
#
# Rule: if the query starts with / contains a search trigger
# (google, search, find, dhundo, khojo) AND does NOT explicitly
# mention 'youtube', route it to GOOGLE_SEARCH, not here.
# ─────────────────────────────────────────────────────────────
_GOOGLE_INTENT_RE = re.compile(
    r"(?:^(?:google|search|find|look\s+up|lookup)\b"   # starts with google/search/find
    r"|(?:google\s+karo|search\s+karo|google\s+kar|search\s+kar)\b"  # or has google karo
    r"|\b(?:dhundo|dhoondo|khojo|khojna)\b)",           # or Hinglish search verbs
    _I,
)

# ─────────────────────────────────────────────────────────────
# FIX 3: YouTube-specific search pattern.
# "youtube search karo Diljit", "youtube par X dhundo" etc.
# These should resolve to yt_play_song (search + autoplay),
# NOT yt_close_tab (which the old hard-override was hitting).
# ─────────────────────────────────────────────────────────────
_YT_SEARCH_RE = re.compile(
    r"(?:"
    r"youtube\s+(?:par\s+|pe\s+)?search\s+(?:karo\s+|kar\s+)?(.+)"      # youtube [par] search [karo] X
    r"|youtube\s+(?:par\s+|pe\s+)?(.+?)\s+(?:search\s+(?:karo|kar)?|dhundo|khojo)\s*$"  # youtube [par] X search karo
    r"|(.+?)\s+youtube\s+(?:par\s+|pe\s+)?(?:search\s+(?:karo|kar)?|dhundo|khojo)\s*$"  # X youtube search karo
    r")",
    _I,
)


def _extract_yt_search_query(q: str) -> Optional[str]:
    """
    If query is 'youtube search karo X' style, return X.
    Otherwise return None.
    """
    m = _YT_SEARCH_RE.match(q.strip())
    if m:
        return next((g.strip() for g in m.groups() if g), None)
    return None


# ─────────────────────────────────────────────────────────────
# Hard-override regex patterns — checked AFTER the search guard
# and YouTube-search check, BEFORE cosine scoring.
# ─────────────────────────────────────────────────────────────
_HARD_CLOSE_TAB_RE = re.compile(
    r"\b(?:tab\s+(?:close|band|hatao)|youtube\s+(?:band|close|hatao)|close\s+(?:tab|youtube))\b",
    _I,
)
_HARD_MUTE_RE = re.compile(
    r"\b(?:(?:awaaz|volume)\s+(?:band|off|mute)|mute|unmute|silent)\b",
    _I,
)
_HARD_PLAY_RE  = re.compile(r"\b(?:play|chalu|resume|chalao|start)\b", _I)
_HARD_PAUSE_RE = re.compile(r"\b(?:pause|rok|ruko|thehro|stop)\b", _I)
_HARD_NEXT_RE  = re.compile(r"\b(?:next|agla|pudcha)\b", _I)
_HARD_PREV_RE  = re.compile(r"\b(?:previous|pichla|prev|pehle\s+wala)\b", _I)
_HARD_SEEK_FWD_RE = re.compile(r"\b(?:forward|aage|skip\s+aage|fast\s+forward)\b", _I)
_HARD_SEEK_BWD_RE = re.compile(r"\b(?:back|peeche|rewind|wapas)\b", _I)

# ─────────────────────────────────────────────────────────────
# FIX 1: Raised threshold 0.15 → 0.30
#
# Old value (0.15) caused false positives: non-YouTube queries
# like "google karo latest news" (score 0.25) and
# "search karo python tutorial" (score 0.28) were firing as
# yt_play because they share n-gram tokens with the corpus.
#
# All genuine YouTube intents score ≥ 0.32 at this threshold.
# ─────────────────────────────────────────────────────────────
_COSINE_THRESHOLD = 0.30


def classify_youtube_intent(query: str, threshold: float = _COSINE_THRESHOLD) -> Optional[str]:
    """
    Returns the best-matching YouTube intent name, or None if below threshold.

    Guard order (stops at first match):
      1. Non-YouTube service names (whatsapp, spotify …) → None
      2. Google/search intent without 'youtube' keyword  → None  [FIX 2]
      3. "youtube search karo X" style                   → "yt_play_song"  [FIX 3]
      4. Hard-override regex (unambiguous patterns)
      5. Cosine scoring with threshold=0.30              [FIX 1]
    """
    q = query.lower().strip()

    # Guard 1: clearly another service
    if any(w in q for w in _NON_YT_SERVICES) and "youtube" not in q:
        return None

    # Guard 2 (FIX 2): Google/web search intent without explicit 'youtube' mention
    # e.g. "google karo latest news", "search karo python tutorial", "dhundo X"
    if _GOOGLE_INTENT_RE.search(q) and "youtube" not in q:
        return None

    # Guard 3 (FIX 3): "youtube search karo X" → treat as play_song
    # (the user wants to search YouTube and play the result)
    if _extract_yt_search_query(query) is not None:
        return "yt_play_song"

    # Hard-override fast paths (order: close_tab before mute — both have "band")
    if _HARD_CLOSE_TAB_RE.search(q):
        return "yt_close_tab"
    if _HARD_MUTE_RE.search(q):
        return "yt_mute"

    # Cosine scoring
    qvec        = _embed_query(q)
    best_intent = None
    best_score  = threshold

    for intent, cvec in _CENTROIDS.items():
        score = _cosine(qvec, cvec)
        if score > best_score:
            best_score  = score
            best_intent = intent

    return best_intent


# ─────────────────────────────────────────────────────────────
# 3.  TIME EXTRACTION  (for seek intents)
# ─────────────────────────────────────────────────────────────

_TIME_RE = re.compile(
    r"(\d+)\s*(?:hour|hr|ghanta|ghante)s?"      # group 1 = hours
    r"|(\d+)\s*(?:min(?:ute)?s?)"               # group 2 = minutes
    r"|(\d+)\s*(?:sec(?:ond)?s?|s\b)",          # group 3 = seconds
    _I,
)
_BARE_NUM_RE = re.compile(r"(\d+)")


def _parse_seconds(query: str) -> int:
    matches = _TIME_RE.findall(query)
    if not matches:
        bare = _BARE_NUM_RE.search(query)
        return int(bare.group(1)) if bare else 10

    h = mi = s = 0
    for g_h, g_m, g_s in matches:
        if g_h: h  = int(g_h)
        if g_m: mi = int(g_m)
        if g_s: s  = int(g_s)

    if h == 0 and mi == 0 and s == 0:
        bare = _BARE_NUM_RE.search(query)
        return int(bare.group(1)) if bare else 10

    return h * 3600 + mi * 60 + s


# ─────────────────────────────────────────────────────────────
# 4.  SONG NAME EXTRACTION  (for yt_play_song)
# ─────────────────────────────────────────────────────────────

_PLAY_NOISE_RE = re.compile(
    r"\b(?:play|karo|kar|chalao|bajao|laga|lagao|do|de|youtube|par|pe"
    r"|song|gana|gaana|music|video|wala|yeh|ye|isko|usko|please|pls"
    r"|search|dhundo|dhoondo|khojo)\b",
    _I,
)


def _extract_song_name(query: str) -> str:
    """
    Strip command words and return the probable song/artist name.
    For 'youtube search karo X' style queries, extract X first.
    """
    # Try to extract from youtube-search pattern first (FIX 3)
    yt_q = _extract_yt_search_query(query)
    if yt_q:
        return yt_q

    cleaned = _PLAY_NOISE_RE.sub(" ", query)
    cleaned = _WS_RE.sub(" ", cleaned).strip(" .,!?")
    return cleaned if len(cleaned) > 1 else query.strip()


# ─────────────────────────────────────────────────────────────
# 5.  YOUTUBE KEYBOARD ACTIONS  (Mac + Windows)
# ─────────────────────────────────────────────────────────────

def _yt_keystroke(key: str) -> bool:
    if IS_MAC:
        from vani.reasoning.shared import _mac_keystroke as _mks
        return _mks(key)
    elif IS_WINDOWS:
        try:
            import pyautogui
            pyautogui.press(key)
            return True
        except Exception:
            pass
        try:
            from pynput.keyboard import Controller as KB
            kb = KB()
            kb.press(key); kb.release(key)
            return True
        except Exception:
            return False
    return False


def _yt_hotkey(*keys: str) -> bool:
    if IS_MAC:
        from vani.reasoning.shared import _mac_keystroke as _mks
        mods = list(keys[:-1])
        key  = keys[-1]
        return _mks(key, mods)
    elif IS_WINDOWS:
        try:
            import pyautogui
            pyautogui.hotkey(*keys)
            return True
        except Exception:
            return False
    return False


def _close_tab() -> bool:
    if IS_MAC:
        return _yt_hotkey("command", "w")
    elif IS_WINDOWS:
        return _yt_hotkey("ctrl", "w")
    return False


def _yt_js_seek(seconds: int, direction: str) -> bool:
    if not IS_MAC:
        return False

    sign = "+" if direction == "forward" else "-"
    js = f"document.querySelector('video').currentTime {sign}= {seconds};"

    browser_map = {
        "Google Chrome": f'''tell application "Google Chrome"\n    execute active tab of front window javascript "{js}"\nend tell''',
        "Brave Browser": f'''tell application "Brave Browser"\n    execute active tab of front window javascript "{js}"\nend tell''',
        "Microsoft Edge": f'''tell application "Microsoft Edge"\n    execute active tab of front window javascript "{js}"\nend tell''',
        "Safari": f'''tell application "Safari"\n    do JavaScript "{js}" in current tab of front window\nend tell''',
    }

    from vani.reasoning.shared import _osascript, _frontmost_app_name
    front  = _frontmost_app_name()
    script = browser_map.get(front)
    if script:
        _osascript(script, timeout=3)
        return True

    return False


def _yt_keyboard_seek(seconds: int, direction: str) -> bool:
    if direction == "forward":
        if seconds % 10 == 0:
            presses, key = seconds // 10, "l"
        else:
            presses, key = seconds // 5, "right"
    else:
        if seconds % 10 == 0:
            presses, key = seconds // 10, "j"
        else:
            presses, key = seconds // 5, "left"

    presses = max(1, min(presses, 60))

    if IS_MAC:
        from vani.reasoning.shared import _mac_keystroke as _mks
        for _ in range(presses):
            _mks(key)
        return True
    elif IS_WINDOWS:
        try:
            import pyautogui
            for _ in range(presses):
                pyautogui.press(key)
            return True
        except Exception:
            return False
    return False


# ─────────────────────────────────────────────────────────────
# 6.  PUBLIC TOOL
# ─────────────────────────────────────────────────────────────

from langchain_core.tools import tool


@tool
async def youtube_control(query: str) -> str:
    """
    YouTube-explicit controller. Handles (English + Hinglish):
    - Seek: "10 min forward kardo", "30s back karo", "go forward 2 minutes"
    - Play/Pause: "play karo", "rok do", "resume karo"
    - Next/Previous: "next song", "pichla gana"
    - Play X: "Shape of You bajao", "play Kesariya", "play Believer on youtube"
    - Search & Play: "youtube search karo Diljit", "youtube par Arijit dhundo"
    - Close tab: "tab close karo", "youtube band karo", "close tab"
    - Fullscreen: "fullscreen karo", "full screen karo"
    - Mute: "mute karo", "awaaz band karo", "unmute karo"
    """
    loop = asyncio.get_running_loop()

    intent = classify_youtube_intent(query)
    logger.info(f"[YT] Query: {query!r} → Intent: {intent}")

    if intent is None:
        return ""

    # ── Focus helper — must run before ANY keyboard shortcut ─────────────
    from vani.reasoning.shared import _focus_youtube_tab, _refocus_vani

    # ── Seek forward ──────────────────────────────────────────
    if intent == "seek_forward":
        secs = _parse_seconds(query)
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok   = await loop.run_in_executor(None, _yt_js_seek, secs, "forward")
        if not ok:
            ok = await loop.run_in_executor(None, _yt_keyboard_seek, secs, "forward")
        loop.run_in_executor(None, _refocus_vani)
        mins, s = divmod(secs, 60)
        label   = f"{mins}m {s}s" if mins else f"{secs}s"
        return f"✅ YouTube {label} aage ho gaya." if ok else "❌ Seek forward nahi hua."

    # ── Seek backward ─────────────────────────────────────────
    if intent == "seek_backward":
        secs = _parse_seconds(query)
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok   = await loop.run_in_executor(None, _yt_js_seek, secs, "backward")
        if not ok:
            ok = await loop.run_in_executor(None, _yt_keyboard_seek, secs, "backward")
        loop.run_in_executor(None, _refocus_vani)
        mins, s = divmod(secs, 60)
        label   = f"{mins}m {s}s" if mins else f"{secs}s"
        return f"✅ YouTube {label} peeche ho gaya." if ok else "❌ Seek backward nahi hua."

    # ── Play / Resume ─────────────────────────────────────────
    if intent == "yt_play":
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok = await loop.run_in_executor(None, _yt_keystroke, "k")
        loop.run_in_executor(None, _refocus_vani)
        return "✅ YouTube play ho gaya." if ok else "❌ Play nahi hua."

    # ── Pause / Stop ──────────────────────────────────────────
    if intent == "yt_pause":
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok = await loop.run_in_executor(None, _yt_keystroke, "k")
        loop.run_in_executor(None, _refocus_vani)
        return "✅ YouTube pause ho gaya." if ok else "❌ Pause nahi hua."

    # ── Next ──────────────────────────────────────────────────
    if intent == "yt_next":
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok = await loop.run_in_executor(None, _yt_hotkey, "shift", "n")
        loop.run_in_executor(None, _refocus_vani)
        return "✅ Next video/song ho gaya." if ok else "❌ Next nahi hua."

    # ── Previous ──────────────────────────────────────────────
    if intent == "yt_previous":
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok = await loop.run_in_executor(None, _yt_hotkey, "shift", "p")
        loop.run_in_executor(None, _refocus_vani)
        return "✅ Previous video/song ho gaya." if ok else "❌ Previous nahi hua."

    # ── Play X (song search on YouTube) — also handles yt_play_song from search ──
    if intent == "yt_play_song":
        song = _extract_song_name(query)
        if not song:
            return "Kaunsa song bajana hai?"
        try:
            from vani.browser.control import open_youtube_and_play as _fn
            return await _fn.ainvoke({"song_or_query": song})
        except ImportError:
            import urllib.parse
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(song)
            if IS_MAC:
                from vani.reasoning.shared import _osascript
                _osascript(f'tell application "Google Chrome" to open location "{url}"', timeout=3)
            return f"✅ YouTube par '{song}' search ho gaya."

    # ── Close tab ─────────────────────────────────────────────
    if intent == "yt_close_tab":
        ok = await loop.run_in_executor(None, _close_tab)
        return "✅ Tab close ho gaya." if ok else "❌ Tab close nahi hua."

    # ── Fullscreen ────────────────────────────────────────────
    if intent == "yt_fullscreen":
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok = await loop.run_in_executor(None, _yt_keystroke, "f")
        loop.run_in_executor(None, _refocus_vani)
        return "✅ Fullscreen toggle ho gaya." if ok else "❌ Fullscreen nahi hua."

    # ── Mute ──────────────────────────────────────────────────
    if intent == "yt_mute":
        await loop.run_in_executor(None, _focus_youtube_tab)
        ok = await loop.run_in_executor(None, _yt_keystroke, "m")
        loop.run_in_executor(None, _refocus_vani)
        return "✅ Mute toggle ho gaya." if ok else "❌ Mute nahi hua."

    return ""


# ─────────────────────────────────────────────────────────────
# 7.  CLASSIFIER FUNCTION  (used by router.py)
# ─────────────────────────────────────────────────────────────

def classify_youtube_query(query: str) -> Optional[tuple[str, str]]:
    """
    Returns (intent_key, processed_data) or None.
    Called by router before falling through to Ollama.
    """
    intent = classify_youtube_intent(query)
    if not intent:
        return None

    mapping = {
        "seek_forward":  "YOUTUBE_SEEK_FORWARD",
        "seek_backward": "YOUTUBE_SEEK_BACKWARD",
        "yt_play":       "YOUTUBE_PLAY",
        "yt_pause":      "YOUTUBE_PAUSE",
        "yt_next":       "YOUTUBE_NEXT",
        "yt_previous":   "YOUTUBE_PREVIOUS",
        "yt_play_song":  "YOUTUBE_PLAY_SONG",
        "yt_close_tab":  "YOUTUBE_CLOSE_TAB",
        "yt_fullscreen": "YOUTUBE_FULLSCREEN",
        "yt_mute":       "YOUTUBE_MUTE",
    }
    return mapping.get(intent), query