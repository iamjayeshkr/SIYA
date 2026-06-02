"""
vani/planner/verifier.py — Phase 5

Verification layer: inspects tool results before they reach the response pipeline.

Role in the flow:
    _dispatch_intent → result → verify_result() → [retry?] → persona layer → Vani speaks

What the verifier does:
  1. Detects empty or clearly failed results
  2. Classifies failure type (empty, error string, tool crash, side-effect mismatch)
  3. Advises the executor: ok to pass / retry safe / do not retry
  4. Logs verification decisions for self-improvement (Phase 8)

What the verifier does NOT do:
  - Never generates user-facing text
  - Never calls tools
  - Never modifies the result string (returns it as-is or signals failure)
  - Never blocks — all operations are synchronous and fast

Integration point (executor.py):
    result = await _dispatch_intent(...)
    ok, verified_result, advice = verify_result(intent, result, raw_query)
    if not ok and advice.retryable:
        result = await _dispatch_intent(...)   # one retry
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("vani.planner.verifier")


# ── Failure signal sets ───────────────────────────────────────────────────────
# Split by severity so the verifier can distinguish transient vs permanent errors.

# Hard failures — tool crashed or returned a definitive error
_HARD_FAILURE_SIGNALS: tuple[str, ...] = (
    "❌",
    "Error:",
    "error:",
    "Exception",
    "Traceback",
    "nahi ho paya",
    "nahi kar saka",
)

# Soft failures — may be transient (timeout, network, not-ready)
_SOFT_FAILURE_SIGNALS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "not found",
    "nahi mila",
    "failed",
    "connection",
    "unavailable",
)

# Success signals — if these appear, override any soft failure match
# (e.g. "WhatsApp not found" might be a success message for open_chat)
_SUCCESS_OVERRIDES: tuple[str, ...] = (
    "✅",
    "bhej diya",
    "sent",
    "opened",
    "playing",
    "done",
    "ho gaya",
    "complete",
)

# Intents whose results are hard to verify (UI-only feedback — no string confirmation)
_UNVERIFIABLE_INTENTS: frozenset[str] = frozenset({
    "APP_OPEN",
    "APP_CLOSE",
    "APP_SWITCH",
    "BROWSER_TAB_CLOSE",
    "BROWSER_TAB_NEXT",
    "BROWSER_TAB_PREV",
    "MEDIA_CONTROL",
    "VOLUME_SET",
    "SWIPE_GESTURE",
    "MOUSE_CLICK",
    "CURSOR_MOVE",
    "KEY_PRESS",
    "HOTKEY",
    "TYPE_TEXT",
})

# Intents with side effects — a second call would duplicate the action
_NO_RETRY_INTENTS: frozenset[str] = frozenset({
    "WHATSAPP_SEND",
    "WHATSAPP_CALL",
    "TELEGRAM_SEND",
    "INSTAGRAM_SEND",
    "SAVE_NOTE",
    "WRITE_CODE_TO_FILE",
})


# ── Result object ─────────────────────────────────────────────────────────────

@dataclass
class VerifyResult:
    """
    Outcome of verify_result().

    Attributes:
        ok:          True if the result looks valid; False if it looks like a failure.
        result:      The (unmodified) result string.
        retryable:   True if the executor should attempt one retry.
        reason:      Short human-readable reason for the verdict (for logging only).
        failure_type: "none" | "empty" | "hard" | "soft" | "unverifiable"
    """
    ok: bool
    result: str
    retryable: bool
    reason: str
    failure_type: str = "none"


# ── Public API ────────────────────────────────────────────────────────────────

def verify_result(intent: str, result: str, query: str = "") -> VerifyResult:
    """
    Inspect a tool result and decide if it's valid.

    Args:
        intent:  Router intent string (e.g. "WHATSAPP_SEND", "GOOGLE_SEARCH")
        result:  Raw string returned by the tool / _dispatch_intent
        query:   Original user query (for logging context only)

    Returns:
        VerifyResult — verdict, retryability, and reason.

    The executor should:
        vr = verify_result(intent, result, query)
        if not vr.ok and vr.retryable:
            result = await retry(...)
    """
    intent_upper = (intent or "").upper()

    # ── 1. Unverifiable intents — UI actions with no string confirmation ──────
    if intent_upper in _UNVERIFIABLE_INTENTS:
        logger.debug(f"[VERIFIER] {intent_upper} — unverifiable (UI action), passing through")
        return VerifyResult(
            ok=True,
            result=result or "",
            retryable=False,
            reason="UI action — no string confirmation expected",
            failure_type="unverifiable",
        )

    # ── 2. Empty result ───────────────────────────────────────────────────────
    if not result or not result.strip():
        retryable = intent_upper not in _NO_RETRY_INTENTS
        logger.warning(
            f"[VERIFIER] {intent_upper} — empty result "
            f"(retryable={retryable}) | query={query[:60]!r}"
        )
        return VerifyResult(
            ok=False,
            result="",
            retryable=retryable,
            reason="Empty result",
            failure_type="empty",
        )

    result_lower = result.lower()

    # ── 3. Success override — explicit ✅ or Hinglish success phrase ──────────
    if any(sig.lower() in result_lower for sig in _SUCCESS_OVERRIDES):
        logger.debug(f"[VERIFIER] {intent_upper} — success signal found, ok")
        return VerifyResult(
            ok=True,
            result=result,
            retryable=False,
            reason="Success signal present",
            failure_type="none",
        )

    # ── 4. Hard failure — definitive error, no retry ──────────────────────────
    for sig in _HARD_FAILURE_SIGNALS:
        if sig.lower() in result_lower:
            logger.warning(
                f"[VERIFIER] {intent_upper} — hard failure ({sig!r}): {result[:80]!r}"
            )
            return VerifyResult(
                ok=False,
                result=result,
                retryable=False,   # hard failures don't benefit from retry
                reason=f"Hard failure signal: {sig!r}",
                failure_type="hard",
            )

    # ── 5. Soft failure — may be transient, retry if safe ────────────────────
    for sig in _SOFT_FAILURE_SIGNALS:
        if sig.lower() in result_lower:
            retryable = intent_upper not in _NO_RETRY_INTENTS
            logger.warning(
                f"[VERIFIER] {intent_upper} — soft failure ({sig!r}) "
                f"(retryable={retryable}): {result[:80]!r}"
            )
            return VerifyResult(
                ok=False,
                result=result,
                retryable=retryable,
                reason=f"Soft failure signal: {sig!r}",
                failure_type="soft",
            )

    # ── 6. Default: looks ok ─────────────────────────────────────────────────
    logger.debug(f"[VERIFIER] {intent_upper} — no failure signals, ok")
    return VerifyResult(
        ok=True,
        result=result,
        retryable=False,
        reason="No failure signals detected",
        failure_type="none",
    )


def is_retryable(intent: str) -> bool:
    """
    Convenience check: is this intent safe to retry?

    True for most intents. False for side-effect operations
    (sending messages, writing files) where a retry would duplicate the action.

    Args:
        intent: Router intent string

    Returns:
        True if a retry is safe, False if it would cause a duplicate side effect.
    """
    return (intent or "").upper() not in _NO_RETRY_INTENTS


def summarise_verdict(vr: VerifyResult) -> str:
    """
    One-line human-readable verdict string.
    Used by executor for structured logging (not shown to Rudra).

    Example:
        "ok=True  | type=none    | retryable=False | reason=No failure signals detected"
    """
    return (
        f"ok={str(vr.ok):<5} | "
        f"type={vr.failure_type:<13} | "
        f"retryable={str(vr.retryable):<5} | "
        f"reason={vr.reason}"
    )
