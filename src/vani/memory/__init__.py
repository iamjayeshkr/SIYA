"""
vani/memory/__init__.py — Phase 6

Unified memory interface for VANI.

Provides get_full_context() — a single call that assembles memory from all
layers and returns a prompt-ready block. The planner, worker brain, and
prompt_manager.py can all call this without knowing which memory modules exist.

Memory hierarchy (all layers are independent — one failing doesn't break others):
    1. Working memory   → pending reminders, active topics, recent songs/searches
    2. Permanent memory → durable facts, preferences, user-taught items
    3. Relationship memory → people Vani knows, nicknames, platforms (Phase 6 NEW)
    4. Task history     → recent completed tasks for context (Phase 6 NEW)

Each layer has a try/except so a broken module never silently breaks VANI.
This file previously contained only a single docstring comment — all additions
here are backward-safe (no removal of existing exports).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("vani.memory")


# ── Unified context builder ─────────────────────────────────────────────────────

def get_full_context(
    limit_chars: int = 2000,
    include_working: bool = True,
    include_permanent: bool = True,
    include_relationships: bool = True,
    include_task_history: bool = False,   # off by default — noisy for realtime sessions
) -> str:
    """
    Assemble a combined memory block from all available memory layers.

    Designed for injection into the system prompt or planner context.
    Each section is pulled independently — if one module errors, the rest
    still contribute. Total output is capped at limit_chars.

    Args:
        limit_chars:           Hard character cap on the returned string
        include_working:       Include working_memory block (reminders, topics)
        include_permanent:     Include permanent_memory block (user facts)
        include_relationships: Include relationship_memory block (contacts) — Phase 6
        include_task_history:  Include recent task history — Phase 6 (off by default)

    Returns:
        Multi-line string ready for prompt injection.
        Empty string if all layers fail or return nothing.

    Example output:
        [Working Memory]
        Reminders: study at 6pm, call mom tomorrow
        Active topics: Python, VANI architecture

        [Permanent Memory]
        Rudra likes dark mode. Rudra is preparing for UPSC.

        [Contacts Vani knows about]
          • Neha Sharma / didi [whatsapp]
          • Rahul [telegram]

    Usage:
        from vani.memory import get_full_context
        context = get_full_context()
        # inject into prompt_manager.py or planner
    """
    parts: list[str] = []

    # ── 1. Working memory ────────────────────────────────────────────────────
    if include_working:
        try:
            from vani.memory.working_memory import get_working_memory_block
            wm = get_working_memory_block()
            if wm and wm.strip():
                parts.append(wm.strip())
        except Exception as e:
            logger.debug(f"[MEMORY] working_memory failed (non-fatal): {e}")

    # ── 2. Permanent memory ──────────────────────────────────────────────────
    if include_permanent:
        try:
            from vani.memory.human_memory import get_permanent_memory_block
            pm = get_permanent_memory_block(limit=5)
            if pm and pm.strip():
                parts.append(pm.strip())
        except Exception as e:
            logger.debug(f"[MEMORY] human_memory failed (non-fatal): {e}")

    # ── 3. Relationship memory (Phase 6) ─────────────────────────────────────
    if include_relationships:
        try:
            from vani.memory.relationship_memory import build_contacts_block
            cb = build_contacts_block(limit=8)
            if cb and cb.strip():
                parts.append(cb.strip())
        except Exception as e:
            logger.debug(f"[MEMORY] relationship_memory failed (non-fatal): {e}")

    # ── 4. Task history (Phase 6, optional) ──────────────────────────────────
    if include_task_history:
        try:
            from vani.memory.task_history import get_history_block
            th = get_history_block(limit=5)
            if th and th.strip():
                parts.append(th.strip())
        except Exception as e:
            logger.debug(f"[MEMORY] task_history failed (non-fatal): {e}")

    if not parts:
        return ""

    combined = "\n\n".join(parts)
    return combined[:limit_chars]


# ── Convenience re-exports ──────────────────────────────────────────────────────
# These allow `from vani.memory import X` without knowing the sub-module.
# Only import what's guaranteed to exist (Phases 1–5 baseline).

def get_working_memory_block() -> str:
    """Shortcut to working_memory.get_working_memory_block()."""
    try:
        from vani.memory.working_memory import get_working_memory_block as _fn
        return _fn()
    except Exception:
        return ""


def get_permanent_memory_block(limit: int = 5) -> str:
    """Shortcut to human_memory.get_permanent_memory_block()."""
    try:
        from vani.memory.human_memory import get_permanent_memory_block as _fn
        return _fn(limit=limit)
    except Exception:
        return ""


def resolve_contact(name: str) -> dict | None:
    """Shortcut to relationship_memory.resolve_contact()."""
    try:
        from vani.memory.relationship_memory import resolve_contact as _fn
        return _fn(name)
    except Exception:
        return None


def remember_contact(name: str, **kwargs) -> dict | None:
    """Shortcut to relationship_memory.remember_contact()."""
    try:
        from vani.memory.relationship_memory import remember_contact as _fn
        return _fn(name, **kwargs)
    except Exception:
        return None


def record_task(intent: str, query: str, result: str, duration_ms: float, success: bool, **kwargs) -> None:
    """Shortcut to task_history.record_task(). Non-blocking."""
    try:
        from vani.memory.task_history import record_task as _fn
        _fn(intent=intent, query=query, result=result, duration_ms=duration_ms, success=success, **kwargs)
    except Exception:
        pass


__all__ = [
    "get_full_context",
    "get_working_memory_block",
    "get_permanent_memory_block",
    "resolve_contact",
    "remember_contact",
    "record_task",
]
