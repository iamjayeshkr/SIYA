"""
vani/db.py
──────────
Vani OS SQLite database layer.

• Single DB file, WAL mode for concurrent reads
• Initialises all tables on first run (safe to call repeatedly)
• Async-friendly: uses aiosqlite so DB writes never block the event loop

Usage:
    from vani.db import init_db, write_tool_audit, get_tool_history

    await init_db()          # call once at startup
    await write_tool_audit(...)
    rows = await get_tool_history(tool_name="whatsapp_send", limit=20)
"""

import os
from pathlib import Path
from typing import Optional

import aiosqlite

from vani.logging_config import get_logger

log = get_logger("db")

# ── DB path ──────────────────────────────────────────────────────────────────
_DEFAULT_DB_PATH = Path.home() / "vani.db"
DB_PATH = Path(os.getenv("VANI_DB_PATH", str(_DEFAULT_DB_PATH)))

# ── Schema ───────────────────────────────────────────────────────────────────
_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

-- ── Core memory tables (keep existing ones unchanged) ─────────────────────

-- ── Tool audit trail (new in P0) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tool_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              DATETIME DEFAULT CURRENT_TIMESTAMP,
    tool_name       TEXT NOT NULL,
    args_json       TEXT,
    result_summary  TEXT,       -- first 200 chars of result
    duration_ms     INTEGER,
    success         BOOLEAN NOT NULL DEFAULT 0,
    error_msg       TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_audit_ts
    ON tool_audit (ts DESC);

CREATE INDEX IF NOT EXISTS idx_tool_audit_name
    ON tool_audit (tool_name, ts DESC);
"""


# ── Initialisation ────────────────────────────────────────────────────────────

async def init_db() -> None:
    """
    Create the DB file and run schema migrations.
    Safe to call on every startup — all statements use IF NOT EXISTS.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    log.info("db_ready", path=str(DB_PATH))


# ── tool_audit helpers ────────────────────────────────────────────────────────

async def write_tool_audit(
    tool_name: str,
    args_json: str,
    result_summary: Optional[str],
    duration_ms: int,
    success: bool,
    error_msg: Optional[str] = None,
) -> None:
    """Insert one row into tool_audit. Called from tool_runner via create_task."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO tool_audit
                (tool_name, args_json, result_summary, duration_ms, success, error_msg)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (tool_name, args_json, result_summary, duration_ms, int(success), error_msg),
        )
        await db.commit()


async def get_tool_history(
    tool_name: Optional[str] = None,
    limit: int = 50,
    only_failures: bool = False,
) -> list[dict]:
    """
    Query recent tool audit rows.

    Args:
        tool_name:     Filter by tool name (None = all tools).
        limit:         Max rows to return.
        only_failures: If True, return only failed executions.

    Returns:
        List of dicts with keys: id, ts, tool_name, args_json,
        result_summary, duration_ms, success, error_msg
    """
    conditions = []
    params: list = []

    if tool_name:
        conditions.append("tool_name = ?")
        params.append(tool_name)

    if only_failures:
        conditions.append("success = 0")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"""
            SELECT id, ts, tool_name, args_json, result_summary,
                   duration_ms, success, error_msg
            FROM tool_audit
            {where}
            ORDER BY ts DESC
            LIMIT ?
            """,
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_tool_stats(days: int = 7) -> list[dict]:
    """
    Aggregate stats per tool for the last N days.
    Returns: tool_name, call_count, success_rate, avg_duration_ms, timeout_count
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT
                tool_name,
                COUNT(*)                                        AS call_count,
                ROUND(AVG(success) * 100, 1)                   AS success_rate,
                ROUND(AVG(duration_ms), 0)                     AS avg_duration_ms,
                SUM(CASE WHEN error_msg LIKE '%timeout%' THEN 1 ELSE 0 END) AS timeout_count
            FROM tool_audit
            WHERE ts >= datetime('now', ? || ' days')
            GROUP BY tool_name
            ORDER BY call_count DESC
            """,
            (f"-{days}",),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
