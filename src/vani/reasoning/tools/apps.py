"""
vani/reasoning/tools/apps.py
App open/close/switch, tab control, mouse/keyboard, URL, and system tools.
"""

import os
import sys
import re
import asyncio
import subprocess
import logging
from langchain_core.tools import tool

from vani.reasoning.shared import IS_MAC, IS_WINDOWS, logger

# ── URL helpers ───────────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"^(?:https?://)?(?!\d+\.\d+\.\d+\.\d+)[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+(?::\d+)?(?:/\S*)?$",
    re.IGNORECASE,
)

_child_procs: list = []


def _safe_popen(cmd: list) -> None:
    """Launch a fire-and-forget process; reap any previously finished children."""
    global _child_procs
    _child_procs = [p for p in _child_procs if p.poll() is None]
    try:
        proc = subprocess.Popen(cmd)
        _child_procs.append(proc)
    except Exception as e:
        logger.warning(f"[popen] launch failed: {e}")


def _clean_spoken_domain(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"^(open|kholo|launch|visit|go to|open website)\s+", "", text).strip()
    text = re.sub(r"\s+(kholo|open karo|open kar|pe jao|par jao)$", "", text).strip()
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("., ")


def _looks_like_url(text: str) -> bool:
    lowered = (text or "").lower()
    non_url_words = {
        "file", "folder", "vscode", "vs code", "code", "banao", "bana",
        "create", "new", "naya", "nayi", "rename", "delete", "hata",
    }
    if any(word in lowered for word in non_url_words):
        return False
    return bool(_URL_RE.match(_clean_spoken_domain(text)))


def _is_file_operation_intent(query: str) -> bool:
    q = (query or "").lower()
    phrases = [
        "create file", "new file", "file banao", "file bana",
        "nayi file", "naya file", "vscode mein file", "vs code mein file",
        "vscode mein new file", "vs code mein new file",
        "create a file", "create a .", "new .", "newfile", "file name", "file naam",
    ]
    return any(p in q for p in phrases) or bool(re.search(r"\bcreate\s+(?:a\s+)?\.[a-z0-9+#]+\s+file\b", q))


# ── macOS helpers ─────────────────────────────────────────────────────────────

def _verify_app_running(app_name: str) -> bool:
    if not IS_MAC:
        return True
    search = app_name.lower().replace(" ", "").replace(".app", "")
    try:
        r = subprocess.run(["pgrep", "-fi", search], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return True
    except Exception:
        pass
    try:
        script = 'tell application "System Events" to get name of every process'
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
        procs = r.stdout.lower()
        if search[:6] in procs or app_name.lower().split()[0] in procs:
            return True
    except Exception:
        pass
    return False


def _frontmost_app_name() -> str:
    if not IS_MAC:
        return ""
    from vani.reasoning.shared import _osascript
    return _osascript(
        'tell application "System Events" to get name of first application process whose frontmost is true',
        timeout=1,
    )


def _mac_keystroke(key: str, modifiers: list[str] | None = None, timeout: float = 2.0) -> bool:
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


# ── Intent classifier ─────────────────────────────────────────────────────────

def _classify_app_intent(query: str):
    q = query.lower().strip()

    tab_next = [
        "next tab", "agla tab", "tab aage", "forward tab",
        "next browser tab", "next chrome tab", "next vscode tab",
        "next editor tab", "agla vscode tab"
    ]
    tab_prev = [
        "previous tab", "pichla tab", "tab peeche", "back tab",
        "previous browser tab", "previous chrome tab", "previous vscode tab",
        "previous editor tab", "pichla vscode tab"
    ]
    tab_close = [
        "close tab", "tab close", "tab band", "close current tab", "current tab band",
        "close browser tab", "close this tab", "close current browser tab",
        "close vscode tab", "close editor tab", "close current file",
        "close file", "file close kar", "current file close"
    ]

    for t in tab_next:
        if t in q: return ("TAB_NEXT", "")
    for t in tab_prev:
        if t in q: return ("TAB_PREVIOUS", "")
    for t in tab_close:
        if t in q: return ("TAB_CLOSE", "")

    if q.startswith("switch to "):
        return ("APP_SWITCH", q.replace("switch to ", "").strip())
    if q.endswith(" pe jao") or q.endswith(" par jao"):
        app = q.replace(" pe jao", "").replace(" par jao", "").strip()
        return ("APP_SWITCH", app)

    if q in ["close current app", "current app band", "close app", "app band karo"]:
        return ("APP_CLOSE", "current")

    if q.startswith("close "):
        target = q.replace("close ", "").strip()
        if target in {"this", "current", "current window", "window"}:
            return ("APP_CLOSE", "current")
        return ("APP_CLOSE", target)
    if q.endswith(" band karo") or q.endswith(" close kar"):
        app = q.replace(" band karo", "").replace(" close kar", "").strip()
        return ("APP_CLOSE", app)

    if q.startswith("open "):
        target = q.replace("open ", "").strip()
        if _looks_like_url(target):
            return ("OPEN_URL", _clean_spoken_domain(target))
        return ("APP_OPEN", target)
    if q.endswith(" kholo") or q.endswith(" open karo") or q.endswith(" open kar"):
        app = q.replace(" kholo", "").replace(" open karo", "").replace(" open kar", "").strip()
        if _looks_like_url(app):
            return ("OPEN_URL", _clean_spoken_domain(app))
        return ("APP_OPEN", app)

    return None


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
async def open_application(app_name: str) -> str:
    """Opens any application generically."""
    logger.info(f"[APP] Launch: {app_name}")
    try:
        return await open_app_smart.ainvoke({"app_name": app_name})
    except Exception as e:
        logger.error(f"[APP] Result: Error - {e}")
        return f"❌ {app_name} open karne mein issue: {e}"


@tool
async def close_application(app_name: str) -> str:
    """Closes any application generically."""
    logger.info(f"[APP] Intent: APP_CLOSE")
    logger.info(f"[APP] App: {app_name}")

    if not IS_MAC:
        from vani.tools.window_control import close_app
        return await close_app.ainvoke(app_name)

    if app_name == "current":
        script = 'tell application "System Events" to set frontApp to name of first application process whose frontmost is true\n tell application frontApp to quit'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
        return "✅ Current app band ho gaya."

    sanitized_app = "".join(c for c in app_name if c.isalnum() or c in (" ", ".", "_", "-"))
    script = f'tell application "{sanitized_app}" to quit'
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    # No sleep needed — quit is synchronous on Mac; verify immediately
    if _verify_app_running(app_name):
        return f"❌ {app_name} band nahi hua."
    return f"✅ {app_name.title()} band ho gaya."


@tool
async def switch_application(app_name: str) -> str:
    """Switches to any application generically."""
    logger.info(f"[APP] Intent: APP_SWITCH | App: {app_name}")

    if not IS_MAC:
        return f"✅ Switching not supported directly on Windows yet."

    sanitized_app = "".join(c for c in app_name if c.isalnum() or c in (" ", ".", "_", "-"))
    script = f'tell application "{sanitized_app}" to activate'
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    # activate is instant on Mac — check immediately
    check_script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    r = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True, timeout=3)
    if r.returncode == 0 and app_name.lower().replace(" ", "") in r.stdout.lower().replace(" ", ""):
        return f"✅ {app_name.title()} pe switch ho gaya."
    return f"❌ {app_name} switch nahi ho paya."


@tool
async def switch_tab_by_name(query: str) -> str:
    """Switch to the browser tab whose title best matches the given name or site."""
    from vani.browser.tab_navigator import switch_to_tab_by_name
    return await switch_to_tab_by_name(query)


@tool
async def close_tab_by_name(query: str) -> str:
    """Close the single browser tab whose title best matches the given name or site."""
    from vani.browser.tab_navigator import close_tab_by_name as _fn
    return await _fn(query)


@tool
async def close_all_tabs_by_name(query: str) -> str:
    """Close ALL browser tabs whose title matches the given name or site (e.g. 'YouTube')."""
    from vani.browser.tab_navigator import close_all_tabs_by_name as _fn
    return await _fn(query)


@tool
async def close_active_tab() -> str:
    """Closes the current active browser/editor tab."""
    if IS_MAC:
        app = _frontmost_app_name()
        ok = _mac_keystroke("w", ["command"])
        if ok:
            return f"✅ {app or 'current app'} ka current tab close ho gaya."
        return "❌ Current tab close nahi hua."
    elif IS_WINDOWS:
        from pynput.keyboard import Key, Controller as KB
        kb = KB()
        kb.press(Key.ctrl); kb.press("w"); kb.release("w"); kb.release(Key.ctrl)
        return "✅ Tab close ho gaya."
    return "❌ OS support nahi hai."


@tool
async def next_tab() -> str:
    """Switches to the next tab."""
    if IS_MAC:
        app = _frontmost_app_name().lower()
        ok = _mac_key_code(124, ["control"]) if "code" in app else _mac_keystroke("]", ["command", "shift"])
        return "✅ Next tab." if ok else "❌ Next tab nahi hua."
    elif IS_WINDOWS:
        from pynput.keyboard import Key, Controller as KB
        kb = KB()
        kb.press(Key.ctrl); kb.press(Key.tab); kb.release(Key.tab); kb.release(Key.ctrl)
        return "✅ Next tab."
    return "❌ OS support nahi hai."


@tool
async def previous_tab() -> str:
    """Switches to the previous tab."""
    if IS_MAC:
        app = _frontmost_app_name().lower()
        ok = _mac_key_code(123, ["control"]) if "code" in app else _mac_keystroke("[", ["command", "shift"])
        return "✅ Previous tab." if ok else "❌ Previous tab nahi hua."
    elif IS_WINDOWS:
        from pynput.keyboard import Key, Controller as KB
        kb = KB()
        kb.press(Key.ctrl); kb.press(Key.shift); kb.press(Key.tab)
        kb.release(Key.tab); kb.release(Key.shift); kb.release(Key.ctrl)
        return "✅ Previous tab."
    return "❌ OS support nahi hai."


@tool
async def app_search(query: str) -> str:
    """Spotlight (Mac) ya Windows Search se app/file dhundhta hai."""
    from pynput.keyboard import Key, Controller as KB
    kb = KB()
    if IS_MAC:
        kb.press(Key.cmd); kb.press(Key.space)
        kb.release(Key.space); kb.release(Key.cmd)
        await asyncio.sleep(0.15)          # Spotlight animation — unavoidable minimum
        for c in query:
            kb.press(c); kb.release(c)    # no per-char delay — Spotlight handles burst input
        await asyncio.sleep(0.1)           # let Spotlight index the typed text
        kb.press(Key.enter); kb.release(Key.enter)
        return f"✅ Spotlight mein '{query}' search ho gaya."
    elif IS_WINDOWS:
        kb.press(Key.cmd); kb.release(Key.cmd)
        await asyncio.sleep(0.15)
        for c in query:
            kb.press(c); kb.release(c)
        await asyncio.sleep(0.1)
        kb.press(Key.enter); kb.release(Key.enter)
        return f"✅ Windows Search mein '{query}' search ho gaya."
    return "❌ OS detect nahi ho paya."


@tool
async def talking_tom_control(action: str) -> str:
    """Talking Tom mode — mic pitch shift karke repeat. action: on/off/status"""
    try:
        from vani.audio.talking_tom import start_talking_tom, stop_talking_tom, is_active as tom_is_active
        talking_tom_available = True
    except ImportError:
        talking_tom_available = False

    if not talking_tom_available:
        return "❌ vani_talking_tom.py nahi mila."

    a = action.lower().strip()
    if a in ("on", "start", "shuru", "chalu", "activate"):
        if tom_is_active(): return "Talking Tom already on hai!"
        start_talking_tom()
        return "Talking Tom ON! Bol ya gaa, repeat karungi!"
    elif a in ("off", "stop", "band", "bandh", "deactivate"):
        if not tom_is_active(): return "Talking Tom pehle se off tha."
        stop_talking_tom()
        return "Talking Tom OFF. Wapas normal hoon."
    elif a in ("status", "check"):
        return "ON hai!" if tom_is_active() else "OFF hai."
    return f"Samjha nahi '{action}' — on ya off bolo."


# ── Wrapper tools (delegate to vani.browser / vani.tools) ────────────────────

@tool
async def open_url(url: str) -> str:
    """Opens a URL in the default web browser."""
    from vani.tools.window_control import open_url as _open_url
    return await _open_url.ainvoke({"url": url})


@tool
async def open_youtube_and_play(song_or_query: str) -> str:
    """YouTube par song/video chalao."""
    from vani.browser.control import open_youtube_and_play as _fn
    return await _fn.ainvoke({"song_or_query": song_or_query})


@tool
async def open_url_in_browser(url: str, browser: str = "chrome") -> str:
    """Specific browser mein URL kholo."""
    from vani.browser.control import open_url_in_browser as _fn
    return await _fn.ainvoke({"url": url, "browser": browser})


@tool
async def open_app_smart(app_name: str) -> str:
    """Smart app opener that can map names to web apps or desktop fallbacks."""
    from vani.browser.control import open_app_smart as _fn
    return await _fn.ainvoke({"app_name": app_name})


@tool
async def folder_file(command: str) -> str:
    """File/folder operations perform karta hai."""
    from vani.tools.window_control import folder_file as _fn
    return await _fn.ainvoke({"command": command})


@tool
async def Play_file(file_path: str) -> str:
    """File dhundh ke chalao."""
    try:
        from vani.tools.file_opener import Play_file as _fn
        return await _fn.ainvoke({"file_path": file_path})
    except ImportError:
        return "File player module nahi mila."


# ── Keyboard/mouse tools ──────────────────────────────────────────────────────

@tool
async def move_cursor_tool(x: int, y: int) -> str:
    """Mouse cursor move karo."""
    from vani.tools.keyboard_mouse import move_cursor_tool as _fn
    return await _fn.ainvoke({"x": x, "y": y})


@tool
async def mouse_click_tool(button: str = "left", clicks: int = 1) -> str:
    """Mouse click perform karo."""
    from vani.tools.keyboard_mouse import mouse_click_tool as _fn
    return await _fn.ainvoke({"button": button, "clicks": clicks})


@tool
async def scroll_cursor_tool(direction: str, amount: int = 10) -> str:
    """Scroll cursor up, down, left, or right."""
    from vani.tools.keyboard_mouse import scroll_cursor_tool as _fn
    return await _fn.ainvoke({"direction": direction, "amount": amount})


@tool
async def type_text_tool(text: str) -> str:
    """Keyboard se text type karo."""
    from vani.tools.keyboard_mouse import type_text_tool as _fn
    return await _fn.ainvoke({"text": text})


@tool
async def press_key_tool(key: str) -> str:
    """Single key press karo."""
    from vani.tools.keyboard_mouse import press_key_tool as _fn
    return await _fn.ainvoke({"key": key})


@tool
async def press_hotkey_tool(keys: list) -> str:
    """Hotkey (multiple keys) press karo."""
    from vani.tools.keyboard_mouse import press_hotkey_tool as _fn
    return await _fn.ainvoke({"keys": keys})


@tool
async def control_volume_tool(action: str, percent: int = 10) -> str:
    """System volume control karo. action: up/down/mute/unmute. percent: kitna change (default 10)."""
    from vani.tools.keyboard_mouse import control_volume_tool as _fn
    return await _fn.ainvoke({"action": action, "step": percent})


@tool
async def swipe_gesture_tool(direction: str) -> str:
    """Swipe gesture perform karo."""
    from vani.tools.keyboard_mouse import swipe_gesture_tool as _fn
    return await _fn.ainvoke({"direction": direction})