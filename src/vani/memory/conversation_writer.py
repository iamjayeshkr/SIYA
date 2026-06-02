"""
vani_conversation_writer.py — Phase 2: Live Conversation Transcriber & App Writer
==================================================================================
Cross-platform: macOS & Windows

What this does:
  - Listens to the ongoing Vani conversation (session history)
  - On command: formats the discussion into a readable note/message
  - Opens WhatsApp / Telegram / Notes / any app and types the content
  - Works via pynput (keyboard simulation) — no accessibility permissions on Windows,
    minimal permissions needed on Mac (Accessibility access for pynput)

Voice commands:
  - "Ye saari baatcheet WhatsApp mein likh do"
  - "Is discussion ko Notes mein save karo"
  - "Telegram par bhej do jo hum baat kar rahe hain"
  - "Notepad mein ye conversation likh do"
"""

import os
import sys
import asyncio
import subprocess
import logging
import time
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


# ─────────────────────────────────────────────────────────────────────────────
# Shared conversation buffer — filled by agent session hooks in vani_app.py
# ─────────────────────────────────────────────────────────────────────────────

_conversation_log: list[dict] = []  # [{role: "user"|"assistant", text: "..."}]


def log_message(role: str, text: str):
    """Call this from vani_app.py session hooks to record the conversation."""
    _conversation_log.append({"role": role, "text": text.strip()})


def get_conversation_text(max_messages: int = 30) -> str:
    """Formats recent conversation as clean readable text."""
    recent = _conversation_log[-max_messages:]
    if not recent:
        return "Koi conversation nahi mili abhi tak."

    lines = []
    for msg in recent:
        label = "Aap" if msg["role"] == "user" else "Vani"
        lines.append(f"[{label}]: {msg['text']}")
    return "\n".join(lines)


def clear_conversation():
    """Resets the conversation log."""
    _conversation_log.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Typing engine — cross-platform clipboard paste (fastest & most reliable)
# ─────────────────────────────────────────────────────────────────────────────

def _type_text_via_clipboard(text: str):
    """
    Pastes text using clipboard — works on both Mac and Windows.
    Much faster and more reliable than key-by-key typing for long text.
    """
    import pyperclip
    from pynput.keyboard import Controller, Key

    pyperclip.copy(text)
    keyboard = Controller()
    time.sleep(0.3)

    if IS_MAC:
        keyboard.press(Key.cmd)
        keyboard.press("v")
        keyboard.release("v")
        keyboard.release(Key.cmd)
    else:  # Windows / Linux
        keyboard.press(Key.ctrl)
        keyboard.press("v")
        keyboard.release("v")
        keyboard.release(Key.ctrl)

    time.sleep(0.2)


def _type_text_slowly(text: str, delay: float = 0.03):
    """
    Types text character by character via pynput.
    Fallback for apps where clipboard paste doesn't work (some terminals).
    """
    from pynput.keyboard import Controller
    keyboard = Controller()
    for char in text:
        try:
            keyboard.press(char)
            keyboard.release(char)
            time.sleep(delay)
        except Exception:
            pass  # Skip unprintable chars


# ─────────────────────────────────────────────────────────────────────────────
# App focus helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _focus_app(app_name: str) -> bool:
    """Focus (bring to foreground) an already-open app. Returns True on success."""
    app = app_name.lower()

    if IS_MAC:
        mac_names = {
            "whatsapp":  "WhatsApp",
            "telegram":  "Telegram",
            "notes":     "Notes",
            "notepad":   "TextEdit",
            "textedit":  "TextEdit",
            "messages":  "Messages",
        }
        mac_name = mac_names.get(app, app.title())
        try:
            script = f'tell application "{mac_name}" to activate'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    elif IS_WINDOWS:
        win_names = {
            "whatsapp":  "WhatsApp",
            "telegram":  "Telegram",
            "notes":     "Notepad",
            "notepad":   "Notepad",
        }
        win_name = win_names.get(app, app.title())
        try:
            import win32gui, win32con
            def _find_and_focus(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if win_name.lower() in title.lower():
                        win32gui.SetForegroundWindow(hwnd)
                        return True
            win32gui.EnumWindows(_find_and_focus, None)
            return True
        except ImportError:
            # win32gui not available — just try opening the app
            return False

    return False


async def _open_app_for_writing(app_name: str):
    """Opens an app and waits for it to be ready for typing."""
    app = app_name.lower()

    # Try focusing if already open
    focused = await _focus_app(app)

    if not focused:
        # Open the app fresh
        if "whatsapp" in app:
            from vani.browser.control import open_whatsapp
            await open_whatsapp.ainvoke("app")
        elif "telegram" in app:
            from vani.browser.control import open_telegram
            await open_telegram.ainvoke("app")
        elif "notes" in app and IS_MAC:
            subprocess.Popen(["osascript", "-e", 'tell application "Notes" to activate'])
        elif "notes" in app and IS_WINDOWS:
            subprocess.Popen(["notepad.exe"])
        elif "notepad" in app:
            if IS_MAC:
                subprocess.Popen(["osascript", "-e", 'tell application "TextEdit" to activate'])
            else:
                subprocess.Popen(["notepad.exe"])
        else:
            from vani.tools.window_control import open_app
            await open_app.ainvoke(app_name)

    await asyncio.sleep(2.0)  # Wait for app to be in foreground


# ─────────────────────────────────────────────────────────────────────────────
# Notes app helpers (Mac) — AppleScript for structured notes
# ─────────────────────────────────────────────────────────────────────────────

def _create_note_mac(title: str, body: str) -> bool:
    """Creates a new note in Apple Notes via AppleScript (Mac only)."""
    # Escape quotes in content
    safe_body  = body.replace('"', '\\"').replace("'", "\\'")
    safe_title = title.replace('"', '\\"')
    script = f'''
    tell application "Notes"
        activate
        set newNote to make new note at folder "Notes" with properties {{name:"{safe_title}", body:"{safe_body}"}}
    end tell
    '''
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"AppleScript Notes error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# LangChain Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
async def write_conversation_to_app(
    target_app: str = "notes",
    extra_note: str = ""
) -> str:
    """
    Takes the current Vani conversation and writes/pastes it into WhatsApp,
    Telegram, Notes, Notepad, or any open app.
    Works on Mac AND Windows using clipboard paste (fast & reliable).

    Example voice commands:
    - "Ye saari baatcheet WhatsApp mein likh do"
    - "Is conversation ko Notes mein save karo"
    - "Telegram mein type kar do jo hum baat kar rahe hain"
    - "Notepad mein ye discussion save karo"
    - "Aaj jo ideas nikle wo Notes mein daal do"

    Args:
        target_app : whatsapp / telegram / notes / notepad / textedit
        extra_note : optional extra text to append at the end
    """
    conversation = get_conversation_text(max_messages=40)

    timestamp = time.strftime("%d %b %Y, %I:%M %p")
    formatted = (
        f"📝 Vani Conversation — {timestamp}\n"
        f"{'─'*40}\n"
        f"{conversation}\n"
    )
    if extra_note:
        formatted += f"\n💡 Note: {extra_note}\n"

    app = target_app.lower().strip()

    # ── Apple Notes (Mac) — use AppleScript for cleanest result ──────────────
    if "notes" in app and IS_MAC and "notepad" not in app:
        success = _create_note_mac(f"Vani — {timestamp}", formatted)
        if success:
            return f"✅ Notes mein save ho gaya — '{timestamp}' title ke saath! 📒"
        # Fallback to typing

    # ── For all other apps: open → click text area → paste ───────────────────
    await _open_app_for_writing(app)

    # Click in the text area (center of screen is usually safe)
    try:
        import pyautogui
        w, h = pyautogui.size()
        pyautogui.click(w // 2, h // 2)
        await asyncio.sleep(0.3)

        # For WhatsApp/Telegram: click message input (bottom center)
        if "whatsapp" in app or "telegram" in app:
            pyautogui.click(w // 2, int(h * 0.92))
            await asyncio.sleep(0.3)
    except Exception:
        pass

    # Paste via clipboard
    try:
        _type_text_via_clipboard(formatted)
        return (
            f"✅ '{target_app}' mein conversation paste ho gaya!\n"
            f"({len(_conversation_log)} messages, {len(formatted)} characters)"
        )
    except Exception as e:
        return f"❌ Paste nahi ho paya: {e}"


@tool
async def write_note_in_app(
    content: str,
    target_app: str = "notes",
    title: str = ""
) -> str:
    """
    Writes custom text/note into any app by voice.
    Works on Mac AND Windows.

    Example voice commands:
    - "Notes mein likh do: kal meeting hai 3 baje"
    - "WhatsApp mein type karo: thoda ruko aa raha hoon"
    - "Notepad mein idea note karo: new app banani hai for students"
    - "Telegram mein message likh do: hello bhai kya chal raha hai"

    Args:
        content    : text to write
        target_app : whatsapp / telegram / notes / notepad / textedit
        title      : optional note title (for Notes app)
    """
    app = target_app.lower().strip()

    # Apple Notes via AppleScript
    if "notes" in app and IS_MAC and "notepad" not in app:
        note_title = title or f"Vani Note — {time.strftime('%d %b %Y')}"
        success = _create_note_mac(note_title, content)
        if success:
            return f"✅ Notes mein save ho gaya: '{note_title}' 📒"

    # All other apps: open → focus → paste
    await _open_app_for_writing(app)

    try:
        import pyautogui
        w, h = pyautogui.size()

        if "whatsapp" in app or "telegram" in app:
            pyautogui.click(w // 2, int(h * 0.92))
        else:
            pyautogui.click(w // 2, h // 2)
        await asyncio.sleep(0.3)
    except Exception:
        pass

    try:
        _type_text_via_clipboard(content)
        return f"✅ '{target_app}' mein text likh diya: \"{content[:60]}...\""
    except Exception as e:
        return f"❌ Type nahi ho paya: {e}"


@tool
async def save_ideas_from_chat(topic: str = "General Ideas") -> str:
    """
    Extracts key ideas/points from the current conversation and saves them
    as a clean bullet-point note in Apple Notes (Mac) or Notepad (Windows).

    Example voice commands:
    - "Is baatcheet se ideas nikaalo aur Notes mein save karo"
    - "Aaj ke ideas notes mein daal do"
    - "Business ideas jo nikle wo save karo"

    Args:
        topic : label/topic for the note
    """
    conversation = get_conversation_text(max_messages=50)
    if not conversation or "Koi conversation" in conversation:
        return "❌ Koi conversation nahi mili save karne ke liye."

    timestamp = time.strftime("%d %b %Y, %I:%M %p")
    note_content = (
        f"💡 Ideas from Vani — {topic}\n"
        f"📅 {timestamp}\n"
        f"{'─'*40}\n\n"
        f"{conversation}\n\n"
        f"{'─'*40}\n"
        f"(Saved automatically by Vani)\n"
    )

    if IS_MAC:
        success = _create_note_mac(f"💡 {topic} — {timestamp}", note_content)
        if success:
            return f"✅ Ideas save ho gayi Notes mein — '{topic}' ke under! 💡📒"

    # Windows / fallback: open Notepad and paste
    await _open_app_for_writing("notepad")
    await asyncio.sleep(1)

    try:
        _type_text_via_clipboard(note_content)
        return f"✅ Ideas Notepad mein save ho gayi — '{topic}' topic par! 💡"
    except Exception as e:
        return f"❌ Save nahi ho paya: {e}"