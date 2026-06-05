"""
vani/security_state.py
━━━━━━━━━━━━━━━━━━━━━━
Tracks the security lockdown state for unverified speakers.

When voice verification is enabled and the speaker does NOT match Rudra's
voiceprint, Vani enters LOCKDOWN MODE:
  - Asks mandatory interrogation questions one by one
  - Blocks ALL command execution until all are answered
  - Requires MINIMUM word-length answers — one-word deflections are rejected
  - Only the voice system (not verbal claims) can clear lockdown
  - Threshold: VANI_SPEAKER_THRESHOLD (default 0.82, stricter than before)

State is session-scoped — resets when a new session starts.
"""

from __future__ import annotations

import logging
import threading
import os
import random

log = logging.getLogger("vani.security_state")

# ── Interrogation questions ───────────────────────────────────────────────────
# Expanded to 6 questions; asked one by one.
# Questions are in Hinglish — intentionally personal so only Rudra can answer.

INTERROGATION_QUESTIONS = [
    "Aap kaun hain? Apna poora naam batao.",
    "Aap Rudra ke laptop par kaise pahunche? Kisne access diya?",
    "Is waqt aap yahan kya kaam karne aaye hain?",
    "Rudra aapko jaante hain? Unse aapka kya rishta hai?",
    "Aapko is laptop ka password kaise pata chala, ya kisi ne diya?",
    "Agar main Rudra ko abhi call karun, toh woh aapko confirm karenge?",
]

# How many questions to actually ask before closing (all 6 by default)
REQUIRED_QUESTIONS = int(os.getenv("VANI_SECURITY_QUESTIONS", str(len(INTERROGATION_QUESTIONS))))

LOCKDOWN_OPENING = (
    "Ruko. Tumhari awaaz meri registered voiceprint se match nahi karti. "
    "Security protocol activate ho gaya hai. "
    "Jab tak tum mere sawalon ka jawab nahi dete — "
    "main koi bhi command execute nahi karungi, koi bhi kaam nahi karungi. "
    f"Pehla sawaal: {INTERROGATION_QUESTIONS[0]}"
)

LOCKDOWN_CLOSING = (
    "Maine tumhare jawab note kar liye hain. "
    "Lekin mere paas Rudra ki taraf se koi direct authorization nahi hai, "
    "isliye main abhi bhi koi kaam execute nahi kar sakti. "
    "Rudra ko personally aana hoga ya mujhe unka confirmed voice verification dena hoga. "
    "Tab tak main lockdown mein rehungi."
)

DEFLECT_TEMPLATE = (
    "Pehle yeh sawaal ka jawab do — {question} "
    "Jab tak jawab nahi milta, main bilkul kuch nahi karungi."
)

TOO_SHORT_RESPONSES = [
    "Yeh kafi nahi hai. Thoda detail mein batao — {question}",
    "Ek word se kaam nahi chalega. Poora jawab do — {question}",
    "Main samjhi nahi. Dobara, poori baat karo — {question}",
]

NEXT_QUESTION_PHRASES = [
    "Theek hai. Ab agla sawaal: {q}",
    "Samajh gayi. Ab batao — {q}",
    "Noted. Agle sawaal par: {q}",
    "Achha. Ab yeh batao — {q}",
]

# ── State ────────────────────────────────────────────────

_lock = threading.Lock()

_lockdown_active: bool = False
_current_question_idx: int = 0
_answers: list[str] = []
_opening_sent: bool = False
# Track how many times user gave a too-short answer in a row
_short_answer_streak: int = 0
MAX_SHORT_STREAK = 2  # after this many one-word answers, stop advancing

# ── Public API ──────────────────────────────────────────────

def is_verify_enabled() -> bool:
    """Return True if speaker verification is active in .env."""
    return os.getenv("VANI_SPEAKER_VERIFY", "0") == "1"


def activate_lockdown() -> None:
    """Enter lockdown mode. Called when voice mismatch is detected."""
    global _lockdown_active, _current_question_idx, _answers, _opening_sent, _short_answer_streak
    with _lock:
        _lockdown_active = True
        _current_question_idx = 0
        _answers = []
        _opening_sent = False
        _short_answer_streak = 0
    log.warning("security_state: LOCKDOWN ACTIVATED — unverified speaker (threshold=%.2f)",
                float(os.getenv("VANI_SPEAKER_THRESHOLD", "0.82")))


def deactivate_lockdown() -> None:
    """Exit lockdown mode. Called ONLY when voice system verifies the speaker."""
    global _lockdown_active, _current_question_idx, _answers, _opening_sent, _short_answer_streak
    with _lock:
        _lockdown_active = False
        _current_question_idx = 0
        _answers = []
        _opening_sent = False
        _short_answer_streak = 0
    log.info("security_state: lockdown deactivated — speaker verified by voiceprint")


def is_locked_down() -> bool:
    with _lock:
        return _lockdown_active


def all_questions_answered() -> bool:
    with _lock:
        return _current_question_idx >= REQUIRED_QUESTIONS


def opening_sent() -> bool:
    with _lock:
        return _opening_sent


def mark_opening_sent() -> None:
    global _opening_sent
    with _lock:
        _opening_sent = True


def get_current_question() -> str:
    with _lock:
        idx = _current_question_idx
    if idx < REQUIRED_QUESTIONS:
        return INTERROGATION_QUESTIONS[idx]
    return ""


def _is_answer_sufficient(answer: str) -> bool:
    """
    An answer is sufficient if it has at least 3 meaningful words.
    Single words, 'haan', 'nahi', 'pata nahi' alone are NOT sufficient.
    """
    words = answer.strip().split()
    # Reject pure deflections
    deflections = {"haan", "nahi", "na", "nope", "yes", "no", "ok", "okay",
                   "hmm", "uh", "um", "pata", "nahi pata", "idk", "dunno"}
    if len(words) <= 2 or answer.strip().lower() in deflections:
        return False
    return True


def record_answer(answer: str) -> bool:
    """
    Record the user's answer to the current question and advance to the next.
    Returns True if the answer was accepted, False if too short/deflecting.
    """
    global _current_question_idx, _short_answer_streak
    answer = (answer or "").strip()

    if not _is_answer_sufficient(answer):
        with _lock:
            _short_answer_streak += 1
        log.info("security_state: answer insufficient (%r), streak=%d", answer, _short_answer_streak)
        return False

    with _lock:
        if _current_question_idx < REQUIRED_QUESTIONS:
            _answers.append(answer)
            log.info(
                "security_state: Q%d answered: %r",
                _current_question_idx + 1, answer
            )
            _current_question_idx += 1
            _short_answer_streak = 0
    return True


def get_lockdown_response(user_text: str) -> str:
    """
    Given the user's latest speech, return what Vani should say in lockdown mode.

    Logic:
      - Opening not yet sent → return opening
      - All questions answered → closing (still locked, voice needed)
      - Answer too short → firm repeat with no progress
      - Answer accepted → ask next question
    """
    if not opening_sent():
        mark_opening_sent()
        return LOCKDOWN_OPENING

    accepted = record_answer(user_text)

    if all_questions_answered():
        return LOCKDOWN_CLOSING

    current_q = get_current_question()

    if not accepted:
        with _lock:
            streak = _short_answer_streak
        if streak >= MAX_SHORT_STREAK:
            # Firm, no more chances on this question
            return (
                f"Main seriously pooch rahi hoon — yeh koi option nahi hai. "
                f"Seedha jawab do: {current_q} "
                f"Varna main bilkul kuch nahi karungi."
            )
        return random.choice(TOO_SHORT_RESPONSES).format(question=current_q)

    return random.choice(NEXT_QUESTION_PHRASES).format(q=current_q)


def get_deflect_response() -> str:
    """Response when user tries to give a command instead of answering."""
    current_q = get_current_question()
    if not current_q:
        return LOCKDOWN_CLOSING
    return DEFLECT_TEMPLATE.format(question=current_q)


# ── Phase 8: Tool Safety Classifications & Gates ─────────────────────────────

import json
import time
import re
import sys
from vani.config import PROJECT_ROOT

# Safe: Read-only, simple computations, status checks
SAFE_TOOLS = {
    "google_search", "get_weather", "read_screen", "study_status",
    "talking_tom_control", "media_control", "youtube_control",
    "notifications_read", "whatsapp_read", "telegram_read",
    "fetch_stock_price", "sip_calculator", "calculate_emi",
    "tax_slab_info", "investment_compare", "compliance_calendar",
    "financial_ratio_explain", "close_active_tab", "next_tab", "previous_tab",
    "switch_tab_by_name", "close_tab_by_name", "close_all_tabs_by_name",
}

# Confirm Required: Modifies state, opens app, sends messages, browser crawls
CONFIRM_REQUIRED_TOOLS = {
    "whatsapp_send", "whatsapp_call", "telegram_send", "save_note",
    "write_code_to_file", "open_application", "close_application",
    "switch_application", "open_url", "open_youtube_and_play",
    "open_url_in_browser", "open_app_smart", "control_volume_tool",
    "move_cursor_tool", "mouse_click_tool", "scroll_cursor_tool",
    "type_text_tool", "press_key_tool", "press_hotkey_tool",
    "swipe_gesture_tool", "start_study_session", "end_study_session",
    "crawl_url", "whatsapp_open_chat", "whatsapp_shortcut", "telegram_chats"
}

# Sandboxed: Dangerous file execution, shell actions, or arbitrary code
SANDBOXED_TOOLS = {
    "code_assist", "folder_file", "Play_file", "app_search"
}

# Global approved tool calls dictionary: key: (tool_name, json_args_str) -> status
_tool_approvals: dict[tuple[str, str], bool] = {}
_approval_lock = threading.Lock()


class ToolPermissionGate:
    """
    Validates tool permissions based on classification level:
    - SAFE: Executes immediately.
    - CONFIRM_REQUIRED: Requires voice or environment authorization.
    - SANDBOXED: Requires strict confirmation.
    """

    @staticmethod
    def classify_tool(tool_name: str) -> str:
        if tool_name in SAFE_TOOLS:
            return "SAFE"
        elif tool_name in CONFIRM_REQUIRED_TOOLS:
            return "CONFIRM_REQUIRED"
        elif tool_name in SANDBOXED_TOOLS:
            return "SANDBOXED"
        # Default safety: anything unrecognized is CONFIRM_REQUIRED
        return "CONFIRM_REQUIRED"

    @staticmethod
    def approve_tool_execution(tool_name: str, args: dict) -> None:
        """Approve a specific tool execution with given arguments."""
        with _approval_lock:
            key = (tool_name, json.dumps(args, sort_keys=True))
            _tool_approvals[key] = True

    @staticmethod
    def clear_approvals() -> None:
        """Clear all pending/approved tool executions."""
        with _approval_lock:
            _tool_approvals.clear()

    @staticmethod
    def is_approved(tool_name: str, args: dict) -> bool:
        """Check if a tool execution is approved."""
        # Auto-approve if specified by environment (e.g. for testing)
        if os.getenv("VANI_AUTO_APPROVE_TOOLS", "0") == "1":
            return True
            
        with _approval_lock:
            key = (tool_name, json.dumps(args, sort_keys=True))
            return _tool_approvals.get(key, False)

    @classmethod
    def check_permission(cls, tool_name: str, args: dict) -> tuple[bool, str]:
        """
        Check if the tool execution is permitted.
        Returns:
            (is_permitted, action_required_description)
        """
        # If lockdown is active, reject EVERYTHING
        if is_locked_down():
            return False, "REJECTED_LOCKDOWN"

        level = cls.classify_tool(tool_name)
        if level == "SAFE":
            return True, "SAFE"

        if cls.is_approved(tool_name, args):
            return True, f"APPROVED_{level}"

        # Otherwise, requires confirmation
        return False, f"REQUIRES_CONFIRMATION_{level}"


# ── Phase 8: Log Scrubbing and Auditing ──────────────────────────────────────

def scrub_secrets(data: Any) -> Any:
    """
    Recursively scrub sensitive keys and values from strings/dicts/lists.
    """
    sensitive_keys = {
        "key", "api", "token", "password", "secret", "auth", "pwd", "credential"
    }
    
    # Fetch actual env secrets to do literal search-and-replace
    env_secrets = []
    for k, v in os.environ.items():
        if any(sk in k.lower() for sk in sensitive_keys) and len(v) > 4:
            env_secrets.append(v)

    def _scrub_val(val: Any) -> Any:
        if isinstance(val, str):
            scrubbed = val
            for secret in env_secrets:
                scrubbed = scrubbed.replace(secret, "[SCRUBBED]")
            # Regex patterns for keys, tokens, etc.
            scrubbed = re.sub(r"(?i)\b(api_?key|password|secret|token)\b\s*[:=]\s*['\"][^'\"]+['\"]", r"\1: '[SCRUBBED]'", scrubbed)
            return scrubbed
        elif isinstance(val, dict):
            new_dict = {}
            for k, v in val.items():
                if any(sk in k.lower() for sk in sensitive_keys):
                    new_dict[k] = "[SCRUBBED]"
                else:
                    new_dict[k] = _scrub_val(v)
            return new_dict
        elif isinstance(val, list):
            return [_scrub_val(item) for item in val]
        return val

    return _scrub_val(data)


class AuditLogger:
    """Logs agent actions, tool executions, and security validations to audit_log.jsonl."""

    @staticmethod
    def log_entry(agent: str, action_type: str, action_name: str, args: dict | Any, status: str, error: Optional[str] = None) -> None:
        try:
            log_dir = PROJECT_ROOT / "conversations"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "audit_log.jsonl"
            
            clean_args = scrub_secrets(args)
            
            entry = {
                "timestamp": time.time(),
                "agent": agent,
                "action_type": action_type,    # e.g. "tool", "delegate", "agent_run"
                "action_name": action_name,    # e.g. "google_search", "run"
                "arguments": clean_args,
                "status": status,              # e.g. "success", "failed", "requires_confirm", "blocked"
                "error": error
            }
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Error writing to audit log: {e}", file=sys.stderr)


# ── Phase 8: Environment Secret Validation ───────────────────────────────────

def validate_environment() -> dict[str, str]:
    """
    Validate environment variables and return a dictionary of validation issues (if any).
    Checks formatting, completeness, and safety constraints.
    """
    issues = {}
    
    # 1. Check Ollama url
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    if not (ollama_url.startswith("http://") or ollama_url.startswith("https://")):
        issues["OLLAMA_URL"] = f"Invalid URL format: {ollama_url}"
        
    # 2. Check threshold
    threshold_str = os.getenv("VANI_SPEAKER_THRESHOLD", "0.82")
    try:
        val = float(threshold_str)
        if not (0.0 <= val <= 1.0):
            issues["VANI_SPEAKER_THRESHOLD"] = f"Value must be between 0.0 and 1.0: {threshold_str}"
    except ValueError:
        issues["VANI_SPEAKER_THRESHOLD"] = f"Invalid float value: {threshold_str}"
        
    # 3. Check Speaker Verify settings
    verify_enabled = os.getenv("VANI_SPEAKER_VERIFY", "0")
    if verify_enabled not in ("0", "1"):
        issues["VANI_SPEAKER_VERIFY"] = f"Must be '0' or '1': {verify_enabled}"
        
    if issues:
        log.warning("Environment validation found issues: %s", issues)
    else:
        log.info("Environment validation passed successfully.")
        
    return issues


# Validate environment automatically on module load
validate_environment()
