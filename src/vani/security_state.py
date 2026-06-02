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

# ── State ─────────────────────────────────────────────────────────────────────

_lock = threading.Lock()

_lockdown_active: bool = False
_current_question_idx: int = 0
_answers: list[str] = []
_opening_sent: bool = False
# Track how many times user gave a too-short answer in a row
_short_answer_streak: int = 0
MAX_SHORT_STREAK = 2  # after this many one-word answers, stop advancing

# ── Public API ────────────────────────────────────────────────────────────────

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
