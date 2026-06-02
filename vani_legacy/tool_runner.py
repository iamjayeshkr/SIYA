"""
vani/tool_runner.py
───────────────────
Central execution wrapper for all Vani tools.

Replaces direct `await tool_fn(**args)` calls in the planner with:

    from vani.tool_runner import execute_tool
    result = await execute_tool("whatsapp_send", tool_fn, args)

Features:
  • Per-tool timeout enforcement (never hangs the event loop)
  • Structured logging for every execution
  • Async audit trail written to SQLite (non-blocking)
  • TokenJuice compression on output before returning to planner
"""

import asyncio
import time
from typing import Any, Callable, Coroutine

from vani.logging_config import get_logger
from vani.tokenjuice import compress

log = get_logger("tool_runner")

# ── Per-tool timeout config (seconds) ────────────────────────────────────────
# Override specific tools here; everything else gets DEFAULT_TIMEOUT.
DEFAULT_TIMEOUT = 15

TOOL_TIMEOUTS: dict[str, int] = {
    # WhatsApp / UI automation — pyautogui can be slow
    "whatsapp_send":          30,
    "whatsapp_read":          30,
    "whatsapp_reply":         30,
    "pyautogui_click":        30,
    "pyautogui_type":         30,
    "browser_click":          20,
    "browser_navigate":       20,
    "browser_fill":           20,
    "browser_scrape":         20,
    # Telegram
    "telegram_send":          20,
    "telegram_read":          20,
    # Network / API tools
    "web_search":             20,
    "youtube_search":         20,
    "youtube_play":           20,
    # Memory reads should be fast
    "memory_read":             5,
    "memory_search":           5,
    "memory_write":            8,
    # Screen reading (Gemini Vision round-trip)
    "screen_read":            25,
}


# ── Audit writer (imported lazily to avoid circular deps) ────────────────────

async def _write_audit(
    tool_name: str,
    args: dict,
    result: Any,
    duration_ms: int,
    success: bool,
    error_msg: str | None,
) -> None:
    """Write a row to tool_audit table. Called via asyncio.create_task."""
    try:
        # Import here to avoid circular dependency at module load time
        from vani.db import write_tool_audit  # noqa: PLC0415
        result_summary = str(result)[:200] if result is not None else None
        import json
        args_json = json.dumps(args, default=str)[:1000]
        await write_tool_audit(
            tool_name=tool_name,
            args_json=args_json,
            result_summary=result_summary,
            duration_ms=duration_ms,
            success=success,
            error_msg=error_msg,
        )
    except Exception as e:
        # Audit failure must never crash the assistant
        log.warning("audit_write_failed", tool=tool_name, error=str(e))


# ── Main executor ─────────────────────────────────────────────────────────────

async def execute_tool(
    name: str,
    fn: Callable[..., Coroutine],
    args: dict[str, Any],
    compress_output: bool = True,
    max_output_tokens: int = 400,
) -> Any:
    """
    Execute a tool with timeout, logging, audit trail, and output compression.

    Args:
        name:               Tool name (must match TOOL_TIMEOUTS keys or gets DEFAULT_TIMEOUT).
        fn:                 Async callable implementing the tool.
        args:               Keyword arguments to pass to fn.
        compress_output:    Whether to run TokenJuice on string output.
        max_output_tokens:  Token ceiling for compression.

    Returns:
        Tool result (compressed if string), or error dict on failure.
    """
    timeout = TOOL_TIMEOUTS.get(name, DEFAULT_TIMEOUT)
    start = time.monotonic()
    success = False
    error_msg = None
    result = None

    log.info("tool_start", tool=name, args_keys=list(args.keys()), timeout_s=timeout)

    try:
        result = await asyncio.wait_for(fn(**args), timeout=timeout)
        success = True

        duration_ms = int((time.monotonic() - start) * 1000)
        log.info("tool_success", tool=name, duration_ms=duration_ms)

        # Compress string output before handing back to the planner
        if compress_output and isinstance(result, str):
            result = compress(result, max_tokens=max_output_tokens)

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start) * 1000)
        error_msg = f"timeout after {timeout}s"
        log.error("tool_timeout", tool=name, timeout_s=timeout, duration_ms=duration_ms)
        result = {"error": "tool_timeout", "tool": name, "timeout_s": timeout}

    except asyncio.CancelledError:
        duration_ms = int((time.monotonic() - start) * 1000)
        error_msg = "cancelled"
        log.warning("tool_cancelled", tool=name, duration_ms=duration_ms)
        result = {"error": "tool_cancelled", "tool": name}
        raise  # Re-raise so the planner's cancellation chain works correctly

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        error_msg = str(exc)
        log.exception("tool_error", tool=name, duration_ms=duration_ms, error=error_msg)
        result = {"error": error_msg, "tool": name}

    finally:
        # Fire-and-forget audit write — never blocks the response
        asyncio.create_task(
            _write_audit(
                tool_name=name,
                args=args,
                result=result,
                duration_ms=duration_ms,
                success=success,
                error_msg=error_msg,
            )
        )

    return result
