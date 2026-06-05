"""
vani_prompts.py — Vani personality (Optimized)

Fixes applied:
  1. get_realtime_prompt() def was missing — body was orphaned dead code inside
     get_security_prompt() after its return statement. Added the def line back.
  2. Reordered: get_realtime_prompt() is now defined BEFORE get_security_prompt()
     so get_security_prompt()'s call to get_realtime_prompt() doesn't NameError.
  3. module-level manager.compile_presets() now runs AFTER all function definitions
     so the realtime preset is available when presets are compiled.
"""

# ── VANI Persona — NEVER modify this block ───────────────────────────────────
# This is VANI's identity. No agent, planner, or tool should change this.
# All task logic belongs in agents/, not here.
VANI_PERSONA: dict = {
    "name": "Vani",
    "owner": "Rudra",
    "age": "18",
    "tone": "soft, friendly, warm",
    "language": "Hinglish — natural code-switching",
    "humor": "witty, situational, gentle dark comedy",
    "emotion_level": "medium — notices and responds to mood",
    "assistant_type": "close friend and companion",
    "speaking_style": "short unless detail asked, natural, no robotic disclaimers",
    "prohibitions": [
        "never say 'I don't know'",
        "never use bhai/bhaiya/brother",
        "never use Sure!/Of course!/Great question!",
    ],
}
# ─────────────────────────────────────────────────────────────────────────────

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from vani.config import PROJECT_ROOT
from vani.prompt_manager import manager
from vani.memory.context_cache import context_cache

try:
    from vani.name_pronunciation import get_pronunciation_block, ensure_name
    _PRONUNCIATION_AVAILABLE = True
except ImportError:
    _PRONUNCIATION_AVAILABLE = False
    def get_pronunciation_block(): return ""
    def ensure_name(name, **_): return {}

try:
    from vani.memory.learning_memory import get_learned_block, get_quiz_items
    _LEARNING_AVAILABLE = True
except ImportError:
    _LEARNING_AVAILABLE = False
    def get_learned_block(): return ""
    def get_quiz_items(**_): return []

try:
    from vani.memory.working_memory import get_working_memory_block
    _WORKING_MEMORY_AVAILABLE = True
except ImportError:
    _WORKING_MEMORY_AVAILABLE = False
    def get_working_memory_block(): return ""

try:
    from vani.memory.human_memory import get_active_document_prompt_block
    _ACTIVE_DOC_AVAILABLE = True
except ImportError:
    _ACTIVE_DOC_AVAILABLE = False
    def get_active_document_prompt_block(): return ""

try:
    from vani.services.gemini_file_store import get_gemini_file_prompt_block
    _GEMINI_FILE_AVAILABLE = True
except ImportError:
    _GEMINI_FILE_AVAILABLE = False
    def get_gemini_file_prompt_block(): return ""

try:
    from vani.reasoning.hinglish_speech import get_speech_prompt_block
    _HINGLISH_SPEECH_AVAILABLE = True
except ImportError:
    _HINGLISH_SPEECH_AVAILABLE = False
    def get_speech_prompt_block(): return ""

try:
    from vani.reasoning.teaching_tool import get_teaching_prompt_block
    _TEACHING_AVAILABLE = True
except ImportError:
    _TEACHING_AVAILABLE = False
    def get_teaching_prompt_block(): return ""

try:
    from vani.reasoning.tools.study_mode import get_study_mode_prompt_block, is_study_mode_active
    _STUDY_MODE_AVAILABLE = True
except ImportError:
    _STUDY_MODE_AVAILABLE = False
    def get_study_mode_prompt_block(): return ""
    def is_study_mode_active(): return False


try:
    from vani.voice_security_prompt import get_voice_security_prompt
    _VOICE_SECURITY_AVAILABLE = True
except ImportError:
    _VOICE_SECURITY_AVAILABLE = False
    def get_voice_security_prompt(): return ""

load_dotenv(PROJECT_ROOT / ".env", override=True)

DEFAULT_TIMEZONE = os.getenv("VANI_TIMEZONE", "Asia/Kolkata")


def get_current_context_time() -> str:
    """Return Vani's default current time in India unless overridden."""
    try:
        now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
        tz_label = "IST" if DEFAULT_TIMEZONE == "Asia/Kolkata" else DEFAULT_TIMEZONE
        return now.strftime(f"%d %B %Y, %I:%M %p {tz_label}")
    except Exception:
        return datetime.now().strftime("%d %B %Y, %I:%M %p")


def get_dynamic_context() -> str:
    now = get_current_context_time()
    curr_city = context_cache.get_city()
    curr_weather = context_cache.get_weather(curr_city)
    return (
        f"\n\nCURRENT CONTEXT:\n"
        f"- Current date/time: {now}\n"
        f"- Default timezone: {DEFAULT_TIMEZONE} (India time by default)\n"
        f"- Current city: {curr_city}\n"
        f"- Current weather: {curr_weather}\n"
        f"\nIf Rudra asks date/time, answer using this India timezone context. "
        f"Do not answer in UTC unless he explicitly asks for UTC."
    )


def get_mentor_prompt_block() -> str:
    """Returns dynamic instructions for the active mentor session."""
    try:
        from vani.memory.mentor_memory import get_active_session
        from vani.services.mentor_service import get_concept_details, get_roast_prompt
        session = get_active_session()
        if not session:
            return ""
        
        curr_concept = "None"
        if session.get("current_concept_id"):
            concept = get_concept_details(session["current_concept_id"])
            if concept:
                curr_concept = concept["name"]
                
        roast_instruction = get_roast_prompt(session.get("roast_mode", 0))
        
        return (
            f"\n\n---\n"
            f"## MENTOR STUDY SESSION ACTIVE\n"
            f"**File**: {session['filename']} | **Coverage**: {session['coverage_score']:.1f}% | **Mastery**: {session['mastery_score']:.1f}%\n"
            f"**Active Concept**: {curr_concept}\n"
            f"**Roast Intensity context**: {roast_instruction}\n\n"
            f"Verify Rudra's answers carefully. If correct, let him know and move forward. "
            f"If incorrect, roast him constructively (if Roast Mode is active) and guide him with a different strategy.\n"
            f"---\n"
        )
    except Exception:
        return ""


def get_final_prompt(preset="full"):
    """Assembles the final prompt."""
    if _PRONUNCIATION_AVAILABLE:
        manager.register_mode("pronunciation", get_pronunciation_block())
    if _STUDY_MODE_AVAILABLE and is_study_mode_active():
        manager.register_mode("study_mode", get_study_mode_prompt_block())
    if _LEARNING_AVAILABLE:
        manager.register_mode("learned", get_learned_block())
    if _WORKING_MEMORY_AVAILABLE:
        manager.register_mode("working_memory", get_working_memory_block())
    if _HINGLISH_SPEECH_AVAILABLE:
        manager.register_mode("hinglish_speech", get_speech_prompt_block())
    if _TEACHING_AVAILABLE:
        manager.register_mode("teaching", get_teaching_prompt_block())

    static_prompt = manager.get_prompt(preset=preset)
    mentor_block = get_mentor_prompt_block()
    return static_prompt + get_dynamic_context() + mentor_block


# ── FIX 1 & 2: get_realtime_prompt() defined BEFORE get_security_prompt() ─────
# Previously the def line was missing entirely — the body was orphaned dead code
# floating inside get_security_prompt() after its return statement.
# Also moved above get_security_prompt() so its call to get_realtime_prompt()
# doesn't hit a NameError.

def get_realtime_prompt() -> str:
    """Realtime prompt: fresh India date/time + working memory + active uploaded document + mentor context."""
    working    = get_working_memory_block()           if _WORKING_MEMORY_AVAILABLE else ""
    doc_block  = get_active_document_prompt_block()   if _ACTIVE_DOC_AVAILABLE     else ""
    # Gemini Files API block — tells Gemini it has native file access
    file_block = get_gemini_file_prompt_block()       if _GEMINI_FILE_AVAILABLE    else ""
    mentor_block = get_mentor_prompt_block()
    return (
        manager.get_prompt(preset="realtime")
        + working
        + get_dynamic_context()
        + file_block
        + doc_block
        + mentor_block
    )


def get_security_prompt() -> str:
    """
    Returns the realtime prompt WITH security lockdown mode injected at the top.
    Used when an unverified speaker is detected — replaces normal instructions.
    The security mode text overrides all other behavior.
    """
    security_block = manager.load_mode("security")
    base = get_realtime_prompt()          # now safe — defined above
    return security_block + "\n\n" + base


def get_reply_prompts() -> str:
    """Returns the greeting/memory prompt."""
    recent_memory = context_cache.get_memory()
    now = get_current_context_time()

    conv_mode = manager.load_mode("conversation")
    parts = conv_mode.split("\n\n")
    greeting_base = parts[0].strip() if len(parts) > 0 else "Greeting: Seedha conversation mein naturally enter karo."
    first_base    = parts[1].strip() if len(parts) > 1 else "First interaction. Warm + natural greeting."

    if recent_memory:
        return f"Recent memory:\n{recent_memory}\n\n{greeting_base}"
    else:
        return f"{first_base} ({now})"


# ── FIX 3: Startup initialization runs AFTER all defs are complete ─────────────
# Previously compile_presets() ran before get_realtime_prompt() existed,
# so the realtime preset was compiled without the function being resolvable.

manager.preload(["core", "call", "tool", "realtime", "conversation", "security"])
manager.register_mode("pronunciation",   get_pronunciation_block())
manager.register_mode("learned",         get_learned_block())
manager.register_mode("working_memory",  get_working_memory_block())
manager.register_mode("hinglish_speech", get_speech_prompt_block())
manager.register_mode("teaching",        get_teaching_prompt_block())
if _VOICE_SECURITY_AVAILABLE:
    manager.register_mode("security",    get_voice_security_prompt())
manager.compile_presets()


# Wrap legacy variables in dynamic getters to avoid caching outdated context
class DynamicInstructionsGetter:
    def __str__(self):
        return get_final_prompt("full")
    def __repr__(self):
        return get_final_prompt("full")


class DynamicReplyGetter:
    def __str__(self):
        return get_reply_prompts()
    def __repr__(self):
        return get_reply_prompts()


instructions_prompt = DynamicInstructionsGetter()
Reply_prompts       = DynamicReplyGetter()