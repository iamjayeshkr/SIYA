"""
vani/workers/maintenance_worker.py — Phase 7

Maintenance Worker: periodic housekeeping tasks that run every 60 minutes.

Tasks performed:
  1. task_history.jsonl rotation — archives the file if it exceeds 50MB
  2. agent_failures.jsonl trimming — keeps only the last 500 failure entries
  3. Expired document cleanup — purges temp_documents past their TTL
     (human_memory already has this; this just calls it on a schedule)

These tasks are silent — no user notification unless something unusual happens.
All operations have try/except wrappers so a failure never affects VANI.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("vani.workers.maintenance")

# Max failure log entries to keep (older entries are trimmed)
_MAX_FAILURE_ENTRIES = 500


def run_maintenance() -> None:
    """
    Main maintenance tick. Called by WorkerManager every 60 minutes.
    Runs all maintenance tasks in sequence; errors in one don't stop others.
    """
    logger.debug("[MAINTENANCE] Running maintenance cycle...")

    _rotate_task_history()
    _trim_failure_log()
    _purge_expired_documents()

    logger.debug("[MAINTENANCE] Maintenance cycle complete.")


# ── Individual maintenance tasks ──────────────────────────────────────────────

def _rotate_task_history() -> None:
    """Rotate task_history.jsonl if it's grown too large."""
    try:
        from vani.memory.task_history import rotate_if_large
        rotated = rotate_if_large()
        if rotated:
            logger.info("[MAINTENANCE] task_history.jsonl rotated successfully.")
    except Exception as e:
        logger.debug(f"[MAINTENANCE] task_history rotation skipped: {e}")


def _trim_failure_log() -> None:
    """
    Trim agent_failures.jsonl to the last _MAX_FAILURE_ENTRIES entries.
    The file is append-only by executor.py; this prevents unbounded growth.
    """
    try:
        from vani.config import PROJECT_ROOT
        import json

        log_path = PROJECT_ROOT / "conversations" / "agent_failures.jsonl"
        if not log_path.exists():
            return

        size_mb = log_path.stat().st_size / (1024 * 1024)
        if size_mb < 5.0:   # Don't bother if under 5MB
            return

        with open(log_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        if len(lines) <= _MAX_FAILURE_ENTRIES:
            return

        kept = lines[-_MAX_FAILURE_ENTRIES:]
        archive_path = log_path.with_suffix(
            f".{time.strftime('%Y%m%d_%H%M%S')}.jsonl.bak"
        )
        log_path.rename(archive_path)

        with open(log_path, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")

        logger.info(
            f"[MAINTENANCE] agent_failures.jsonl trimmed: "
            f"kept {len(kept)} of {len(lines)} entries, "
            f"archived {size_mb:.1f}MB to {archive_path.name}"
        )
    except Exception as e:
        logger.debug(f"[MAINTENANCE] failure log trim skipped: {e}")


def _purge_expired_documents() -> None:
    """Purge temporary documents past their TTL from human_memory SQLite."""
    try:
        from vani.memory.human_memory import purge_expired_documents
        purge_expired_documents()
        logger.debug("[MAINTENANCE] Expired document purge complete.")
    except Exception as e:
        logger.debug(f"[MAINTENANCE] Document purge skipped: {e}")
