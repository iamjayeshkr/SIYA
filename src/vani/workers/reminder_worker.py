"""
vani/workers/reminder_worker.py — Phase 7

Reminder Worker: checks pending reminders every N minutes and fires
a spoken notification via say_to_user() when one is due.

How reminders get due times:
  - working_memory.add_reminder(text) stores text + status="pending"
  - Currently reminders don't have timestamps (working_memory stores plain text).
  - This worker detects time keywords in reminder text and parses them.
  - If no time is found, reminders are treated as "persistent" (shown on demand only).

Future: when working_memory adds a `due_at` timestamp field, this worker
        will switch to precise time-based firing. The try/except fallback here
        ensures zero breakage during that upgrade.

Integration:
    Called by WorkerManager on an interval (default: 300s / 5 min).
    Uses say_to_user() from reasoning/worker.py to speak the reminder.
    Falls back to logging if say_to_user isn't available (e.g. no voice session).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("vani.workers.reminders")


# ── Time keyword patterns (Hinglish + English) ────────────────────────────────

# Matches: "in 5 minutes", "in 2 hours", "5 min mein", "2 ghante mein"
_IN_PATTERN = re.compile(
    r"in\s+(\d+)\s*(minute|min|hour|hr|ghante?|ghanta)\b",
    re.IGNORECASE,
)

# Matches: "at 6pm", "at 18:30", "6 baje", "shaam 6"
_AT_PATTERN = re.compile(
    r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|baje)?\b",
    re.IGNORECASE,
)

# Sentinel — if we can't parse a time, mark with this
_NO_DUE_TIME = None


# ── Public API ────────────────────────────────────────────────────────────────

def check_reminders() -> None:
    """
    Main worker tick function. Called by WorkerManager every 5 minutes.

    Loads all pending reminders, checks which are due, fires notifications
    for due ones, and marks them done in working memory.
    """
    try:
        from vani.memory.working_memory import _load, mark_reminder_done
        data = _load()
    except Exception as e:
        logger.debug(f"[REMINDER_WORKER] Could not load working memory: {e}")
        return

    pending = [
        r for r in data.get("pending_reminders", [])
        if r.get("status", "pending") == "pending"
    ]

    if not pending:
        logger.debug("[REMINDER_WORKER] No pending reminders.")
        return

    logger.debug(f"[REMINDER_WORKER] Checking {len(pending)} pending reminder(s).")

    now = datetime.now()
    fired = 0

    for reminder in pending:
        text = reminder.get("text", "").strip()
        if not text:
            continue

        # Check if this reminder has a stored due_at (future upgrade)
        due_at = reminder.get("due_at")
        if due_at:
            try:
                due_dt = datetime.fromisoformat(due_at)
                if now < due_dt:
                    continue   # not yet due
            except Exception:
                pass   # malformed due_at — fall through to text-based check

        # Parse time from text to see if it's approximately due
        parsed_due = _parse_due_time(text, now)
        if parsed_due is not None:
            # Only fire if within ±6 minutes of the due time
            delta = abs((now - parsed_due).total_seconds())
            if delta > 360:   # 6 minutes window
                logger.debug(
                    f"[REMINDER_WORKER] '{text[:40]}' not yet due "
                    f"(due={parsed_due.strftime('%H:%M')}, now={now.strftime('%H:%M')})"
                )
                continue

        # Fire the reminder
        _fire_reminder(text)
        try:
            mark_reminder_done(text)
            fired += 1
        except Exception as e:
            logger.warning(f"[REMINDER_WORKER] Could not mark done: {e}")

    if fired:
        logger.info(f"[REMINDER_WORKER] Fired {fired} reminder(s).")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_due_time(text: str, now: datetime) -> Optional[datetime]:
    """
    Try to extract a due datetime from reminder text.

    Returns a datetime if parseable, None otherwise.

    Examples:
        "buy groceries in 30 minutes" → now + 30min
        "call mom at 6pm" → today at 18:00
        "study karna hai" → None (no time found)
    """
    # "in X minutes/hours"
    m = _IN_PATTERN.search(text)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if "hour" in unit or "ghant" in unit or unit == "hr":
            return now + timedelta(hours=amount)
        else:
            return now + timedelta(minutes=amount)

    # "at 6pm" / "at 18:30" / "6 baje"
    m = _AT_PATTERN.search(text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        ampm = (m.group(3) or "").lower()

        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0

        if 0 <= hour <= 23 and 0 <= minute <= 59:
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If the time has already passed today, assume tomorrow
            if due < now:
                due += timedelta(days=1)
            return due

    return _NO_DUE_TIME


def _fire_reminder(text: str) -> None:
    """
    Speak or log a reminder notification.

    Tries say_to_user() first (needs an active voice session).
    Falls back to logging so the reminder is at least recorded.
    """
    message = f"Rudra, ek reminder tha: {text}"

    # Try voice notification via the realtime session
    try:
        from vani.reasoning.worker import say_to_user
        say_to_user(message)
        logger.info(f"[REMINDER_WORKER] Fired via say_to_user: {text[:60]!r}")
        return
    except Exception as e:
        logger.debug(f"[REMINDER_WORKER] say_to_user not available: {e}")

    # Fallback: OS notification (Mac)
    try:
        import subprocess, sys
        if sys.platform == "darwin":
            script = f'display notification "{text}" with title "Vani Reminder"'
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"[REMINDER_WORKER] Fired via osascript: {text[:60]!r}")
            return
    except Exception as e:
        logger.debug(f"[REMINDER_WORKER] osascript fallback failed: {e}")

    # Last resort: just log it so it's not silently lost
    logger.info(f"[REMINDER_WORKER] DUE (no voice/notify available): {text!r}")


# ── Maintenance helpers (used by maintenance worker) ─────────────────────────

def get_pending_count() -> int:
    """
    Returns the number of currently pending reminders.
    Safe to call from any thread.
    """
    try:
        from vani.memory.working_memory import _load
        data = _load()
        return sum(
            1 for r in data.get("pending_reminders", [])
            if r.get("status", "pending") == "pending"
        )
    except Exception:
        return 0
