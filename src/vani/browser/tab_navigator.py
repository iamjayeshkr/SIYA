"""
vani/browser/tab_navigator.py  —  v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Semantic tab navigation: switch to / close tabs by name.

DESIGN
──────
• Reads live tab titles once per command via AppleScript (Mac) or
  Chrome DevTools Protocol (Windows/Linux), then caches for TTL seconds.
• Matching pipeline (weighted, first hit wins):
    1. Exact title match              score = 1.00
    2. Normalised substring           score = 0.90
    3. Known-site alias expansion     score = 0.85
    4. Token-overlap ratio            score = variable
    5. SequenceMatcher difflib ratio  score = variable
  Threshold: MATCH_THRESHOLD (0.40) — tweak if too aggressive/loose.
• Three public async functions:
    switch_to_tab_by_name(query)            → str (result message)
    close_tab_by_name(query)                → str
    close_all_tabs_by_name(query)           → str

PERFORMANCE
───────────
• _TabCache holds titles for TAB_CACHE_TTL seconds (default 3 s).
  Repeated AppleScript calls within the TTL are skipped entirely.
• Chrome AppleScript fetches all tabs in one osascript call (not per-tab).
• Windows path uses CDP via existing websocket if available; falls back
  to keyboard-only (Ctrl+Tab scan) — declared clearly in return message.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# ── Tuning knobs ──────────────────────────────────────────────────────────────
TAB_CACHE_TTL   = 1.5    # seconds before re-querying browser (was 3.0)
MATCH_THRESHOLD = 0.40   # minimum score to accept a match
MAX_TABS_SCAN   = 50     # safety cap for keyboard-scan fallback on Windows

# ── Well-known site aliases (query word → title fragment to prefer) ──────────
_SITE_ALIASES: dict[str, list[str]] = {
    "youtube":    ["youtube", "yt"],
    "yt":         ["youtube", "yt"],
    "claude":     ["claude", "anthropic"],
    "chatgpt":    ["chatgpt", "chat.openai", "openai"],
    "gpt":        ["chatgpt", "chat.openai", "openai"],
    "gmail":      ["gmail", "google mail", "mail.google"],
    "mail":       ["gmail", "mail", "outlook", "yahoo mail"],
    "github":     ["github"],
    "gh":         ["github"],
    "google":     ["google", "google.com"],
    "stackoverflow": ["stack overflow", "stackoverflow"],
    "so":         ["stack overflow", "stackoverflow"],
    "netflix":    ["netflix"],
    "spotify":    ["spotify"],
    "twitter":    ["twitter", "x.com", "x —"],
    "x":          ["twitter", "x.com"],
    "instagram":  ["instagram"],
    "insta":      ["instagram"],
    "reddit":     ["reddit"],
    "linkedin":   ["linkedin"],
    "amazon":     ["amazon"],
    "leetcode":   ["leetcode"],
    "notion":     ["notion"],
    "figma":      ["figma"],
    "whatsapp":   ["whatsapp"],
    "telegram":   ["telegram"],
    "meet":       ["google meet", "meet.google"],
    "zoom":       ["zoom"],
    "docs":       ["google docs", "docs.google"],
    "sheets":     ["google sheets", "sheets.google"],
    "slides":     ["google slides", "slides.google"],
    "drive":      ["google drive", "drive.google"],
    "calendar":   ["google calendar", "calendar.google"],
    "maps":       ["google maps", "maps.google"],
    "medium":     ["medium"],
    "vercel":     ["vercel"],
    "heroku":     ["heroku"],
    "jira":       ["jira"],
    "confluence": ["confluence"],
    "trello":     ["trello"],
    "slack":      ["slack"],
    "discord":    ["discord"],
}


# ── Tab metadata ──────────────────────────────────────────────────────────────
@dataclass
class TabInfo:
    index:     int          # 1-based position within the window
    window:    int          # window index (1-based, Mac only)
    title:     str          # raw title string
    url:       str          # full URL
    browser:   str          # "Google Chrome" / "Brave Browser" / "Safari" etc.
    norm:      str = field(init=False)   # lowercased, no punctuation

    def __post_init__(self) -> None:
        self.norm = _normalise(self.title + " " + self.url)


# ── Simple time-based cache ───────────────────────────────────────────────────
class _TabCache:
    def __init__(self) -> None:
        self._tabs:      list[TabInfo] = []
        self._timestamp: float        = 0.0
        self._lock                    = asyncio.Lock()

    async def get(self) -> list[TabInfo]:
        async with self._lock:
            if time.monotonic() - self._timestamp < TAB_CACHE_TTL and self._tabs:
                return self._tabs
            self._tabs     = await _fetch_all_tabs()
            self._timestamp = time.monotonic()
            return self._tabs

    def invalidate(self) -> None:
        self._timestamp = 0.0


_cache = _TabCache()


# ── Text helpers ──────────────────────────────────────────────────────────────
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

def _normalise(text: str) -> str:
    """Lowercase, strip accents, collapse punctuation to spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode()
    text = _PUNCT_RE.sub(" ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return set(t for t in _normalise(text).split() if len(t) > 1)


def _score(query_norm: str, tab: TabInfo) -> float:
    """
    Return a [0, 1] match score between normalised query string and a TabInfo.
    Higher = better match.
    """
    q = query_norm
    t = tab.norm

    # 1. Exact title match
    if q == _normalise(tab.title):
        return 1.0

    # 2. Normalised substring — query fully inside title
    if q and q in t:
        return 0.90

    # 3. Known-site alias expansion
    for alias_key, fragments in _SITE_ALIASES.items():
        if alias_key in q.split():
            for frag in fragments:
                if frag in t:
                    return 0.85

    # 4. Token overlap (Jaccard-like)
    q_tok = _tokens(q)
    t_tok = _tokens(t)
    if q_tok and t_tok:
        overlap = len(q_tok & t_tok) / len(q_tok | t_tok)
        if overlap >= MATCH_THRESHOLD:
            return overlap * 0.80   # scale to leave room above alias

    # 5. SequenceMatcher on full normalised strings
    ratio = SequenceMatcher(None, q, t[:200]).ratio()
    return ratio * 0.70


def _best_match(query: str, tabs: list[TabInfo]) -> Optional[TabInfo]:
    """Return the single best-matching tab, or None if below threshold."""
    q = _normalise(query)
    scored = [(tab, _score(q, tab)) for tab in tabs]
    scored.sort(key=lambda x: x[1], reverse=True)
    if scored and scored[0][1] >= MATCH_THRESHOLD:
        return scored[0][0]
    return None


def _all_matches(query: str, tabs: list[TabInfo]) -> list[TabInfo]:
    """Return ALL tabs above threshold, sorted best-first."""
    q = _normalise(query)
    scored = [(tab, _score(q, tab)) for tab in tabs]
    return [tab for tab, s in sorted(scored, key=lambda x: x[1], reverse=True)
            if s >= MATCH_THRESHOLD]


# ── AppleScript helpers (Mac) ─────────────────────────────────────────────────
_CHROMIUM_APPS = [
    "Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium",
]
_ALL_BROWSERS = _CHROMIUM_APPS + ["Safari", "Firefox"]


def _osa(script: str, timeout: float = 6.0) -> str:
    """Run an AppleScript and return stdout (empty on error)."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _running_browsers_mac() -> list[str]:
    """Return which of the known browsers are currently running — checked in parallel."""
    import concurrent.futures

    def _is_running(app: str) -> tuple[str, bool]:
        out = _osa(
            f'tell application "System Events" to '
            f'(name of processes) contains "{app}"'
        )
        return app, out.lower() == "true"

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_ALL_BROWSERS)) as pool:
        results = list(pool.map(_is_running, _ALL_BROWSERS))

    return [app for app, running in results if running]


def _fetch_tabs_chromium_mac(app: str) -> list[TabInfo]:
    """
    Fetch all tabs from a Chromium-family browser in ONE AppleScript call.
    Returns list of TabInfo objects.
    """
    script = f"""
tell application "{app}"
    set out to ""
    set wi to 0
    repeat with w in windows
        set wi to wi + 1
        set ti to 0
        repeat with t in tabs of w
            set ti to ti + 1
            set out to out & wi & "|||" & ti & "|||" & (title of t) & "|||" & (URL of t) & "~~~"
        end repeat
    end repeat
    return out
end tell
"""
    raw = _osa(script)
    tabs: list[TabInfo] = []
    for entry in raw.split("~~~"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|||")
        if len(parts) < 4:
            continue
        try:
            wi, ti, title, url = int(parts[0]), int(parts[1]), parts[2], parts[3]
            tabs.append(TabInfo(index=ti, window=wi, title=title, url=url, browser=app))
        except (ValueError, IndexError):
            continue
    return tabs


def _fetch_tabs_safari_mac() -> list[TabInfo]:
    script = """
tell application "Safari"
    set out to ""
    set wi to 0
    repeat with w in windows
        set wi to wi + 1
        set ti to 0
        try
            repeat with t in tabs of w
                set ti to ti + 1
                set out to out & wi & "|||" & ti & "|||" & (name of t) & "|||" & (URL of t) & "~~~"
            end repeat
        end try
    end repeat
    return out
end tell
"""
    raw = _osa(script)
    tabs: list[TabInfo] = []
    for entry in raw.split("~~~"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|||")
        if len(parts) < 4:
            continue
        try:
            wi, ti, title, url = int(parts[0]), int(parts[1]), parts[2], parts[3]
            tabs.append(TabInfo(index=ti, window=wi, title=title, url=url, browser="Safari"))
        except (ValueError, IndexError):
            continue
    return tabs


async def _fetch_all_tabs() -> list[TabInfo]:
    """Aggregate tab lists from all running browsers (async, thread-safe)."""
    if IS_MAC:
        return await asyncio.get_event_loop().run_in_executor(
            None, _fetch_all_tabs_mac_sync
        )
    elif IS_WINDOWS:
        return await _fetch_all_tabs_windows()
    return []


def _fetch_all_tabs_mac_sync() -> list[TabInfo]:
    """Fetch tabs from all running browsers IN PARALLEL using threads."""
    import concurrent.futures
    browsers = _running_browsers_mac()
    if not browsers:
        return []

    def _fetch_one(b: str) -> list[TabInfo]:
        if b == "Safari":
            return _fetch_tabs_safari_mac()
        elif b in _CHROMIUM_APPS:
            return _fetch_tabs_chromium_mac(b)
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(browsers)) as pool:
        results = pool.map(_fetch_one, browsers)

    tabs: list[TabInfo] = []
    for r in results:
        tabs.extend(r)
    return tabs


async def _fetch_all_tabs_windows() -> list[TabInfo]:
    """
    Windows: attempt CDP (port 9222), fall back to empty list.
    Chrome/Edge must be launched with --remote-debugging-port=9222 for CDP.
    """
    try:
        import json
        import urllib.request
        with urllib.request.urlopen("http://localhost:9222/json", timeout=1) as resp:
            data = json.loads(resp.read())
        tabs: list[TabInfo] = []
        for i, t in enumerate(data, 1):
            if t.get("type") == "page":
                tabs.append(TabInfo(
                    index=i, window=1,
                    title=t.get("title", ""),
                    url=t.get("url", ""),
                    browser="Chrome",
                ))
        return tabs
    except Exception:
        return []   # CDP not available; caller will report gracefully


# ── AppleScript actions (Mac) ─────────────────────────────────────────────────

def _activate_tab_mac(tab: TabInfo) -> bool:
    """Bring a specific tab to front (Chromium or Safari)."""
    if tab.browser == "Safari":
        script = f"""
tell application "Safari"
    set current tab of window {tab.window} to tab {tab.index} of window {tab.window}
    activate
end tell
"""
    else:
        script = f"""
tell application "{tab.browser}"
    set active tab index of window {tab.window} to {tab.index}
    set index of window {tab.window} to 1
    activate
end tell
"""
    return bool(_osa(script))


def _close_tab_mac(tab: TabInfo) -> bool:
    """Close a specific tab (Chromium or Safari)."""
    if tab.browser == "Safari":
        script = f"""
tell application "Safari"
    close tab {tab.index} of window {tab.window}
end tell
"""
    else:
        script = f"""
tell application "{tab.browser}"
    close tab {tab.index} of window {tab.window}
end tell
"""
    return bool(_osa(script))


# ── Windows actions (CDP or keyboard fallback) ────────────────────────────────

async def _activate_tab_windows(tab: TabInfo) -> bool:
    """Activate tab on Windows via CDP activate endpoint."""
    try:
        import json, urllib.request
        with urllib.request.urlopen("http://localhost:9222/json", timeout=1) as resp:
            pages = json.loads(resp.read())
        page = next(
            (p for p in pages if p.get("type") == "page" and
             p.get("title", "") == tab.title), None
        )
        if page and "id" in page:
            url = f"http://localhost:9222/json/activate/{page['id']}"
            urllib.request.urlopen(url, timeout=1)
            return True
    except Exception:
        pass
    return False


async def _close_tab_windows(tab: TabInfo) -> bool:
    """Close tab on Windows via CDP close endpoint."""
    try:
        import json, urllib.request
        with urllib.request.urlopen("http://localhost:9222/json", timeout=1) as resp:
            pages = json.loads(resp.read())
        page = next(
            (p for p in pages if p.get("type") == "page" and
             p.get("title", "") == tab.title), None
        )
        if page and "id" in page:
            url = f"http://localhost:9222/json/close/{page['id']}"
            urllib.request.urlopen(url, timeout=1)
            return True
    except Exception:
        pass
    return False


# ── Public async API ──────────────────────────────────────────────────────────

async def switch_to_tab_by_name(query: str) -> str:
    """
    Switch focus to the browser tab whose title best matches `query`.
    Returns a human-readable result string (English + Hinglish).
    """
    tabs = await _cache.get()
    if not tabs:
        return (
            "❌ Koi bhi browser tab nahi mila. "
            "Make sure Chrome/Safari/Edge chal raha ho."
        )

    best = _best_match(query, tabs)
    if best is None:
        candidates = sorted(
            [t.title for t in tabs], key=len
        )[:5]
        sample = " | ".join(f'"{c}"' for c in candidates)
        return (
            f"❌ '{query}' se koi tab match nahi hua.\n"
            f"Available tabs (sample): {sample}"
        )

    if IS_MAC:
        ok = await asyncio.get_event_loop().run_in_executor(
            None, _activate_tab_mac, best
        )
    elif IS_WINDOWS:
        ok = await _activate_tab_windows(best)
    else:
        ok = False

    if ok:
        _cache.invalidate()
        return f"✅ '{best.title[:60]}' tab pe switch ho gaya."
    return f"❌ Tab mila lekin switch nahi ho paya: '{best.title[:60]}'"


async def close_tab_by_name(query: str) -> str:
    """
    Close the single browser tab whose title best matches `query`.
    """
    tabs = await _cache.get()
    if not tabs:
        return "❌ Koi bhi browser tab nahi mila."

    best = _best_match(query, tabs)
    if best is None:
        return f"❌ '{query}' se koi tab match nahi hua."

    if IS_MAC:
        ok = await asyncio.get_event_loop().run_in_executor(
            None, _close_tab_mac, best
        )
    elif IS_WINDOWS:
        ok = await _close_tab_windows(best)
    else:
        ok = False

    if ok:
        _cache.invalidate()
        return f"✅ '{best.title[:60]}' tab close ho gaya."
    return f"❌ Tab mila lekin close nahi ho paya: '{best.title[:60]}'"


async def close_all_tabs_by_name(query: str) -> str:
    """
    Close ALL browser tabs whose titles match `query` (above threshold).
    Processes in reverse-index order so window indices stay valid.
    """
    tabs = await _cache.get()
    if not tabs:
        return "❌ Koi bhi browser tab nahi mila."

    matched = _all_matches(query, tabs)
    if not matched:
        return f"❌ '{query}' se koi tab match nahi hua."

    # Close in reverse order within each browser to preserve indices
    matched_sorted = sorted(
        matched,
        key=lambda t: (t.browser, t.window, -t.index),
    )

    closed, failed = 0, 0
    for tab in matched_sorted:
        if IS_MAC:
            ok = await asyncio.get_event_loop().run_in_executor(
                None, _close_tab_mac, tab
            )
        elif IS_WINDOWS:
            ok = await _close_tab_windows(tab)
        else:
            ok = False
        if ok:
            closed += 1
        else:
            failed += 1

    _cache.invalidate()

    if failed == 0:
        return f"✅ {closed} '{query}' tab{'s' if closed != 1 else ''} close ho gaye."
    return (
        f"⚠️ {closed} tabs close hue, {failed} tabs close nahi ho sake "
        f"(try karte raho ya manually close karo)."
    )


# ── Debug helper (call from REPL/test) ───────────────────────────────────────

async def debug_list_tabs() -> None:
    """Print all currently open tabs for debugging."""
    tabs = await _cache.get()
    if not tabs:
        print("No tabs found.")
        return
    print(f"{'#':>3}  {'Win':>3}  {'Browser':<20}  {'Title':<50}  URL")
    print("-" * 100)
    for t in tabs:
        print(f"{t.index:>3}  {t.window:>3}  {t.browser:<20}  {t.title[:50]:<50}  {t.url[:60]}")