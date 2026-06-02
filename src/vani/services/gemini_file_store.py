"""
vani/services/gemini_file_store.py
═══════════════════════════════════════════════════════════════════════════════
Gemini Files API — upload a document so Realtime Gemini has native file context.

Flow:
  1. upload_to_gemini_files(filename, data, mime_type)
     → calls google.genai Files API, returns file URI + expiry
  2. URI is stored in SQLite (same DB as human_memory) with 48hr TTL
  3. get_active_gemini_file_uri() → latest valid URI or None
  4. get_gemini_file_prompt_block() → small instruction block for system prompt
     (tells Gemini "you have this file; refer to it directly")

The Gemini Files API keeps files for 48 hours automatically — we mirror that.

Dependencies: google-genai>=2.5.0  (already in requirements)
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import sqlite3
import threading
import time
from pathlib import Path

from vani.config import PROJECT_ROOT

log = logging.getLogger("vani.services.gemini_file_store")

DB_PATH = PROJECT_ROOT / "conversations" / "vani_gemini_files.sqlite3"
FILE_TTL_SECONDS = 48 * 3600  # Gemini keeps files 48 h


# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gemini_files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT NOT NULL,
            file_uri    TEXT NOT NULL,
            file_name   TEXT NOT NULL,
            mime_type   TEXT NOT NULL,
            uploaded_at INTEGER NOT NULL,
            expires_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_gemini_files_expires
            ON gemini_files(expires_at);
    """)
    conn.commit()
    return conn


def _now() -> int:
    return int(time.time())


def _cleanup_expired():
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM gemini_files WHERE expires_at <= ?", (_now(),))
            conn.commit()
    except Exception:
        pass


def _store_uri(filename: str, file_uri: str, file_name: str, mime_type: str):
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO gemini_files (filename, file_uri, file_name, mime_type, uploaded_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (filename, file_uri, file_name, mime_type, now, now + FILE_TTL_SECONDS),
        )
        conn.commit()


def get_active_gemini_file() -> dict | None:
    """Return the most recent unexpired Gemini file record, or None."""
    _cleanup_expired()
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT filename, file_uri, file_name, mime_type, uploaded_at, expires_at
                FROM gemini_files
                WHERE expires_at > ?
                ORDER BY uploaded_at DESC
                LIMIT 1
                """,
                (_now(),),
            ).fetchone()
        if row:
            return {
                "filename":    row[0],
                "file_uri":    row[1],
                "file_name":   row[2],
                "mime_type":   row[3],
                "uploaded_at": row[4],
                "expires_at":  row[5],
            }
    except Exception as e:
        log.warning(f"[GEMINI_FILES] get_active_gemini_file error: {e}")
    return None


def get_gemini_file_prompt_block() -> str:
    """
    Returns a small system-prompt block that tells Gemini Realtime
    it has a native file reference it can use directly.
    Called by get_realtime_prompt() in prompts.py.
    """
    rec = get_active_gemini_file()
    if not rec:
        return ""
    import datetime
    expires_dt = datetime.datetime.fromtimestamp(rec["expires_at"]).strftime("%d %b %Y %H:%M IST")
    return (
        f"\n\n---\n"
        f"## UPLOADED FILE (Gemini Native Access)\n"
        f"**File:** {rec['filename']}  |  expires {expires_dt}\n"
        f"**Gemini File URI:** {rec['file_uri']}\n\n"
        f"This file has been uploaded directly to Gemini Files API. "
        f"You have full native access to its content — answer Rudra's questions "
        f"about it directly without saying 'I cannot access files'.\n"
        f"---\n"
    )


# ── Upload ────────────────────────────────────────────────────────────────────

def _guess_mime(filename: str, data: bytes) -> str:
    mime, _ = mimetypes.guess_type(filename)
    if mime:
        return mime
    # Sniff PDF magic bytes
    if data[:4] == b"%PDF":
        return "application/pdf"
    # Sniff DOCX (ZIP-based)
    if data[:2] == b"PK":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "text/plain"


def upload_to_gemini_files(filename: str, data: bytes, mime_type: str = "") -> dict | None:
    """
    Upload file bytes to Gemini Files API.
    Returns {"file_uri": ..., "file_name": ..., "mime_type": ...} or None on failure.

    This is blocking — call it from a background thread.
    """
    try:
        import google.genai as genai

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            log.warning("[GEMINI_FILES] GOOGLE_API_KEY not set — skipping Gemini file upload")
            return None

        client = genai.Client(api_key=api_key)

        mime = mime_type or _guess_mime(filename, data)
        file_bytes = io.BytesIO(data)
        file_bytes.name = filename  # some SDK versions use this

        log.info(f"[GEMINI_FILES] Uploading '{filename}' ({len(data):,} bytes, {mime}) ...")

        # google-genai>=2.5.0 API
        response = client.files.upload(
            file=file_bytes,
            config={
                "mime_type": mime,
                "display_name": filename,
            },
        )

        # Wait for file to be ACTIVE (usually instant for text files)
        max_wait = 60  # seconds
        waited = 0
        while waited < max_wait:
            file_info = client.files.get(name=response.name)
            state = getattr(file_info, "state", None)
            state_name = state.name if hasattr(state, "name") else str(state)
            if state_name == "ACTIVE":
                break
            if state_name == "FAILED":
                log.error(f"[GEMINI_FILES] File processing FAILED for '{filename}'")
                return None
            time.sleep(2)
            waited += 2

        uri = response.uri
        name = response.name
        log.info(f"[GEMINI_FILES] Upload complete: uri={uri}, name={name}")

        _store_uri(filename, uri, name, mime)

        return {"file_uri": uri, "file_name": name, "mime_type": mime}

    except ImportError:
        log.warning("[GEMINI_FILES] google-genai not installed — pip install google-genai")
        return None
    except Exception as e:
        log.error(f"[GEMINI_FILES] Upload failed for '{filename}': {e}")
        return None


def upload_in_background(filename: str, data: bytes, mime_type: str = "",
                         on_complete=None):
    """
    Fire-and-forget background upload.
    on_complete(result_dict | None) is called when done (optional).
    """
    def _worker():
        result = upload_to_gemini_files(filename, data, mime_type)
        if on_complete:
            try:
                on_complete(result)
            except Exception as e:
                log.warning(f"[GEMINI_FILES] on_complete callback error: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="gemini-file-upload")
    t.start()
    return t
