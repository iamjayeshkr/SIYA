"""
vani_browser_control.py — Phase 1: Smart Browser & YouTube/App Launcher
=====================================================================
Cross-platform: macOS (AppleScript + subprocess) & Windows (subprocess)

Features:
  - Open any URL in Chrome, Safari, Edge, Firefox, or default browser
  - YouTube voice control: search + direct video URL via yt-dlp
  - WhatsApp desktop app / Web fallback
  - Telegram desktop app / Web fallback
  - Universal app launcher (web apps + desktop apps)

NO extra permissions needed beyond what the OS already allows.
Requires: yt-dlp  (pip install yt-dlp)
"""

import os
import sys
import asyncio
import subprocess
import urllib.parse
import logging
import re
import json
import shutil
import threading
import unicodedata
from difflib import SequenceMatcher

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

SITE_HOME_URLS = {
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "leetcode": "https://leetcode.com",
    "leet code": "https://leetcode.com",
    "hackerrank": "https://www.hackerrank.com",
    "hacker rank": "https://www.hackerrank.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "web whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "openai chat": "https://chatgpt.com",
    "google": "https://www.google.com",
    "google.com": "https://www.google.com",
    "amazon": "https://www.amazon.in",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "linkedln": "https://www.linkedin.com",
    "linked in": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "x.com": "https://twitter.com",
}

SITE_SEARCH_URLS = {
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "yt": "https://www.youtube.com/results?search_query={query}",
    "leetcode": "https://leetcode.com/problemset/?search={query}",
    "leet code": "https://leetcode.com/problemset/?search={query}",
    "hackerrank": "https://www.hackerrank.com/search?term={query}",
    "hacker rank": "https://www.hackerrank.com/search?term={query}",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "web whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com/?q={query}",
    "chat gpt": "https://chatgpt.com/?q={query}",
    "openai chat": "https://chatgpt.com/?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "google.com": "https://www.google.com/search?q={query}",
    "amazon": "https://www.amazon.in/s?k={query}",
    "github": "https://github.com/search?q={query}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "linkedln": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "linked in": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "instagram": "https://www.instagram.com/explore/search/keyword/?q={query}",
    "insta": "https://www.instagram.com/explore/search/keyword/?q={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "twitter": "https://twitter.com/search?q={query}",
    "x": "https://twitter.com/search?q={query}",
    "x.com": "https://twitter.com/search?q={query}",
}

SITE_NAME_PATTERN = (
    r"youtube|yt|leetcode|leet\s*code|hackerrank|hacker\s*rank|"
    r"whatsapp(?:\s*web)?|web\s*whatsapp|chatgpt|chat\s*gpt|openai\s*chat|"
    r"google(?:\.com)?|amazon|github|reddit|linkedin|linkedln|linked\s*in|"
    r"instagram|insta|twitter|x(?:\.com)?"
)

SITE_ALIAS_NORMALIZATIONS = (
    (re.compile(r"\bleet\s+code\b", re.IGNORECASE), "leet code"),
    (re.compile(r"\bhacker\s+rank\b", re.IGNORECASE), "hacker rank"),
    (re.compile(r"\blinked\s+in\b", re.IGNORECASE), "linked in"),
    (re.compile(r"\bchat\s+gpt\b", re.IGNORECASE), "chat gpt"),
    (re.compile(r"\bopenai\s+chat\b", re.IGNORECASE), "openai chat"),
    (re.compile(r"\bweb\s+whatsapp\b", re.IGNORECASE), "web whatsapp"),
    (re.compile(r"\bx\s+com\b", re.IGNORECASE), "x.com"),
)

DESKTOP_APP_ALIASES = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "brave": "Brave Browser",
    "brave browser": "Brave Browser",
    "safari": "Safari",
    "firefox": "Firefox",
    "edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "telegram": "Telegram",
    "terminal": "Terminal",
    "finder": "Finder",
    "settings": "System Settings",
    "system settings": "System Settings",
    "calculator": "Calculator",
    "notes": "Notes",
    "music": "Music",
    "spotify": "Spotify",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
}

WEB_APPS = {
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://twitter.com",
    "x.com": "https://twitter.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
    "netflix": "https://www.netflix.com",
    "prime video": "https://www.primevideo.com",
    "amazon prime": "https://www.primevideo.com",
    "hotstar": "https://www.hotstar.com",
    "jio cinema": "https://www.jiocinema.com",
    "chatgpt": "https://chat.openai.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com",
    "docs": "https://docs.google.com",
    "sheets": "https://sheets.google.com",
    "meet": "https://meet.google.com",
    "google meet": "https://meet.google.com",
    "claude": "https://claude.ai",
    "perplexity": "https://www.perplexity.ai",
}


def _normalize_user_command(text: str) -> str:
    q = " ".join((text or "").strip().lower().split())
    if not q:
        return ""
    prefix = r"(?:arey|aree|arre|are|ary|hey|hello|hi|suno|sun|ok|okay|please|pls|bhai|bro|yaar)"
    assistant = r"(?:vani|vaani|wani|waani|vanni|wanni)"
    changed = True
    while changed and q:
        before = q
        q = re.sub(rf"^(?:{prefix})[\s,]+", "", q).strip()
        q = re.sub(rf"^(?:{assistant})[\s,]+", "", q).strip()
        q = re.sub(rf"^(?:{prefix})[\s,]+(?:{assistant})[\s,]+", "", q).strip()
        q = re.sub(rf"^(?:{assistant})[\s,]+(?:{prefix})[\s,]+", "", q).strip()
        changed = q != before
    return q


# ─────────────────────────────────────────────────────────────────────────────
# Browser detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_browser_mac(hint: str = "chrome") -> str | None:
    """Return path to preferred browser on Mac, or None if not found."""
    hint = hint.lower()
    candidates = {
        "chrome": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        ],
        "edge": [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ],
        "firefox": [
            "/Applications/Firefox.app/Contents/MacOS/firefox",
        ],
        "safari": [],  # Safari uses AppleScript, not direct binary
    }
    for key, paths in candidates.items():
        if hint in key or key in hint:
            for p in paths:
                if os.path.exists(p):
                    return p
    for p in candidates["chrome"]:
        if os.path.exists(p):
            return p
    return None


def _find_browser_win(hint: str = "chrome") -> str | None:
    """Return path to preferred browser on Windows, or None if not found."""
    hint = hint.lower()
    candidates = {
        "chrome": [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "edge": [
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "firefox": [
            os.path.expandvars(r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe"),
        ],
    }
    for key, paths in candidates.items():
        if hint in key or key in hint:
            for p in paths:
                if os.path.exists(p):
                    return p
    for p in candidates["chrome"]:
        if os.path.exists(p):
            return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core URL opener
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Convert spoken/typed domains into a clean URL."""
    raw = (url or "").strip().strip("., ")
    if not raw:
        return ""

    # Direct URLs can contain case-sensitive paths/query params, especially
    # YouTube video IDs. Never run them through the lowercasing voice normalizer.
    if re.match(r"^https?://", raw, flags=re.IGNORECASE):
        return raw
    if " " not in raw and re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9.-]+(?::\d+)?(?:/\S*)?$", raw):
        return "https://" + raw.lstrip("/")

    url = _normalize_user_command(raw).strip("., ")
    url = re.sub(r"^(open|kholo|launch|go to|visit)\s+", "", url, flags=re.IGNORECASE).strip()
    url = re.sub(r"\s+(kholo|open karo|open kar|pe jao|par jao)$", "", url, flags=re.IGNORECASE).strip()
    url = re.sub(r"\s+dot\s+", ".", url, flags=re.IGNORECASE)
    url = re.sub(r"\s+", "", url)
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    return url


_SEARCH_PATTERNS = [
    re.compile(
        rf"^(?:open|kholo|launch|visit|go\s+to)?\s*(?P<site>{SITE_NAME_PATTERN})\s+"
        r"(?:and|aur|then|phir)?\s*"
        r"(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s+"
        r"(?P<query>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s*(?:karo|kar|kar\s*do|kardo|do|for)?\s+"
        r"(?P<query>.+?)\s+"
        rf"(?:on|par|pe|mein|me)\s+(?P<site>{SITE_NAME_PATTERN})$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<query>.+?)\s+"
        r"(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s*(?:karo|kar|kar\s*do|kardo|do)?\s+"
        rf"(?:on|par|pe|mein|me)\s+(?P<site>{SITE_NAME_PATTERN})$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<site>[a-z.]+(?:\s[a-z]+)?)\s+"
        r"(?:par|pe|mein|me|on|ko)\s+"
        r"(?P<query>.+?)\s*"
        r"(?:search\s*(?:karo|kar|kar\s*do|kardo|do)?|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo|find\s*(?:karo|kar)?)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^search\s*(?:karo|kar|kar\s*do|kardo|do)?\s+"
        r"(?P<query>.+?)\s+"
        r"(?:on|par|pe|mein|me)\s+"
        r"(?P<site>[a-z.]+(?:\s[a-z]+)?)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<site>google(?:\.com)?|youtube|yt|amazon|github|reddit|"
        r"linkedin|linkedln|linked\s*in|twitter|x\.com|instagram|insta|"
        r"leetcode|leet\s*code|hackerrank|hacker\s*rank|chatgpt|chat\s*gpt)\s+"
        r"(?P<query>.+)$",
        re.IGNORECASE,
    ),
]

_QUERY_TAIL_STRIP_RE = re.compile(
    r"\s*\b(?:search|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo|find|karo|kar|kar\s*do|kardo|do|please|pls|batao|bata)\b\s*$",
    flags=re.IGNORECASE,
)


def _clean_search_query(text: str) -> str:
    query = " ".join((text or "").strip().split())
    query = re.sub(r"^(?:open|kholo|launch|visit|go\s+to)\s+", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(
        r"^(?:and|aur|then|phir)?\s*(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s+(?:karo|kar|kar\s*do|kardo|for)?\s*",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    query = re.sub(r"^(?:on|par|pe|mein|me|for)\s+", "", query, flags=re.IGNORECASE).strip()
    while True:
        cleaned = _QUERY_TAIL_STRIP_RE.sub("", query).strip()
        if cleaned == query:
            break
        query = cleaned
    return query.strip(".,!? ")


def _normalize_site_key(site: str) -> str:
    key = " ".join((site or "").lower().strip().split())
    for pattern, repl in SITE_ALIAS_NORMALIZATIONS:
        key = pattern.sub(repl, key)
    if key.endswith(".com") and key not in SITE_HOME_URLS:
        bare = key[:-4]
        if bare in SITE_HOME_URLS:
            return bare
    return key


def _resolve_site_url(normalized_text: str) -> str | None:
    text = normalized_text.strip().lower()

    for site in sorted(SITE_HOME_URLS, key=len, reverse=True):
        if text == site.lower():
            return SITE_HOME_URLS[site]

    for pattern in _SEARCH_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue

        site_raw = _normalize_site_key(match.group("site"))
        query_raw = match.group("query").strip()
        query_clean = _clean_search_query(query_raw)
        if not query_clean:
            continue

        matched_site = None
        for site_key in sorted(SITE_HOME_URLS, key=len, reverse=True):
            if site_raw == site_key or site_raw.startswith(site_key) or site_key.startswith(site_raw):
                matched_site = site_key
                break

        if not matched_site:
            continue

        search_template = SITE_SEARCH_URLS.get(matched_site, "")
        if "{query}" in search_template:
            encoded = urllib.parse.quote_plus(query_clean)
            url = search_template.format(query=encoded)
            logger.debug("[resolve] %r -> %r on %s -> %s", text, query_clean, matched_site, url)
            return url
        return SITE_HOME_URLS[matched_site]

    if _looks_like_url(text):
        return _normalize_url(text)

    return None


def _site_search_or_home_url(name: str) -> str | None:
    text = _normalize_user_command(name)
    text = re.sub(
        r"^(?:open|kholo|launch|go\s+to|visit|chalo|jao)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        r"\s+(?:kholo|open\s*karo|open\s*kar|pe\s*jao|par\s*jao|chalo|jao)$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return _resolve_site_url(text)

def _open_with_default_browser(url: str) -> str:
    if IS_MAC:
        try:
            result = subprocess.run(["open", url], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return f"✅ Default browser mein khula: {url}"
            logger.warning("[browser] macOS open failed: %s", result.stderr.strip())
        except Exception as e:
            logger.warning("[browser] macOS open exception: %s", e)
        for browser_hint in ("chrome", "safari", "brave", "firefox"):
            try:
                if browser_hint == "safari":
                    script = f'tell application "Safari" to open location "{url}"\ntell application "Safari" to activate'
                    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return f"✅ Safari mein khula: {url}"
                    continue
                browser_bin = _find_browser_mac(browser_hint)
                if browser_bin:
                    subprocess.Popen([browser_bin, url])
                    return f"✅ {os.path.basename(browser_bin)} mein khula: {url}"
            except Exception as e:
                logger.warning("[browser] fallback %s failed: %s", browser_hint, e)
        return f"❌ Browser open nahi hua: {url}"
    elif IS_WINDOWS:
        subprocess.Popen(["cmd", "/c", "start", "", url])
        return f"✅ Default browser mein khula: {url}"
    else:
        subprocess.Popen(["xdg-open", url])
        return f"✅ Default browser mein khula: {url}"
    return f"✅ Default browser mein khula: {url}"

def _open_url(url: str, browser_hint: str = "default", new_window: bool = False) -> str:
    url = _normalize_url(url)
    if not url:
        return "❌ URL empty hai."
    # Security: strip characters that could escape or break out of an AppleScript string literal.
    # AppleScript strings are delimited by double-quotes; backslash is not an escape character.
    # A raw " or \ in the URL would terminate or corrupt the script — strip them.
    url = url.replace('"', "%22").replace("\\", "%5C")

    hint = browser_hint.lower().strip()
    if hint in {"", "default", "system", "browser", "default browser"}:
        return _open_with_default_browser(url)

    if IS_MAC:
        if "safari" in hint:
            try:
                script = (
                    f'tell application "Safari" to open location "{url}"\n'
                    f'tell application "Safari" to activate'
                )
                subprocess.Popen(["osascript", "-e", script])
                return f"✅ Safari mein khula: {url}"
            except Exception as e:
                logger.warning(f"Safari AppleScript failed: {e}")

        if "firefox" in hint:
            try:
                script = (
                    f'tell application "Firefox" to open location "{url}"\n'
                    f'tell application "Firefox" to activate'
                )
                subprocess.Popen(["osascript", "-e", script])
                return f"✅ Firefox mein khula: {url}"
            except Exception as e:
                logger.warning(f"Firefox AppleScript failed: {e}")

        browser_bin = _find_browser_mac(hint)
        if browser_bin:
            cmd = [browser_bin, url]
            if new_window:
                cmd.insert(1, "--new-window")
            subprocess.Popen(cmd)
            browser_name = os.path.basename(browser_bin).replace(" ", "")
            return f"✅ {browser_name} mein khula: {url}"

        return _open_with_default_browser(url)

    elif IS_WINDOWS:
        browser_bin = _find_browser_win(hint)
        if browser_bin:
            cmd = [browser_bin, url]
            if new_window:
                cmd.insert(1, "--new-window")
            subprocess.Popen(cmd)
            return f"✅ Browser mein khula: {url}"

        return _open_with_default_browser(url)

    else:
        subprocess.Popen(["xdg-open", url])
        return f"✅ Browser mein khula: {url}"


# ─────────────────────────────────────────────────────────────────────────────
# YouTube: get direct video URL via yt-dlp
# ─────────────────────────────────────────────────────────────────────────────

_YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
_YT_URL_ID_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})")
_YT_PLATFORM_RE = re.compile(r"\b(?:youtube|yt|spotify|gaana|jiosaavn|saavn)\b", flags=re.IGNORECASE)
_YT_INTENT_RE = re.compile(
    r"\b(?:"
    r"play(?:ing|karo|kar|kardo|do)?|"
    r"chala(?:o|do|na|kar|karo)?|"
    r"sun(?:ao|a|na|ne)?|"
    r"open|launch|kholo|"
    r"baja(?:o|na|kar|kardo)?|"
    r"laga(?:o|na|do)?|lagao|"
    r"karo|kar|kardo|karde|do|"
    r"search|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo|"
    r"on|par|pe|mein|me|ko|ka|ki|ke|"
    r"and|aur|please|pls|zara"
    r")\b",
    flags=re.IGNORECASE,
)
_HINGLISH_MAP = {
    r"aa+": "a",
    r"ii+": "i",
    r"uu+": "u",
    r"ee(?=\b|[^a-z])": "i",
    r"oo(?=\b|[^a-z])": "u",
    r"kh": "k",
    r"gh": "g",
    r"ch": "c",
    r"jh": "j",
    r"th": "t",
    r"dh": "d",
    r"ph": "f",
    r"bh": "b",
    r"w": "v",
    r"q": "k",
    r"(?<=[a-z])a\b": "",
}


def _extract_video_id(entry: dict) -> str | None:
    raw_id = str(entry.get("id") or "")
    if _YT_ID_RE.match(raw_id):
        return raw_id
    for field in ("id", "url", "webpage_url", "original_url"):
        val = str(entry.get(field) or "")
        match = _YT_URL_ID_RE.search(val)
        if match:
            return match.group(1)
    return None


def _strip_yt_intent(raw: str) -> str:
    q = _normalize_user_command(raw)
    q = _YT_PLATFORM_RE.sub(" ", q)
    q = _YT_INTENT_RE.sub(" ", q)
    q = re.sub(r"\s{2,}", " ", q).strip()
    return q.strip(".,!? ") or _normalize_user_command(raw)


def _strip_youtube_intent(raw: str) -> str:
    return _strip_yt_intent(raw)


def _build_yt_search_query(raw: str) -> str:
    stripped = _strip_yt_intent(raw)
    music_words = {
        "song", "songs", "music", "album", "track", "official",
        "audio", "video", "lyrics", "cover", "mix", "remix",
    }
    if not (set(stripped.lower().split()) & music_words):
        stripped = f"{stripped} song"
    return stripped


def _build_youtube_search_query(raw: str) -> str:
    return _build_yt_search_query(raw)


def _hinglish_normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "").lower())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    for pattern, repl in _HINGLISH_MAP.items():
        normalized = re.sub(pattern, repl, normalized)
    return normalized


def _soundex(word: str) -> str:
    if not word:
        return ""
    word = word.upper()
    mapping = {
        "B": "1", "F": "1", "P": "1", "V": "1",
        "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
        "D": "3", "T": "3",
        "L": "4",
        "M": "5", "N": "5",
        "R": "6",
    }
    first = word[0]
    coded = first
    prev = mapping.get(first, "0")
    for ch in word[1:]:
        code = mapping.get(ch, "0")
        if code != "0" and code != prev:
            coded += code
        prev = code
    return (coded + "0000")[:4]


def _token_soundex_set(text: str) -> set[str]:
    return {_soundex(w) for w in re.findall(r"[a-zA-Z]+", text) if len(w) >= 2}


def _score_title_match(title: str, query: str) -> float:
    title_l = (title or "").strip().lower()
    query_l = (query or "").strip().lower()
    query_for_score = re.sub(r"\bsong\b", "", query_l).strip()
    if query_for_score and query_for_score in title_l:
        return 1.0

    title_norm = _hinglish_normalize(title_l)
    query_norm = _hinglish_normalize(query_for_score)
    if query_norm and query_norm in title_norm:
        return 0.95
    if query_norm and query_norm in title_norm.replace(" ", ""):
        return 0.90

    query_sx = _token_soundex_set(query_norm)
    title_sx = _token_soundex_set(title_norm)
    if query_sx and title_sx:
        overlap = len(query_sx & title_sx) / len(query_sx)
        if overlap >= 0.6:
            return 0.50 + overlap * 0.40

    q_tokens = re.findall(r"[a-z]+", query_norm)
    t_tokens = re.findall(r"[a-z]+", title_norm)
    if q_tokens and t_tokens:
        scores = []
        for qt in q_tokens:
            if len(qt) < 3:
                continue
            scores.append(max((SequenceMatcher(None, qt, tt).ratio() for tt in t_tokens), default=0.0))
        if scores:
            avg = sum(scores) / len(scores)
            if avg >= 0.55:
                return 0.30 + avg * 0.40

    qw = set(re.findall(r"[a-z0-9]+", query_l)) - {"song", "songs", "music"}
    tw = set(re.findall(r"[a-z0-9]+", title_l))
    if qw:
        return (len(qw & tw) / len(qw)) * 0.50
    return 0.0


def _is_short_or_live(entry: dict) -> bool:
    duration = entry.get("duration") or 0
    is_live = bool(entry.get("is_live") or entry.get("was_live"))
    url = entry.get("url") or entry.get("webpage_url") or ""
    is_short = (0 < duration <= 62) or "/shorts/" in url
    return is_live or is_short


def get_youtube_url(
    raw_user_query: str,
    skip_ids: set[str] | None = None,
    allow_shorts: bool = False,
    max_results: int = 5,
) -> str | None:
    """
    Resolve a raw voice command to the best matching YouTube watch URL using yt-dlp.
    """
    ytdlp_bin = shutil.which("yt-dlp")
    if not ytdlp_bin:
        for candidate in (
            "/opt/homebrew/bin/yt-dlp",
            "/usr/local/bin/yt-dlp",
            os.path.expanduser("~/Library/Python/3.11/bin/yt-dlp"),
            os.path.expanduser("~/Library/Python/3.12/bin/yt-dlp"),
            os.path.expanduser("~/Library/Python/3.13/bin/yt-dlp"),
            os.path.expanduser("~/Library/Python/3.14/bin/yt-dlp"),
        ):
            if os.path.exists(candidate):
                ytdlp_bin = candidate
                break
    ytdlp_bin = ytdlp_bin or "yt-dlp"
    timeout = float(os.getenv("VANI_YOUTUBE_YTDLP_TIMEOUT", "30"))
    skip_ids = {v for v in (skip_ids or set()) if v}
    env_max_results = os.getenv("VANI_YOUTUBE_YTDLP_RESULTS")
    if env_max_results:
        max_results = int(env_max_results)
    search_query = _build_yt_search_query(raw_user_query)

    logger.info("[youtube] raw=%r -> search=%r", raw_user_query, search_query)

    try:
        result = subprocess.run(
            [
                ytdlp_bin,
                "--no-warnings",
                "--flat-playlist",
                "--dump-json",
                "--playlist-items",
                f"1:{max_results}",
                f"ytsearch{max_results}:{search_query}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        logger.error("[youtube] yt-dlp not found; install it with pip install yt-dlp")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("[youtube] yt-dlp timed out")
        return None
    except Exception as e:
        logger.warning("[youtube] yt-dlp subprocess error for %r: %s", raw_user_query, e)
        return None

    if result.returncode != 0 or not result.stdout.strip():
        logger.warning("[youtube] yt-dlp search failed rc=%s stderr=%s", result.returncode, result.stderr.strip()[-220:])
        return None

    candidates: list[tuple[float, str, str]] = []
    stripped_query = _strip_yt_intent(raw_user_query)
    for line in result.stdout.strip().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        video_id = _extract_video_id(entry)
        if not video_id or video_id in skip_ids:
            continue
        allow_entry_shorts = allow_shorts or os.getenv("VANI_YOUTUBE_ALLOW_SHORTS", "0") == "1"
        if not allow_entry_shorts and _is_short_or_live(entry):
            continue
        title = entry.get("title") or ""
        score = _score_title_match(title, stripped_query)
        candidates.append((score, video_id, title))
        logger.debug("[youtube] candidate %.3f %s %s", score, video_id, title)

    if not candidates:
        logger.warning("[youtube] no yt-dlp candidates for %r", search_query)
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    score, video_id, title = candidates[0]
    logger.info("[youtube] yt-dlp winner %.3f %s %s", score, video_id, title)
    return f"https://www.youtube.com/watch?v={video_id}"


def _get_youtube_direct_url(query: str, skip_ids: set[str] | None = None) -> str | None:
    return get_youtube_url(query, skip_ids=skip_ids, max_results=8)


_youtube_play_jobs: list[threading.Thread] = []


def _reap_youtube_play_jobs() -> None:
    global _youtube_play_jobs
    _youtube_play_jobs = [job for job in _youtube_play_jobs if job.is_alive()]


def _youtube_search_url(song_or_query: str) -> str:
    search_query = _build_yt_search_query(song_or_query)
    encoded = urllib.parse.quote_plus(search_query)
    return f"https://www.youtube.com/results?search_query={encoded}"


def _yt_force_play_mac(delay: float = 3.5) -> None:
    """
    After YouTube opens, inject JS to call video.play() and unmute.
    Retries multiple times so page load timing doesn't matter.
    Works for Chrome, Brave, Edge, Safari on macOS.
    """
    import time as _time

    # JS: retry until video element exists and is ready to play
    js = (
        "(function(){"
        "var attempt=0;"
        "function tryPlay(){"
        "  var v=document.querySelector('video');"
        "  if(v&&v.readyState>=2){v.muted=false;v.volume=1;v.play();return;}"
        "  if(attempt++<8){setTimeout(tryPlay,1000);}"
        "}"
        "tryPlay();"
        "})();"
    )

    browser_scripts = {
        "Google Chrome": f'tell application "Google Chrome" to execute active tab of front window javascript "{js}"',
        "Brave Browser": f'tell application "Brave Browser" to execute active tab of front window javascript "{js}"',
        "Microsoft Edge": f'tell application "Microsoft Edge" to execute active tab of front window javascript "{js}"',
        "Safari":         f'tell application "Safari" to do JavaScript "{js}" in current tab of front window',
    }

    _time.sleep(delay)

    from vani.reasoning.shared import _osascript, _frontmost_app_name
    front = _frontmost_app_name()
    script = browser_scripts.get(front)
    if script:
        _osascript(script, timeout=5)
        return

    # Fallback: try Chrome then Brave regardless of frontmost
    for app, scr in browser_scripts.items():
        if "Safari" in app:
            continue
        result = _osascript(scr, timeout=3)
        if result is not None:
            break


def _yt_force_play_win(delay: float = 4.0) -> None:
    """Windows fallback: press Space after YouTube loads to start playback. Retries 3 times."""
    import time as _time
    _time.sleep(delay)
    for _ in range(3):
        try:
            import pyautogui
            pyautogui.click()  # focus window first
            _time.sleep(0.3)
            pyautogui.press("space")
            return
        except Exception:
            pass
        try:
            from pynput.keyboard import Controller as KB, Key
            kb = KB()
            kb.press(Key.space)
            kb.release(Key.space)
            return
        except Exception:
            pass
        _time.sleep(1.5)


def _resolve_and_open_youtube(song_or_query: str, browser: str = "chrome") -> None:
    direct_url = get_youtube_url(song_or_query)
    if direct_url:
        # Append autoplay=1 — helps when browser autoplay policy is relaxed
        sep = "&" if "?" in direct_url else "?"
        play_url = f"{direct_url}{sep}autoplay=1"
        _open_url(play_url, browser_hint=browser)
        # Also JS-inject video.play() after page loads, as autoplay=1 alone
        # is blocked by Chrome's autoplay-with-sound policy
        if IS_MAC:
            threading.Thread(target=_yt_force_play_mac, daemon=True).start()
        elif IS_WINDOWS:
            threading.Thread(target=_yt_force_play_win, daemon=True).start()
        return
    _open_url(_youtube_search_url(song_or_query), browser_hint=browser)


def start_youtube_play_background(song_or_query: str, browser: str = "chrome") -> str:
    """
    Start yt-dlp resolution in a daemon thread and return immediately.
    The thread opens the direct watch URL when found; otherwise it opens search.
    """
    _reap_youtube_play_jobs()
    display_name = _strip_yt_intent(song_or_query)
    job = threading.Thread(
        target=_resolve_and_open_youtube,
        args=(song_or_query, browser),
        daemon=True,
        name=f"vani-youtube-play-{len(_youtube_play_jobs) + 1}",
    )
    job.start()
    _youtube_play_jobs.append(job)
    return f"⏳ '{display_name}' YouTube par dhoondh rahi hoon — abhi browser mein khul raha hai, kuch seconds mein play hoga."


# ─────────────────────────────────────────────────────────────────────────────
# LangChain Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def open_youtube_and_play(song_or_query: str, browser: str = "chrome") -> str:
    """
    Opens a browser and plays the requested song/video on YouTube.
    This is the PRIMARY tool for all YouTube playback requests.

    Strategy:
      1. Start yt-dlp search in the background so Vani replies immediately
      2. Open the direct watch URL when found
      3. Fallback → open YouTube search results page if direct resolution fails

    Works on Mac (Chrome/Safari/Firefox) and Windows (Chrome/Edge/Firefox).
    Install yt-dlp for best results: pip install yt-dlp

    Example voice commands:
    - "YouTube par Zulfiqar play karo"
    - "Chrome mein YouTube kholo aur Arijit Singh chalao"
    - "Safari mein Lo-fi music laga do YouTube par"
    - "Play Sidhu Moosewala on YouTube"
    - "YouTube open karo aur Dildarian chalao"

    Args:
        song_or_query : song name, artist, or any YouTube search query
        browser       : chrome / safari / firefox / edge / default
    """
    return start_youtube_play_background(song_or_query, browser=browser)


@tool
async def open_url_in_browser(url: str, browser: str = "default") -> str:
    """
    Opens any website or URL in the specified browser.
    Works on Mac and Windows both.

    Args:
        url     : full URL or domain (https:// auto-added if missing)
        browser : chrome / safari / firefox / edge / default
    """
    return _open_url(url, browser_hint=browser)


@tool
async def open_whatsapp(mode: str = "web") -> str:
    """
    Opens WhatsApp Web by default.

    Args:
        mode : 'web' (default) or 'app' (try desktop first)
    """
    mode = mode.lower().strip()

    if "web" not in mode:
        if IS_MAC:
            try:
                result = subprocess.run(
                    ["osascript", "-e", 'tell application "WhatsApp" to activate'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return "✅ WhatsApp desktop khul gaya (Mac) ✓"
            except Exception:
                pass

        elif IS_WINDOWS:
            try:
                subprocess.Popen("start whatsapp:", shell=True)
                return "✅ WhatsApp khul gaya (Windows) ✓"
            except Exception:
                wa_paths = [
                    os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe"),
                    os.path.expandvars(r"%PROGRAMFILES%\WindowsApps\WhatsApp.exe"),
                ]
                for p in wa_paths:
                    if os.path.exists(p):
                        subprocess.Popen([p])
                        return "✅ WhatsApp khul gaya (Windows) ✓"

    result = _open_url("https://web.whatsapp.com", browser_hint="chrome")
    return f"✅ WhatsApp Web khul gaya browser mein. {result}"


@tool
async def open_telegram(mode: str = "app") -> str:
    """
    Opens Telegram — tries desktop app first, falls back to Telegram Web.

    Args:
        mode : 'app' or 'web'
    """
    mode = mode.lower().strip()

    if "web" not in mode:
        if IS_MAC:
            # Use the same robust app opener as generic app launch. It handles
            # normal /Applications installs, renamed apps, and Spotlight paths.
            try:
                from vani.tools.window_control import open_app
                result = await open_app.ainvoke({"app_title": "telegram"})
                if "✅" in str(result):
                    return str(result)
            except Exception:
                pass

            for cmd in (["open", "-a", "Telegram"], ["open", "/Applications/Telegram.app"]):
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return "✅ Telegram desktop khul gaya (Mac) ✓"
                except Exception:
                    pass

        elif IS_WINDOWS:
            tg_paths = [
                os.path.expandvars(r"%APPDATA%\Telegram Desktop\Telegram.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Telegram Desktop\Telegram.exe"),
            ]
            for p in tg_paths:
                if os.path.exists(p):
                    subprocess.Popen([p])
                    return "✅ Telegram khul gaya (Windows) ✓"

    result = _open_url("https://web.telegram.org", browser_hint="chrome")
    return f"✅ Telegram Web khul gaya. {result}"


@tool
async def open_app_smart(app_name: str, browser: str = "default") -> str:
    """
    Universal smart launcher — opens any app or website by voice.
    Works on Mac AND Windows.

    Args:
        app_name : any app name in Hindi/English/Hinglish
        browser  : preferred browser for web apps
    """
    name = _normalize_user_command(app_name)
    name = re.sub(r"^(open|kholo|launch|go to|visit)\s+", "", name).strip()
    name = re.sub(r"\s+(kholo|open karo|open kar|launch karo)$", "", name).strip()

    if _looks_like_url(name):
        return _open_url(name, browser_hint="default")

    if name in DESKTOP_APP_ALIASES:
        try:
            from vani.tools.window_control import open_app
            return await open_app.ainvoke({"app_title": DESKTOP_APP_ALIASES[name]})
        except Exception as e:
            return f"⚠️ '{app_name}' open karne mein dikkat aayi: {e}"

    site_url = _site_search_or_home_url(name)
    if site_url:
        return _open_url(site_url, browser_hint=browser)

    for key, url in WEB_APPS.items():
        if key in name:
            return _open_url(url, browser_hint=browser)

    if "whatsapp" in name:
        return await open_whatsapp.ainvoke({"mode": "web"})

    if "telegram" in name:
        return await open_telegram.ainvoke({"mode": "app"})

    try:
        from vani.tools.window_control import open_app
        return await open_app.ainvoke({"app_title": app_name})
    except Exception as e:
        return f"⚠️ '{app_name}' open karne mein dikkat aayi: {e}"


def _looks_like_url(text: str) -> bool:
    text = (text or "").strip().lower()
    text = re.sub(r"^(open|kholo|launch|go to|visit)\s+", "", text).strip()
    text = re.sub(r"\s+(kholo|open karo|open kar|pe jao|par jao)$", "", text).strip()
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+", "", text)
    if text.startswith(("http://", "https://")):
        return True
    return bool(re.search(r"^[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+(?::\d+)?(?:/\S*)?$", text))