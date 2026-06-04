"""
vani/planner/executor.py — updated Phase 5

Worker Twin — Execution half.

Takes a TaskPlan produced by TaskPlanner and executes each SubTask.
Delegates actual tool calls to the existing _dispatch_intent router —
no tool logic lives here.

Responsibilities:
  - Execute subtasks in order
  - Verify each result via verifier.verify_result() before accepting it  ← Phase 5
  - Retry once on soft/empty failures for retryable intents              ← Phase 5
  - Log failures to agent_failures.jsonl  (for Phase 8 self-improvement)
  - Write task timing to task_history.jsonl
  - Return combined result string back to the Worker Twin (brain.py)
  - Never call say_to_user / never generate text — Twin A (Talker) does that
"""

from __future__ import annotations
import asyncio
import logging
import time

from vani.planner.models import TaskPlan, SubTask

logger = logging.getLogger("vani.planner.executor")

# ── Verifier (Phase 5) ────────────────────────────────────────────────────────
# Import with graceful fallback so executor still works if verifier isn't deployed yet.
try:
    from vani.planner.verifier import verify_result, VerifyResult
    _VERIFIER_AVAILABLE = True
except ImportError:
    _VERIFIER_AVAILABLE = False
    logger.warning("[EXECUTOR] verifier.py not found — using legacy failure detection")

# ── Legacy failure detection (fallback if verifier not available) ─────────────
_FAILURE_SIGNALS = (
    "❌", "Error:", "error:", "nahi ho paya", "failed",
    "timeout", "not found", "nahi mila",
)

# ── Intents that must NOT be retried (side-effect operations) ────────────────
_NO_RETRY_INTENTS = frozenset({
    "WHATSAPP_SEND", "WHATSAPP_CALL",
    "TELEGRAM_SEND",
    "INSTAGRAM_SEND",
})


def _looks_like_failure(result: str) -> bool:
    """Legacy heuristic — used only when verifier.py is not available."""
    if not result or not result.strip():
        return True
    low = result.lower()
    return any(sig.lower() in low for sig in _FAILURE_SIGNALS)


# ── Public API ────────────────────────────────────────────────────────────────

async def execute_plan(plan: TaskPlan) -> str | None:
    """
    Execute all subtasks in the plan.

    Returns:
        str  — combined result for single or multi-task plans
        None — signals caller to fall back to Qwen
    """
    if not plan.subtasks:
        return None

    results: list[str] = []
    state_context: dict[str, Any] = {}

    for task in plan.subtasks:
        result = await _execute_one(task, plan.raw_query, state_context)

        if result is None:
            # Executor couldn't handle this subtask — signal LLM fallback
            logger.warning(
                f"[EXECUTOR] SubTask {task.task_id} ({task.intent}) returned None "
                f"— falling back to LLM for full query"
            )
            return None

        if result:
            results.append(result)
            state_context[task.task_id] = result

    # Single task: return its result directly
    if len(plan.subtasks) == 1:
        return plan.subtasks[0].result

    # Multiple tasks: join non-empty results
    combined = " | ".join(r for r in results if r and r.strip())
    return combined if combined else f"✅ {len(results)} kaam ho gaye."


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _execute_one(task: SubTask, raw_query: str, context: dict[str, Any] | None = None) -> str | None:
    """
    Execute a single SubTask via _dispatch_intent.

    Returns:
        str  — tool result (may be an error string)
        None — executor can't handle this intent (caller falls back to LLM)
    """
    if not task.intent:
        return None     # No intent → needs LLM

    task.status = "running"
    t_start = time.monotonic()

    try:
        from vani.agents import get_agent
        agent = get_agent(task.agent) if task.agent else None
        
        if agent:
            logger.info(f"[EXECUTOR] Routing subtask {task.task_id} through stateful agent '{task.agent}'")
            result = await agent.run(task.query or raw_query, context)
        else:
            from vani.reasoning.router import _dispatch_intent
            result = await _dispatch_intent(task.intent, task.data, task.query or raw_query)

        elapsed_ms = (time.monotonic() - t_start) * 1000
        task.duration_ms = elapsed_ms

        # ── Phase 5: Verify result via verifier, fall back to legacy heuristic ──
        if _VERIFIER_AVAILABLE:
            from vani.planner.verifier import verify_result, summarise_verdict
            vr = verify_result(task.intent, result, task.query or raw_query)
            logger.debug(f"[EXECUTOR] verify {task.task_id}: {summarise_verdict(vr)}")
            should_retry = not vr.ok and vr.retryable
        else:
            # Legacy path — kept for backward compat
            should_retry = _looks_like_failure(result) and task.intent not in _NO_RETRY_INTENTS

        # ── Retry once if result looks like a failure and intent is retryable ──
        if should_retry:
            logger.info(
                f"[EXECUTOR] Task {task.task_id} looks failed "
                f"({result[:60]!r}) — retrying once"
            )
            # ── Phase 8: Consult self-improvement strategy library ──────────
            try:
                from vani.core.self_improvement import get_retry_strategy
                hint = get_retry_strategy(task.intent or "", task.error or result[:80])
                if hint:
                    logger.info(f"[EXECUTOR] Strategy hint for {task.intent}: {hint}")
            except Exception:
                pass
            # ────────────────────────────────────────────────────────────────
            await asyncio.sleep(0)   # yield event loop, no artificial delay
            retry_result = await _dispatch_intent(task.intent, task.data, task.query or raw_query)
            if not _looks_like_failure(retry_result):
                result = retry_result
                logger.info(f"[EXECUTOR] Retry succeeded for {task.task_id}")

        task.result = str(result) if result else ""
        task.status = "done"

        # Log to task history (non-blocking fire-and-forget)
        _log_task_history(
            intent=task.intent,
            query=task.query or raw_query,
            result=task.result,
            duration_ms=elapsed_ms,
            success=not _looks_like_failure(task.result),
        )

        return task.result

    except asyncio.CancelledError:
        task.status = "stale"
        logger.info(f"[EXECUTOR] Task {task.task_id} cancelled (new instruction arrived)")
        raise   # propagate so the worker loop handles it correctly

    except Exception as e:
        elapsed_ms = (time.monotonic() - t_start) * 1000
        task.status = "failed"
        task.error = str(e)
        task.duration_ms = elapsed_ms

        logger.error(f"[EXECUTOR] Task {task.task_id} ({task.intent}) failed: {e}")

        # Log failure for self-improvement layer
        _log_failure(task, raw_query)

        # Return error string — don't crash; Twin A will speak it naturally
        return f"Ek kaam mein dikkat aayi: {e}"


# ── Persistence helpers (fire-and-forget, never block execution) ─────────────

def _log_failure(task: SubTask, raw_query: str) -> None:
    """Append failure to agent_failures.jsonl for self-improvement analysis."""
    import json
    try:
        from vani.config import PROJECT_ROOT
        log_path = PROJECT_ROOT / "conversations" / "agent_failures.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "query": raw_query[:200],
            "intent": task.intent,
            "agent": task.agent,
            "error": task.error,
            "duration_ms": round(task.duration_ms, 1),
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as _e:
        logger.debug(f"[EXECUTOR] _log_failure write failed (non-fatal): {_e}")


def _log_task_history(
    intent: str,
    query: str,
    result: str,
    duration_ms: float,
    success: bool,
) -> None:
    """Append to task_history.jsonl for analytics."""
    import json
    try:
        from vani.config import PROJECT_ROOT
        log_path = PROJECT_ROOT / "conversations" / "task_history.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "intent": intent,
            "query": query[:150],
            "success": success,
            "duration_ms": round(duration_ms, 1),
            "result_preview": result[:80] if result else "",
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as _e:
        logger.debug(f"[EXECUTOR] _log_task_history write failed (non-fatal): {_e}")