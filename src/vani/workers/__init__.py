"""
vani/workers/__init__.py — Phase 7

Background worker package.

Exports the singleton WorkerManager and registers all built-in workers.
app.py calls start_background_workers() once during startup — that's all
that's needed to activate all periodic background tasks.

Workers registered here:
    "reminders"   → check_reminders()   every 5 min   (reminder_worker.py)
    "maintenance" → run_maintenance()   every 60 min  (maintenance_worker.py)
    "self_improve"→ run_improvement_cycle() every 60 min (core/self_improvement.py, Phase 8)

Self_improve is registered here but starts only if the Phase 8 module exists —
graceful degradation if Phase 8 hasn't been deployed yet.

Usage in app.py:
    try:
        from vani.workers import start_background_workers
        start_background_workers()
        log.info("[workers] Background workers started")
    except Exception as e:
        log.warning(f"[workers] Worker startup failed (non-fatal): {e}")
"""

from __future__ import annotations

import logging

from vani.workers.worker_manager import WorkerManager

logger = logging.getLogger("vani.workers")

# Singleton — shared across the whole process
_manager = WorkerManager()


def get_worker_manager() -> WorkerManager:
    """Returns the singleton WorkerManager instance."""
    return _manager


def start_background_workers() -> None:
    """
    Register and start all built-in background workers.

    Safe to call multiple times — WorkerManager.start() is idempotent
    (won't re-start a worker that's already running).

    Called once from app.py after the HTTP state server starts.
    """
    # ── 1. Reminder worker — check every 5 minutes ──────────────────────────
    try:
        from vani.workers.reminder_worker import check_reminders
        _manager.start("reminders", check_reminders, interval_s=300)
        logger.info("[WORKERS] 'reminders' worker started (every 5 min)")
    except Exception as e:
        logger.warning(f"[WORKERS] Could not start 'reminders' worker: {e}")

    # ── 2. Maintenance worker — every 60 minutes ─────────────────────────────
    try:
        from vani.workers.maintenance_worker import run_maintenance
        _manager.start("maintenance", run_maintenance, interval_s=3600)
        logger.info("[WORKERS] 'maintenance' worker started (every 60 min)")
    except Exception as e:
        logger.warning(f"[WORKERS] Could not start 'maintenance' worker: {e}")

    # ── 3. Self-improvement worker — Phase 8 (graceful if not deployed yet) ──
    try:
        from vani.core.self_improvement import run_improvement_cycle
        _manager.start("self_improve", run_improvement_cycle, interval_s=3600)
        logger.info("[WORKERS] 'self_improve' worker started (every 60 min)")
    except ImportError:
        logger.debug("[WORKERS] 'self_improve' worker skipped (Phase 8 not deployed yet)")
    except Exception as e:
        logger.warning(f"[WORKERS] Could not start 'self_improve' worker: {e}")

    # Log final status
    logger.info(f"[WORKERS] {_manager.status_summary()}")


def stop_all_workers() -> None:
    """
    Signal all workers to stop. Called on clean shutdown.
    Threads are daemon=True so this is optional — OS will clean up anyway.
    """
    _manager.stop_all()
    logger.info("[WORKERS] All workers signalled to stop.")


__all__ = [
    "get_worker_manager",
    "start_background_workers",
    "stop_all_workers",
    "_manager",
]
