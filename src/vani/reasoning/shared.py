"""
vani/reasoning/shared.py
Shared constants, logger, and small utility helpers used across the reasoning package.
"""

import sys
import logging
import subprocess

# ── Platform flags ────────────────────────────────────────────────────────────

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# ── Logger ────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# ── Ollama config ─────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

# ── Small macOS/text utilities ────────────────────────────────────────────────

def _safe_popen(cmd: list) -> None:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.error(f"Command failed: {cmd} -> {e}")


def _osascript(script: str, timeout: float = 1.2) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _compact_lines(text: str, max_lines: int = 40, max_chars: int = 3000) -> str:
    seen = set()
    lines = []
    for raw in (text or "").replace("\r", "\n").splitlines():
        line = " ".join(raw.split()).strip()
        if len(line) < 2 or line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)[:max_chars].strip()


def _frontmost_app_name() -> str:
    if not IS_MAC:
        return ""
    return _osascript(
        'tell application "System Events" to get name of first application process whose frontmost is true',
        timeout=1,
    )


def _mac_keystroke(key: str, modifiers: list[str] | None = None, timeout: float = 2.0) -> bool:
    if not IS_MAC:
        return False
    modifiers = modifiers or []
    key = key.replace('"', '\\"')
    if modifiers:
        mod_text = "{" + ", ".join(f"{m} down" for m in modifiers) + "}"
        script = f'tell application "System Events" to keystroke "{key}" using {mod_text}'
    else:
        script = f'tell application "System Events" to keystroke "{key}"'
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except Exception:
        return False


def _mac_key_code(code: int, modifiers: list[str] | None = None, timeout: float = 2.0) -> bool:
    if not IS_MAC:
        return False
    modifiers = modifiers or []
    if modifiers:
        mod_text = "{" + ", ".join(f"{m} down" for m in modifiers) + "}"
        script = f'tell application "System Events" to key code {code} using {mod_text}'
    else:
        script = f'tell application "System Events" to key code {code}'
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except Exception:
        return False


def _focus_youtube_tab() -> str:
    """
    Bring the YouTube browser tab to the foreground and focus it.

    Returns the browser app name that was focused ("Google Chrome", "Brave Browser", etc.)
    or "" if no YouTube tab was found.

    This MUST be called before sending keyboard shortcuts to YouTube (next, prev, seek, etc.)
    because System Events sends keystrokes to whichever app is frontmost — if Vani's UI
    window is in front, the shortcut lands on Vani, not YouTube.
    """
    if not IS_MAC:
        return ""

    browsers = ["Google Chrome", "Brave Browser", "Chromium", "Microsoft Edge", "Safari"]
    yt_hints = ["youtube.com"]

    for browser in browsers:
        if browser == "Safari":
            script = f'''
tell application "Safari"
    set winList to every window
    repeat with w in winList
        set tabList to every tab of w
        set tabIdx to 1
        repeat with t in tabList
            if URL of t contains "youtube.com" then
                set current tab of w to t
                set index of w to 1
                activate
                return "Safari"
            end if
            set tabIdx to tabIdx + 1
        end repeat
    end repeat
end tell
return ""
'''
        else:
            script = f'''
tell application "{browser}"
    set winList to every window
    repeat with w in winList
        set tabList to every tab of w
        set tabIdx to 1
        repeat with t in tabList
            if URL of t contains "youtube.com" then
                set active tab index of w to tabIdx
                set index of w to 1
                activate
                return "{browser}"
            end if
            set tabIdx to tabIdx + 1
        end repeat
    end repeat
end tell
return ""
'''
        result = _osascript(script, timeout=4)
        if result and result.strip() not in ("", "missing value"):
            return result.strip()

    return ""


def _refocus_vani() -> None:
    """
    Bring Vani's own UI window back to the foreground after sending a
    YouTube keystroke.

    Why: _focus_youtube_tab() moves Chrome/Brave to front so keystrokes land
    on YouTube.  But NSSpeechRecognizer uses listensInForegroundOnly=False so
    it keeps listening regardless — the real problem was audio ducking, not
    focus.  Still, refocusing Vani after the command keeps the UI responsive
    and prevents accidental keyboard input going to the browser.
    """
    if not IS_MAC:
        return
    try:
        import subprocess as _sp
        # Vani runs as a Python process; its UI is served via a browser window
        # pointed at localhost.  We activate Python (the server) and let the
        # UI stay in the browser — simply bring the localhost tab to front.
        script = '''
tell application "Google Chrome"
    set winList to every window
    repeat with w in winList
        repeat with t in every tab of w
            if URL of t contains "127.0.0.1" or URL of t contains "localhost" then
                set active tab index of w to (index of t)
                set index of w to 1
                activate
                return
            end if
        end repeat
    end repeat
end tell
'''
        _sp.Popen(["osascript", "-e", script], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    except Exception:
        pass