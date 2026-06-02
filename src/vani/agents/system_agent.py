"""
vani/agents/system_agent.py — Phase 3

Handles all system/OS-level intents:
  app open/close/switch, media playback control, volume,
  mouse & keyboard automation, swipe gestures, voice enrollment.

Wraps:
  - reasoning/tools/apps.py   → open_application, close_application, switch_application,
                                 open_app_smart, talking_tom_control,
                                 move_cursor_tool, mouse_click_tool, scroll_cursor_tool,
                                 type_text_tool, press_key_tool, press_hotkey_tool,
                                 control_volume_tool, swipe_gesture_tool
  - reasoning/tools/media.py  → media_control
  - services/voice_enrollment → VOICE_ENROLL, VOICE_DELETE, VOICE_STATUS (via router)

Phase 3: delegates to _dispatch_intent — zero behavior change.
Future:  add platform adapter integration (Phase 9), scheduled app switching,
         macro recording and playback.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class SystemAgent(BaseAgent):
    name = "system"
    description = (
        "App open/close/switch, media control, volume, "
        "mouse/keyboard automation, voice enrollment"
    )
    owned_tools = [
        "open_application",
        "close_application",
        "switch_application",
        "open_app_smart",
        "media_control",
        "control_volume_tool",
        "move_cursor_tool",
        "mouse_click_tool",
        "scroll_cursor_tool",
        "type_text_tool",
        "press_key_tool",
        "press_hotkey_tool",
        "swipe_gesture_tool",
        "talking_tom_control",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route system intents through the existing deterministic dispatcher.

        Intents handled:
          APP_OPEN, APP_CLOSE, APP_SWITCH, MEDIA_CONTROL, VOLUME_*,
          CURSOR_MOVE, MOUSE_CLICK, SCROLL, TYPE_TEXT, KEY_PRESS, HOTKEY,
          SWIPE_GESTURE, TALKING_TOM_*, VOICE_ENROLL, VOICE_DELETE, VOICE_STATUS

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)
