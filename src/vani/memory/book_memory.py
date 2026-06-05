import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from vani.config import BOOK_MEMORY_DIR, env_int
from vani.memory.human_memory import (
    latest_temp_document_context,
    latest_temp_document_snapshot,
    list_temp_documents,
    remember_temp_document,
    retrieve_temp_document_context,
)

BOOK_DIR = BOOK_MEMORY_DIR
BOOK_INDEX = BOOK_DIR / "index.json"

CHUNK_SIZE = env_int("VANI_BOOK_CHUNK_SIZE", 1800)
CHUNK_OVERLAP = env_int("VANI_BOOK_CHUNK_OVERLAP", 250)
MAX_CONTEXT_CHARS = env_int("VANI_BOOK_CONTEXT_CHARS", 45000)
MAX_FULL_DOCUMENT_CONTEXT_CHARS = env_int("VANI_FULL_DOCUMENT_CONTEXT_CHARS", 120000)

STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "what", "why", "how", "when", "where", "which", "who", "about", "into",
    "hai", "hain", "tha", "thi", "kya", "kaise", "kyu", "kyun", "mein", "mai",
    "mujhe", "bata", "samjha", "explain", "book", "pdf", "chapter", "concept",
    "iske", "isme", "usme", "from", "related", "vani", "rudra",
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

BOOK_REFERENCE_WORDS = {
    "book", "books", "pdf", "pdfs", "document", "documents", "doc", "docs",
    "file", "uploaded", "upload", "sent", "send", "learned", "learnt",
    "remember", "memory", "summary", "summarize", "about",
    "bheja", "bheji", "send", "kiya", "kya", "yaad", "padh", "padha",
}


def _ensure_store():
    BOOK_DIR.mkdir(exist_ok=True)
    if not BOOK_INDEX.exists():
        _write_index({"books": [], "chunks": []})


def _read_index() -> dict:
    _ensure_store()
    try:
        return json.loads(BOOK_INDEX.read_text(encoding="utf-8"))
    except Exception:
        return {"books": [], "chunks": []}


def _write_index(data: dict):
    BOOK_DIR.mkdir(exist_ok=True)
    tmp = BOOK_INDEX.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
            f.flush()
            import os as _os
            _os.fsync(f.fileno())
        tmp.replace(BOOK_INDEX)
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).error(f"[BOOK_MEMORY] Index write failed: {e}")
        try: tmp.unlink(missing_ok=True)
        except Exception: pass


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


def _extract_docx_text(data: bytes) -> str:
    chunks = []
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
        names = [
            n for n in zf.namelist()
            if n.startswith("word/") and n.endswith(".xml")
            and any(part in n for part in ("document", "header", "footer", "footnotes", "endnotes"))
        ]
        for name in names:
            root = ET.fromstring(zf.read(name))
            for node in root.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag == "t" and node.text:
                    chunks.append(node.text)
                elif tag in {"tab", "br", "cr"}:
                    chunks.append("\n")
                elif tag == "p":
                    chunks.append("\n")
    return _compact_text(" ".join(chunks).replace(" \n ", "\n"))


def _extract_with_textutil(path: str) -> str:
    try:
        result = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", path],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0 and result.stdout.strip():
            return _compact_text(result.stdout)
    except Exception:
        pass
    return ""


def _extract_pdf_text(path: str) -> str:
    for cmd in (
        ["pdftotext", "-layout", path, "-"],
        ["mdls", "-raw", "-name", "kMDItemTextContent", path],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            text = result.stdout.strip()
            if result.returncode == 0 and text and text != "(null)":
                return _compact_text(text)
        except Exception:
            continue

    try:
        result = subprocess.run(["strings", path], capture_output=True, text=True, timeout=25)
        if result.returncode == 0 and result.stdout.strip():
            return _compact_text(result.stdout)
    except Exception:
        pass
    return ""


def extract_document_text(filename: str, data: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".py", ".js", ".ts", ".html", ".css", ".xml"}:
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                return _compact_text(data.decode(enc))
            except Exception:
                continue
    if suffix == ".docx":
        return _extract_docx_text(data)

    with tempfile.NamedTemporaryFile(suffix=suffix or ".document", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        if suffix == ".pdf":
            return _extract_pdf_text(tmp.name)
        if suffix in {".rtf", ".doc", ".odt"}:
            return _extract_with_textutil(tmp.name)
    return ""


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_]{3,}", (text or "").lower())
    return {w for w in words if w not in STOP_WORDS}


def _chunk_text(text: str) -> list[str]:
    text = _compact_text(text)
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _call_model(prompt: str, timeout: int = 45) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            model_name = os.getenv("VANI_TEXT_MODEL", "gemini-flash-lite-latest")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response.text and response.text.strip():
                return response.text.strip()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[BOOK_MEMORY] google-genai Client failed: {e}")

    try:
        import requests

        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"), "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception:
        return ""


def learn_book(filename: str, data: bytes, user_prompt: str = "") -> dict:
    text = extract_document_text(filename, data)
    if not text:
        return {
            "ok": False,
            "reply": "Is file se readable text nahi nikal paayi. Agar PDF scanned image hai toh OCR chahiye.",
        }

    chunks = _chunk_text(text)
    digest = hashlib.sha256(data).hexdigest()[:16]
    book = remember_temp_document(
        filename=filename,
        full_text=text,
        digest=digest,
        user_prompt=user_prompt,
    )

    sample_parts = []
    if chunks:
        sample_parts.append(chunks[0])
        if len(chunks) > 2:
            sample_parts.append(chunks[len(chunks) // 2])
        if len(chunks) > 1:
            sample_parts.append(chunks[-1])
    sample = "\n\n---\n\n".join(sample_parts)[:9000]
    requested_depth = user_prompt or "Go deep and understand this completely."
    prompt = f"""You are Vani. Rudra uploaded a book/document for long-term learning.

Document: {book['filename']}
Chunks stored: {book['chunk_count']}
Characters extracted: {book['char_count']}
User instruction: {requested_depth}

Create a compact study map in Hinglish by default. If the user instruction asks English, use English.

Return Markdown with:
# Learned: {book['filename']}
## Big Picture
## Core Concepts
## How To Study This
## What You Can Ask Me Later
## Limitations

Be honest: the full document is stored in chunks for later retrieval; this response is only the first study map.

Sample from document:
{sample}
"""
    reply = _call_model(prompt, timeout=45)
    if not reply:
        reply = (
            f"# Learned: {book['filename']}\n"
            f"Stored full document temporarily for {book.get('ttl_days', 2)} days "
            f"({book['chunk_count']} searchable chunks). "
            "Ab tu 2 din tak is PDF/book se related questions puch sakta hai."
        )
    # ── Signal realtime session to refresh its system prompt ──────────────
    # The document is now in temp DB. If a live session exists, nudge it so
    # the next user turn sees the injected document context immediately.
    try:
        from vani.reasoning.worker import say_to_user
        import asyncio, threading
        def _nudge():
            # Fire-and-forget: update Gemini's context with the fresh doc block
            try:
                from vani.memory.human_memory import get_active_document_prompt_block
                _block = get_active_document_prompt_block()
                if _block:
                    import logging
                    logging.getLogger(__name__).info(
                        "[BOOK_MEMORY] Active doc block ready (%d chars) — realtime prompt will include it.",
                        len(_block),
                    )
            except Exception:
                pass
        threading.Thread(target=_nudge, daemon=True).start()
    except Exception:
        pass

    return {"ok": True, "reply": reply, "book": book}


def retrieve_book_context(query: str, max_chunks: int = 5) -> list[dict]:
    temp_chunks = retrieve_temp_document_context(query, max_chunks=max_chunks)
    if temp_chunks:
        return temp_chunks

    index = _read_index()
    chunks = index.get("chunks", [])
    if not chunks:
        return []
    q_tokens = _tokens(query)
    if not q_tokens:
        return []

    scored = []
    q_lower = query.lower()
    for chunk in chunks:
        c_tokens = set(chunk.get("tokens", []))
        overlap = len(q_tokens & c_tokens)
        title_bonus = 3 if chunk.get("book", "").lower() in q_lower else 0
        score = overlap + title_bonus
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored or scored[0][0] < 2:
        return []
    return [chunk for _, chunk in scored[:max_chunks]]


def _latest_book_context(max_chunks: int = 5) -> list[dict]:
    temp_chunks = latest_temp_document_context(max_chunks=max_chunks)
    if temp_chunks:
        return temp_chunks

    index = _read_index()
    books = index.get("books", [])
    chunks = index.get("chunks", [])
    if not books or not chunks:
        return []

    latest = max(books, key=lambda b: b.get("created_at", 0))
    book_id = latest.get("id")
    if not book_id:
        return []

    book_chunks = [c for c in chunks if c.get("book_id") == book_id]
    if not book_chunks:
        return []

    if len(book_chunks) <= max_chunks:
        return book_chunks

    picks = [0, len(book_chunks) // 2, len(book_chunks) - 1]
    for i in range(1, len(book_chunks)):
        if len(picks) >= max_chunks:
            break
        if i not in picks:
            picks.append(i)
    return [book_chunks[i] for i in sorted(set(picks))[:max_chunks]]


def _is_generic_book_query(query: str) -> bool:
    q = (query or "").lower()
    tokens = set(re.findall(r"[a-zA-Z0-9_]{2,}", q))
    if tokens & BOOK_REFERENCE_WORDS:
        return True
    return any(phrase in q for phrase in (
        "what did i send", "what i sent", "kya bheja", "kya upload",
        "which pdf", "kaunsi pdf", "kaunsa pdf", "recent pdf",
    ))


def _needs_full_document_context(query: str) -> bool:
    q = (query or "").lower()
    return any(phrase in q for phrase in (
        "whole pdf", "whole document", "entire pdf", "entire document",
        "full pdf", "full document", "complete pdf", "complete document",
        "summarize this pdf", "summarise this pdf", "summary of this pdf",
        "analyze this pdf", "analyse this pdf", "understand this pdf",
        "exam practice", "practice questions", "question paper", "important questions",
        "make notes", "study plan", "revision", "revise", "chapter wise",
        "poora pdf", "puri pdf", "pure pdf", "poori book", "puri book",
        "is pdf ko pura", "is book ko pura", "exam ke liye",
    ))


def answer_from_books(query: str) -> str:
    full_doc = latest_temp_document_snapshot(MAX_FULL_DOCUMENT_CONTEXT_CHARS) if _needs_full_document_context(query) else {}
    context_chunks = []
    if not full_doc:
        context_chunks = retrieve_book_context(query, max_chunks=24)
    if not context_chunks and _is_generic_book_query(query):
        context_chunks = _latest_book_context()
    if not context_chunks and not full_doc:
        return ""

    context = []
    total = 0
    if full_doc:
        outline = full_doc.get("outline", "").strip()
        if outline:
            context.append(f"[{full_doc['filename']} | extracted outline]\n{outline}")
        trunc_note = "\n[NOTE: Full text was capped for model context. Ask more specific follow-ups for deeper sections.]" if full_doc.get("truncated") else ""
        context.append(f"[{full_doc['filename']} | full extracted text]\n{full_doc.get('full_text', '')}{trunc_note}")
    else:
        for chunk in context_chunks:
            block = f"[{chunk['book']} | chunk {chunk['chunk_id']}]\n{chunk['text']}"
            if total + len(block) > MAX_CONTEXT_CHARS:
                break
            context.append(block)
            total += len(block)

    prompt = f"""You are Vani (Rudra's close friend). Respond naturally in Hinglish, with a warm, casual, and authentic tone. No robotic buffering, and no rigid structured formats (like "Short direct answer first", "Deep explanation", etc.) unless Rudra explicitly asks for study notes, deep study maps, or revision checklists.

Keep your response friendly, concise (1-3 sentences normally), and highly genuine, just like a real human companion. Use the relevant book context provided below to answer Rudra's question directly, integrating the information naturally into a friendly chat.

Relevant book context:
{chr(10).join(context)}

Rudra's question:
{query}
"""
    reply = _call_model(prompt, timeout=45)
    if reply:
        return reply

    latest_book = full_doc.get("filename") if full_doc else context_chunks[0].get("book", "uploaded document")
    excerpts = []
    if full_doc:
        excerpt = _compact_text(full_doc.get("full_text", ""), limit=2500)
        if excerpt:
            excerpts.append(f"- {excerpt}")
    else:
        for chunk in context_chunks[:5]:
            text = _compact_text(chunk.get("text", ""), limit=900)
            if text:
                excerpts.append(f"- {text}")
    if not excerpts:
        return ""
    return (
        f"# From {latest_book}\n"
        "Model abhi available nahi hai, par PDF/document memory se relevant stored text mil gaya.\n\n"
        "## Stored Context\n"
        + "\n".join(excerpts)
        + "\n\nTu specific question puchega toh main isi stored PDF context se answer nikalungi."
    )


def list_learned_books() -> str:
    temp_docs = list_temp_documents()
    if temp_docs:
        lines = ["# Temporary Document Memory", "These documents auto-delete after 2 days:"]
        now = int(time.time())
        for book in temp_docs:
            hours_left = max(0, int((book["expires_at"] - now) / 3600))
            lines.append(
                f"- **{book['filename']}** - {book['chunk_count']} chunks, "
                f"{book['char_count']} chars, expires in ~{hours_left}h"
            )
        return "\n".join(lines)

    books = _read_index().get("books", [])
    if not books:
        return "Abhi koi temporary PDF/document memory nahi hai."
    lines = ["# Learned Books"]
    for book in books[-20:]:
        lines.append(f"- **{book['filename']}** - {book['chunk_count']} chunks, {book['char_count']} chars")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# BRIDGE API — compatibility shim for document_service.py (merged feature)
# ══════════════════════════════════════════════════════════════════════════════

def store_book(filename: str, full_text: str) -> str:
    """
    Bridge: index a document's full text for BM25 retrieval.
    Called by document_service.py after the human_memory store.
    Returns a book_id string.
    """
    import hashlib as _hashlib
    digest = _hashlib.sha256(full_text.encode()).hexdigest()[:16]
    # Reuse remember_temp_document which is already imported in this module
    book = remember_temp_document(
        filename=filename,
        full_text=full_text,
        digest=digest,
    )
    return book.get("id", digest)
