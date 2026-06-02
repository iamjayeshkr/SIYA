import time

from vani.memory import human_memory


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(human_memory, "DB_PATH", tmp_path / "vani_human_memory.sqlite3")


def test_temp_document_memory_expires_after_ttl(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    doc = human_memory.remember_temp_document(
        filename="architecture.pdf",
        full_text="Latency routing queue websocket memory architecture " * 20,
        digest="doc1",
        ttl_days=2,
    )

    assert doc["ttl_days"] == 2
    assert human_memory.retrieve_temp_document_context("latency architecture")

    with human_memory._connect() as conn:
        conn.execute("UPDATE temp_documents SET expires_at = ?", (int(time.time()) - 1,))

    assert human_memory.cleanup_expired_temp_documents() == 1
    assert human_memory.retrieve_temp_document_context("latency architecture") == []


def test_book_memory_uses_temporary_document_store(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    from vani.memory import book_memory

    monkeypatch.setattr(book_memory, "_call_model", lambda *_, **__: "")
    result = book_memory.learn_book(
        "notes.txt",
        b"Gemini realtime voice should stay fast while tool execution runs in background.",
    )

    assert result["ok"] is True
    assert result["book"]["ttl_days"] == 2
    chunks = book_memory.retrieve_book_context("realtime voice tool execution")
    assert chunks
    assert chunks[0]["memory_type"] == "temporary_document"


def test_temp_document_retrieval_can_return_many_chunks(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    text = "\n\n".join(
        f"Chapter {i}: Operating systems memory scheduling process exam practice topic {i}. "
        * 8
        for i in range(30)
    )
    human_memory.remember_temp_document(filename="os-book.txt", full_text=text, digest="os-book")

    chunks = human_memory.retrieve_temp_document_context(
        "operating systems memory scheduling exam practice",
        max_chunks=24,
    )

    assert len(chunks) > 5
    assert len(chunks) <= human_memory.TEMP_MAX_RETRIEVAL_CHUNKS


def test_full_document_snapshot_for_exam_queries(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    text = (
        "Chapter 1 Introduction\n"
        "This book explains database normalization, indexing, joins, and transactions for exams.\n"
        "Chapter 2 Transactions\n"
        "ACID properties include atomicity consistency isolation durability.\n"
    )
    human_memory.remember_temp_document(filename="dbms.txt", full_text=text, digest="dbms")

    snapshot = human_memory.latest_temp_document_snapshot()

    assert snapshot["filename"] == "dbms.txt"
    assert "ACID properties" in snapshot["full_text"]
    assert "Chapter 1 Introduction" in snapshot["outline"]


def test_permanent_memory_search(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    saved = human_memory.remember_permanent(
        "Rudra prefers concise Hinglish explanations",
        raw="remember Rudra prefers concise Hinglish explanations",
        kind="preference",
        category="preference",
        importance=8,
    )

    assert saved["id"]
    results = human_memory.search_permanent_memory("Hinglish explanations")
    assert results
    assert results[0]["category"] == "preference"
    assert "Hinglish" in human_memory.get_permanent_memory_block()
