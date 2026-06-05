"""
Human-like memory layers for Vani.

Temporary document memory:
- Stores the full extracted text of uploaded documents.
- Keeps searchable chunks for retrieval.
- Expires automatically after 2 days by default.

Permanent memory:
- Stores durable facts, preferences, and important user-taught items.
- This is the "human brain" layer that survives restarts.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path

from vani.config import PROJECT_ROOT, env_int

DB_PATH = PROJECT_ROOT / "conversations" / "vani_human_memory.sqlite3"
TEMP_DOC_TTL_DAYS = env_int("VANI_TEMP_DOCUMENT_TTL_DAYS", 2)
TEMP_CHUNK_SIZE = env_int("VANI_TEMP_DOCUMENT_CHUNK_SIZE", 1800)
TEMP_CHUNK_OVERLAP = env_int("VANI_TEMP_DOCUMENT_CHUNK_OVERLAP", 250)
TEMP_MAX_RETRIEVAL_CHUNKS = env_int("VANI_TEMP_DOCUMENT_MAX_RETRIEVAL_CHUNKS", 24)
TEMP_FULL_CONTEXT_CHARS = env_int("VANI_TEMP_DOCUMENT_FULL_CONTEXT_CHARS", 120000)

STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "what", "why", "how", "when", "where", "which", "who", "about", "into",
    "hai", "hain", "tha", "thi", "kya", "kaise", "kyu", "kyun", "mein", "mai",
    "mujhe", "bata", "samjha", "explain", "book", "pdf", "chapter", "concept",
    "iske", "isme", "usme", "related", "vani", "rudra",
    # Added common conversational words and pronouns:
    "you", "your", "yours", "yourself", "me", "my", "myself", "mine", "we", "us", "our", "ours",
    "he", "him", "his", "himself", "she", "her", "hers", "herself", "they", "them", "their", "theirs",
    "who", "whom", "whose", "which", "that", "this", "these", "those",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    "a", "an", "the", "but", "or", "as", "if", "because", "until", "while", "of", "at", "by", "up", "down", "in", "out",
    "hello", "hi", "hey", "yaar", "naam", "name", "batao", "karo", "karna", "krna", "bol", "bolo", "chal", "chalo",
    "acha", "accha", "haan", "ha", "no", "yes", "please", "thanks", "thank", "sorry", "welcome",
}


def _now() -> int:
    return int(time.time())


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
        CREATE TABLE IF NOT EXISTS temp_documents (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            full_text TEXT NOT NULL,
            outline TEXT DEFAULT '',
            user_prompt TEXT DEFAULT '',
            digest TEXT,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            char_count INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS temp_document_chunks (
            document_id TEXT NOT NULL REFERENCES temp_documents(id) ON DELETE CASCADE,
            chunk_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            tokens TEXT NOT NULL,
            PRIMARY KEY (document_id, chunk_id)
        );

        CREATE INDEX IF NOT EXISTS idx_temp_documents_expires_at
            ON temp_documents(expires_at);

        CREATE TABLE IF NOT EXISTS permanent_memories (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            raw TEXT DEFAULT '',
            importance INTEGER NOT NULL DEFAULT 5,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_permanent_memories_category
            ON permanent_memories(category);
        CREATE INDEX IF NOT EXISTS idx_permanent_memories_updated
            ON permanent_memories(updated_at);
        """
    )
    existing_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(temp_documents)").fetchall()
    }
    if "outline" not in existing_cols:
        conn.execute("ALTER TABLE temp_documents ADD COLUMN outline TEXT DEFAULT ''")


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_]{3,}", (text or "").lower())
    return {w for w in words if w not in STOP_WORDS}


def _compact_text(text: str, limit: int | None = None) -> str:
    lines = []
    seen_blank = False
    for raw in (text or "").replace("\r", "\n").splitlines():
        line = " ".join(raw.split()).strip()
        if not line:
            if not seen_blank:
                lines.append("")
            seen_blank = True
            continue
        seen_blank = False
        lines.append(line)
    compact = "\n".join(lines).strip()
    return compact[:limit] if limit else compact


def _chunk_text(text: str) -> list[str]:
    text = _compact_text(text)
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + TEMP_CHUNK_SIZE)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - TEMP_CHUNK_OVERLAP, start + 1)
    return chunks


def _build_outline(text: str, limit: int = 120) -> str:
    """Extract a lightweight outline from visible chapter/section headings."""
    headings = []
    seen = set()
    heading_re = re.compile(
        r"^(?:chapter|unit|module|section|part)\s+[\w.-]+(?:\s*[:.-]\s*|\s+).+|"
        r"^\d+(?:\.\d+){0,3}\s+[\w][\w\s,;:()/-]{4,100}$",
        re.IGNORECASE,
    )
    for raw in (text or "").splitlines():
        line = " ".join(raw.split()).strip()
        if not 5 <= len(line) <= 140:
            continue
        if heading_re.match(line) or (line.isupper() and len(line.split()) <= 12):
            key = line.lower()
            if key not in seen:
                headings.append(line)
                seen.add(key)
        if len(headings) >= limit:
            break
    return "\n".join(f"- {heading}" for heading in headings)


def cleanup_expired_temp_documents() -> int:
    """Delete expired temporary document memory rows."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM temp_documents WHERE expires_at <= ?", (_now(),))
        return int(cur.rowcount or 0)


def remember_temp_document(
    *,
    filename: str,
    full_text: str,
    digest: str = "",
    user_prompt: str = "",
    ttl_days: int | None = None,
) -> dict:
    """Store a whole uploaded document as temporary memory."""
    cleanup_expired_temp_documents()
    text = _compact_text(full_text)
    chunks = _chunk_text(text)
    outline = _build_outline(text)
    created_at = _now()
    ttl = TEMP_DOC_TTL_DAYS if ttl_days is None else ttl_days
    expires_at = created_at + max(1, ttl) * 24 * 60 * 60
    doc_id = digest or uuid.uuid4().hex[:16]
    safe_filename = Path(filename or "document").name

    with _connect() as conn:
        conn.execute("DELETE FROM temp_documents WHERE id = ?", (doc_id,))
        conn.execute(
            """
            INSERT INTO temp_documents
                (id, filename, full_text, outline, user_prompt, digest, created_at, expires_at, char_count, chunk_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, safe_filename, text, outline, user_prompt, digest, created_at, expires_at, len(text), len(chunks)),
        )
        conn.executemany(
            """
            INSERT INTO temp_document_chunks (document_id, chunk_id, text, tokens)
            VALUES (?, ?, ?, ?)
            """,
            [
                (doc_id, i, chunk, json.dumps(sorted(_tokens(chunk))[:240]))
                for i, chunk in enumerate(chunks)
            ],
        )

    return {
        "id": doc_id,
        "filename": safe_filename,
        "created_at": created_at,
        "expires_at": expires_at,
        "char_count": len(text),
        "chunk_count": len(chunks),
        "outline": outline,
        "ttl_days": ttl,
    }


def retrieve_temp_document_context(query: str, max_chunks: int = 5) -> list[dict]:
    """Retrieve relevant chunks from unexpired temporary documents."""
    cleanup_expired_temp_documents()
    q_tokens = _tokens(query)
    if not q_tokens:
        return []

    scored: list[tuple[int, int, dict]] = []
    q_lower = (query or "").lower()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.filename, d.created_at, d.expires_at,
                   c.chunk_id, c.text, c.tokens
            FROM temp_document_chunks c
            JOIN temp_documents d ON d.id = c.document_id
            WHERE d.expires_at > ?
            """,
            (_now(),),
        ).fetchall()

    min_score = 2 if len(q_tokens) >= 2 else 1
    for row in rows:
        c_tokens = set(json.loads(row["tokens"] or "[]"))
        overlap = len(q_tokens & c_tokens)
        title_bonus = 3 if row["filename"].lower() in q_lower else 0
        score = overlap + title_bonus
        if score >= min_score:
            scored.append(
                (
                    score,
                    int(row["created_at"]),
                    {
                        "book_id": row["id"],
                        "book": row["filename"],
                        "chunk_id": row["chunk_id"],
                        "text": row["text"],
                        "expires_at": row["expires_at"],
                        "memory_type": "temporary_document",
                    },
                )
            )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    limit = min(max_chunks, TEMP_MAX_RETRIEVAL_CHUNKS)
    return [chunk for _, _, chunk in scored[:limit]]


def latest_temp_document_snapshot(max_chars: int | None = None) -> dict:
    """Return newest unexpired document metadata, outline, and capped full text."""
    cleanup_expired_temp_documents()
    limit = TEMP_FULL_CONTEXT_CHARS if max_chars is None else max_chars
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, filename, full_text, outline, created_at, expires_at, char_count, chunk_count
            FROM temp_documents
            WHERE expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_now(),),
        ).fetchone()
    if not row:
        return {}
    data = dict(row)
    data["full_text"] = _compact_text(data.get("full_text", ""), limit=limit)
    data["truncated"] = data.get("char_count", 0) > len(data["full_text"])
    return data


def latest_temp_document_context(max_chunks: int = 5) -> list[dict]:
    cleanup_expired_temp_documents()
    with _connect() as conn:
        doc = conn.execute(
            """
            SELECT id, filename, expires_at
            FROM temp_documents
            WHERE expires_at > ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_now(),),
        ).fetchone()
        if not doc:
            return []
        rows = conn.execute(
            """
            SELECT chunk_id, text
            FROM temp_document_chunks
            WHERE document_id = ?
            ORDER BY chunk_id
            """,
            (doc["id"],),
        ).fetchall()

    if not rows:
        return []
    if len(rows) <= max_chunks:
        picked = list(range(len(rows)))
    else:
        picked = [0, len(rows) // 2, len(rows) - 1]
        for i in range(1, len(rows)):
            if len(picked) >= max_chunks:
                break
            if i not in picked:
                picked.append(i)
        picked = sorted(set(picked))[:max_chunks]

    return [
        {
            "book_id": doc["id"],
            "book": doc["filename"],
            "chunk_id": rows[i]["chunk_id"],
            "text": rows[i]["text"],
            "expires_at": doc["expires_at"],
            "memory_type": "temporary_document",
        }
        for i in picked
    ]


def list_temp_documents(limit: int = 20) -> list[dict]:
    cleanup_expired_temp_documents()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, created_at, expires_at, char_count, chunk_count
            FROM temp_documents
            WHERE expires_at > ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (_now(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def remember_permanent(
    content: str,
    *,
    raw: str = "",
    kind: str = "fact",
    category: str = "knowledge",
    importance: int = 5,
) -> dict:
    """Store/update durable memory."""
    content = _compact_text(content, limit=1200)
    raw = _compact_text(raw or content, limit=1600)
    if not content:
        return {}

    new_words = _tokens(content)
    now = _now()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM permanent_memories").fetchall()
        for row in rows:
            existing_words = _tokens(row["content"])
            if new_words and existing_words:
                overlap = len(new_words & existing_words) / max(len(new_words), len(existing_words))
                if overlap > 0.6:
                    conn.execute(
                        """
                        UPDATE permanent_memories
                        SET content = ?, raw = ?, kind = ?, category = ?, importance = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (content, raw, kind, category, importance, now, row["id"]),
                    )
                    return {
                        "id": row["id"],
                        "kind": kind,
                        "category": category,
                        "content": content,
                        "updated_at": now,
                    }

        item_id = uuid.uuid4().hex[:10]
        conn.execute(
            """
            INSERT INTO permanent_memories
                (id, kind, category, content, raw, importance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, kind, category, content, raw, importance, now, now),
        )
    return {
        "id": item_id,
        "kind": kind,
        "category": category,
        "content": content,
        "created_at": now,
    }


def search_permanent_memory(query: str, limit: int = 8) -> list[dict]:
    q_tokens = _tokens(query)
    if not q_tokens:
        return []
    scored: list[tuple[int, int, dict]] = []
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM permanent_memories").fetchall()
    for row in rows:
        overlap = len(q_tokens & _tokens(row["content"]))
        if overlap:
            scored.append((overlap, int(row["updated_at"]), dict(row)))
    scored.sort(key=lambda item: (item[0], item[1], item[2].get("importance", 0)), reverse=True)
    return [item for _, _, item in scored[:limit]]


def get_permanent_memory_block(limit: int = 20) -> str:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT kind, category, content
            FROM permanent_memories
            ORDER BY importance DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    if not rows:
        return ""
    lines = [f"  - [{row['category']}] {row['content'][:140]}" for row in rows]
    return "\n\nPERMANENT MEMORY (important facts/preferences; never forget unless user asks):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Active document block — injected into realtime system prompt so Gemini
# can answer PDF/document questions instantly without tool calls.
# ---------------------------------------------------------------------------

PROMPT_INJECT_CHARS = env_int("VANI_PROMPT_INJECT_DOC_CHARS", 18000)


def get_active_document_prompt_block() -> str:
    """
    Returns a compact system-prompt block for the most recently uploaded
    document (if any unexpired one exists). Capped at PROMPT_INJECT_CHARS so
    the realtime Gemini context window isn't blown.

    Called every time get_realtime_prompt() is assembled — keeps the session
    always aware of whatever Rudra last uploaded.
    """
    cleanup_expired_temp_documents()
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT id, filename, full_text, outline, char_count, chunk_count,
                       expires_at, created_at
                FROM temp_documents
                WHERE expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_now(),),
            ).fetchone()
        if not row:
            return ""

        data = dict(row)
        filename   = data.get("filename", "uploaded document")
        outline    = _compact_text(data.get("outline", ""), limit=2000)
        full_text  = _compact_text(data.get("full_text", ""), limit=PROMPT_INJECT_CHARS)
        char_count = data.get("char_count", 0)
        chunk_count= data.get("chunk_count", 0)
        truncated  = char_count > len(full_text)

        trunc_note = (
            f"\n[NOTE: Document is {char_count:,} chars. Showing first {PROMPT_INJECT_CHARS:,} chars. "
            "For deeper sections, Rudra can ask specifically.]"
            if truncated else ""
        )

        outline_block = f"\n\n### Outline\n{outline}" if outline else ""

        # Check if Gemini Files API has a native copy of this file
        gemini_uri_block = ""
        try:
            from vani.services.gemini_file_store import get_active_gemini_file
            gf = get_active_gemini_file()
            if gf:
                gemini_uri_block = (
                    f"\n**Gemini File URI:** {gf['file_uri']}  "
                    f"(native file access — you can reference this directly)\n"
                )
        except Exception:
            pass

        return (
            f"\n\n---\n"
            f"## ACTIVE DOCUMENT (uploaded by Rudra)\n"
            f"**File:** {filename}  |  {char_count:,} chars, {chunk_count} chunks\n"
            f"{gemini_uri_block}"
            f"{outline_block}\n\n"
            f"### Full Content\n{full_text}{trunc_note}\n"
            f"---\n"
            f"Use this document content to answer Rudra's questions directly and instantly. "
            f"Do NOT say 'document is being processed' or 'I need to check' — the content is RIGHT HERE above.\n"
        )
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# BRIDGE API — compatibility shim for document_service.py (merged feature)
# These wrap the existing remember_temp_document / temp_documents system.
# ══════════════════════════════════════════════════════════════════════════════

# Expose a simple constant so document_service.py can import DOC_TTL_HOURS
DOC_TTL_HOURS: int = TEMP_DOC_TTL_DAYS * 24


def store_active_document(filename: str, text: str) -> None:
    """
    Bridge: store a document so it appears in get_active_document_prompt_block().
    Wraps the existing remember_temp_document SQLite layer.
    Called by document_service.py after text extraction.
    """
    remember_temp_document(filename=filename, full_text=text)


def get_active_document_status() -> dict:
    """
    Return metadata about the currently stored document.
    Used by /document_status HTTP endpoint in app.py.
    """
    cleanup_expired_temp_documents()
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT id, filename, char_count, chunk_count, created_at, expires_at
                FROM temp_documents
                WHERE expires_at > ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (_now(),),
            ).fetchone()
        if not row:
            return {"present": False}
        data = dict(row)
        import datetime
        return {
            "present":     True,
            "expired":     False,
            "filename":    data.get("filename", "unknown"),
            "uploaded_at": str(data.get("created_at", "")),
            "expires_at":  str(data.get("expires_at", "")),
            "char_count":  data.get("char_count", 0),
        }
    except Exception:
        return {"present": False}


def clear_active_document() -> None:
    """
    Manually remove all temp documents from memory.
    Used by /clear_document HTTP endpoint in app.py.
    """
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM temp_documents")
            conn.commit()
    except Exception:
        pass

    try:
        from vani.services.gemini_file_store import clear_active_gemini_files
        clear_active_gemini_files()
    except Exception:
        pass
