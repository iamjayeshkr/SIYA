# 📄 VANI — PDF Upload & Document Memory Feature

## What This Feature Does

Upload any PDF through the Vani UI → Vani reads every word → Gemini Realtime
gets the full document injected into its system prompt → you can ask anything
about it in voice or text. Auto-forgets after **48 hours (2 days)** to keep
the system lean.

---

## Files Added / Changed

```
src/vani/
├── memory/
│   ├── __init__.py              ← new (package marker)
│   ├── human_memory.py          ← new ★ CORE: active-doc store + 2-day TTL
│   └── book_memory.py           ← new ★ BM25 retrieval index (text_chat fallback)
├── services/
│   └── document_service.py      ← new ★ /analyze_document handler + text extraction
├── app_server_patch.py          ← new (Flask routes to add to your app.py)
└── ui/
    └── ui.html                  ← patched (doc-badge, clearDocument, badge polling)
```

---

## Integration — 3 Steps

### Step 1: Add routes to your `vani/app.py`

Open `src/vani/app.py` (the file that already has `/analyze_image` on port 5500).

Add at the top:
```python
from vani.services.document_service import analyze_document
from vani.memory.human_memory import get_active_document_status, clear_active_document
```

Add these Flask routes alongside your existing ones:
```python
@app.route("/analyze_document", methods=["POST"])
def route_analyze_document():
    file   = request.files.get("file")
    prompt = request.form.get("prompt", "").strip()
    if not file or not file.filename:
        return jsonify({"reply": "❌ Koi file nahi mili."})
    ok, reply = analyze_document(
        file.filename, file.read(), prompt, file.mimetype or ""
    )
    return jsonify({"reply": reply})

@app.route("/document_status", methods=["GET"])
def route_document_status():
    return jsonify(get_active_document_status())

@app.route("/clear_document", methods=["POST"])
def route_clear_document():
    clear_active_document()
    return jsonify({"ok": True, "reply": "Document memory clear ho gaya."})
```

### Step 2: Verify `prompts.py` already has the injection point

`src/vani/prompts.py` already imports:
```python
from vani.memory.human_memory import get_active_document_prompt_block
```
and calls it in `get_realtime_prompt()`. ✅ Nothing to change.

### Step 3: Install dependencies

```bash
pip install pdfminer.six pypdf python-docx
```

---

## How It Works End-to-End

```
User selects PDF in UI
       │
       ▼
POST /analyze_document  (port 5500)
       │
       ▼
document_service.py
  extract_text()        ← pdfminer.six → full text, every word
       │
       ├──► human_memory.store_active_document()
       │         stores: {filename, uploaded_at, expires_at, full_text}
       │         to:     book_memory_store/active_doc.json
       │
       └──► book_memory.store_book()
                BM25 chunk index for text_chat fallback
       │
       ▼
UI shows: "✅ 'vani.pdf' ab mujhe poora yaad hai! 3,241 words..."
       │
       ▼
Next time Vani starts / get_realtime_prompt() is called:
  human_memory.get_active_document_prompt_block()
    → checks TTL (expires after 48h)
    → if valid: injects FULL text into Gemini system prompt
    → with strict gate: "only use when explicitly asked about this doc"
       │
       ▼
Gemini Realtime knows every word. User asks:
  "Vani, architecture pdf mein Brain 1 kya hai?"
  → Gemini answers from full doc knowledge
  "Vani, what's the weather?"
  → Gemini answers normally, does NOT mention the PDF
```

---

## Usage Rules (enforced via system prompt)

Gemini is explicitly instructed:

> **Use this document ONLY when the user explicitly asks about the PDF / document / uploaded file.**
> In all other conversations, do NOT reference it.

Trigger phrases that activate doc knowledge:
- "vani.pdf ke baare mein..."
- "architecture pdf explain karo"
- "jo document tune padha..."
- "uploaded file mein kya likha hai"
- "tell me about the document"

Normal conversation is unaffected.

---

## Auto-Expiry (2 Days)

- Documents are stored with `uploaded_at` + `expires_at` timestamps.
- On every `get_realtime_prompt()` call, TTL is checked.
- Expired docs are silently removed — Gemini gets no doc block.
- User can also manually clear via the **📚 ✕** badge in the UI.

---

## File Formats Supported

| Extension | Extractor |
|-----------|-----------|
| `.pdf` | pdfminer.six → pypdf fallback |
| `.docx` / `.doc` | python-docx → raw XML fallback |
| `.txt`, `.md`, `.csv`, `.json` | utf-8 text |
| `.py`, `.js`, `.ts`, `.html`, `.css` | utf-8 text |

---

## Troubleshooting

**"Document memory mein save nahi ho paya"**
→ Check `book_memory_store/` directory permissions.

**Gemini still doesn't know the doc**
→ Restart Vani after upload — `get_realtime_prompt()` is called on session start.

**PDF extraction empty**
→ Scanned/image PDF — needs OCR (pytesseract + pdftoppm). Coming in next version.

**Badge not showing**
→ Check `/document_status` endpoint is live: `curl http://127.0.0.1:5500/document_status`
