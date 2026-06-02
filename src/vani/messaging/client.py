"""
vani/messaging/client.py — WhatsApp, Telegram, Instagram, Mac Notifications

SETUP:
  1. Telegram: https://my.telegram.org → API ID + Hash .env mein daalo
  2. Instagram (optional): INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD
  3. WhatsApp: Desktop app + osascript. No extra setup needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import subprocess as _sp
import sys
import time as _time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from dotenv import load_dotenv

from vani.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

load_dotenv(PROJECT_ROOT / ".env")

IS_MAC = sys.platform == "darwin"

# ── CONTACT CACHE — TTL 60s ───────────────────────────────────────────────────
_contacts_cache: dict = {}
_CONTACTS_TTL = 60.0



# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

class TelegramNotAuthorizedError(Exception):
    pass


@asynccontextmanager
async def _telegram_client_context() -> AsyncIterator:
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError:
        raise ImportError("telethon install nahi hai. Chalao: pip install telethon")

    api_id   = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone    = os.getenv("TELEGRAM_PHONE")

    if not api_id or not api_hash:
        raise TelegramNotAuthorizedError("❌ .env mein TELEGRAM_API_ID aur TELEGRAM_API_HASH daalo.")

    session_path = str(PROJECT_ROOT / "vani_session")
    client = TelegramClient(session_path, int(api_id), api_hash)
    try:
        await client.connect()
        authorized = await client.is_user_authorized()
        if not authorized:
            if not phone:
                raise TelegramNotAuthorizedError(
                    "❌ Telegram authorized nahi hai aur TELEGRAM_PHONE missing hai.")
            try:
                await client.start(phone=phone)
                authorized = await client.is_user_authorized()
            except SessionPasswordNeededError:
                raise TelegramNotAuthorizedError("❌ Telegram 2FA enabled hai. Terminal mein manually login karo.")
        if not authorized:
            raise TelegramNotAuthorizedError("❌ Telegram login nahi hua.")
        yield client
    finally:
        if client.is_connected():
            await client.disconnect()


async def telegram_read_chat(contact: str, limit: int = 20) -> str:
    log = logging.getLogger("vani.messaging.telegram")
    try:
        from telethon.tl.types import User, Chat, Channel
        async with _telegram_client_context() as client:
            try:
                entity = await client.get_entity(contact)
            except ValueError:
                return f"❌ Telegram contact '{contact}' nahi mila."
            except Exception as exc:
                return f"❌ Telegram contact lookup failed: {exc}"
            messages = await client.get_messages(entity, limit=limit)
            if not messages:
                return f"'{contact}' ke saath koi message nahi mila."
            lines = []
            for msg in reversed(messages):
                if not msg:
                    continue
                try:
                    import datetime
                    local_dt = msg.date.astimezone()
                    time_str = local_dt.strftime("%H:%M")
                except Exception:
                    time_str = "??"
                sender_name = contact
                if msg.out:
                    sender_name = "Aap"
                else:
                    try:
                        if msg.sender_id:
                            sender = await client.get_entity(msg.sender_id)
                            if isinstance(sender, User):
                                sender_name = sender.first_name or sender.username or contact
                            elif isinstance(sender, (Chat, Channel)):
                                sender_name = sender.title or contact
                    except Exception:
                        pass
                text = msg.text or "[media/file]"
                lines.append(f"[{time_str}] {sender_name}: {text}")
            return f"--- {contact} Telegram chat ---\n" + "\n".join(lines)
    except TelegramNotAuthorizedError as exc:
        return str(exc)
    except ImportError as exc:
        return f"❌ {exc}"
    except Exception as exc:
        log.warning("telegram_read_chat failed: %s", exc)
        return f"❌ Telegram read error: {exc}"


async def telegram_send_message(contact: str, message: str) -> str:
    log = logging.getLogger("vani.messaging.telegram")
    try:
        async with _telegram_client_context() as client:
            try:
                entity = await client.get_entity(contact)
            except ValueError:
                return f"❌ Telegram contact '{contact}' nahi mila."
            await client.send_message(entity, message)
            return f"✅ Telegram pe '{contact}' ko bhej diya: {message}"
    except TelegramNotAuthorizedError as exc:
        return str(exc)
    except ImportError as exc:
        return f"❌ {exc}"
    except Exception as exc:
        log.warning("telegram_send_message failed: %s", exc)
        return f"❌ Telegram send error: {exc}"


async def telegram_list_chats(limit: int = 10) -> str:
    log = logging.getLogger("vani.messaging.telegram")
    try:
        async with _telegram_client_context() as client:
            dialogs = await client.get_dialogs(limit=limit)
            if not dialogs:
                return "Koi Telegram chat nahi mila."
            lines = []
            for d in dialogs:
                last = (d.message.text[:60] if d.message and d.message.text else "[media]")
                lines.append(f"• {d.name}: {last}")
            return "Recent Telegram chats:\n" + "\n".join(lines)
    except TelegramNotAuthorizedError as exc:
        return str(exc)
    except ImportError as exc:
        return f"❌ {exc}"
    except Exception as exc:
        log.warning("telegram_list_chats failed: %s", exc)
        return f"❌ Telegram error: {exc}"


# ══════════════════════════════════════════════════════════════════════════════
# WHATSAPP — HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def check_macos_permissions() -> str:
    res = []
    try:
        r = _sp.run(["osascript", "-e", 'tell application "System Events" to get name'],
                    capture_output=True, text=True, timeout=2)
        res.append(f"Accessibility: {'OK' if r.returncode == 0 else 'Missing'}")
    except Exception:
        res.append("Accessibility: Missing")
    try:
        r = _sp.run(["osascript", "-e", 'tell application "Finder" to get name'],
                    capture_output=True, text=True, timeout=2)
        res.append(f"Automation: {'OK' if r.returncode == 0 else 'Missing'}")
    except Exception:
        res.append("Automation: Missing")
    import glob
    db_path = os.path.expanduser("~/Library/Application Support/NotificationCenter/*.db")
    res.append("Notifications: OK" if glob.glob(db_path) else "Notifications: Missing")
    return "\n".join(res)


def _wa_copy_paste(text: str):
    _sp.run("pbcopy", input=text.encode("utf-8"), check=True)


def _wa_process_running() -> bool:
    try:
        r = _sp.run(["pgrep", "-fi", "whatsapp"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return True
    except Exception:
        pass
    try:
        script = 'tell application "System Events" to get name of every process whose name contains "WhatsApp"'
        r = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip()) and r.stdout.strip() != "{}"
    except Exception:
        pass
    return False


def _wa_find_app_path() -> str:
    import os as _os2, glob as _glob
    try:
        for entry in _os2.listdir("/Applications"):
            if "WhatsApp" in entry and entry.endswith(".app"):
                return f"/Applications/{entry}"
    except Exception:
        pass
    for pattern in ["/Applications/*WhatsApp*.app",
                    _os2.path.expanduser("~/Applications/*WhatsApp*.app")]:
        hits = _glob.glob(pattern)
        if hits:
            return hits[0]
    return ""


# ── PATCH 2: Fixed _wa_open_app ──────────────────────────────────────────────
def _wa_open_app() -> bool:
    """
    Open & focus WhatsApp Desktop app.
    Verifies frontmost state, retries 3x if needed.
    Returns True only when process confirmed running.
    """
    def _bring_to_front() -> bool:
        script = """
tell application "System Events"
    set waNames to {"WhatsApp", "WhatsApp Desktop", "WhatsApp Messenger"}
    repeat with waName in waNames
        if exists process waName then
            set frontmost of process waName to true
            delay 0.4
            if frontmost of process waName then return "OK"
        end if
    end repeat
    return "NOT_FOUND"
end tell
"""
        try:
            r = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
            return r.stdout.strip() == "OK"
        except Exception:
            return False

    if _wa_process_running():
        for _ in range(3):
            if _bring_to_front():
                _time.sleep(0.3)
                return True
            _time.sleep(0.3)
        return True  # Process running even if frontmost uncertain

    app_path = _wa_find_app_path()
    if not app_path:
        logger.error("[WA_OPEN] WhatsApp.app not found in /Applications")
        return False

    try:
        _sp.run(["open", "-a", app_path], capture_output=True, text=True, timeout=5)
    except Exception as exc:
        logger.error("[WA_OPEN] Launch failed: %s", exc)
        return False

    for i in range(16):
        _time.sleep(0.5)
        if _wa_process_running():
            _time.sleep(1.5)
            _bring_to_front()
            logger.info("[WA_OPEN] App launched after %.1fs", (i + 1) * 0.5)
            return True

    logger.error("[WA_OPEN] App did not start within 8s")
    return False


def _run_js_in_browser(js: str, timeout: int = 6, tab_url_contains: str = "") -> str:
    for app_name in ["Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge"]:
        if tab_url_contains:
            script = f"""
tell application "System Events"
    if not (exists process "{app_name}") then return ""
end tell
tell application "{app_name}"
    if (count of windows) is 0 then return ""
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t contains "{tab_url_contains}" then
                return execute t javascript {_applescript_quote(js)}
            end if
        end repeat
    end repeat
    return execute active tab of front window javascript {_applescript_quote(js)}
end tell
"""
        else:
            script = f"""
tell application "System Events"
    if not (exists process "{app_name}") then return ""
end tell
tell application "{app_name}"
    if (count of windows) is 0 then return ""
    return execute active tab of front window javascript {_applescript_quote(js)}
end tell
"""
        try:
            r = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return ""


def _applescript_quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"'  )
    return f'"{escaped}"'



# ── PATCH 1: Fixed WA_SHORTCUTS — Desktop shortcuts ──────────────────────────
WA_SHORTCUTS = {
    # Desktop App shortcuts (confirmed Mac WhatsApp Desktop)
    "NEW_CHAT":            ("n",      ["command", "control"]),
    "NEXT_CHAT":           ("tab",    ["command", "control"]),
    "PREVIOUS_CHAT":       ("tab",    ["command", "control", "shift"]),
    # Desktop: Cmd+F opens search. Web "/" kept as WEB variant
    "SEARCH_CHAT":         ("f",      ["command"]),
    "SEARCH_WITHIN_CHAT":  ("f",      ["command", "shift"]),
    "CLOSE_CHAT":          ("escape", []),
    "ARCHIVE_CHAT":        ("e",      ["command", "control", "shift"]),
    "MUTE_CHAT":           ("m",      ["command", "control", "shift"]),
    "MARK_UNREAD":         ("u",      ["command", "control", "shift"]),
    "DELETE_CHAT":         ("delete", ["command", "control"]),
    "PIN_CHAT":            ("p",      ["command", "control", "shift"]),
    # Call shortcuts — Desktop only
    "VOICE_CALL":          ("c",      ["command", "shift"]),
    "VIDEO_CALL":          ("v",      ["command", "shift"]),
    "MUTE_MIC":            ("m",      ["command", "shift"]),
    "TOGGLE_CAMERA":       ("o",      ["command", "shift"]),
    "END_CALL":            ("escape", []),
}

_KEY_CODES = {"escape": 53, "tab": 48, "delete": 51, "down": 125, "enter": 36}

_MODIFIER_NAMES = {
    "command": "command down",
    "control": "control down",
    "shift":   "shift down",
    "option":  "option down",
}


def _modifier_text(modifiers: list) -> str:
    return "{" + ", ".join(_MODIFIER_NAMES[m] for m in modifiers) + "}"


def _wa_keystroke_target(action: str, target: str = "frontmost") -> bool:
    shortcut = WA_SHORTCUTS.get(action)
    if not shortcut:
        logger.error("[WA_SHORTCUT] Unknown action: %s", action)
        return False
    key, modifiers = shortcut
    if key in _KEY_CODES:
        key_command = f"key code {_KEY_CODES[key]}"
    else:
        key_command = f'keystroke "{key}"'
    if modifiers:
        key_command = f"{key_command} using {_modifier_text(modifiers)}"
    if target == "whatsapp_desktop":
        script = f"""
tell application "System Events"
    set waNames to {{"WhatsApp", "WhatsApp Desktop", "WhatsApp Messenger"}}
    repeat with waName in waNames
        if exists process waName then
            tell process waName
                set frontmost to true
                {key_command}
                return "OK"
            end tell
        end if
    end repeat
    return "NO_PROCESS"
end tell
"""
    else:
        script = f'tell application "System Events" to {key_command}'
    try:
        result = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        if result.returncode != 0 or "NO_PROCESS" in result.stdout:
            logger.error("[WA_SHORTCUT] Failed %s: %s", action, result.stderr.strip())
            return False
        _time.sleep(0.5)
        return True
    except Exception as exc:
        logger.error("[WA_SHORTCUT] Error %s: %s", action, exc)
        return False


def _wa_shortcut(action: str) -> bool:
    if not _wa_ensure_frontmost():
        return False
    return _wa_keystroke_target(action, target="whatsapp_desktop")


def _wa_press_key(key: str):
    _sp.run(["osascript", "-e", f'tell application "System Events" to key code {key}'], check=True)
    _time.sleep(0.3)


# ── PATCH 7: Fixed _wa_type_text — saves/restores clipboard ──────────────────
def _wa_type_text(text: str):
    """Type text via clipboard paste. Saves and restores previous clipboard content."""
    try:
        save_result = _sp.run("pbpaste", capture_output=True, timeout=2)
        saved_clipboard = save_result.stdout
    except Exception:
        saved_clipboard = b""
    try:
        _sp.run("pbcopy", input=text.encode("utf-8"), check=True, timeout=3)
        _sp.run(["osascript", "-e",
                 'tell application "System Events" to keystroke "v" using command down'],
                check=True, timeout=4)
        _time.sleep(0.4)
    finally:
        if saved_clipboard:
            try:
                _sp.run("pbcopy", input=saved_clipboard, timeout=2)
            except Exception:
                pass


def _wa_press_enter():
    _sp.run(["osascript", "-e", 'tell application "System Events" to key code 36'], check=True)
    _time.sleep(0.3)



def _wa_reset_state():
    if not _wa_ensure_frontmost():
        return
    try:
        reset_script = """
tell application "System Events"
    tell process "WhatsApp"
        key code 53
        delay 0.1
        key code 53
        delay 0.1
    end tell
end tell
"""
        _sp.run(["osascript", "-e", reset_script], capture_output=True, timeout=4)
    except Exception:
        pass


def _wa_ensure_frontmost() -> bool:
    check_script = """
tell application "System Events"
    set waNames to {"WhatsApp", "WhatsApp Desktop", "WhatsApp Messenger"}
    repeat with waName in waNames
        if exists process waName then
            if frontmost of process waName then return "YES"
            set frontmost of process waName to true
            delay 0.5
            if frontmost of process waName then return "YES"
        end if
    end repeat
    return "NO"
end tell
"""
    for attempt in range(2):
        try:
            r = _sp.run(["osascript", "-e", check_script], capture_output=True, text=True, timeout=4)
            if r.stdout.strip() == "YES":
                return True
            if attempt == 0:
                _wa_open_app()
        except Exception:
            pass
    return False


_selected_contact_cache: dict = {}
_SELECTED_TTL = 1800.0


def _get_cached_selection(name: str) -> Optional[str]:
    entry = _selected_contact_cache.get(name.lower())
    if entry and (_time.time() - entry["ts"]) < _SELECTED_TTL:
        return entry["actual_name"]
    return None


def _set_cached_selection(name: str, actual_name: str):
    _selected_contact_cache[name.lower()] = {"actual_name": actual_name, "ts": _time.time()}


# ── PATCH 3: Fixed _wa_search_contact — Desktop Cmd+F ────────────────────────
def _wa_search_contact(contact: str) -> bool:
    """
    Open Desktop search (Cmd+F) and type contact name.
    Retries once if search box does not open.
    """
    search_script = f"""
tell application "System Events"
    set waNames to {{"WhatsApp", "WhatsApp Desktop", "WhatsApp Messenger"}}
    repeat with waName in waNames
        if exists process waName then
            tell process waName
                set frontmost to true
                delay 0.2
                -- Cmd+F opens search in Desktop app
                keystroke "f" using command down
                delay 0.5
                -- Select all + delete to clear existing text
                keystroke "a" using command down
                delay 0.1
                key code 51
                delay 0.1
                return "OPENED"
            end tell
        end if
    end repeat
    return "NO_PROCESS"
end tell
"""
    for attempt in range(2):
        try:
            r = _sp.run(["osascript", "-e", search_script],
                        capture_output=True, text=True, timeout=6)
            result = r.stdout.strip()
            logger.info("[WA_SEARCH] Attempt %d: %s", attempt + 1, result)
            if result == "OPENED":
                _time.sleep(0.3)
                _wa_type_text(contact)
                _time.sleep(1.0)
                return True
        except Exception as exc:
            logger.warning("[WA_SEARCH] Attempt %d failed: %s", attempt + 1, exc)
        _time.sleep(0.5)
    return False


_WA_SECTION_HEADERS = {
    "chats", "groups", "groups in common", "media",
    "messages", "contacts", "people", "business",
}


def _wa_dump_results() -> list:
    tree_script = """
tell application "System Events"
    tell process "WhatsApp"
        set out to ""
        set navCount to 0
        try
            set sidebar to group 1 of window 1
            set sa to scroll area 1 of sidebar
            set theList to list 1 of sa
            set topGroups to every group of theList
            repeat with tg in topGroups
                set tgName to ""
                try
                    set tgName to name of static text 1 of tg
                end try
                if tgName is "Media" then
                    set navCount to navCount + 4
                else if (count of every group of tg) > 0 then
                    set children to every group of tg
                    repeat with child in children
                        set childName to ""
                        try
                            set childName to name of static text 1 of child
                        end try
                        if childName is not "" then
                            set navCount to navCount + 1
                            set out to out & navCount & ":::" & childName & "|||"
                        end if
                    end repeat
                else
                    if tgName is not "" then
                        set navCount to navCount + 1
                        set out to out & navCount & ":::" & tgName & "|||"
                    end if
                end if
            end repeat
        end try
        if out is "" then set out to "EMPTY"
        return out
    end tell
end tell
"""
    try:
        r = _sp.run(["osascript", "-e", tree_script], capture_output=True, text=True, timeout=8)
        raw = r.stdout.strip()
        if not raw or raw == "EMPTY":
            return []
        results = []
        for token in raw.split("|||"):
            token = token.strip()
            if ":::" in token:
                nav_str, name = token.split(":::", 1)
                name = name.strip()
                if name.lower() in _WA_SECTION_HEADERS:
                    continue
                try:
                    results.append({"name": name, "nav_steps": int(nav_str.strip())})
                except ValueError:
                    pass
        return results
    except Exception as exc:
        logger.info("[WA_RESULTS] Dump failed: %s", exc)
        return []


# ── PATCH 4 v2: _wa_get_chat_header — reads from chat panel header ────────────
def _wa_get_chat_header() -> str:
    """
    Read the name of the currently open chat from WhatsApp Desktop.

    WhatsApp Mac layout:
      group 1 = sidebar (search, chat list)
      group 2 = chat panel (header with contact name, messages, input)

    The contact name appears as the FIRST static text inside group 2's header area.
    Falls back to broader scan if layout differs.
    """
    header_script = """
tell application "System Events"
    tell process "WhatsApp"
        if (count of windows) is 0 then return ""
        set w to window 1

        -- Strategy 1: first static text of group 2 (chat panel header)
        try
            set chatPanel to group 2 of w
            set allST to every static text of chatPanel
            repeat with st in allST
                set n to name of st
                if n is not "" and (length of n) < 80 then
                    return n
                end if
            end repeat
        end try

        -- Strategy 2: walk all groups from index 2 onward, first non-empty static text
        try
            repeat with i from 2 to (count of groups of w)
                try
                    set allST to every static text of group i of w
                    repeat with st in allST
                        set n to name of st
                        if n is not "" and (length of n) < 80 then
                            return n
                        end if
                    end repeat
                end try
            end repeat
        end try

        return ""
    end tell
end tell
"""
    try:
        r = _sp.run(["osascript", "-e", header_script], capture_output=True, text=True, timeout=5)
        result = r.stdout.strip()
        logger.debug("[WA_HEADER] Got: %r", result)
        return result
    except Exception as exc:
        logger.warning("[WA_HEADER] Failed: %s", exc)
        return ""


# ── PATCH 5: Fixed _wa_focus_message_box — targets textarea correctly ─────────
def _wa_focus_message_box() -> bool:
    """
    Focus the message input box. 3 strategies.
    Returns True if any strategy succeeds.
    """
    focus_script = """
tell application "System Events"
    tell process "WhatsApp"
        set frontmost to true
        delay 0.2

        -- Strategy 1: text area with description containing "message" or "Type"
        try
            set allTA to every text area of window 1
            repeat with ta in allTA
                try
                    set d to description of ta
                    set n to name of ta
                    if d contains "message" or d contains "Message" or d contains "Type" ¬
                        or n contains "message" or n contains "Type" then
                        click ta
                        return "FOCUSED_TEXTAREA_DESC"
                    end if
                end try
            end repeat
        end try

        -- Strategy 2: any text area in window (last = message box)
        try
            set allTA to every text area of window 1
            if (count of allTA) > 0 then
                click (last item of allTA)
                return "FOCUSED_TEXTAREA_LAST"
            end if
        end try

        -- Strategy 3: Tab key to cycle focus
        repeat 3 times
            key code 48
            delay 0.15
        end repeat
        return "FOCUSED_TAB"
    end tell
end tell
"""
    try:
        r = _sp.run(["osascript", "-e", focus_script], capture_output=True, text=True, timeout=6)
        result = r.stdout.strip()
        logger.info("[WA_FOCUS_BOX] %s", result)
        return bool(result)
    except Exception as exc:
        logger.warning("[WA_FOCUS_BOX] Failed: %s", exc)
        return False


# ── PATCH 6 v2: _wa_open_chat_verified — direct name-match click ──────────────
def _wa_open_chat_verified(contact: str, index: int = 1) -> bool:
    """
    Open a chat after _wa_search_contact() has run.

    Root cause of old bug (confirmed via screenshot):
      WhatsApp Desktop search results look like:
        [Chats header]
          Shrey Upadhyay          ← actual chat row
        [Groups in common header]
          Group 1 ...
          Group 2 ...
        [Media header]
          Photos, GIFs, Links, Videos, Documents, Audio  ← 6 items
        [Messages header]
          ...
      Arrow-down from the search box lands on "Chats" section HEADER first,
      not on the first chat row. So pressing Enter opened nothing / wrong item.

    New strategy — NO arrow navigation at all:
      1. Walk every UI element in the sidebar scroll area
      2. Find the first group/row whose static text CONTAINS contact name
         (case-insensitive), skipping known section headers
      3. Click it directly
      4. Verify header matches, retry up to 3x
    """
    contact_lower = contact.lower().strip()

    # Section headers to skip when scanning rows
    SKIP_NAMES = {
        "chats", "groups", "groups in common", "media", "messages",
        "contacts", "people", "business", "photos", "gifs", "links",
        "videos", "documents", "audio",
    }

    click_script = f"""
tell application "System Events"
    tell process "WhatsApp"
        set frontmost to true
        delay 0.2
        set w to window 1

        -- Walk the sidebar (group 1) scroll area recursively
        try
            set sidebar to group 1 of w
            set sa to scroll area 1 of sidebar
            set theList to list 1 of sa

            -- Iterate top-level groups in the list
            set topGroups to every group of theList
            repeat with tg in topGroups
                -- Each tg is either a section header+children OR a direct row
                -- Try children first (section contains rows)
                set childGroups to every group of tg
                if (count of childGroups) > 0 then
                    repeat with child in childGroups
                        set childName to ""
                        try
                            set childName to name of static text 1 of child
                        end try
                        set childNameLow to do shell script "echo " & quoted form of childName & " | tr '[:upper:]' '[:lower:]'"
                        if childNameLow contains "{contact_lower}" and childName is not "" then
                            click child
                            return "CLICKED_CHILD:" & childName
                        end if
                    end repeat
                else
                    -- tg itself is a row (no children)
                    set rowName to ""
                    try
                        set rowName to name of static text 1 of tg
                    end try
                    set rowNameLow to do shell script "echo " & quoted form of rowName & " | tr '[:upper:]' '[:lower:]'"
                    if rowNameLow contains "{contact_lower}" and rowName is not "" then
                        click tg
                        return "CLICKED_ROW:" & rowName
                    end if
                end if
            end repeat
        end try
        return "NOT_FOUND"
    end tell
end tell
"""

    for attempt in range(3):
        _time.sleep(0.4 * (attempt + 1))
        try:
            r = _sp.run(["osascript", "-e", click_script],
                        capture_output=True, text=True, timeout=10)
            result = r.stdout.strip()
            logger.info("[WA_OPEN_V2] attempt=%d result=%s", attempt + 1, result)
        except Exception as exc:
            logger.warning("[WA_OPEN_V2] osascript error: %s", exc)
            result = ""

        if "CLICKED" in result:
            _time.sleep(1.2)
            header = _wa_get_chat_header()
            logger.info("[WA_OPEN_V2] header after click: %r", header)
            if contact_lower in header.lower():
                _wa_focus_message_box()
                return True
            # Header mismatch — maybe it opened but header read failed, try anyway
            if header:
                logger.warning("[WA_OPEN_V2] Header mismatch: got %r, expected %r", header, contact)

        # Re-search and retry
        if attempt < 2:
            _wa_keystroke_target("CLOSE_CHAT", target="whatsapp_desktop")
            _time.sleep(0.4)
            _wa_search_contact(contact)
            _time.sleep(1.0)

    logger.error("[WA_OPEN_V2] All attempts failed for contact=%r", contact)
    return False


def _wa_get_chat_text() -> str:
    try:
        script = """
tell application "System Events"
    tell process "WhatsApp"
        set chatText to ""
        try
            set allText to entire contents of window 1
            repeat with t in allText
                try
                    set chatText to chatText & (value of t) & "\n"
                end try
            end repeat
        end try
        return chatText
    end tell
end tell
"""
        result = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as exc:
        return f"Error reading chat: {exc}"



async def whatsapp_read_chat(contact: str, limit: int = 10, index: int = 1, skip_search: bool = False) -> str:
    loop = asyncio.get_running_loop()
    def _read():
        try:
            if not _wa_open_app():
                return "❌ WhatsApp Desktop app nahi khula."
            if not skip_search:
                if not _wa_search_contact(contact):
                    return f"❌ WhatsApp mein '{contact}' search nahi hua."
                _time.sleep(0.5)
                if not _wa_open_chat_verified(contact, index=index):
                    return f"❌ WhatsApp mein '{contact}' ka chat open nahi hua."
            text = _wa_get_chat_text()
            if not text or len(text.strip()) < 5:
                return f"❌ WhatsApp chat text read nahi hua."
            lines = []
            for raw in text.splitlines():
                line = " ".join(raw.split()).strip()
                if line and line not in lines:
                    lines.append(line)
            lines = lines[-limit * 4:]
            return f"--- {contact} WhatsApp chat ---\n" + "\n".join(lines)
        except Exception as exc:
            return f"❌ WhatsApp read error: {exc}"
    return await loop.run_in_executor(None, _read)


async def whatsapp_call(contact: str, video: bool = False, index: int = 1, skip_search: bool = False) -> str:
    """WhatsApp call karta hai — Desktop app only (Web calls disabled)."""
    loop = asyncio.get_running_loop()
    call_type = "video" if video else "voice"

    # ── PATCH 8: Fixed _call_desktop ─────────────────────────────────────────
    def _call_desktop() -> str:
        """
        WhatsApp Desktop se call — voice ya video.
        Flow: Open app → Search → Verify chat open → Keyboard shortcut
        """
        if not _wa_open_app():
            return "❌ WhatsApp Desktop app nahi mila. Mac pe install karo: whatsapp.com/download"

        if not _wa_search_contact(contact):
            return f"❌ WhatsApp mein '{contact}' search nahi hua."

        if not _wa_open_chat_verified(contact, index=index):
            return f"❌ WhatsApp mein '{contact}' ka chat open nahi hua."

        _time.sleep(0.5)  # Let chat fully render before calling

        shortcut = "VIDEO_CALL" if video else "VOICE_CALL"
        if _wa_keystroke_target(shortcut, target="whatsapp_desktop"):
            _time.sleep(2.0)
            logger.info("[WA_CALL] %s call triggered for %s", call_type, contact)
            return f"✅ '{contact}' ko WhatsApp {call_type} call laga diya."

        _time.sleep(0.5)
        if _wa_keystroke_target(shortcut, target="whatsapp_desktop"):
            return f"✅ '{contact}' ko WhatsApp {call_type} call laga diya."

        return (f"❌ WhatsApp {call_type} call trigger nahi hua. "
                "Chat toh open hua — manually call button click karo.")

    return await loop.run_in_executor(None, _call_desktop)


async def whatsapp_send_message(contact: str, message: str, index: int = 1, skip_search: bool = False) -> str:
    loop = asyncio.get_running_loop()
    def _send():
        try:
            if not _wa_open_app():
                return "❌ WhatsApp Desktop app nahi khula."
            if not skip_search:
                if not _wa_search_contact(contact):
                    return f"❌ WhatsApp mein '{contact}' search nahi hua."
                _time.sleep(0.5)
                if not _wa_open_chat_verified(contact, index=index):
                    return f"❌ WhatsApp mein '{contact}' ka chat open nahi hua."
            if not _wa_focus_message_box():
                return "❌ WhatsApp message box focus nahi hua."
            _wa_type_text(message)
            _time.sleep(0.3)
            _wa_press_enter()
            return f"✅ WhatsApp pe '{contact}' ko bhej diya: {message}"
        except Exception as exc:
            return f"❌ WhatsApp send error: {exc}"
    return await loop.run_in_executor(None, _send)


async def whatsapp_open_chat_only(contact: str, index: int = 1, skip_search: bool = False) -> str:
    loop = asyncio.get_running_loop()
    def _open():
        try:
            if not _wa_open_app():
                return "❌ WhatsApp Desktop app nahi khula."
            if skip_search:
                return f"✅ WhatsApp khul gaya."
            if not _wa_search_contact(contact):
                return f"❌ WhatsApp mein '{contact}' search nahi hua."
            _time.sleep(0.5)
            ok = _wa_open_chat_verified(contact, index=index)
            return (f"✅ WhatsApp pe '{contact}' ka chat khul gaya." if ok
                    else f"❌ WhatsApp mein '{contact}' ka chat open nahi hua.")
        except Exception as exc:
            return f"❌ WhatsApp open chat error: {exc}"
    return await loop.run_in_executor(None, _open)


# ══════════════════════════════════════════════════════════════════════════════
# INSTAGRAM
# ══════════════════════════════════════════════════════════════════════════════

_IG_INBOX_URL = "https://www.instagram.com/direct/inbox/"
_ig_logged_in: bool = False

_IG_NICKNAMES: dict[str, str] = {
    "sk":      "hey_imsk11",
    "vishal":  "vishal",
}

def _ig_resolve_username(name: str) -> str:
    return _IG_NICKNAMES.get(name.lower().strip(), name.strip().lstrip("@"))


def _ig_run_js(js: str, timeout: int = 8) -> str:
    return _run_js_in_browser(js, timeout=timeout)


def _ig_browser_url() -> str:
    return _ig_run_js("window.location.href", timeout=4)


def _ig_wait_for_url_change(away_from: str, timeout_s: float = 10.0) -> bool:
    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        current = _ig_browser_url()
        if away_from not in current:
            return True
        _time.sleep(0.8)
    return False


def _ig_open_browser_url(url: str) -> bool:
    log = logging.getLogger("vani.messaging.instagram")
    from urllib.parse import urlparse
    origin = urlparse(url).netloc

    for app_name in ["Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge"]:
        script = f'''
tell application "System Events"
    if not (exists process "{app_name}") then return "NOT_RUNNING"
end tell
tell application "{app_name}"
    activate
    set igTab to missing value
    set igWin to missing value
    repeat with w in windows
        repeat with t in tabs of w
            if URL of t contains "{origin}" then
                set igTab to t
                set igWin to w
                exit repeat
            end if
        end repeat
        if igTab is not missing value then exit repeat
    end repeat
    if igTab is not missing value then
        set active tab index of igWin to (index of igTab)
        set index of igWin to 1
        set URL of igTab to "{url}"
        return "NAVIGATED"
    else
        if (count of windows) is 0 then make new window
        tell front window
            set newTab to make new tab with properties {{URL:"{url}"}}
            set active tab index to (index of newTab)
        end tell
        return "NEW_TAB"
    end if
end tell
'''
        try:
            r = _sp.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
            result = r.stdout.strip()
            if result in ("NAVIGATED", "NEW_TAB"):
                log.info("[IG_OPEN_URL] %s → %s in %s", url[:60], result, app_name)
                return True
        except Exception:
            pass
    return False


def _ig_open_inbox() -> bool:
    log = logging.getLogger("vani.messaging.instagram")
    global _ig_logged_in

    if not _ig_open_browser_url(_IG_INBOX_URL):
        return False

    _time.sleep(3.0)
    current_url = _ig_browser_url()
    log.info("[IG_OPEN] Current URL: %s", current_url)

    if "/accounts/login" in current_url or "login" in current_url.lower():
        username = os.getenv("INSTAGRAM_USERNAME", "").strip()
        password = os.getenv("INSTAGRAM_PASSWORD", "").strip()
        if not username or not password:
            return False

        u = username.replace("'", "\\'")
        p = password.replace("'", "\\'")

        login_js = f"""
(function() {{
  var uField = document.querySelector('input[name="username"]');
  var pField = document.querySelector('input[name="password"]');
  if (!uField || !pField) return 'NO_FORM';
  var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  nativeInputValueSetter.call(uField, '{u}');
  uField.dispatchEvent(new Event('input', {{ bubbles: true }}));
  nativeInputValueSetter.call(pField, '{p}');
  pField.dispatchEvent(new Event('input', {{ bubbles: true }}));
  var loginBtn = document.querySelector('button[type="submit"]');
  if (loginBtn) {{ loginBtn.click(); return 'SUBMITTED'; }}
  return 'NO_BUTTON';
}})()
"""
        result = _ig_run_js(login_js, timeout=8)
        if result not in ("SUBMITTED", "NO_BUTTON"):
            return False
        if not _ig_wait_for_url_change("/accounts/login", timeout_s=12.0):
            return False
        _time.sleep(2.0)
        _ig_open_browser_url(_IG_INBOX_URL)
        _time.sleep(3.0)
        _ig_logged_in = True

    verify_js = """
(function() {
  if (document.querySelector('[role="listbox"]')) return 'LISTBOX';
  if (document.querySelector('div[data-testid="direct-thread-list"]')) return 'THREAD_LIST';
  if (window.location.pathname.includes('/direct/')) return 'URL_OK';
  return 'NOT_LOADED';
})()
"""
    verify = _ig_run_js(verify_js, timeout=6)
    return verify != "NOT_LOADED" and verify != ""


def _ig_open_dm(contact: str) -> bool:
    log = logging.getLogger("vani.messaging.instagram")
    if not _ig_open_inbox():
        return False

    search_js = """
(function() {
  var searchSelectors = [
    'svg[aria-label="New message"]',
    'a[href="/direct/new/"]',
  ];
  for (var sel of searchSelectors) {
    var btn = document.querySelector(sel);
    if (btn) { btn.click(); break; }
  }
  return 'SEARCH_CLICKED';
})()
"""
    _ig_run_js(search_js, timeout=4)
    _time.sleep(1.0)

    contact_safe = contact.replace("'", "\\'")
    type_js = f"""
(function() {{
  var inputs = document.querySelectorAll('input[placeholder], input[type="text"]');
  for (var inp of inputs) {{
    var ph = (inp.placeholder || '').toLowerCase();
    if (ph.includes('search') || ph.includes('to:') || ph.includes('name')) {{
      inp.focus();
      var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeInputValueSetter.call(inp, '{contact_safe}');
      inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
      return 'TYPED';
    }}
  }}
  return 'NO_INPUT';
}})()
"""
    _ig_run_js(type_js, timeout=5)
    _time.sleep(1.5)

    click_result_js = f"""
(function() {{
  var contact = '{contact_safe}'.toLowerCase();
  var candidates = document.querySelectorAll('[role="option"], [role="listitem"]');
  for (var el of candidates) {{
    if ((el.innerText || '').toLowerCase().includes(contact)) {{
      el.click();
      return 'CLICKED:' + (el.innerText || '').trim().slice(0, 40);
    }}
  }}
  var first = document.querySelector('[role="option"]');
  if (first) {{ first.click(); return 'CLICKED_FIRST'; }}
  return 'NO_RESULT';
}})()
"""
    click_r = _ig_run_js(click_result_js, timeout=5)
    _time.sleep(1.5)

    if "NO_RESULT" in click_r:
        _ig_open_browser_url(f"https://www.instagram.com/{contact}/")
        _time.sleep(2.0)

    current_url = _ig_browser_url()
    return "/direct/t/" in current_url or "CLICKED" in click_r


def _ig_send_message_in_open_chat(message: str) -> str:
    log = logging.getLogger("vani.messaging.instagram")
    msg_safe = message.replace("'", "\\'").replace("\n", " ")

    send_js = f"""
(function() {{
  var input = document.querySelector('div[role="textbox"][aria-label*="essage"]');
  if (!input) input = document.querySelector('div[contenteditable="true"][aria-label*="essage"]');
  if (!input) input = document.querySelector('div[contenteditable="true"]');
  if (!input) return 'NO_INPUT';

  input.focus();
  var sent = document.execCommand('insertText', false, '{msg_safe}');
  if (!sent) {{
    var dt = new DataTransfer();
    dt.setData('text/plain', '{msg_safe}');
    input.dispatchEvent(new ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true }}));
  }}
  input.dispatchEvent(new InputEvent('input', {{ bubbles: true }}));

  setTimeout(function() {{
    input.dispatchEvent(new KeyboardEvent('keydown', {{
      bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13
    }}));
  }}, 300);

  return 'SENT';
}})()
"""
    result = _ig_run_js(send_js, timeout=8)
    log.info("[IG_SEND_OPEN] JS result: %s", result)

    if result == "NO_INPUT":
        try:
            _sp.run("pbcopy", input=message.encode("utf-8"), check=True)
            _time.sleep(0.3)
            paste_script = """
tell application "System Events"
    keystroke "v" using command down
    delay 0.5
    key code 36
end tell
"""
            _sp.run(["osascript", "-e", paste_script], capture_output=True, timeout=5)
            return "SENT_VIA_KEYBOARD"
        except Exception as exc:
            return f"NO_INPUT_OR_KEYBOARD: {exc}"
    return result


async def instagram_read_dm(contact: str, limit: int = 10) -> str:
    log = logging.getLogger("vani.messaging.instagram")
    loop = asyncio.get_running_loop()
    def _read():
        if not _ig_open_dm(contact):
            return "❌ Instagram DMs load nahi hue."
        limit_val = int(limit)
        js = f"""
(function() {{
  var LIMIT = {limit_val};
  var seen = new Set();
  var msgs = [];
  var bubbles = document.querySelectorAll('[data-testid="message-container-text"] span');
  if (!bubbles || bubbles.length === 0)
    bubbles = document.querySelectorAll('div[dir="auto"] span[dir="auto"]');
  for (var el of bubbles) {{
    var t = (el.innerText || '').trim();
    if (t && t.length > 0 && t.length < 1000 && !seen.has(t)) {{
      seen.add(t);
      msgs.push(t);
    }}
  }}
  return msgs.slice(-LIMIT).join('\\n');
}})()
"""
        result = _ig_run_js(js, timeout=8)
        if not result or not result.strip():
            return f"❌ '{contact}' ke Instagram DMs empty hain."
        return f"--- {contact} Instagram DMs ---\n{result.strip()}"
    return await loop.run_in_executor(None, _read)


async def instagram_send_dm(contact: str, message: str) -> str:
    log = logging.getLogger("vani.messaging.instagram")
    loop = asyncio.get_running_loop()
    def _send():
        if not _ig_open_dm(contact):
            return f"❌ '{contact}' ka Instagram chat open nahi hua."
        result = _ig_send_message_in_open_chat(message)
        if "NO_INPUT" in result or "NO_INPUT_OR_KEYBOARD" in result:
            return "❌ Instagram message input box nahi mila."
        _time.sleep(1.2)
        return f"✅ Instagram pe '{contact}' ko bhej diya: {message}"
    return await loop.run_in_executor(None, _send)


async def instagram_list_dms(limit: int = 10) -> str:
    log = logging.getLogger("vani.messaging.instagram")
    loop = asyncio.get_running_loop()
    def _list():
        if not _ig_open_inbox():
            return "❌ Instagram inbox load nahi hua."
        limit_val = int(limit)
        js = f"""
(function() {{
  var LIMIT = {limit_val};
  var results = [];
  var threads = document.querySelectorAll('[role="listbox"] > [role="option"]');
  if (!threads || threads.length === 0)
    threads = document.querySelectorAll('div[role="list"] > div[role="listitem"]');
  for (var t of Array.from(threads).slice(0, LIMIT)) {{
    var spans = t.querySelectorAll('span');
    var name = spans[0] ? spans[0].innerText.trim() : '';
    var preview = spans[1] ? spans[1].innerText.trim().slice(0, 60) : '';
    if (name) results.push(name + (preview ? ': ' + preview : ''));
  }}
  return results.join('\\n');
}})()
"""
        result = _ig_run_js(js, timeout=8)
        if not result or not result.strip():
            return "❌ Instagram DM list load nahi hua."
        return "Recent Instagram DMs:\n" + result.strip()
    return await loop.run_in_executor(None, _list)


def _ig_get_first_thread_url() -> str:
    js = """
(function() {
  var opts = document.querySelectorAll('[role="listbox"] [role="option"] a, [role="option"] a');
  for (var a of opts) {
    if (a.href && a.href.includes('/direct/t/')) return a.href;
  }
  var links = document.querySelectorAll('a[href*="/direct/t/"]');
  if (links.length > 0) return links[0].href;
  return '';
})()
"""
    return _ig_run_js(js, timeout=5).strip()


def _ig_click_first_thread() -> bool:
    js = """
(function() {
  var opts = document.querySelectorAll('[role="listbox"] [role="option"], [role="option"]');
  if (opts.length > 0) { opts[0].click(); return 'CLICKED_OPTION'; }
  var links = document.querySelectorAll('a[href*="/direct/t/"]');
  if (links.length > 0) { links[0].click(); return 'CLICKED_LINK'; }
  return 'NO_THREAD_FOUND';
})()
"""
    result = _ig_run_js(js, timeout=5)
    return "NO_THREAD_FOUND" not in result and result != ""


def _ig_open_last_conversation() -> bool:
    log = logging.getLogger("vani.messaging.instagram")
    if not _ig_open_inbox():
        return False
    _time.sleep(1.5)
    thread_url = _ig_get_first_thread_url()
    if thread_url and "/direct/t/" in thread_url:
        _ig_open_browser_url(thread_url)
        _time.sleep(2.5)
        if "/direct/t/" in _ig_browser_url():
            return True
    if _ig_click_first_thread():
        _time.sleep(2.0)
        if "/direct/" in _ig_browser_url():
            return True
    return False


async def instagram_send_dm_to_last(message: str) -> str:
    loop = asyncio.get_running_loop()
    def _send():
        if not _ig_open_last_conversation():
            return "❌ Instagram ki last conversation open nahi hui."
        _time.sleep(1.0)
        result = _ig_send_message_in_open_chat(message)
        if "NO_INPUT" in result or "NO_INPUT_OR_KEYBOARD" in result:
            return "❌ Instagram message input box nahi mila."
        _time.sleep(1.5)
        return f"✅ Instagram last conversation mein bhej diya: {message}"
    return await loop.run_in_executor(None, _send)


async def instagram_send_dm_improved(contact: str, message: str) -> str:
    loop = asyncio.get_running_loop()
    def _send():
        if not _ig_open_inbox():
            return "❌ Instagram inbox load nahi hua."
        _time.sleep(2.0)
        contact_safe = contact.lstrip("@").replace("'", "\\'").lower()
        find_js = f"""
(function() {{
  var contact = '{contact_safe}';
  var opts = document.querySelectorAll('[role="option"]');
  for (var opt of opts) {{
    var text = (opt.innerText || '').toLowerCase();
    var link = opt.querySelector('a[href*="/direct/t/"]');
    if (text.includes(contact) && link) return link.href;
  }}
  return '';
}})()
"""
        thread_url = _ig_run_js(find_js, timeout=6).strip()
        if thread_url and "/direct/t/" in thread_url:
            _ig_open_browser_url(thread_url)
            _time.sleep(2.5)
        else:
            username = contact.lstrip("@")
            _ig_open_browser_url(f"https://www.instagram.com/{username}/")
            _time.sleep(2.5)
            msg_btn_js = """
(function() {
  var btns = document.querySelectorAll('button, [role="button"]');
  for (var b of btns) {
    var t = (b.innerText || b.getAttribute('aria-label') || '').toLowerCase();
    if (t.includes('message') || t.includes('msg')) { b.click(); return 'CLICKED_MSG_BTN'; }
  }
  return 'NO_MSG_BTN';
})()
"""
            _ig_run_js(msg_btn_js, timeout=5)
            _time.sleep(2.0)

        result = _ig_send_message_in_open_chat(message)
        if "NO_INPUT" in result or "NO_INPUT_OR_KEYBOARD" in result:
            return f"❌ '{contact}' ka Instagram chat open nahi hua."
        _time.sleep(1.5)
        return f"✅ Instagram pe '{contact}' ko bhej diya: {message}"
    return await loop.run_in_executor(None, _send)


# ══════════════════════════════════════════════════════════════════════════════
# MAC NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _get_notification_db_path() -> Optional[str]:
    try:
        import glob
        legacy = os.path.expanduser("~/Library/Application Support/NotificationCenter/*.db")
        found = glob.glob(legacy)
        if found:
            return found[0]
        r = _sp.run(["getconf", "DARWIN_USER_DIR"], capture_output=True, text=True)
        if r.returncode == 0:
            base = r.stdout.strip()
            path = os.path.join(base, "com.apple.notificationcenter", "db", "db")
            if os.path.exists(path):
                return path
    except Exception:
        pass
    return None


async def read_mac_notifications() -> str:
    loop = asyncio.get_running_loop()
    def _read():
        db_path = _get_notification_db_path()
        if not db_path:
            return "❌ Notification database nahi mila. Full Disk Access permission check karo."
        import sqlite3
        results = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT app.identifier, record.title, record.subtitle, record.body
                    FROM record
                    JOIN app ON record.app_id = app.app_id
                    ORDER BY record.delivered_date DESC
                    LIMIT 15
                """)
                rows = cur.fetchall()
                conn.close()
                for row in rows:
                    app, title, subtitle, body = row
                    results.append(f"[{app.split('.')[-1]}] {title or ''}: {body or subtitle or ''}")
            except Exception:
                cur.execute("SELECT app, title, subtitle, body FROM notifications ORDER BY date DESC LIMIT 15")
                rows = cur.fetchall()
                conn.close()
                for row in rows:
                    app, title, subtitle, body = row
                    results.append(f"[{app}] {title or ''}: {body or subtitle or ''}")
        except Exception as exc:
            return f"❌ Notification DB read error: {exc}. Full Disk Access required."
        return "\n".join(results) if results else "Koi recent notification nahi mili."
    return await loop.run_in_executor(None, _read)


async def read_whatsapp_notifications() -> str:
    loop = asyncio.get_running_loop()
    def _read():
        db_path = _get_notification_db_path()
        if not db_path:
            return "Notification database nahi mila."
        import sqlite3
        results = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT record.title, record.body
                    FROM record
                    JOIN app ON record.app_id = app.app_id
                    WHERE app.identifier LIKE '%WhatsApp%'
                    ORDER BY record.delivered_date DESC
                    LIMIT 10
                """)
            except Exception:
                cur.execute("SELECT title, body FROM notifications WHERE app LIKE '%WhatsApp%' ORDER BY date DESC LIMIT 10")
            rows = cur.fetchall()
            conn.close()
            for row in rows:
                title, body = row
                results.append(f"{title or ''}: {body or ''}")
        except Exception as exc:
            return f"Error: {exc}"
        return "\n".join(results) if results else "Koi WhatsApp notification nahi mili."
    return await loop.run_in_executor(None, _read)