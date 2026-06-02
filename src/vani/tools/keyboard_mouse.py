"""
keyboard_mouse_control.py — Cross-Platform Edition (Windows + Mac)
pyautogui + pynput work on both platforms natively.
Volume control uses OS-specific commands where needed.
"""

import sys
import asyncio
import time
import subprocess
import logging
from datetime import datetime
from typing import List
from langchain_core.tools import tool
import codecs

logger = logging.getLogger(__name__)

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

_pyautogui = None

def _ensure_pyautogui():
    """Lazy-load pyautogui once and cache it. Avoids 1-2s import penalty at startup."""
    global _pyautogui
    if _pyautogui is None:
        import importlib
        _pyautogui = importlib.import_module("pyautogui")
    return _pyautogui


# ── Controller ────────────────────────────────────────────────────────────────

class SafeController:
    def __init__(self):
        self.active          = False
        self._keyboard       = None
        self._mouse          = None
        self.valid_keys      = set("abcdefghijklmnopqrstuvwxyz1234567890")

    @property
    def keyboard(self):
        if self._keyboard is None:
            from pynput.keyboard import Controller as KeyboardController
            self._keyboard = KeyboardController()
        return self._keyboard

    @property
    def mouse(self):
        if self._mouse is None:
            from pynput.mouse import Controller as MouseController
            self._mouse = MouseController()
        return self._mouse

    @property
    def special_keys(self):
        from pynput.keyboard import Key
        return {
            "enter":     Key.enter,     "space":     Key.space,
            "tab":       Key.tab,       "shift":     Key.shift,
            "ctrl":      Key.ctrl,      "alt":       Key.alt,
            "esc":       Key.esc,       "backspace": Key.backspace,
            "delete":    Key.delete,    "up":        Key.up,
            "down":      Key.down,      "left":      Key.left,
            "right":     Key.right,     "caps_lock": Key.caps_lock,
            "cmd":       Key.cmd,       "win":       Key.cmd,
            "home":      Key.home,      "end":       Key.end,
            "page_up":   Key.page_up,   "page_down": Key.page_down,
        }

    def resolve_key(self, key):
        return self.special_keys.get(key.lower(), key)

    def log(self, action: str):
        logger.info(f"SafeController action: {action}")

    def activate(self, token=None):
        if token != "my_secret_token":
            return
        self.active = True

    def deactivate(self):
        self.active = False

    def is_active(self):
        return self.active

    # ── Mouse ──────────────────────────────────────────────────────────────

    async def move_cursor(self, direction: str, distance: int = 100):
        if not self.is_active(): return "🛑 Controller inactive hai."
        x, y = self.mouse.position
        moves = {"left": (-distance, 0), "right": (distance, 0),
                 "up": (0, -distance),   "down":  (0, distance)}
        dx, dy = moves.get(direction, (0, 0))
        self.mouse.position = (x + dx, y + dy)
        await asyncio.sleep(0.2)
        self.log(f"Mouse moved {direction}")
        return f"🖱️ Mouse {direction} move ho gaya."

    async def mouse_click(self, button: str = "left"):
        if not self.is_active(): return "🛑 Controller inactive hai."
        from pynput.mouse import Button
        clicks = {"left": (Button.left, 1), "right": (Button.right, 1), "double": (Button.left, 2)}
        btn, count = clicks.get(button, (Button.left, 1))
        self.mouse.click(btn, count)
        await asyncio.sleep(0.2)
        self.log(f"Mouse click: {button}")
        return f"🖱️ {button.capitalize()} click ho gaya."

    async def scroll_cursor(self, direction: str, amount: int = 10):
        if not self.is_active(): return "🛑 Controller inactive hai."
        dy = amount if direction == "up" else -amount
        self.mouse.scroll(0, dy)
        await asyncio.sleep(0.2)
        self.log(f"Scroll {direction}")
        return f"🖱️ Scroll {direction} ho gaya."

    # ── Keyboard ───────────────────────────────────────────────────────────

    async def type_text(self, text: str):
        if not self.is_active(): return "🛑 Controller inactive hai."
        from pynput.keyboard import Key
        try:
            text = codecs.decode(text, "unicode_escape")
        except Exception:
            pass
        for char in text:
            try:
                if char == "\n":
                    self.keyboard.press(Key.enter); self.keyboard.release(Key.enter)
                elif char == "\t":
                    self.keyboard.press(Key.tab);   self.keyboard.release(Key.tab)
                elif char.isprintable():
                    self.keyboard.press(char);      self.keyboard.release(char)
                await asyncio.sleep(0.04)
            except Exception:
                continue
        self.log(f"Typed: {text}")
        return f"⌨️ Type ho gaya: {text}"

    async def press_key(self, key: str):
        if not self.is_active(): return "🛑 Controller inactive hai."
        if key.lower() not in self.special_keys and key.lower() not in self.valid_keys:
            return f"❌ Invalid key: {key}"
        k = self.resolve_key(key)
        self.keyboard.press(k); self.keyboard.release(k)
        await asyncio.sleep(0.2)
        self.log(f"Key pressed: {key}")
        return f"⌨️ '{key}' press ho gaya."

    async def press_hotkey(self, keys: List[str]):
        if not self.is_active(): return "🛑 Controller inactive hai."
        resolved = []
        for k in keys:
            if k.lower() not in self.special_keys and k.lower() not in self.valid_keys:
                return f"❌ Invalid key: {k}"
            resolved.append(self.resolve_key(k))
        for k in resolved:         self.keyboard.press(k)
        for k in reversed(resolved): self.keyboard.release(k)
        await asyncio.sleep(0.3)
        self.log(f"Hotkey: {' + '.join(keys)}")
        return f"⌨️ Hotkey {' + '.join(keys)} press ho gaya."

    # ── Volume (cross-platform) ────────────────────────────────────────────

    async def control_volume(self, action: str, step: int = 10):
        if not self.is_active(): return "🛑 Controller inactive hai."
        try:
            if IS_MAC:
                # AppleScript volume control — system-wide, no focus needed
                step = max(1, min(step, 100))
                scripts = {
                    "up":     f'set volume output volume (output volume of (get volume settings) + {step})',
                    "down":   f'set volume output volume (output volume of (get volume settings) - {step})',
                    "mute":   'set volume with output muted',
                    "unmute": 'set volume without output muted',
                }
                script = scripts.get(action)
                if script:
                    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3)
            elif IS_WINDOWS:
                keys = {"up": "volumeup", "down": "volumedown", "mute": "volumemute"}
                if action in keys:
                    _ensure_pyautogui().press(keys[action])
        except Exception as e:
            return f"❌ Volume control failed: {e}"
        self.log(f"Volume: {action}")
        return f"🔊 Volume {action} ho gaya."

    # ── Swipe ──────────────────────────────────────────────────────────────

    async def swipe_gesture(self, direction: str):
        if not self.is_active(): return "🛑 Controller inactive hai."
        pag = _ensure_pyautogui()
        sw, sh = pag.size()
        cx, cy = sw // 2, sh // 2
        swipes = {
            "up":    ((cx, cy + 200), (cx, cy - 200)),
            "down":  ((cx, cy - 200), (cx, cy + 200)),
            "left":  ((cx + 200, cy), (cx - 200, cy)),
            "right": ((cx - 200, cy), (cx + 200, cy)),
        }
        if direction in swipes:
            start, end = swipes[direction]
            pag.moveTo(*start)
            pag.dragTo(*end, duration=0.5)
        await asyncio.sleep(0.5)
        self.log(f"Swipe: {direction}")
        return f"🖱️ Swipe {direction} ho gaya."


controller = SafeController()

async def _with_activation(fn, *args, **kwargs):
    controller.activate("my_secret_token")
    result = await fn(*args, **kwargs)
    await asyncio.sleep(1.5)
    controller.deactivate()
    return result


# ── Exported tools ─────────────────────────────────────────────────────────────

@tool
async def move_cursor_tool(direction: str, distance: int = 100) -> str:
    """
    Mouse cursor ko kisi direction mein move karta hai.
    direction: up / down / left / right. distance pixels mein (default 100).
    Example: "Mouse right move karo 200 pixels"
    """
    return await _with_activation(controller.move_cursor, direction, distance)

@tool
async def mouse_click_tool(button: str = "left") -> str:
    """
    Mouse click karta hai. button: left / right / double.
    Example: "Left click karo" / "Double click karo"
    """
    return await _with_activation(controller.mouse_click, button)

@tool
async def scroll_cursor_tool(direction: str, amount: int = 10) -> str:
    """
    Screen scroll karta hai. direction: up / down. amount: scroll steps.
    Example: "Neeche scroll karo" / "Upar scroll karo"
    """
    return await _with_activation(controller.scroll_cursor, direction, amount)

@tool
async def type_text_tool(text: str) -> str:
    """
    Text type karta hai jaise keyboard se. Kisi bhi active field mein.
    Example: "Hello World type karo" / "Email mein ye likho: ..."
    """
    return await _with_activation(controller.type_text, text)

@tool
async def press_key_tool(key: str) -> str:
    """
    Ek key press karta hai. enter / esc / tab / backspace / up / down etc.
    Example: "Enter dabao" / "Escape press karo"
    """
    return await _with_activation(controller.press_key, key)

@tool
async def press_hotkey_tool(keys: List[str]) -> str:
    """
    Keyboard shortcut press karta hai. keys ek list mein do.
    Example: ["cmd", "s"] Mac par save. ["ctrl", "c"] Windows par copy.
    """
    return await _with_activation(controller.press_hotkey, keys)

@tool
async def control_volume_tool(action: str, step: int = 10) -> str:
    """
    System volume control karta hai. action: up / down / mute / unmute.
    step: volume change amount (default 10, range 1-100).
    Mac aur Windows dono par kaam karta hai.
    Example: "Volume badhao" / "Sound band karo" / "Awaaz 20 badha do"
    """
    # Volume control uses AppleScript (Mac) or key press (Windows) —
    # both are system-global and don't need window focus.
    # We skip _with_activation's 1.5s sleep since no activation needed.
    controller.activate("my_secret_token")
    result = await controller.control_volume(action, step)
    controller.deactivate()
    return result

@tool
async def swipe_gesture_tool(direction: str) -> str:
    """
    Screen par swipe gesture simulate karta hai. direction: up / down / left / right.
    Example: "Upar swipe karo" / "Left swipe karo"
    """
    return await _with_activation(controller.swipe_gesture, direction)