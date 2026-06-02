"""
vani/reasoning/__init__.py
Public API for the vani.reasoning package.
"""

from vani.reasoning.worker import (
    thinking_capability,
    get_thinking_capability_tool,
    register_session,
    say_to_user,
    speak_to_user_from_thread,
    ask_realtime_from_text,
    ask_realtime_from_text_thread,
)

from vani.reasoning.hinglish_speech import (
    normalize_for_tts,
    get_speech_prompt_block,
)

from vani.reasoning.teaching_tool import (
    TeachingEngine,
    get_teaching_prompt_block,
)

__all__ = [
    "thinking_capability",
    "get_thinking_capability_tool",
    "register_session",
    "say_to_user",
    "speak_to_user_from_thread",
    "ask_realtime_from_text",
    "ask_realtime_from_text_thread",
    # Hinglish TTS
    "normalize_for_tts",
    "get_speech_prompt_block",
    # Teaching engine
    "TeachingEngine",
    "get_teaching_prompt_block",
]
