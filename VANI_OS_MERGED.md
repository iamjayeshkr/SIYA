# Vani OS — Merged Codebase (Main + P0 + P1 + P2)

## What's in here

| Folder | What |
|--------|------|
| `src/vani/` | Original Vani codebase |
| `vani/` | P0 + P1 + P2 new modules |
| `docs/INTEGRATE_P0.md` | How to wire P0 into app.py |
| `docs/INTEGRATE_P1.md` | How to wire P1 into planner |
| `docs/INTEGRATE_P2.md` | How to wire P2 into voice stack |
| `requirements/requirements-all.txt` | All dependencies combined |

## Setup Order

```bash
# 1. Install all dependencies
pip install -r requirements/requirements-all.txt

# 2. Pull offline models
ollama pull nomic-embed-text
ollama pull qwen2.5:14b

# 3. Migrate secrets to keychain (one time)
python -m vani.migrate_secrets

# 4. Follow integration guides in order:
# docs/INTEGRATE_P0.md → then P1 → then P2
```

## New modules added (vani/ folder)

### P0 — Stability
- `vani/logging_config.py` — Structured logging (structlog)
- `vani/tool_runner.py` — Timeout enforcement for all tools
- `vani/tokenjuice.py` — LLM context compression (30-60% reduction)
- `vani/db.py` — Tool audit SQLite table
- `vani/secrets.py` — macOS Keychain secret management
- `vani/migrate_secrets.py` — One-time .env → Keychain migration

### P1 — Semantic Memory
- `vani/embeddings.py` — Local embeddings via nomic-embed-text (Ollama)
- `vani/memory_semantic.py` — sqlite-vec vector memory store
- `vani/memory_router.py` — Unified memory context assembler
- `vani/memory_ingestion.py` — Background turn ingestion

### P2 — Offline & Multi-model
- `vani/model_registry.py` — Model catalogue with fallback chains
- `vani/model_router.py` — Smart routing (Gemini → Flash → Qwen local)
- `vani/stt_whisper.py` — Offline STT via faster-whisper
- `vani/voice_stack.py` — Hybrid voice (LiveKit primary, offline fallback)
