"""
vani/planner/brain.py

Worker Twin — PlannerBrain (the coordinator).

This is the single entry point the Worker Twin exposes to worker.py.
It coordinates TaskPlanner (what to do) + executor (how to do it).

                    ┌─────────────────────────────────────┐
                    │         TWIN BRAIN ARCHITECTURE      │
                    │                                      │
  User speaks ───►  │  Twin A: Gemini Realtime (TALKER)   │ ◄─── speaks result
                    │         ↕  (via thinking_capability) │
  Tool runs  ───►  │  Twin B: PlannerBrain (WORKER)       │ ───► executes silently
                    │                                      │
                    │  Flow inside Twin B:                 │
                    │    query → TaskPlanner               │
                    │              ↓                       │
                    │          TaskPlan                    │
                    │              ↓                       │
                    │          executor.execute_plan()     │
                    │              ↓                       │
                    │          result string               │
                    │              ↓ (if None → Qwen)      │
                    └─────────────────────────────────────┘

PlannerBrain.think_and_execute(query):
  → Returns str result  if planner handled it   (Qwen never wakes up)
  → Returns None        if planner can't handle (caller falls through to Qwen)

This is the ONLY place in worker.py that needs to change.
"""

from __future__ import annotations
import asyncio
import logging
import time

logger = logging.getLogger("vani.planner.brain")

# Singleton planner instance — created once per process
_planner_instance = None


def _get_planner():
    global _planner_instance
    if _planner_instance is None:
        from vani.planner.task_planner import TaskPlanner
        _planner_instance = TaskPlanner()
    return _planner_instance


class PlannerBrain:
    """
    Worker Twin's central brain.

    Usage (in worker.py):
        result = await PlannerBrain.think_and_execute(query)
        if result is not None:
            return result          # planner handled it
        # else fall through to Qwen
    """

    @staticmethod
    async def think_and_execute(query: str) -> str | None:
        """
        Main entry point for the Worker Twin.

        Steps:
          0. Plugins → Check if any enabled plugin matches the triggers first
          1. Plan  → TaskPlanner converts query to TaskPlan
          2. Check → if plan.requires_llm: return None (→ Qwen)
          3. Execute → executor runs each SubTask
          4. Return result string or None

        Never raises. Always returns str | None.
        """
        t_start = time.monotonic()

        # ── Check if any enabled plugin matches the query triggers ────────────────
        try:
            from vani.plugins import get_registry
            from vani.plugins.registry import PluginContext
            
            registry = get_registry()
            messages = []
            try:
                from vani.reasoning.worker import _session_ref
                if _session_ref and hasattr(_session_ref, "history") and hasattr(_session_ref.history, "items"):
                    for item in list(_session_ref.history.items):
                        role = "user" if item.role == "user" else "assistant"
                        content = getattr(item, "text", "") or ""
                        if content:
                            messages.append({"role": role, "content": content})
            except Exception:
                pass

            context = PluginContext(recent_messages=messages)
            plugin_result = await registry.route_to_plugin(query, context)
            if plugin_result is not None:
                logger.info(f"[BRAIN] Plugin matched and executed: message='{plugin_result.message}'")
                return plugin_result.message
        except Exception as e:
            logger.warning(f"[BRAIN] Dynamic plugin routing failed: {e}")

        try:
            planner = _get_planner()
            plan = planner.plan(query)
        except Exception as e:
            logger.warning(f"[BRAIN] Planning failed: {e} — routing to LLM")
            return None

        # ── Planner explicitly says LLM is needed ─────────────────────────────
        if plan.requires_llm:
            logger.info(f"[BRAIN] LLM path for: {query!r}")
            return None

        # ── No subtasks produced (shouldn't happen, but guard it) ─────────────
        if not plan.subtasks:
            logger.warning(f"[BRAIN] Empty plan for: {query!r} — routing to LLM")
            return None

        # ── Execute the plan ──────────────────────────────────────────────────
        logger.info(
            f"[BRAIN] Executing plan: intent={plan.intent}, "
            f"tasks={len(plan.subtasks)}, compound={plan.is_compound}"
        )

        try:
            from vani.planner.executor import execute_plan
            result = await execute_plan(plan)
        except asyncio.CancelledError:
            raise   # propagate so worker.py handles it correctly
        except Exception as e:
            logger.error(f"[BRAIN] Execution error: {e} — routing to LLM")
            return None

        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            f"[BRAIN] Done in {elapsed_ms:.0f}ms: "
            f"intent={plan.intent}, result_len={len(result) if result else 0}"
        )

        # ── None result → executor signals LLM fallback ───────────────────────
        if result is None:
            return None

        return result

    @staticmethod
    def get_status() -> dict:
        """Returns current brain status for diagnostics."""
        global _planner_instance
        return {
            "planner_ready": _planner_instance is not None,
            "twin": "worker",
        }
