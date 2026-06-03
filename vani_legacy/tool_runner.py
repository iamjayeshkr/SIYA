"""
vani/tool_runner.py  —  P4 Edition
────────────────────────────────────
Central execution wrapper for all Vani tools.

P4 changes vs P3:
  • Retry-with-backoff for flaky tools (WhatsApp, browser, screen_read)
  • Adaptive timeout: increases by 50% on first retry
  • Concurrent tool execution support (run_tools_parallel)
  • asyncio.CancelledError handling fixed (re-raises cleanly)
  • Per-tool retry config separate from timeout config
"""

import asyncio
import time
from typing import Any, Callable, Coroutine

from vani.logging_config import get_logger
from vani.tokenjuice import compress

log = get_logger("tool_runner")

# ── Per-tool timeout config (seconds) ────────────────────────────────────────
DEFAULT_TIMEOUT = 15

TOOL_TIMEOUTS: dict[str, int] = {
    "whatsapp_send":          20,   # P4: reduced from 30 (sleep reductions done in P4a)
    "whatsapp_read":          20,
    "whatsapp_reply":         20,
    "whatsapp_call":          20,
    "pyautogui_click":        25,
    "pyautogui_type":         25,
    "browser_click":          18,
    "browser_navigate":       18,
    "browser_fill":           18,
    "browser_scrape":         18,
    "telegram_send":          18,
    "telegram_read":          18,
    "web_search":             18,
    "youtube_search":         18,
    "youtube_play":           18,
    "memory_read":             5,
    "memory_search":           5,
    "memory_write":            8,
    "screen_read":            20,   # P4: reduced from 25
}

# ── P4: Retry config ──────────────────────────────────────────────────────────
# Tools that should auto-retry once on timeout (flaky I/O operations).
# max_retries=1 means: one initial attempt + one retry = two total attempts.
# backoff_factor: each retry multiplies the timeout by this factor.
RETRYABLE_TOOLS: dict[str, dict] = {
    "whatsapp_send":   {"max_retries": 1, "backoff_factor": 1.5},
    "whatsapp_read":   {"max_retries": 1, "backoff_factor": 1.5},
    "whatsapp_reply":  {"max_retries": 1, "backoff_factor": 1.5},
    "whatsapp_call":   {"max_retries": 1, "backoff_factor": 1.5},
    "browser_scrape":  {"max_retries": 1, "backoff_factor": 1.4},
    "screen_read":     {"max_retries": 1, "backoff_factor": 1.5},
    "web_search":      {"max_retries": 1, "backoff_factor": 1.3},
    "telegram_send":   {"max_retries": 1, "backoff_factor": 1.4},
}


# ── Audit writer ─────────────────────────────────────────────────────────────

async def _write_audit(
    tool_name: str,
    args: dict,
    result: Any,
    duration_ms: int,
    success: bool,
    error_msg: str | None,
    attempt: int = 1,
) -> None:
    try:
        from vani.db import write_tool_audit
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
        log.warning("audit_write_failed", tool=tool_name, error=str(e))


# ── P4: single-attempt executor ───────────────────────────────────────────────

async def _execute_once(
    name: str,
    fn: Callable[..., Coroutine],
    args: dict[str, Any],
    timeout: float,
) -> tuple[Any, bool, str | None, int]:
    """
    Execute fn(**args) with the given timeout.
    Returns (result, success, error_msg, duration_ms).
    Raises asyncio.CancelledError if cancelled (never catches it).
    """
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(fn(**args), timeout=timeout)
        duration_ms = int((time.monotonic() - start) * 1000)
        return result, True, None, duration_ms

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start) * 1000)
        error_msg = f"timeout after {timeout:.0f}s"
        log.warning("tool_timeout", tool=name, timeout_s=timeout, duration_ms=duration_ms)
        return {"error": "tool_timeout", "tool": name, "timeout_s": timeout}, False, error_msg, duration_ms

    except asyncio.CancelledError:
        raise   # always propagate cancellation

    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        error_msg = str(exc)
        log.exception("tool_error", tool=name, duration_ms=duration_ms, error=error_msg)
        return {"error": error_msg, "tool": name}, False, error_msg, duration_ms


# ── Main executor ─────────────────────────────────────────────────────────────

async def execute_tool(
    name: str,
    fn: Callable[..., Coroutine],
    args: dict[str, Any],
    compress_output: bool = True,
    max_output_tokens: int = 400,
) -> Any:
    """
    Execute a tool with timeout, retry-with-backoff, logging, audit trail,
    and output compression.

    P4: flaky tools (whatsapp_*, screen_read, browser_scrape, etc.) get one
    automatic retry with an expanded timeout if the first attempt times out.
    """
    base_timeout = TOOL_TIMEOUTS.get(name, DEFAULT_TIMEOUT)
    retry_cfg = RETRYABLE_TOOLS.get(name)
    max_retries = retry_cfg["max_retries"] if retry_cfg else 0
    backoff = retry_cfg["backoff_factor"] if retry_cfg else 1.0

    log.info("tool_start", tool=name, args_keys=list(args.keys()),
             timeout_s=base_timeout, max_retries=max_retries)

    result = None
    success = False
    error_msg = None
    duration_ms = 0
    attempt = 0

    for attempt in range(max_retries + 1):
        timeout = base_timeout * (backoff ** attempt)
        if attempt > 0:
            log.info("tool_retry", tool=name, attempt=attempt, timeout_s=timeout)
            await asyncio.sleep(0.5 * attempt)   # brief pause before retry

        result, success, error_msg, duration_ms = await _execute_once(
            name, fn, args, timeout
        )

        if success:
            log.info("tool_success", tool=name, duration_ms=duration_ms, attempt=attempt)
            break

        # Only retry on timeout, not on application errors
        if error_msg and "timeout" not in error_msg:
            log.info("tool_no_retry", tool=name, reason="non-timeout error")
            break

    # Compress string output before handing back to the planner
    if compress_output and success and isinstance(result, str):
        result = compress(result, max_tokens=max_output_tokens)

    # Fire-and-forget audit — never blocks
    asyncio.create_task(
        _write_audit(
            tool_name=name,
            args=args,
            result=result,
            duration_ms=duration_ms,
            success=success,
            error_msg=error_msg,
            attempt=attempt + 1,
        )
    )

    return result


# ── P4: Parallel tool execution ───────────────────────────────────────────────

async def run_tools_parallel(
    calls: list[tuple[str, Callable[..., Coroutine], dict[str, Any]]],
    max_concurrency: int = 4,
) -> list[Any]:
    """
    Run multiple tools concurrently with a semaphore cap.

    Args:
        calls: list of (tool_name, tool_fn, args_dict)
        max_concurrency: max tools running simultaneously

    Returns:
        list of results in the same order as calls
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def _guarded(name, fn, args):
        async with sem:
            return await execute_tool(name, fn, args)

    return await asyncio.gather(*[_guarded(n, f, a) for n, f, a in calls])
