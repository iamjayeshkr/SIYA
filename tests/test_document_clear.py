import pytest
from unittest.mock import patch, MagicMock

from vani.reasoning.router import _router_classify, _dispatch_intent
from vani.memory import human_memory
from vani.services import gemini_file_store


def _use_temp_dbs(tmp_path, monkeypatch):
    # Mock databases to use temp paths for tests
    monkeypatch.setattr(human_memory, "DB_PATH", tmp_path / "vani_human_memory.sqlite3")
    monkeypatch.setattr(gemini_file_store, "DB_PATH", tmp_path / "vani_gemini_files.sqlite3")


def test_clear_document_memory_classification():
    # Test English and Hinglish variations
    test_queries = [
        "remove docx knowledge",
        "delete pdf memory",
        "clear document memory",
        "pdf memory clear karo",
        "document knowledge remove kar do",
        "clear book knowledge",
    ]
    for q in test_queries:
        intent, data = _router_classify(q)
        assert intent == "CLEAR_DOCUMENT_MEMORY", f"Query '{q}' failed classification"


def test_clear_document_memory_dispatch(tmp_path, monkeypatch):
    _use_temp_dbs(tmp_path, monkeypatch)

    # 1. Store dummy active document in human_memory
    doc = human_memory.remember_temp_document(
        filename="notes.docx",
        full_text="This is some active knowledge to clear.",
        digest="digest123",
        ttl_days=2,
    )
    assert doc["id"] == "digest123"

    # Verify document exists in memory snapshot
    snapshot = human_memory.latest_temp_document_snapshot()
    assert snapshot["filename"] == "notes.docx"

    # 2. Store dummy active file in gemini_file_store
    with gemini_file_store._connect() as conn:
        import time
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO gemini_files (filename, file_uri, file_name, mime_type, uploaded_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("notes.docx", "https://api.gemini/file1", "file-1234", "text/plain", now, now + 3600),
        )
        conn.commit()

    # Verify Gemini file exists
    gemini_file = gemini_file_store.get_active_gemini_file()
    assert gemini_file is not None
    assert gemini_file["filename"] == "notes.docx"

    # 3. Trigger dispatch to clear it
    import asyncio
    response = asyncio.run(_dispatch_intent("CLEAR_DOCUMENT_MEMORY", {}, "remove docx knowledge"))

    # Verify response message
    assert "clear ho gaya" in response

    # 4. Verify both caches are empty now
    assert human_memory.latest_temp_document_snapshot() == {}
    assert gemini_file_store.get_active_gemini_file() is None
