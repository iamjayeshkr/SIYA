"""
vani/workers/worker_manager.py — Phase 7

Background Worker Manager.

Manages periodic background tasks that run independently of the task queue
(reasoning/worker.py). Those handle user-triggered tasks; this handles
time-driven, scheduled, and maintenance work.

Design principles:
  - Each worker runs in its own daemon thread — VANI's main loop is never blocked.
  - Workers are started once and run on a fixed interval until VANI shuts down.
  - A worker crashing never kills VANI — errors are logged and the loop continues.
  - stop_all() is safe to call on shutdown (threads are daemon=True, so the OS
    also cleans them up automatically).

Built-in workers registered in workers/__init__.py:
  - "reminders"     → checks pending reminders every 5 minutes
  - "maintenance"   → rotates large log files every 60 minutes
  - "self_improve"  → runs failure analysis cycle every 60 minutes (Phase 8)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger("vani.workers")


class WorkerManager:
    """
    Starts, tracks, and stops named periodic background workers.

    Each worker is a daemon thread that calls a plain (synchronous) function
    on a fixed interval. Async functions are not supported here — use
    asyncio.run() inside the worker function if you need async.

    Usage:
        wm = WorkerManager()
        wm.start("reminders", check_reminders, interval_s=300)
        wm.start("maintenance", run_maintenance, interval_s=3600)
        # ... VANI runs ...
        wm.stop_all()   # called on shutdown
    """

    def __init__(self) -> None:
        self._workers: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(
        self,
        name: str,
        fn: Callable[[], None],
        interval_s: float = 60.0,
        run_immediately: bool = False,
    ) -> bool:
        """
        Start a named periodic worker.

        If a worker with this name is already running, this call is a no-op.

        Args:
            name:           Unique worker name (e.g. "reminders")
            fn:             Callable to call on each tick. Must be thread-safe.
                            Errors raised by fn are caught and logged.
            interval_s:     Seconds between calls. The interval begins AFTER each
                            call completes (i.e. not a fixed-rate ticker).
            run_immediately: If True, call fn once before the first sleep.

        Returns:
            True if worker was started, False if it was already running.
        """
        with self._lock:
            existing = self._workers.get(name)
            if existing and existing.is_alive():
                logger.debug(f"[WORKER_MANAGER] {name!r} already running, skipping start")
                return False

            stop_event = threading.Event()
            self._stop_events[name] = stop_event

            def _loop() -> None:
                logger.info(f"[WORKER_MANAGER] '{name}' started (interval={interval_s}s)")

                if run_immediately:
                    _safe_call(name, fn)

                while not stop_event.wait(timeout=interval_s):
                    _safe_call(name, fn)

                logger.info(f"[WORKER_MANAGER] '{name}' stopped")

            thread = threading.Thread(
                target=_loop,
                daemon=True,
                name=f"vani-worker-{name}",
            )
            self._workers[name] = thread
            thread.start()
            return True

    def stop(self, name: str) -> None:
        """
        Signal a named worker to stop after its current tick completes.
        Returns immediately; the thread may still be running briefly.
        """
        with self._lock:
            event = self._stop_events.get(name)
        if event:
            event.set()
            logger.info(f"[WORKER_MANAGER] stop signal sent to '{name}'")

    def stop_all(self) -> None:
        """Signal all running workers to stop. Safe to call on shutdown."""
        with self._lock:
            names = list(self._stop_events.keys())
        for name in names:
            self.stop(name)

    def is_running(self, name: str) -> bool:
        """Returns True if the named worker thread is alive."""
        with self._lock:
            thread = self._workers.get(name)
        return thread is not None and thread.is_alive()

    def status(self) -> dict[str, bool]:
        """
        Returns a snapshot of all worker names and their running state.

        Returns:
            Dict mapping worker name → is_alive bool.
            Example: {"reminders": True, "maintenance": True, "self_improve": False}
        """
        with self._lock:
            names = list(self._workers.keys())
        return {name: self.is_running(name) for name in names}

    def status_summary(self) -> str:
        """
        Returns a one-line human-readable status string.
        Used for health checks and debug logging.

        Example: "Workers: reminders=✅ maintenance=✅ self_improve=❌"
        """
        parts = []
        for name, alive in self.status().items():
            icon = "✅" if alive else "❌"
            parts.append(f"{name}={icon}")
        if not parts:
            return "Workers: none registered"
        return "Workers: " + " ".join(parts)


# ── Internal helper ───────────────────────────────────────────────────────────

def _safe_call(name: str, fn: Callable[[], None]) -> None:
    """Call fn(), catch and log any exception. Never raises."""
    try:
        fn()
    except Exception as e:
        logger.warning(f"[WORKER_MANAGER] '{name}' tick raised an error: {e}")
