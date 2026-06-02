"""
vani_window_control.py — Fixed
Bugs fixed:
  1. YouTube, Instagram, WhatsApp Web etc. were missing — added URL-based opening
  2. open_app now uses 'open' command on Mac for URLs directly (no AppleScript needed)
  3. ClientResponse.json await bug fixed — _run_applescript is sync, kept sync
"""

import os
import sys
import subprocess
import logging
import asyncio
import re
try:
    from rapidfuzz import process
except ImportError:
    from fuzzywuzzy import process
from langchain.tools import tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


# ── App + URL mappings ────────────────────────────────────────────────────────
# Format: "keyword": ("Mac app/url", "Windows cmd/url")

APP_MAPPINGS = {
    # ── Browsers ──
    "chrome":           ("Google Chrome",           r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    "google chrome":    ("Google Chrome",           r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    "brave":            ("Brave Browser",           ""),
    "brave browser":    ("Brave Browser",           ""),
    "safari":           ("Safari",                  ""),
    "firefox":          ("Firefox",                 "firefox"),
    "edge":             ("Microsoft Edge",          ""),
    "microsoft edge":   ("Microsoft Edge",          ""),
    "browser":          ("Google Chrome",           r"C:\Program Files\Google\Chrome\Application\chrome.exe"),

    # ── Websites (open as URLs) ──
    "youtube":          ("__url__https://youtube.com",          "__url__https://youtube.com"),
    "youtube music":    ("__url__https://music.youtube.com",    "__url__https://music.youtube.com"),
    "instagram":        ("__url__https://instagram.com",        "__url__https://instagram.com"),
    "whatsapp web":     ("__url__https://web.whatsapp.com",     "__url__https://web.whatsapp.com"),
    "gmail":            ("__url__https://mail.google.com",      "__url__https://mail.google.com"),
    "google":           ("__url__https://google.com",           "__url__https://google.com"),
    "twitter":          ("__url__https://twitter.com",          "__url__https://twitter.com"),
    "x":                ("__url__https://x.com",                "__url__https://x.com"),
    "reddit":           ("__url__https://reddit.com",           "__url__https://reddit.com"),
    "netflix":          ("__url__https://netflix.com",          "__url__https://netflix.com"),
    "github":           ("__url__https://github.com",           "__url__https://github.com"),
    "chatgpt":          ("__url__https://chatgpt.com",          "__url__https://chatgpt.com"),
    "chat gpt":         ("__url__https://chatgpt.com",          "__url__https://chatgpt.com"),
    "leetcode":         ("__url__https://leetcode.com",         "__url__https://leetcode.com"),
    "leet code":        ("__url__https://leetcode.com",         "__url__https://leetcode.com"),
    "hackerrank":       ("__url__https://www.hackerrank.com",   "__url__https://www.hackerrank.com"),
    "hacker rank":      ("__url__https://www.hackerrank.com",   "__url__https://www.hackerrank.com"),
    "linkedin":         ("__url__https://www.linkedin.com",     "__url__https://www.linkedin.com"),
    "linkedln":         ("__url__https://www.linkedin.com",     "__url__https://www.linkedin.com"),
    "linked in":        ("__url__https://www.linkedin.com",     "__url__https://www.linkedin.com"),
    "insta":            ("__url__https://www.instagram.com",    "__url__https://www.instagram.com"),
    "web whatsapp":     ("__url__https://web.whatsapp.com",     "__url__https://web.whatsapp.com"),

    # ── Apps ──
    "notepad":          ("TextEdit",                "notepad"),
    "textedit":         ("TextEdit",                "notepad"),
    "calculator":       ("Calculator",              "calc"),
    "vlc":              ("VLC",                     r"C:\Program Files\VideoLAN\VLC\vlc.exe"),
    "vs code":          ("Visual Studio Code",      r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
    "vscode":           ("Visual Studio Code",      r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe"),
    "terminal":         ("Terminal",                "cmd"),
    "command prompt":   ("Terminal",                "cmd"),
    "cmd":              ("Terminal",                "cmd"),
    "finder":           ("Finder",                  "explorer"),
    "explorer":         ("Finder",                  "explorer"),
    "spotify":          ("Spotify",                 "spotify"),
    "slack":            ("Slack",                   "slack"),
    "whatsapp":         ("WhatsApp",                "whatsapp"),   # confirmed: /Applications/WhatsApp.app
    "zoom":             ("zoom.us",                 "zoom"),
    "settings":         ("System Settings",         "start ms-settings:"),
    "system settings":  ("System Settings",         "start ms-settings:"),
    "photos":           ("Photos",                  "ms-photos:"),
    "music":            ("Music",                   "wmplayer"),
    "apple music":      ("Music",                   "wmplayer"),
    "notes":            ("Notes",                   "notepad"),
    "calendar":         ("Calendar",                "outlookcal:"),
    "mail":             ("Mail",                    "mailto:"),
    "paint":            ("",                        "mspaint"),
    "postman":          ("Postman",                 r"C:\Users\%USERNAME%\AppData\Local\Postman\Postman.exe"),
    "figma":            ("Figma",                   "figma"),
    "notion":           ("Notion",                  "notion"),
    "discord":          ("Discord",                 "discord"),
    "telegram":         ("Telegram",               "telegram"),   # confirmed: /Applications/Telegram 2.app
    "preview":          ("Preview",                 ""),
    "xcode":            ("Xcode",                   ""),
}

MAC_BUNDLE_IDS = {
    "App Store": "com.apple.AppStore",
    "Calculator": "com.apple.calculator",
    "Calendar": "com.apple.iCal",
    "FaceTime": "com.apple.FaceTime",
    "Finder": "com.apple.finder",
    "Google Chrome": "com.google.Chrome",
    "Brave Browser": "com.brave.Browser",
    "Safari": "com.apple.Safari",
    "Firefox": "org.mozilla.firefox",
    "Microsoft Edge": "com.microsoft.edgemac",
    "Mail": "com.apple.mail",
    "Maps": "com.apple.Maps",
    "Music": "com.apple.Music",
    "Notes": "com.apple.Notes",
    "Photos": "com.apple.Photos",
    "Preview": "com.apple.Preview",
    "System Settings": "com.apple.systempreferences",
    "Terminal": "com.apple.Terminal",
    "TextEdit": "com.apple.TextEdit",
    "Visual Studio Code": "com.microsoft.VSCode",
}


def _resolve_app(raw: str):
    """Returns (mac_val, win_val) via fuzzy match."""
    raw = raw.lower().strip()
    raw = re.sub(r"^(open|kholo|launch|start)\s+", "", raw).strip()
    raw = re.sub(r"\s+(kholo|open karo|open kar|launch karo|start karo)$", "", raw).strip()
    if raw in APP_MAPPINGS:
        return APP_MAPPINGS[raw]
    keys = list(APP_MAPPINGS.keys())
    res = process.extractOne(raw, keys)
    if res:
        best, score = res[0], res[1]
        if score > 70:
            return APP_MAPPINGS[best]
    # Fallback: try opening as app name directly
    return (raw.title(), raw)


def _open_url_mac(url: str):
    """Open a URL in the default browser on Mac."""
    subprocess.Popen(["open", url])


def _open_url_windows(url: str):
    """Open a URL in the default browser on Windows."""
    subprocess.Popen(["start", url], shell=True)


def _run_applescript(script: str) -> str:
    """Synchronous AppleScript runner."""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    return result.stdout.strip()


# ── Open app ──────────────────────────────────────────────────────────────────

def _find_app_path_mac(app_name: str) -> str:
    """
    Find .app path using os.listdir — handles invisible Unicode prefix chars
    in folder names (e.g. \u200e LRM before WhatsApp.app).
    open -a and hardcoded paths both fail on these. listdir reads raw FS names.
    """
    import os as _os, glob as _glob
    search = re.sub(r"[^a-z0-9]+", "", app_name.lower())
    try:
        for folder in ["/Applications", "/System/Applications", _os.path.expanduser("~/Applications")]:
            if not _os.path.isdir(folder):
                continue
            for entry in _os.listdir(folder):
                normalized = re.sub(r"[^a-z0-9]+", "", entry.lower().replace(".app", ""))
                if entry.endswith(".app") and (search == normalized or search in normalized or normalized in search):
                    return f"{folder}/{entry}"
    except Exception:
        pass
    # glob fallback for ~/Applications
    for pattern in [
        f"{_os.path.expanduser('~')}/Applications/*{app_name}*.app",
    ]:
        hits = _glob.glob(pattern)
        if hits:
            return hits[0]
    return ""


def _verify_process_mac(app_name: str, wait: float = 0.8) -> bool:
    """
    Launch ke baad verify karta hai ki process actually chal rahi hai.
    Method 1: pgrep (fast)
    Method 2: osascript System Events process list (reliable)
    """
    import time
    time.sleep(wait)

    # Method 1: pgrep — process name se match
    search = re.sub(r"[^a-z0-9]+", "", app_name.lower().replace(".app", ""))
    try:
        r = subprocess.run(
            ["pgrep", "-fi", search],
            capture_output=True, text=True, timeout=3
        )
        if r.returncode == 0 and r.stdout.strip():
            logger.info(f"[APP] Process detected via pgrep: {app_name}")
            return True
    except Exception:
        pass

    # Method 2: osascript System Events
    try:
        script = 'tell application "System Events" to get name of every process'
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        procs = r.stdout.lower()
        compact_procs = re.sub(r"[^a-z0-9]+", "", procs)
        if search[:6] in compact_procs or app_name.lower().split()[0] in procs:
            logger.info(f"[APP] Process detected via System Events: {app_name}")
            return True
    except Exception:
        pass

    return False


def _launch_mac_with_fallback(app_name: str) -> tuple[bool, str]:
    """
    Mac app launch — 4-step fallback chain with process verification.
    Returns (success, message).
    """
    logger.info(f"[APP] Launch requested: {app_name}")

    bundle_id = MAC_BUNDLE_IDS.get(app_name)
    if bundle_id:
        cmd = ["open", "-b", bundle_id]
        logger.info(f"[APP] Launch command: {cmd}")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            if r.returncode == 0 and _verify_process_mac(app_name, wait=0.5):
                logger.info(f"[APP] Active: {app_name} (via bundle id)")
                return True, f"✅ {app_name} khul gaya."
        except Exception as e:
            logger.warning(f"[APP] bundle id open exception: {e}")

    # Attempt A: listdir-based path (immune to invisible Unicode prefix in folder names)
    listdir_path = _find_app_path_mac(app_name)
    if listdir_path:
        logger.info(f"[APP] Launch command: open {listdir_path!r} (listdir)")
        try:
            r = subprocess.run(["open", listdir_path], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                if _verify_process_mac(app_name):
                    logger.info(f"[APP] Active: {app_name} (via listdir path)")
                    return True, f"✅ {app_name} khul gaya."
            else:
                logger.info(f"[APP] listdir open failed (rc={r.returncode}): {r.stderr.strip()}")
        except Exception as e:
            logger.warning(f"[APP] listdir open exception: {e}")

    # Attempt B: open -a "<app_name>"
    cmd_a = ["open", "-a", app_name]
    logger.info(f"[APP] Launch command: {cmd_a}")
    try:
        r = subprocess.run(cmd_a, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            if _verify_process_mac(app_name):
                logger.info(f"[APP] Active: {app_name} (via open -a)")
                return True, f"✅ {app_name} khul gaya."
            logger.info(f"[APP] Launch command succeeded but process not detected — trying fallbacks")
        else:
            logger.info(f"[APP] open -a failed (rc={r.returncode}): {r.stderr.strip()}")
    except Exception as e:
        logger.warning(f"[APP] open -a exception: {e}")

    # Attempt C: standard app folders
    for folder in ["/Applications", "/System/Applications", os.path.expanduser("~/Applications")]:
        app_path = f"{folder}/{app_name}.app"
        logger.info(f"[APP] Launch command: open {app_path}")
        if os.path.exists(app_path):
            try:
                subprocess.Popen(["open", app_path])
                if _verify_process_mac(app_name):
                    logger.info(f"[APP] Active: {app_name} (via standard path)")
                    return True, f"✅ {app_name} khul gaya."
            except Exception as e:
                logger.warning(f"[APP] standard path failed: {e}")

    # Attempt C: mdfind — Spotlight se path dhundho
    logger.info(f"[APP] Launch command: mdfind kMDItemKind==Application {app_name}")
    try:
        r = subprocess.run(
            ["mdfind", f'kMDItemKind == "Application" && kMDItemDisplayName == "{app_name}*"'],
            capture_output=True, text=True, timeout=8
        )
        paths = [p.strip() for p in r.stdout.strip().splitlines() if p.strip().endswith(".app")]
        if paths:
            subprocess.Popen(["open", paths[0]])
            if _verify_process_mac(app_name, wait=1.2):
                logger.info(f"[APP] Active: {app_name} (via mdfind: {paths[0]})")
                return True, f"✅ {app_name} khul gaya."
    except Exception as e:
        logger.warning(f"[APP] mdfind failed: {e}")

    # Attempt D: open -a with fuzzy app name (title-case variations)
    for variant in [app_name.title(), app_name.upper(), app_name.lower()]:
        if variant == app_name:
            continue
        try:
            r = subprocess.run(["open", "-a", variant], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and _verify_process_mac(variant, wait=0.6):
                logger.info(f"[APP] Active: {variant} (variant match)")
                return True, f"✅ {variant} khul gaya."
        except Exception:
            pass

    # Attempt E: broader mdfind — partial name match (catches "WhatsApp Business", "Telegram 2" etc.)
    try:
        r = subprocess.run(
            ["mdfind", f'kMDItemKind == "Application" && kMDItemDisplayName == "*{app_name.split()[0]}*"'],
            capture_output=True, text=True, timeout=8
        )
        paths = [p.strip() for p in r.stdout.strip().splitlines() if p.strip().endswith(".app")]
        logger.info(f"[APP] mdfind broad search found: {paths[:3]}")
        for app_path in paths[:3]:
            try:
                subprocess.Popen(["open", app_path])
                found_name = os.path.basename(app_path).replace(".app", "")
                if _verify_process_mac(found_name, wait=1.5):
                    logger.info(f"[APP] Active: {found_name} (via broad mdfind: {app_path})")
                    return True, f"✅ {found_name} khul gaya."
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[APP] broad mdfind failed: {e}")

    logger.error(f"[APP] Launch failed: {app_name} — all attempts exhausted")
    return False, f"❌ {app_name} nahi khula. App installed hai? Ya naam thoda alag ho sakta hai."


@tool
async def open_app(app_title: str) -> str:
    """
    Opens a desktop app or website by name on Mac or Windows.

    Examples:
    - "YouTube kholo"
    - "Spotify open karo"
    - "Chrome launch karo"
    - "Gmail kholo"
    - "Netflix open karo"
    """
    mac_val, win_val = _resolve_app(app_title)

    try:
        if IS_MAC:
            if not mac_val:
                return f"❌ '{app_title}' Mac par available nahi hai."

            # URL-based opening — no verification needed (browser handles it)
            if mac_val.startswith("__url__"):
                url = mac_val.replace("__url__", "")
                logger.info(f"[APP] Launch requested: {app_title} → URL: {url}")
                _open_url_mac(url)
                logger.info(f"[APP] Active: browser opened {url}")
                return f"🌐 {app_title.title()} browser mein khul gaya."

            # App-based opening — with verification
            success, msg = _launch_mac_with_fallback(mac_val)
            return msg

        elif IS_WINDOWS:
            if not win_val:
                return f"❌ '{app_title}' Windows par available nahi hai."

            logger.info(f"[APP] Launch requested: {app_title}")

            if win_val.startswith("__url__"):
                url = win_val.replace("__url__", "")
                logger.info(f"[APP] Launch command: start {url}")
                _open_url_windows(url)
                return f"🌐 {app_title.title()} browser mein khul gaya."

            win_val = os.path.expandvars(win_val)
            logger.info(f"[APP] Launch command: {win_val}")

            if win_val.startswith("start "):
                subprocess.Popen(win_val, shell=True)
            elif win_val.endswith(".exe") and os.path.exists(win_val):
                subprocess.Popen([win_val])
            else:
                subprocess.Popen(win_val, shell=True)

            # Windows: brief wait then check tasklist
            import time; time.sleep(0.8)
            exe_name = os.path.basename(win_val).lower()
            try:
                r = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {exe_name}"],
                    capture_output=True, text=True, timeout=5
                )
                if exe_name in r.stdout.lower():
                    logger.info(f"[APP] Process detected (Windows): {exe_name}")
                    return f"✅ {app_title} khul gaya."
            except Exception:
                pass
            logger.info(f"[APP] Active: {app_title} (assumed — Windows)")
            return f"✅ {app_title} launch hua."

        else:
            return "❌ Unsupported OS."

    except Exception as e:
        logger.error(f"[APP] Launch failed: {app_title} — {e}")
        return f"❌ {app_title} open nahi ho paya: {e}"


# ── Open URL directly ──────────────────────────────────────────────────────────

@tool
async def open_url(url: str) -> str:
    """
    Directly opens any URL in the browser.

    Examples:
    - "https://youtube.com/watch?v=xxx open karo"
    - "Is URL pe jao: https://google.com"
    """
    try:
        if IS_MAC:
            subprocess.Popen(["open", url])
        elif IS_WINDOWS:
            subprocess.Popen(["start", url], shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
        return f"🌐 URL khul gaya: {url}"
    except Exception as e:
        return f"❌ URL open nahi hua: {e}"


# ── Close app ─────────────────────────────────────────────────────────────────

@tool
async def close_app(window_title: str) -> str:
    """
    Closes an open app by name on Mac or Windows.

    Examples:
    - "Chrome band karo"
    - "Spotify bund karo"
    """
    try:
        if IS_MAC:
            mac_val, _ = _resolve_app(window_title)
            if mac_val.startswith("__url__"):
                mac_val = "Google Chrome"   # close browser for URLs
            sanitized_val = "".join(c for c in mac_val if c.isalnum() or c in (" ", ".", "_", "-"))
            script = f'tell application "{sanitized_val}" to quit'
            _run_applescript(script)
            return f"✅ {mac_val} band ho gaya (Mac)."

        elif IS_WINDOWS:
            try:
                import win32gui, win32con
                def _close(hwnd, _):
                    if win32gui.IsWindowVisible(hwnd):
                        if window_title.lower() in win32gui.GetWindowText(hwnd).lower():
                            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                win32gui.EnumWindows(_close, None)
                return f"✅ '{window_title}' band ho gaya (Windows)."
            except ImportError:
                _, win_val = _resolve_app(window_title)
                exe = os.path.basename(win_val) if win_val else window_title
                subprocess.run(["taskkill", "/f", "/im", exe], capture_output=True)
                return f"✅ '{window_title}' process kill ho gaya."

    except Exception as e:
        return f"❌ Close nahi ho paya: {e}"


# ── File/folder indexing ───────────────────────────────────────────────────────

def _default_search_dirs():
    if IS_MAC:
        home = os.path.expanduser("~")
        return [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Movies"),
            os.path.join(home, "Music"),
        ]
    elif IS_WINDOWS:
        return ["D:/", "C:/Users/" + os.environ.get("USERNAME", "User")]
    return [os.path.expanduser("~")]


# FIX: bounded walk — max_depth=3, skip hidden, cache per base_dirs key
import time as _wctrl_time
_index_cache: dict = {}
_INDEX_TTL = 120.0  # seconds


async def _index_items(base_dirs):
    cache_key = tuple(sorted(base_dirs))
    entry = _index_cache.get(cache_key)
    if entry and (_wctrl_time.time() - entry["ts"]) < _INDEX_TTL:
        return entry["index"]

    item_index = []
    MAX_DEPTH = 3
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        base_depth = base_dir.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(base_dir):
            # Skip hidden dirs in-place — prevents descent
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            # Depth limit — prune dirs beyond max_depth
            current_depth = root.count(os.sep) - base_depth
            if current_depth >= MAX_DEPTH:
                dirs.clear()
            for d in dirs:
                item_index.append({"name": d, "path": os.path.join(root, d), "type": "folder"})
            for f in files:
                if not f.startswith('.'):
                    item_index.append({"name": f, "path": os.path.join(root, f), "type": "file"})

    _index_cache[cache_key] = {"index": item_index, "ts": _wctrl_time.time()}
    return item_index


async def _search_item(query, index, item_type):
    filtered = [i for i in index if i["type"] == item_type]
    choices = [i["name"] for i in filtered]
    if not choices:
        return None
    res = process.extractOne(query, choices)
    if res:
        best_match, score = res[0], res[1]
        if score > 70:
            for item in filtered:
                if item["name"] == best_match:
                    return item
    return None


def _open_path(path: str):
    if IS_MAC:
        subprocess.call(["open", path])
    elif IS_WINDOWS:
        os.startfile(path)
    else:
        subprocess.call(["xdg-open", path])


def _open_in_vscode_or_default(path: str):
    if IS_MAC:
        if _find_app_path_mac("Visual Studio Code") or os.path.exists("/Applications/Visual Studio Code.app"):
            subprocess.Popen(["open", "-a", "Visual Studio Code", path])
        else:
            subprocess.Popen(["open", path])
    elif IS_WINDOWS:
        vscode = os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe")
        if os.path.exists(vscode):
            subprocess.Popen([vscode, path])
        else:
            os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", path])


_KNOWN_FILE_EXTENSIONS = {
    "py", "js", "ts", "tsx", "jsx", "java", "html", "css", "json", "md", "txt",
    "csv", "xml", "yml", "yaml", "c", "cpp", "h", "hpp", "cs", "go", "rs",
    "php", "rb", "swift", "kt", "kts", "dart", "sql", "sh", "bat", "ps1",
}

_EXT_WORDS = {
    "python": "py",
    "javascript": "js",
    "typescript": "ts",
    "java": "java",
    "html": "html",
    "css": "css",
    "json": "json",
    "markdown": "md",
    "text": "txt",
    "txt": "txt",
    "csv": "csv",
    "xml": "xml",
    "yaml": "yaml",
    "yml": "yml",
    "c": "c",
    "cpp": "cpp",
    "c++": "cpp",
    "csharp": "cs",
    "c#": "cs",
    "go": "go",
    "rust": "rs",
    "php": "php",
    "ruby": "rb",
    "swift": "swift",
    "kotlin": "kt",
    "dart": "dart",
    "sql": "sql",
    "shell": "sh",
    "bash": "sh",
}


def _sanitize_filename_part(text: str) -> str:
    text = re.sub(r"[\\/:\*\?\"<>\|]", " ", text or "")
    text = " ".join(text.split()).strip(" .")
    return text


def _apply_case_hints(name: str, command: str) -> str:
    cmd = command.lower()
    words = name.split()
    if not words:
        return name

    if any(p in cmd for p in ["first letter capital", "first letter uppercase", "pehla letter capital"]):
        words[0] = words[0][:1].upper() + words[0][1:]

    for m in re.finditer(r"\b([a-z])\s+(?:bada|capital|uppercase)\b", cmd, flags=re.IGNORECASE):
        letter = m.group(1)
        for i, word in enumerate(words):
            if word.lower().startswith(letter.lower()):
                words[i] = letter.upper() + word[1:]
                break

    # Common voice phrase: "vani jisme V bada hoga"
    if "bada" in cmd or "capital" in cmd or "uppercase" in cmd:
        for i, word in enumerate(words):
            if word and word.islower():
                words[i] = word[:1].upper() + word[1:]
                break

    return " ".join(words)


def _extract_create_file_name(command: str) -> str:
    raw = " ".join((command or "").strip().split())
    cmd = raw.lower()

    ext = ""
    dot_match = re.search(r"\.([a-z0-9+#]+)\b", cmd)
    if dot_match:
        ext = _EXT_WORDS.get(dot_match.group(1), dot_match.group(1)).lower()
    if not ext:
        for word, mapped in sorted(_EXT_WORDS.items(), key=lambda item: -len(item[0])):
            if re.search(rf"\b{re.escape(word)}\s+file\b", cmd) or re.search(rf"\bfile\s+{re.escape(word)}\b", cmd):
                ext = mapped
                break

    name = ""
    name_patterns = [
        r"(?:file\s+)?(?:name|named|naam|nam)\s+([A-Za-z0-9 _.-]+?)(?:\s+(?:jisme|jis mein|with|where|ka|ki|ke)\b|$)",
        r"(?:called|call it)\s+([A-Za-z0-9 _.-]+?)(?:\s+(?:jisme|with|where)\b|$)",
    ]
    for pattern in name_patterns:
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            break

    if not name:
        name = raw
        remove_patterns = [
            r"\bopen\s+vscode\b", r"\bopen\s+vs\s+code\b", r"\bin\s+vscode\b", r"\bin\s+vs\s+code\b",
            r"\bvscode\s+mein\b", r"\bvs\s+code\s+mein\b",
            r"\bnewfile\b",
            r"\bcreate\s+(?:a\s+)?(?:new\s+)?(?:\.[a-z0-9+#]+\s+)?file\b",
            r"\bnew\s+(?:\.[a-z0-9+#]+\s+)?file\b",
            r"\bcreate\b",
            r"\b(?:file\s+)?bana(?:o)?\b", r"\bnayi\s+file\b", r"\bnaya\s+file\b",
            r"\b[a-z0-9+#]+\s+file\b",
        ]
        for pattern in remove_patterns:
            name = re.sub(pattern, " ", name, flags=re.IGNORECASE)
        name = re.split(r"\b(?:jisme|jis mein|with|where)\b", name, flags=re.IGNORECASE)[0]

    name = re.sub(r"\.[a-z0-9+#]+\b", " ", name, flags=re.IGNORECASE)
    name = _sanitize_filename_part(name)
    name = _apply_case_hints(name, raw)
    name = _sanitize_filename_part(name) or "Untitled"

    if "." in os.path.basename(name):
        return name
    return f"{name}.{ext or 'txt'}"


# ── Folder / file tool ────────────────────────────────────────────────────────

@tool
async def folder_file(command: str) -> str:
    """
    Opens, creates, renames, or deletes files and folders on Mac and Windows.

    Examples:
    - "Projects folder banao"
    - "Resume.pdf kholo"
    - "OldName ko NewName mein rename karo"
    - "xyz.mp4 delete karo"
    """
    dirs  = _default_search_dirs()
    index = await _index_items(dirs)
    cmd   = command.lower()

    if "create folder" in cmd or "folder banao" in cmd or "folder bana" in cmd:
        for kw in ["create folder", "folder banao", "folder bana"]:
            if kw in cmd:
                name = command[cmd.index(kw) + len(kw):].strip()
                break
        target = os.path.join(os.path.expanduser("~/Desktop"), name)
        os.makedirs(target, exist_ok=True)
        return f"✅ Folder ban gaya: {target}"

    create_file_phrases = [
        "newfile", "new file banao", "new file bana", "nayi file banao", "naya file banao",
        "vscode mein new file", "vs code mein new file",
        "create file", "new file", "file banao", "file bana",
        "nayi file", "naya file", "vscode mein file", "vs code mein file",
    ]
    if any(p in cmd for p in create_file_phrases):
        name = _extract_create_file_name(command)
        target = os.path.join(os.path.expanduser("~/Desktop"), name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "a", encoding="utf-8").close()
        _open_in_vscode_or_default(target)
        return f"✅ File ban gayi aur VS Code mein khul gayi: {target}"

    if "rename" in cmd:
        parts = cmd.replace("rename", "").strip().split(" to ")
        if len(parts) == 2:
            old_q, new_name = parts[0].strip(), parts[1].strip()
            item = await _search_item(old_q, index, "folder") or await _search_item(old_q, index, "file")
            if item:
                new_path = os.path.join(os.path.dirname(item["path"]), new_name)
                os.rename(item["path"], new_path)
                return f"✅ Rename ho gaya → {new_name}"
        return "❌ Format: 'OldName ko NewName mein rename karo'"

    if "delete" in cmd or "hata" in cmd:
        item = await _search_item(cmd, index, "file") or await _search_item(cmd, index, "folder")
        if item:
            if os.path.isdir(item["path"]):
                import shutil; shutil.rmtree(item["path"])
            else:
                os.remove(item["path"])
            return f"🗑️ Delete ho gaya: {item['name']}"
        return "❌ File/folder nahi mila delete karne ke liye."

    if "folder" in cmd:
        item = await _search_item(cmd, index, "folder")
        if item:
            _open_path(item["path"])
            return f"✅ Folder khul gaya: {item['name']}"
        return "❌ Folder nahi mila."

    item = await _search_item(cmd, index, "file")
    if item:
        _open_path(item["path"])
        return f"✅ File khul gayi: {item['name']}"

    return "⚠️ Kuch bhi match nahi hua. Thoda aur specific batao."
