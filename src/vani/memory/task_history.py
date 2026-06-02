"""
vani/memory/task_history.py — Phase 6

Task History: records every completed task for analytics, self-improvement,
and pattern learning.

This is the dedicated memory module for task history data.
Note: executor.py (Phase 5) already writes raw entries to task_history.jsonl
      as fire-and-forget log lines. This module wraps that file with a proper
      read/query API so Phase 8 (self-improvement) and the planner can consume it.

Storage: append-only JSONL file (conversations/task_history.jsonl)
         One JSON object per line; newest at the bottom.

Thread safety: file append is atomic enough for single-process use.
               For multi-process safety, use SQLite (future upgrade).

Backward compat: executor.py already writes this file — this module only
                 adds a read layer on top. Zero risk of data loss.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Iterator

from vani.config import PROJECT_ROOT

logger = logging.getLogger("vani.memory.task_history")

_HISTORY_FILE = PROJECT_ROOT / "conversations" / "task_history.jsonl"
_MAX_FILE_SIZE_MB = 50   # soft cap — rotate if file exceeds this


# ── Write API ───────────────────────────────────────────────────────────────────

def record_task(
    intent: str,
    query: str,
    result: str,
    duration_ms: float,
    success: bool,
    agent: str = "",
    tool: str = "",
) -> None:
    """
    Append a completed task to the history log.

    Called by executor.py after every task. Non-blocking; errors are swallowed
    so a history write failure never crashes the task pipeline.

    Note: executor.py has its own inline _log_task_history() that also writes
    to this file. Both write the same schema. This function is the canonical
    version going forward — executor.py can delegate here in a future cleanup.

    Args:
        intent:      Router intent string (e.g. "WHATSAPP_SEND")
        query:       Original user query (truncated to 200 chars)
        result:      Tool result string (truncated to 100 chars for preview)
        duration_ms: Execution time in milliseconds
        success:     True if tool result looks valid
        agent:       Agent name that handled the task (optional)
        tool:        Specific tool name called (optional)
    """
    try:
        _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "intent": intent or "",
            "query": (query or "")[:200],
            "success": bool(success),
            "duration_ms": round(float(duration_ms), 1),
            "result_preview": (result or "")[:100],
            "agent": agent or "",
            "tool": tool or "",
        }
        with open(_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[TASK_HISTORY] record_task write failed (non-fatal): {e}")


# ── Read API ────────────────────────────────────────────────────────────────────

def _iter_entries(reverse: bool = False) -> Iterator[dict]:
    """
    Yield parsed entries from the history file.
    Silently skips malformed lines.

    Args:
        reverse: If True, yield newest entries first (reads all into memory).
    """
    if not _HISTORY_FILE.exists():
        return

    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning(f"[TASK_HISTORY] Could not read history file: {e}")
        return

    if reverse:
        lines = reversed(lines)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def get_recent(limit: int = 20, intent_filter: str = "") -> list[dict]:
    """
    Return the most recent task entries, newest first.

    Args:
        limit:         Max entries to return
        intent_filter: If set, only return entries matching this intent (prefix match ok)

    Returns:
        List of task entry dicts.
    """
    results = []
    for entry in _iter_entries(reverse=True):
        if intent_filter:
            if not entry.get("intent", "").upper().startswith(intent_filter.upper()):
                continue
        results.append(entry)
        if len(results) >= limit:
            break
    return results


def get_frequent_intents(n: int = 10) -> list[dict]:
    """
    Return the top-N most frequently used intents.

    Useful for the self-improvement layer to focus optimization on high-traffic paths.

    Args:
        n: Number of top intents to return

    Returns:
        List of dicts: [{"intent": "GOOGLE_SEARCH", "count": 42}, ...]
        Sorted by count descending.
    """
    counts: Counter = Counter()
    for entry in _iter_entries():
        intent = entry.get("intent", "unknown")
        if intent:
            counts[intent] += 1

    return [
        {"intent": intent, "count": count}
        for intent, count in counts.most_common(n)
    ]


def get_failure_rate(intent: str = "") -> dict:
    """
    Calculate success/failure rate, optionally filtered to one intent.

    Args:
        intent: If set, filter to this intent. If empty, calculate across all.

    Returns:
        Dict with keys: total, success_count, failure_count, success_rate (0.0-1.0)
    """
    total = 0
    success_count = 0
    key = (intent or "").upper()

    for entry in _iter_entries():
        if key and not entry.get("intent", "").upper().startswith(key):
            continue
        total += 1
        if entry.get("success", False):
            success_count += 1

    failure_count = total - success_count
    success_rate = (success_count / total) if total > 0 else 0.0

    return {
        "intent": intent or "ALL",
        "total": total,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round(success_rate, 3),
    }


def get_slow_intents(threshold_ms: float = 2000.0, min_samples: int = 3) -> list[dict]:
    """
    Return intents whose average duration exceeds the threshold.

    Useful for the self-improvement layer to identify bottlenecks.

    Args:
        threshold_ms:  Intents slower than this average (in ms) are flagged
        min_samples:   Minimum sample count to be included (avoids outliers)

    Returns:
        List of dicts: [{"intent": "CODE_ASSIST", "avg_ms": 4200.0, "samples": 7}, ...]
        Sorted by avg_ms descending.
    """
    durations: dict[str, list[float]] = {}

    for entry in _iter_entries():
        intent = entry.get("intent", "")
        ms = entry.get("duration_ms", 0.0)
        if intent and ms:
            durations.setdefault(intent, []).append(ms)

    results = []
    for intent, times in durations.items():
        if len(times) < min_samples:
            continue
        avg = sum(times) / len(times)
        if avg >= threshold_ms:
            results.append({
                "intent": intent,
                "avg_ms": round(avg, 1),
                "samples": len(times),
            })

    return sorted(results, key=lambda x: x["avg_ms"], reverse=True)


def get_failed_queries(limit: int = 20) -> list[dict]:
    """
    Return the most recent failed task queries.

    Used by the self-improvement layer to analyze failure patterns.

    Args:
        limit: Max entries to return

    Returns:
        List of failed task entry dicts.
    """
    results = []
    for entry in _iter_entries(reverse=True):
        if not entry.get("success", True):  # success=False or missing
            results.append(entry)
            if len(results) >= limit:
                break
    return results


def get_stats_summary() -> str:
    """
    Returns a compact human-readable summary of task history statistics.
    Used for self-improvement logging and debugging.

    Example output:
        Task history: 342 total | success rate: 91.2% | top intents: GOOGLE_SEARCH(45), YOUTUBE_PLAY(30)

    Returns:
        Single-line stats string, or "No task history yet." if file is empty.
    """
    overall = get_failure_rate()
    if overall["total"] == 0:
        return "No task history yet."

    top = get_frequent_intents(n=3)
    top_str = ", ".join(f"{t['intent']}({t['count']})" for t in top)

    return (
        f"Task history: {overall['total']} total | "
        f"success rate: {overall['success_rate'] * 100:.1f}% | "
        f"top intents: {top_str}"
    )


def get_history_block(limit: int = 5) -> str:
    """
    Returns a compact block of recent task history for prompt injection.
    Called by memory/__init__.py's get_full_context().

    Args:
        limit: Max tasks to include

    Returns:
        Multi-line string, or empty string if no history.
    """
    recent = get_recent(limit=limit)
    if not recent:
        return ""

    lines = ["[Recent tasks]"]
    for e in recent:
        status = "✅" if e.get("success") else "❌"
        intent = e.get("intent", "?")
        preview = e.get("result_preview", "")[:50]
        lines.append(f"  {status} {intent}: {preview}")

    return "\n".join(lines)


# ── Maintenance ──────────────────────────────────────────────────────────────────

def rotate_if_large() -> bool:
    """
    If the history file exceeds _MAX_FILE_SIZE_MB, archive it and start fresh.

    Called by worker_manager.py during periodic maintenance.
    Keeps the last 1000 entries in the new file.

    Returns:
        True if rotation happened, False otherwise.
    """
    if not _HISTORY_FILE.exists():
        return False

    size_mb = _HISTORY_FILE.stat().st_size / (1024 * 1024)
    if size_mb < _MAX_FILE_SIZE_MB:
        return False

    try:
        # Keep last 1000 entries
        recent = list(_iter_entries(reverse=True))[:1000]
        recent.reverse()  # back to chronological order

        archive_path = _HISTORY_FILE.with_suffix(
            f".{time.strftime('%Y%m%d_%H%M%S')}.jsonl.bak"
        )
        _HISTORY_FILE.rename(archive_path)

        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            for entry in recent:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(
            f"[TASK_HISTORY] Rotated: archived {size_mb:.1f}MB to {archive_path.name}, "
            f"kept {len(recent)} recent entries"
        )
        return True
    except Exception as e:
        logger.warning(f"[TASK_HISTORY] Rotation failed (non-fatal): {e}")
        return False
