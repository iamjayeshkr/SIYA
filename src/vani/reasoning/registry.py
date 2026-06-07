"""
vani/reasoning/registry.py
Central tool registry — imports every tool and exposes _TOOLS dict + _TOOL_DESCRIPTIONS string.
"""

from vani.reasoning.tools.apps import (
    open_application, close_application, switch_application,
    close_active_tab, next_tab, previous_tab,
    open_app_smart, open_url, open_url_in_browser, open_youtube_and_play,
    app_search, talking_tom_control, folder_file, Play_file,
    move_cursor_tool, mouse_click_tool, scroll_cursor_tool,
    type_text_tool, press_key_tool, press_hotkey_tool,
    control_volume_tool, swipe_gesture_tool,
)
from vani.reasoning.tools.messaging import (
    whatsapp_read, whatsapp_send, whatsapp_call, whatsapp_open_chat,
    whatsapp_shortcut, telegram_read, telegram_send, telegram_chats,
    notifications_read,
)
from vani.reasoning.tools.media import media_control
from vani.reasoning.tools.code import code_assist, write_code_to_file
from vani.reasoning.tools.notes import save_note
from vani.reasoning.tools.youtube import youtube_control
from vani.reasoning.tools.study_mode import (
    start_study_session, end_study_session, study_status,
)
from vani.reasoning.tools.mentor_mode import (
    start_mentor_mode, mentor_teach_next_concept, mentor_quiz_answer,
    mentor_status, mentor_toggle_roast, mentor_final_report,
)
from vani.reasoning.screen import (
    read_screen, learn_this, learn_name, google_search, get_weather,
)
from vani.tools.windows_system import windows_system_control

_TOOLS: dict = {
    "google_search":          google_search,
    "get_weather":            get_weather,
    "open_application":       open_application,
    "close_application":      close_application,
    "switch_application":     switch_application,
    "open_url":               open_url,
    "open_youtube_and_play":  open_youtube_and_play,
    "open_url_in_browser":    open_url_in_browser,
    "open_app_smart":         open_app_smart,
    "folder_file":            folder_file,
    "Play_file":              Play_file,
    "close_active_tab":       close_active_tab,
    "next_tab":               next_tab,
    "previous_tab":           previous_tab,
    "write_code_to_file":     write_code_to_file,
    "code_assist":            code_assist,
    "save_note":              save_note,
    "app_search":             app_search,
    "move_cursor_tool":       move_cursor_tool,
    "mouse_click_tool":       mouse_click_tool,
    "scroll_cursor_tool":     scroll_cursor_tool,
    "type_text_tool":         type_text_tool,
    "press_key_tool":         press_key_tool,
    "press_hotkey_tool":      press_hotkey_tool,
    "control_volume_tool":    control_volume_tool,
    "swipe_gesture_tool":     swipe_gesture_tool,
    "talking_tom_control":    talking_tom_control,
    "whatsapp_read":          whatsapp_read,
    "whatsapp_send":          whatsapp_send,
    "whatsapp_call":          whatsapp_call,
    "whatsapp_open_chat":     whatsapp_open_chat,
    "whatsapp_shortcut":      whatsapp_shortcut,
    "telegram_read":          telegram_read,
    "telegram_send":          telegram_send,
    "telegram_chats":         telegram_chats,
    "notifications_read":     notifications_read,
    "read_screen":            read_screen,
    "media_control":          media_control,
    "youtube_control":        youtube_control,
    "learn_name":             learn_name,
    "learn_this":             learn_this,
    "start_study_session":    start_study_session,
    "end_study_session":      end_study_session,
    "study_status":           study_status,
    "start_mentor_mode":          start_mentor_mode,
    "mentor_teach_next_concept":  mentor_teach_next_concept,
    "mentor_quiz_answer":         mentor_quiz_answer,
    "mentor_status":              mentor_status,
    "mentor_toggle_roast":        mentor_toggle_roast,
    "mentor_final_report":        mentor_final_report,
    "windows_system_control":     windows_system_control,
}

# FIX 19: Aliases split into a separate dict so real tools are enumerable
# without the aliases polluting the set. Qwen sometimes hallucinates these names.
_TOOL_ALIASES: dict[str, str] = {
    "whatsapp_chats":    "notifications_read",
    "whatsapp_messages": "whatsapp_read",
    "whatsapp_open":     "whatsapp_read",
    "whatsapp_search":   "whatsapp_read",
    "screen_read":       "read_screen",
    "analyze_screen":    "read_screen",
}


def resolve_tool(name: str):
    """Look up a tool by canonical name or alias. Returns the callable or None."""
    if name in _TOOLS:
        return _TOOLS[name]
    canonical = _TOOL_ALIASES.get(name)
    return _TOOLS.get(canonical) if canonical else None


# FIX 13: Auto-generate the LiveKit thinking description from the registry so
# it can never drift from the actual tool list. worker.py imports this instead
# of maintaining a hand-written string.
def get_thinking_description() -> str:
    """Return a short LiveKit tool description generated from _TOOLS."""
    tool_names = ", ".join(_TOOLS)
    return (
        "Use this for EVERY task the user gives: "
        + tool_names
        + ". Works on Mac and Windows. Runs in background — Vani stays free to talk."
    )

# ── PHASE 4: Dynamic registry ─────────────────────────────────────────────────
# Adds runtime tool registration alongside the static _TOOLS dict.
# _TOOLS is never modified — full backward compatibility with Qwen/ollama.py.
#
# Use cases:
#   • Platform-specific tools loaded at startup (mobile-only, Mac-only)
#   • Agent-specific tools added by specialized agents at import time
#   • Test/dev tools injected without editing this file
#
# Thread-safe: all mutations go through _registry_lock.

import threading as _threading

_registry_lock = _threading.Lock()
_dynamic_tools: dict = {}          # runtime-registered tools (never mixed into _TOOLS)
_dynamic_descriptions: list[str] = []  # per-tool description lines for each dynamic tool


def register_tool(name: str, fn, description: str = "") -> None:
    """
    Register a tool at runtime.

    Does NOT modify _TOOLS — existing Qwen/ollama path is unaffected.
    Dynamic tools are visible via get_tool() and list_tools() only.

    Args:
        name:        Tool name string (e.g. "my_mobile_tool")
        fn:          Callable — the tool implementation
        description: Optional one-line description appended to _TOOL_DESCRIPTIONS
                     for Qwen's context. Keep it short (same format as existing lines).

    Example:
        from vani.reasoning.registry import register_tool

        async def vibrate(duration_ms: int = 200):
            ...

        register_tool("vibrate", vibrate, "vibrate(duration_ms) - Phone vibrate karo")
    """
    with _registry_lock:
        _dynamic_tools[name] = fn
        if description:
            _dynamic_descriptions.append(description)


def unregister_tool(name: str) -> bool:
    """
    Remove a dynamically registered tool.

    Only affects _dynamic_tools — cannot remove static _TOOLS entries.

    Returns:
        True if the tool was found and removed, False if it wasn't registered.
    """
    with _registry_lock:
        if name in _dynamic_tools:
            del _dynamic_tools[name]
            return True
        return False


def get_tool(name: str):
    """
    Look up a tool by name — dynamic registry first, then static _TOOLS.

    Prefer this over direct _TOOLS access in new code so dynamic tools
    are transparently available.

    Returns:
        The callable, or None if not found in either registry.
    """
    with _registry_lock:
        return _dynamic_tools.get(name) or _TOOLS.get(name)


def list_tools() -> list[str]:
    """
    All available tool names — static _TOOLS + dynamic registry combined.

    Order: static tools first (preserving existing order), then dynamic.
    """
    with _registry_lock:
        return list(_TOOLS.keys()) + list(_dynamic_tools.keys())


def get_all_tool_descriptions() -> str:
    """Return a single string containing all static + dynamic tool descriptions."""
    with _registry_lock:
        dynamic_desc = "\n".join(_dynamic_descriptions)
    if dynamic_desc:
        return _TOOL_DESCRIPTIONS.strip() + "\n" + dynamic_desc
    return _TOOL_DESCRIPTIONS.strip()


def get_tools_for_agent(agent_name: str) -> dict:
    """
    Returns the tool callables owned by a given agent.

    Checks both static _TOOLS and dynamic registry.
    Mirrors the owned_tools list defined on each Agent class in vani/agents/.

    Args:
        agent_name: One of "browser", "communication", "coding", "vision",
                    "system", "file", "automation", "memory", "learning"

    Returns:
        dict mapping tool name → callable for all tools belonging to that agent.
        Empty dict for unknown agent names.
    """
    _AGENT_TOOLS: dict[str, list[str]] = {
        "browser": [
            "google_search", "open_url", "open_url_in_browser",
            "open_youtube_and_play", "youtube_control",
            "close_active_tab", "next_tab", "previous_tab", "app_search",
        ],
        "communication": [
            "whatsapp_send", "whatsapp_read", "whatsapp_call",
            "whatsapp_open_chat", "whatsapp_shortcut",
            "telegram_send", "telegram_read", "telegram_chats",
            "notifications_read",
        ],
        "coding": [
            "code_assist", "write_code_to_file",
        ],
        "vision": [
            "read_screen", "learn_this", "learn_name",
        ],
        "system": [
            "open_application", "close_application", "switch_application",
            "open_app_smart", "media_control", "control_volume_tool",
            "move_cursor_tool", "mouse_click_tool", "scroll_cursor_tool",
            "type_text_tool", "press_key_tool", "press_hotkey_tool",
            "swipe_gesture_tool", "talking_tom_control",
        ],
        "file": [
            "folder_file", "Play_file", "save_note", "app_search",
        ],
        "automation": [
            "start_study_session", "end_study_session", "study_status",
        ],
        "memory": [],       # memory agent uses direct API, not _TOOLS dispatch
        "learning": [
            "learn_this", "learn_name",
            "start_study_session", "end_study_session", "study_status",
        ],
    }
    names = _AGENT_TOOLS.get(agent_name, [])
    result: dict = {}
    with _registry_lock:
        for n in names:
            tool = _dynamic_tools.get(n) or _TOOLS.get(n)
            if tool is not None:
                result[n] = tool
    return result


def registry_stats() -> dict:
    """
    Returns a snapshot of registry state.
    Useful for health-check endpoints and debugging.

    Returns:
        {
          "static_count":  int,   # number of tools in _TOOLS
          "dynamic_count": int,   # number of runtime-registered tools
          "total":         int,
          "dynamic_names": list[str],
        }
    """
    with _registry_lock:
        return {
            "static_count":  len(_TOOLS),
            "dynamic_count": len(_dynamic_tools),
            "total":         len(_TOOLS) + len(_dynamic_tools),
            "dynamic_names": list(_dynamic_tools.keys()),
        }


# ── Extend get_thinking_description to include dynamic tools ──────────────────
# Monkey-patch the existing function so Qwen's tool list stays current
# even when dynamic tools are added after startup.
_original_get_thinking_description = get_thinking_description


def get_thinking_description() -> str:  # type: ignore[no-redef]
    """
    Return LiveKit tool description — now includes dynamic tools.
    Overrides the original to stay in sync with the full registry.
    """
    with _registry_lock:
        all_names = list(_TOOLS.keys()) + list(_dynamic_tools.keys())
    return (
        "Use this for EVERY task the user gives: "
        + ", ".join(all_names)
        + ". Works on Mac and Windows. Runs in background — Vani stays free to talk."
    )

# ─────────────────────────────────────────────────────────────────────────────

_TOOL_DESCRIPTIONS = """
google_search(query)                       - Google par search karo
get_weather(city)                          - Kisi city ka weather lo
open_application(app_name)                 - Koi bhi app open karo
close_application(app_name)                - Koi bhi app band karo
switch_application(app_name)               - Kisi app par jao (switch)
open_url(url)                              - URL browser mein kholo
open_youtube_and_play(song_or_query)       - YouTube par song/video chalao
open_url_in_browser(url, browser)          - Specific browser mein URL kholo
open_app_smart(app_name)                   - Smart app opener
folder_file(command)                       - File/folder operations
Play_file(name)                            - File dhundh ke chalao
close_active_tab()                         - Browser tab close karo
next_tab()                                 - Next tab par jao
previous_tab()                             - Previous tab par jao
write_code_to_file(filename, code, folder) - Code file banao VS Code mein
code_assist(command, filename)             - Existing code/comments/problem padhkar same language mein solution likho
save_note(title, content)                  - Note/plan/list Desktop pe save karo
app_search(query)                          - Spotlight/Windows Search se dhundho
move_cursor_tool(x, y)                     - Mouse cursor move karo
mouse_click_tool(x, y, button)             - Mouse click karo
scroll_cursor_tool(x, y, amount)           - Scroll karo
type_text_tool(text)                       - Text type karo
press_key_tool(key)                        - Key press karo
press_hotkey_tool(keys)                    - Hotkey press karo
control_volume_tool(action, level)         - Volume control karo
swipe_gesture_tool(direction)              - Swipe gesture karo
talking_tom_control(action)                - Talking Tom mode on/off/status
whatsapp_read(contact, limit, selection)   - WhatsApp chat padhna
whatsapp_send(contact, message, selection) - WhatsApp pe message bhejna
whatsapp_call(contact, call_type, selection) - WhatsApp se call karna (call_type: 'voice'/'video')
whatsapp_open_chat(contact, selection)     - WhatsApp pe chat kholna (search only)
whatsapp_shortcut(action)                  - WhatsApp Web shortcut: next_chat/end_call/mute_mic/archive_chat/etc.
telegram_read(contact, limit)              - Telegram chat padhna
telegram_send(contact, message)            - Telegram pe message bhejna
telegram_chats()                           - Recent Telegram chats list
notifications_read(app)                    - Mac notifications padhna (all/whatsapp)
read_screen(query)                         - Screen ka screenshot le ke analyze karo
media_control(action)                      - Media control karo (play/pause/next/previous)
youtube_control(query)                     - YouTube seek/play/pause/next/prev/close/fullscreen/mute — "10 min forward", "30s back", "tab close", "Shape of You bajao"
learn_name(name, phonetic, lang)           - Naam ka pronunciation seekho aur yaad rakho
learn_this(content, raw)                   - Fact/preference/quiz permanently save karo
start_study_session(subject, duration_min) - Study session shuru karo — DND on, tabs band, timer start
end_study_session(reason)                  - Study session khatam karo, stats dikhao
study_status()                             - Timer check karo, kitna time bacha hai — "yaad rakhna", "remember this", "seekho", "baad mein puchna" — "screen dekho", "yeh kya hai", "explain this"
start_mentor_mode(roast_mode, mode_type)   - Start Vani Document/Repository Mentor Mode study session
mentor_teach_next_concept()                - Select and explain the next unmastered concept on the roadmap
mentor_quiz_answer(user_answer)            - Submit user answer for current concept quiz evaluation
mentor_status()                            - Check study session statistics and progress dashboard
mentor_toggle_roast(level)                 - Change Roast Mode level (Off, Light, Medium, Savage)
mentor_final_report()                      - Generate final study summary report once coverage is 100%
windows_system_control(action, query)      - Windows system optimization, settings change, app force control, and low-level PowerShell commands
"""
