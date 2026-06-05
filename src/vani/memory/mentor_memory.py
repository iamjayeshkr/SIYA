"""
src/vani/memory/mentor_memory.py
═══════════════════════════════════════════════════════════════════════════════
SQLite persistence layer for Deep Document Mentor Mode.
Manages sessions, coverage progress checklists, and retention/quiz response states.
Reuses the central database path from human_memory.py to respect mock setups in tests.
"""

import json
import sqlite3
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from vani.memory.human_memory import DB_PATH

logger = logging.getLogger("vani.memory.mentor_memory")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _init_schema(conn)
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mentor_sessions (
            document_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            coverage_score REAL DEFAULT 0.0,
            mastery_score REAL DEFAULT 0.0,
            current_concept_id TEXT,
            roast_mode INTEGER DEFAULT 0, -- 0: Off, 1: Light, 2: Medium, 3: Savage
            mode_type TEXT DEFAULT 'document' -- 'document' or 'repository'
        );

        CREATE TABLE IF NOT EXISTS mentor_coverage_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL REFERENCES mentor_sessions(document_id) ON DELETE CASCADE,
            item_type TEXT NOT NULL, -- 'chapter', 'section', 'table', 'diagram', 'formula', 'code_block'
            item_name TEXT NOT NULL,
            parent_chapter TEXT,
            processed INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS mentor_retention_items (
            id TEXT PRIMARY KEY,
            concept_id TEXT NOT NULL,
            item_type TEXT NOT NULL, -- 'quiz', 'active_recall'
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            options TEXT DEFAULT '[]', -- JSON-serialized list
            user_answer TEXT,
            passed INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL
        );
        """
    )


def create_session(document_id: str, filename: str, mode_type: str = "document") -> Dict[str, Any]:
    created_at = int(time.time())
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO mentor_sessions
                (document_id, filename, status, created_at, coverage_score, mastery_score, roast_mode, mode_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (document_id, filename, "processing", created_at, 0.0, 0.0, 0, mode_type),
        )
        conn.commit()
    return get_session(document_id)


def get_session(document_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM mentor_sessions WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return dict(row) if row else None


def get_active_session() -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM mentor_sessions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def update_session(document_id: str, **kwargs) -> None:
    if not kwargs:
        return
    fields = []
    values = []
    for k, v in kwargs.items():
        fields.append(f"{k} = ?")
        values.append(v)
    values.append(document_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE mentor_sessions SET {', '.join(fields)} WHERE document_id = ?",
            tuple(values),
        )
        conn.commit()


def add_coverage_item(document_id: str, item_type: str, item_name: str, parent_chapter: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mentor_coverage_items (document_id, item_type, item_name, parent_chapter, processed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (document_id, item_type, item_name, parent_chapter),
        )
        conn.commit()


def get_coverage_items(document_id: str) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mentor_coverage_items WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_coverage_processed(document_id: str, item_name: str, item_type: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE mentor_coverage_items
            SET processed = 1
            WHERE document_id = ? AND item_name = ? AND item_type = ?
            """,
            (document_id, item_name, item_type),
        )
        conn.commit()


def add_retention_item(
    item_id: str,
    concept_id: str,
    item_type: str,
    question: str,
    answer: str,
    options: List[str]
) -> None:
    created_at = int(time.time())
    options_json = json.dumps(options)
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO mentor_retention_items
                (id, concept_id, item_type, question, answer, options, passed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (item_id, concept_id, item_type, question, answer, options_json, created_at),
        )
        conn.commit()


def update_retention_response(item_id: str, user_answer: str, passed: bool) -> None:
    passed_val = 1 if passed else 0
    with _connect() as conn:
        conn.execute(
            """
            UPDATE mentor_retention_items
            SET user_answer = ?, passed = ?
            WHERE id = ?
            """,
            (user_answer, passed_val, item_id),
        )
        conn.commit()
