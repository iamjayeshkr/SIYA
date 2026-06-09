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
    async def classify_only(query: str) -> dict | None:
        """
        Classifies the query intent without executing it, and triggers pre-warming if applicable.
        """
        try:
            planner = _get_planner()
            plan = planner.plan(query)
            if not plan or plan.requires_llm:
                return None
            
            intent = plan.intent
            if intent == "YOUTUBE_PLAY":
                subtask = plan.subtasks[0] if plan.subtasks else None
                song_query = subtask.data if (subtask and subtask.data) else ""
                if song_query:
                    import threading
                    from vani.browser.control import (
                        get_youtube_url,
                        _build_yt_search_query,
                        _speculative_yt_cache,
                        _speculative_yt_lock,
                        ResultContainer
                    )
                    search_query = _build_yt_search_query(song_query)
                    normalized = search_query.lower().strip()
                    
                    with _speculative_yt_lock:
                        if normalized not in _speculative_yt_cache:
                            container = ResultContainer()
                            _speculative_yt_cache[normalized] = container
                            
                            def _run_lookup():
                                try:
                                    res = get_youtube_url(song_query)
                                    container.result = res
                                except Exception:
                                    pass
                                finally:
                                    container.done = True
                            
                            threading.Thread(target=_run_lookup, daemon=True, name="speculative-yt").start()
                            logger.info(f"[SPECULATIVE] Kicked off speculative YT lookup for: {song_query!r}")
            elif intent in ("GOOGLE_SEARCH", "OPEN_URL"):
                import sys
                import asyncio
                if sys.platform == "win32":
                    from vani.browser.control import _find_browser_win
                    asyncio.create_task(asyncio.to_thread(_find_browser_win, "chrome"))
                elif sys.platform == "darwin":
                    from vani.browser.control import _find_browser_mac
                    asyncio.create_task(asyncio.to_thread(_find_browser_mac, "chrome"))
            return {"intent": intent, "subtasks": len(plan.subtasks)}
        except Exception as e:
            logger.warning(f"[SPECULATIVE] Classification/warmup failed: {e}")
            return None

    @staticmethod
    def get_status() -> dict:
        """Returns current brain status for diagnostics."""
        global _planner_instance
        return {
            "planner_ready": _planner_instance is not None,
            "twin": "worker",
        }
