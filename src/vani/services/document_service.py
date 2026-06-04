"""
vani/services/document_service.py
═══════════════════════════════════════════════════════════════════════════════
Document Upload Service — handles the /analyze_document HTTP endpoint.

Flow:
  1. Receive uploaded file (PDF, DOCX, TXT, MD, etc.)
  2. Extract full text (pdfminer for PDF, docx XML for DOCX, utf-8 for text)
  3. Store full text → human_memory.store_active_document()
     → Gemini Realtime gets the entire text in its system prompt (BM25 fallback)
  4. Also index in book_memory.store_book()
     → BM25 fallback for text_chat queries
  5. Background: upload raw file bytes to Gemini Files API (48hr native context)
     → gemini_file_store.upload_in_background()
  6. Return confirmation reply with char count and expiry info

Dependencies (pip install):
  pdfminer.six    — PDF text extraction (no Poppler needed)
  python-docx     — DOCX extraction (optional, falls back gracefully)
  google-genai    — Gemini Files API upload (already in requirements)
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("vani.services.document_service")

# ── Text extractors ───────────────────────────────────────────────────────────

def _extract_pdf(data: bytes) -> str:
    """Extract all text from PDF bytes using pdfminer.six."""
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        import io
        buf = io.StringIO()
        extract_text_to_fp(
            io.BytesIO(data),
            buf,
            laparams=LAParams(),
            output_type="text",
            codec="utf-8",
        )
        return buf.getvalue().strip()
    except ImportError:
        logger.warning("[DOC_SERVICE] pdfminer.six not installed — falling back to pypdf")
    except Exception as e:
        logger.warning(f"[DOC_SERVICE] pdfminer failed: {e} — trying pypdf")

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception as e2:
        raise RuntimeError(f"PDF extraction failed: {e2}") from e2


def _extract_docx(data: bytes) -> str:
    """Extract text from DOCX bytes."""
    try:
        import docx
        import io
        doc = docx.Document(io.BytesIO(data))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except ImportError:
        # Fallback: raw XML parse
        import zipfile, io, re
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        return re.sub(r"<[^>]+>", " ", xml).strip()


def _extract_text_file(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_epub(data: bytes) -> str:
    """Extract text from EPUB files without external libraries."""
    import zipfile
    import io
    import re
    try:
        texts = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            content_files = [
                name for name in z.namelist()
                if name.endswith((".xhtml", ".html", ".htm", ".xml"))
                and not name.endswith("container.xml")
                and not name.endswith("toc.ncx")
            ]
            content_files.sort()
            for name in content_files:
                html_content = z.read(name).decode("utf-8", errors="ignore")
                # Remove script/style blocks
                clean_html = re.sub(r"<(script|style)[^>]*>([\s\S]*?)<\/\1>", "", html_content, flags=re.I)
                clean_text = re.sub(r"<[^>]+>", " ", clean_html)
                clean_text = re.sub(r"\s+", " ", clean_text).strip()
                if clean_text:
                    texts.append(clean_text)
        return "\n\n".join(texts).strip()
    except Exception as e:
        logger.warning(f"[DOC_SERVICE] EPUB extract failed: {e}")
        return ""


def _extract_pptx(data: bytes) -> str:
    """Extract text from PPTX slides without python-pptx library."""
    import zipfile
    import io
    import re
    try:
        texts = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            slide_files = [
                name for name in z.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ]
            def _slide_num(name):
                nums = re.findall(r"\d+", name)
                return int(nums[0]) if nums else 0
            slide_files.sort(key=_slide_num)
            for name in slide_files:
                slide_xml = z.read(name).decode("utf-8", errors="ignore")
                text_runs = re.findall(r"<a:t[^>]*>([^<]*)</a:t>", slide_xml)
                slide_text = " ".join(text_runs).strip()
                if slide_text:
                    slide_name = Path(name).stem.capitalize()
                    texts.append(f"=== {slide_name} ===\n{slide_text}")
        return "\n\n".join(texts).strip()
    except Exception as e:
        logger.warning(f"[DOC_SERVICE] PPTX extract failed: {e}")
        return ""


def _extract_repository(data: bytes) -> str:
    """Extract and combine source files from a repository ZIP."""
    import zipfile
    import io
    try:
        texts = []
        extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json",
            ".md", ".java", ".cpp", ".c", ".h", ".cs", ".go", ".rs",
            ".swift", ".kt", ".sh", ".yaml", ".yml"
        }
        ignored_dirs = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__"}
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in sorted(z.namelist()):
                path = Path(name)
                if any(part in ignored_dirs for part in path.parts):
                    continue
                if path.suffix.lower() in extensions:
                    try:
                        content = z.read(name).decode("utf-8", errors="ignore")
                        if content.strip():
                            texts.append(f"=== FILE: {name} ===\n{content}")
                    except Exception:
                        continue
        return "\n\n".join(texts).strip()
    except Exception as e:
        logger.warning(f"[DOC_SERVICE] Repository ZIP extract failed: {e}")
        return ""


def extract_text(filename: str, data: bytes, browser_mime: str = "") -> str:
    """
    Dispatch to the right extractor based on filename extension.
    Returns full extracted text string.
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf" or browser_mime == "application/pdf":
        return _extract_pdf(data)

    if ext in {".docx", ".doc"}:
        return _extract_docx(data)

    if ext == ".epub":
        return _extract_epub(data)

    if ext in {".pptx", ".ppt"}:
        return _extract_pptx(data)

    if ext == ".zip":
        return _extract_repository(data)

    if ext in {".txt", ".md", ".markdown", ".csv", ".tsv",
               ".json", ".py", ".js", ".ts", ".html", ".css",
               ".xml", ".rtf", ".odt", ""}:
        return _extract_text_file(data)

    # Unknown — try as text
    return _extract_text_file(data)



# ── Main handler ──────────────────────────────────────────────────────────────

def analyze_document(
    filename: str,
    data: bytes,
    user_prompt: str = "",
    browser_mime: str = "",
) -> tuple[bool, str]:
    """
    Full document ingestion pipeline.

    Returns (success: bool, reply: str)
    reply is the message shown in the Vani UI bubble.
    """
    if not data:
        return False, "Document empty hai. Dobara try karo."

    # Step 1: Extract text
    try:
        full_text = extract_text(filename, data, browser_mime)
    except Exception as e:
        logger.error(f"[DOC_SERVICE] Extraction failed for '{filename}': {e}")
        return False, f"❌ '{filename}' read nahi ho paya. Error: {e}"

    if not full_text or len(full_text.strip()) < 20:
        return False, (
            f"'{filename}' mein koi readable text nahi mila. "
            "Scanned image PDF hai? OCR support coming soon."
        )

    char_count = len(full_text)
    word_count = len(full_text.split())

    # Step 2: Store in human_memory → Gemini Realtime system prompt (text fallback)
    try:
        from vani.memory.human_memory import store_active_document, DOC_TTL_HOURS
        store_active_document(filename, full_text)
    except Exception as e:
        logger.error(f"[DOC_SERVICE] human_memory store failed: {e}")
        return False, f"❌ Document memory mein save nahi ho paya: {e}"

    # Step 3: Index in book_memory for BM25 text_chat fallback
    try:
        from vani.memory.book_memory import store_book
        store_book(filename, full_text)
    except Exception as e:
        logger.warning(f"[DOC_SERVICE] book_memory index failed (non-fatal): {e}")

    # Step 4: Background — upload raw bytes to Gemini Files API (48hr native context)
    # This gives Gemini Realtime full native file access, not just injected text.
    try:
        from vani.services.gemini_file_store import upload_in_background
        mime = browser_mime or ""
        upload_in_background(filename, data, mime_type=mime)
        logger.info(f"[DOC_SERVICE] Gemini Files API upload queued for '{filename}'")
    except Exception as e:
        logger.warning(f"[DOC_SERVICE] Gemini file upload queue failed (non-fatal): {e}")

    # Step 5: Build confirmation reply
    from vani.memory.human_memory import DOC_TTL_HOURS
    expires_in = f"{DOC_TTL_HOURS} hours (2 days)"
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=DOC_TTL_HOURS)).strftime("%d %b %Y, %H:%M UTC")

    reply = (
        f"✅ '{filename}' ab mujhe poora yaad hai!\n\n"
        f"📊 {word_count:,} words · {char_count:,} characters padhe\n"
        f"⏰ Auto-forget: {expires_at} ({expires_in})\n\n"
        f"Ab seedha baat karo — document ke baare mein kuch bhi poochho. 🎯"
    )

    logger.info(
        f"[DOC_SERVICE] '{filename}' ingested — "
        f"{char_count:,} chars, {word_count:,} words"
    )
    return True, reply
