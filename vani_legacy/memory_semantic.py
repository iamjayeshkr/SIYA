"""
vani/memory_semantic.py
───────────────────────
Semantic (vector) memory layer for Vani OS using sqlite-vec.

Stores memories as text + 768-dim embeddings in SQLite.
Enables "what did we talk about regarding X last month?" queries
that keyword search cannot answer.

Tables created:
  memory_semantic        — text + metadata
  memory_semantic_vec    — virtual vec0 table linked to above

Usage:
    from vani.memory_semantic import SemanticMemory

    mem = SemanticMemory()
    await mem.init()

    # Store a memory
    await mem.store("Rudra decided to use Rust for the Core rewrite", tags=["project", "architecture"])

    # Search
    results = await mem.search("what language for the backend?", top_k=5)
    for r in results:
        print(r["text"], r["score"])

    # Build context block for LLM
    context = await mem.build_context("tell me about the project decisions", max_tokens=600)
"""

import json
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import os

import aiosqlite

from vani.embeddings import embed, embed_batch, EMBED_DIM
from vani.logging_config import get_logger

log = get_logger("memory.semantic")

_DEFAULT_DB = Path.home() / "vani.db"
DB_PATH = Path(os.getenv("VANI_DB_PATH", str(_DEFAULT_DB)))

# ── sqlite-vec serialisation ──────────────────────────────────────────────────

def _vec_to_blob(vector: list[float]) -> bytes:
    """Serialise a float list to the binary format sqlite-vec expects."""
    return struct.pack(f"{len(vector)}f", *vector)


def _blob_to_vec(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = f"""
-- Semantic memory records
CREATE TABLE IF NOT EXISTS memory_semantic (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          DATETIME DEFAULT CURRENT_TIMESTAMP,
    text        TEXT NOT NULL,
    source      TEXT DEFAULT 'conversation',  -- 'conversation' | 'tool' | 'manual'
    tags        TEXT DEFAULT '[]',            -- JSON array of strings
    importance  REAL DEFAULT 1.0,             -- 0.0-2.0 multiplier for ranking
    embedding   BLOB NOT NULL                 -- {EMBED_DIM}-dim float32 binary
);

CREATE INDEX IF NOT EXISTS idx_memory_semantic_ts
    ON memory_semantic (ts DESC);

CREATE INDEX IF NOT EXISTS idx_memory_semantic_source
    ON memory_semantic (source);

-- Virtual vec0 table for ANN search (requires sqlite-vec extension)
-- Falls back gracefully if sqlite-vec not installed.
"""

# Vec0 table — created separately because it requires the extension
_VEC_TABLE = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS memory_semantic_vec
USING vec0(
    embedding FLOAT[{EMBED_DIM}]
);
"""


class SemanticMemory:
    """
    Semantic memory layer. One instance per process — share it.

    If sqlite-vec extension is not installed, falls back to brute-force
    cosine similarity (slower but always works).
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._vec_available = False

    # ── Init ──────────────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Create tables. Safe to call multiple times."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(_SCHEMA)

            # Try to load sqlite-vec and create vec0 virtual table
            try:
                import sqlite_vec
                await db.enable_load_extension(True)
                await db.load_extension(sqlite_vec.loadable_path())
                await db.executescript(_VEC_TABLE)
                self._vec_available = True
                log.info("sqlite_vec_loaded", dim=EMBED_DIM)
            except Exception as e:
                log.warning(
                    "sqlite_vec_unavailable",
                    error=str(e),
                    fallback="brute_force_cosine",
                    hint="pip install sqlite-vec  to enable fast ANN search",
                )

            await db.commit()

    # ── Store ─────────────────────────────────────────────────────────────────

    async def store(
        self,
        text: str,
        source: str = "conversation",
        tags: list[str] | None = None,
        importance: float = 1.0,
    ) -> int:
        """
        Embed and store a memory. Returns the new row id.

        Args:
            text:       The memory text to store.
            source:     Origin — 'conversation', 'tool', 'manual'.
            tags:       Optional list of string tags for filtering.
            importance: Ranking multiplier (1.0 = normal, 2.0 = very important).
        """
        tags = tags or []
        t0 = time.monotonic()

        vector = await embed(text)
        blob = _vec_to_blob(vector)
        tags_json = json.dumps(tags)

        async with aiosqlite.connect(self.db_path) as db:
            if self._vec_available:
                try:
                    import sqlite_vec
                    await db.enable_load_extension(True)
                    await db.load_extension(sqlite_vec.loadable_path())
                except Exception:
                    pass

            cursor = await db.execute(
                """
                INSERT INTO memory_semantic (text, source, tags, importance, embedding)
                VALUES (?, ?, ?, ?, ?)
                """,
                (text, source, tags_json, importance, blob),
            )
            row_id = cursor.lastrowid

            # Mirror into vec0 table for fast ANN search
            if self._vec_available:
                try:
                    await db.execute(
                        "INSERT INTO memory_semantic_vec (rowid, embedding) VALUES (?, ?)",
                        (row_id, blob),
                    )
                except Exception as e:
                    log.warning("vec_insert_failed", error=str(e))

            await db.commit()

        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info("memory_stored", id=row_id, source=source, tags=tags,
                 text_len=len(text), duration_ms=duration_ms)
        return row_id

    async def store_batch(self, entries: list[dict]) -> list[int]:
        """
        Store multiple memories efficiently.

        Each entry: {"text": str, "source": str, "tags": list, "importance": float}
        """
        texts = [e["text"] for e in entries]
        vectors = await embed_batch(texts)

        ids = []
        async with aiosqlite.connect(self.db_path) as db:
            if self._vec_available:
                try:
                    import sqlite_vec
                    await db.enable_load_extension(True)
                    await db.load_extension(sqlite_vec.loadable_path())
                except Exception:
                    pass

            for entry, vector in zip(entries, vectors):
                blob = _vec_to_blob(vector)
                cursor = await db.execute(
                    """
                    INSERT INTO memory_semantic (text, source, tags, importance, embedding)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        entry["text"],
                        entry.get("source", "conversation"),
                        json.dumps(entry.get("tags", [])),
                        entry.get("importance", 1.0),
                        blob,
                    ),
                )
                row_id = cursor.lastrowid
                ids.append(row_id)

                if self._vec_available:
                    try:
                        await db.execute(
                            "INSERT INTO memory_semantic_vec (rowid, embedding) VALUES (?, ?)",
                            (row_id, blob),
                        )
                    except Exception:
                        pass

            await db.commit()

        log.info("memory_batch_stored", count=len(ids))
        return ids

    # ── Search ────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
        min_score: float = 0.3,
        days_limit: Optional[int] = None,
    ) -> list[dict]:
        """
        Semantic search over stored memories.

        Args:
            query:         Natural language query.
            top_k:         Number of results to return.
            source_filter: Only return memories from this source.
            tag_filter:    Only return memories containing this tag.
            min_score:     Minimum cosine similarity threshold (0.0-1.0).
            days_limit:    Only search memories from the last N days.

        Returns:
            List of dicts: {id, ts, text, source, tags, importance, score}
            Sorted by score descending.
        """
        t0 = time.monotonic()
        query_vector = await embed(query)
        query_blob = _vec_to_blob(query_vector)

        results = []

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if self._vec_available:
                try:
                    import sqlite_vec
                    await db.enable_load_extension(True)
                    await db.load_extension(sqlite_vec.loadable_path())
                except Exception:
                    pass

            if self._vec_available:
                results = await self._search_vec(
                    db, query_blob, query_vector, top_k * 3,
                    source_filter, tag_filter, days_limit
                )
            else:
                results = await self._search_brute(
                    db, query_vector, top_k * 3,
                    source_filter, tag_filter, days_limit
                )

        # Apply importance multiplier and re-rank
        for r in results:
            r["score"] = r["score"] * r["importance"]

        # Filter by min_score and truncate
        results = [r for r in results if r["score"] >= min_score]
        results.sort(key=lambda r: r["score"], reverse=True)
        results = results[:top_k]

        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info("memory_search", query_len=len(query), results=len(results),
                 top_score=results[0]["score"] if results else 0,
                 method="vec0" if self._vec_available else "brute",
                 duration_ms=duration_ms)

        return results

    async def _search_vec(self, db, query_blob, query_vector, limit,
                          source_filter, tag_filter, days_limit):
        """ANN search using sqlite-vec vec0 table."""
        # Build join query — vec0 gives rowid + distance
        conditions = ["1=1"]
        params = [query_blob, limit]

        if source_filter:
            conditions.append("ms.source = ?")
            params.append(source_filter)
        if tag_filter:
            conditions.append("ms.tags LIKE ?")
            params.append(f'%"{tag_filter}"%')
        if days_limit:
            conditions.append(f"ms.ts >= datetime('now', '-{days_limit} days')")

        where = " AND ".join(conditions)

        try:
            cursor = await db.execute(
                f"""
                SELECT ms.id, ms.ts, ms.text, ms.source, ms.tags,
                       ms.importance, v.distance
                FROM memory_semantic_vec v
                JOIN memory_semantic ms ON ms.id = v.rowid
                WHERE v.embedding MATCH ?
                  AND k = ?
                  AND {where}
                ORDER BY v.distance ASC
                """,
                params,
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "text": r["text"],
                    "source": r["source"],
                    "tags": json.loads(r["tags"]),
                    "importance": r["importance"],
                    # vec0 returns L2 distance; convert to similarity-ish score
                    "score": max(0.0, 1.0 - r["distance"]),
                }
                for r in rows
            ]
        except Exception as e:
            log.warning("vec_search_failed", error=str(e), fallback="brute")
            return await self._search_brute(db, query_vector, limit,
                                            source_filter, tag_filter, days_limit)

    async def _search_brute(self, db, query_vector, limit,
                            source_filter, tag_filter, days_limit):
        """Brute-force cosine similarity — used when sqlite-vec unavailable."""
        from vani.embeddings import cosine_similarity

        conditions = ["1=1"]
        params = []

        if source_filter:
            conditions.append("source = ?")
            params.append(source_filter)
        if tag_filter:
            conditions.append(f'tags LIKE ?')
            params.append(f'%"{tag_filter}"%')
        if days_limit:
            conditions.append(f"ts >= datetime('now', '-{days_limit} days')")

        where = " AND ".join(conditions)
        cursor = await db.execute(
            f"SELECT id, ts, text, source, tags, importance, embedding FROM memory_semantic WHERE {where}",
            params,
        )
        rows = await cursor.fetchall()

        scored = []
        for r in rows:
            vec = _blob_to_vec(r["embedding"])
            score = cosine_similarity(query_vector, vec)
            scored.append({
                "id": r["id"],
                "ts": r["ts"],
                "text": r["text"],
                "source": r["source"],
                "tags": json.loads(r["tags"]),
                "importance": r["importance"],
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    # ── Context builder ───────────────────────────────────────────────────────

    async def build_context(
        self,
        query: str,
        max_tokens: int = 600,
        top_k: int = 8,
    ) -> str:
        """
        Build a memory context block ready to inject into an LLM prompt.

        Returns a formatted string like:
            [Relevant memories]
            • 2 days ago: Rudra decided to use Rust for the Core rewrite
            • 1 week ago: Project deadline is end of July
            ...

        Stays within max_tokens budget.
        """
        results = await self.search(query, top_k=top_k)
        if not results:
            return ""

        chars_budget = max_tokens * 4  # rough chars-per-token
        lines = ["[Relevant memories]"]
        used = len(lines[0])

        for r in results:
            age = _human_age(r["ts"])
            line = f"• {age}: {r['text']}"
            if used + len(line) > chars_budget:
                break
            lines.append(line)
            used += len(line)

        return "\n".join(lines)

    # ── Maintenance ───────────────────────────────────────────────────────────

    async def delete(self, memory_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM memory_semantic WHERE id = ?", (memory_id,))
            if self._vec_available:
                try:
                    await db.execute(
                        "DELETE FROM memory_semantic_vec WHERE rowid = ?", (memory_id,)
                    )
                except Exception:
                    pass
            await db.commit()
        log.info("memory_deleted", id=memory_id)

    async def count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM memory_semantic")
            row = await cursor.fetchone()
            return row[0]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human_age(ts_str: str) -> str:
    """Convert a SQLite timestamp to a human-readable age string."""
    try:
        ts = datetime.fromisoformat(ts_str)
        delta = datetime.utcnow() - ts
        seconds = delta.total_seconds()
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        if seconds < 86400:
            return f"{int(seconds // 3600)}h ago"
        if seconds < 7 * 86400:
            return f"{int(seconds // 86400)}d ago"
        if seconds < 30 * 86400:
            return f"{int(seconds // (7 * 86400))} weeks ago"
        return f"{int(seconds // (30 * 86400))} months ago"
    except Exception:
        return ts_str
