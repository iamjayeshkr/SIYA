"""
vani/persona/__init__.py — Phase 1 + Phase 5

VANI's frozen identity and response personality filter.

Phase 1: get_persona(), persona_summary(), wrap_with_persona() — identity exports.
Phase 5: wrap_response_with_persona() — post-execution personality hook.
         Currently a passthrough; will inject Hinglish warmth in a later iteration.

Usage:
    from vani.persona import get_persona, wrap_with_persona, wrap_response_with_persona

    persona = get_persona()
    spoken  = wrap_response_with_persona(raw_result, query="open youtube", intent="YOUTUBE_PLAY")
"""

from __future__ import annotations

# Import the single source of truth — defined once in prompts.py
from vani.prompts import VANI_PERSONA


def get_persona() -> dict:
    """
    Returns VANI's frozen identity dict.

    Always returns a copy — callers cannot mutate the original.
    No agent, planner, or tool should modify the returned dict
    and expect changes to propagate; call get_persona() again for
    a fresh copy if needed.

    Returns:
        dict with keys: name, owner, age, tone, language, humor,
                        emotion_level, assistant_type, speaking_style,
                        prohibitions
    """
    return dict(VANI_PERSONA)


def persona_summary() -> str:
    """
    Returns a compact human-readable string of the persona.
    Useful for injecting into agent prompts as a reminder of identity constraints.

    Example output:
        Vani (18) | Tone: soft, friendly, warm | Style: Hinglish | Owner: Rudra
    """
    p = VANI_PERSONA
    return (
        f"{p['name']} ({p['age']}) | "
        f"Tone: {p['tone']} | "
        f"Style: {p['language']} | "
        f"Owner: {p['owner']}"
    )


def wrap_with_persona(raw_response: str) -> str:
    """
    Post-processing hook: ensures agent responses pass through VANI's
    personality filter before being spoken or displayed.

    Phase 1: identity-safe passthrough — returns raw_response unchanged.
    Phase 5: wrap_response_with_persona() is the richer version — use that
             when intent + query context is available.

    Args:
        raw_response: text produced by a tool, agent, or LLM

    Returns:
        Personality-filtered response (passthrough until warmth injection lands)
    """
    return raw_response


def wrap_response_with_persona(raw_result: str, query: str = "", intent: str = "") -> str:
    """
    Phase 5 personality response hook.

    Sits between the executor result and what Vani speaks/displays.
    Called by the Worker Twin (brain.py) after execute_plan() returns.

    Current behaviour (Phase 5):
      Passthrough — Gemini Realtime naturally rephrases tool output in Vani's voice,
      so no additional processing is needed here yet.

    Future behaviour (later iteration):
      For bare tool outputs that Gemini won't see (e.g. background task results
      sent via WebSocket or TTS-only paths), this will:
        1. Strip robotic prefixes ("Result:", "Output:", etc.)
        2. Inject Hinglish warmth based on intent type
        3. Enforce prohibitions from VANI_PERSONA["prohibitions"]
        4. Route to a lightweight LLM call for phrasing if result is a raw data dump

    Args:
        raw_result:  String returned by execute_plan() or a tool
        query:       Original user query (for context — not shown to Rudra)
        intent:      Router intent string (for intent-aware phrasing)

    Returns:
        Personality-filtered result string (currently unchanged).
    """
    # Passthrough — Gemini Realtime handles phrasing for now.
    # Future: inject warmth, strip robotic patterns, enforce prohibitions.
    return raw_result


__all__ = [
    "get_persona",
    "persona_summary",
    "wrap_with_persona",
    "wrap_response_with_persona",
    "VANI_PERSONA",
]
