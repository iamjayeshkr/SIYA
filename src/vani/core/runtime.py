"""Runtime helpers for Vani's live session and background worker.

This module previously maintained its own _session_ref which was never
registered by app.py (which calls vani.reasoning.register_session instead).
All session state is now delegated to vani.reasoning.worker so there is
exactly ONE source of truth for the session reference.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)


# ── Session management — single source of truth is vani.reasoning.worker ──────

def register_session(session) -> None:
    from vani.reasoning.worker import register_session as _reg
    _reg(session)


def unregister_session(session=None) -> None:
    from vani.reasoning import worker as _w
    if session is None or session is _w._session_ref:
        _w._session_ref = None
        _w._session_loop = None
        logger.info("[MESSAGING] Cleared LiveKit session reference")


def _speech_safe_text(text: str, limit: int | None = 360) -> str:
    from vani.reasoning.worker import _speech_safe_text as _sst
    return _sst(text, limit=limit)


async def say_to_user(text: str, limit: int | None = 360) -> None:
    from vani.reasoning.worker import say_to_user as _say
    await _say(text, limit=limit)


def speak_to_user_from_thread(text: str, limit: int | None = 360) -> bool:
    from vani.reasoning.worker import speak_to_user_from_thread as _speak
    return _speak(text, limit=limit)


# ── Worker / queue helpers ─────────────────────────────────────────────────────

def _get_task_queue() -> asyncio.Queue:
    from vani.reasoning.worker import _get_task_queue
    return _get_task_queue()


def ensure_worker(run_query=None) -> None:
    from vani.reasoning.worker import _ensure_worker
    _ensure_worker()


async def shutdown_worker() -> None:
    from vani.reasoning import worker as _w
    task = _w._worker_task
    _w._worker_task = None
    _w._task_queue = None
    _w._worker_loop = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def thinking_capability(query: str, run_query=None) -> str:
    from vani.reasoning.worker import thinking_capability as _tc
    return await _tc(query)
