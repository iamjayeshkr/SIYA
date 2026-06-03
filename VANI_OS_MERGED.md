# Vani OS — Merged Codebase (Main + P0 + P1 + P2 + P3 + P4)

## What's in here

| Folder | What |
|--------|------|
| `src/vani/` | Original Vani Python backend |
| `vani_legacy/` | P0–P4 new modules |
| `src-tauri/` | P3+P4 — Rust/Tauri desktop app backend |
| `ui/` | P3+P4 — React 18 frontend |
| `docs/INTEGRATE_P0.md` | How to wire P0 into app.py |
| `docs/INTEGRATE_P1.md` | How to wire P1 into planner |
| `docs/INTEGRATE_P2.md` | How to wire P2 into voice stack |
| `docs/INTEGRATE_P3.md` | How to build and run the Tauri desktop app |
| `docs/INTEGRATE_P4.md` | P4: Streaming, tools, tray, wake word |

## Setup Order

```bash
# 1. Install all Python dependencies
pip install -r requirements/requirements-all.txt

# 2. Pull offline models
ollama pull nomic-embed-text
ollama pull qwen2.5:14b

# 3. Migrate secrets to keychain (one time)
python -m vani_legacy.migrate_secrets

# 4. Install Node.js deps for Tauri UI
cd ui && npm install && cd ..

# 5. Follow integration guides in order:
# docs/INTEGRATE_P0.md → P1 → P2 → P3 → P4

# 6. Development (two terminals):
#   Terminal 1: python -m vani.app        (Python backend)
#   Terminal 2: cargo tauri dev           (Tauri window)
```

## Modules by phase

### P0 — Stability
- `vani_legacy/logging_config.py`
- `vani_legacy/tool_runner.py` ← **P4 updated**: retry-with-backoff, parallel tools
- `vani_legacy/tokenjuice.py`
- `vani_legacy/db.py`
- `vani_legacy/secrets.py`
- `vani_legacy/migrate_secrets.py`

### P1 — Semantic Memory
- `vani_legacy/embeddings.py`
- `vani_legacy/memory_semantic.py`
- `vani_legacy/memory_router.py`
- `vani_legacy/memory_ingestion.py`

### P2 — Offline & Multi-model
- `vani_legacy/model_registry.py`
- `vani_legacy/model_router.py`
- `vani_legacy/stt_whisper.py`
- `vani_legacy/voice_stack.py`

### P3 — Native Desktop App
- `src-tauri/src/main.rs` ← **P4 updated**
- `src-tauri/Cargo.toml` ← **P4 updated**
- `src-tauri/tauri.conf.json`
- `ui/src/App.tsx` ← **P4 updated**: streaming chat
- `ui/src/store/index.ts`
- `ui/src/hooks/useTauri.ts`

### P4 — Streaming + Reliability
- `vani_legacy/p4_streaming.py` — SSE token streaming (Ollama + Gemini)
- `vani_legacy/p4_state.py` — Persistent tray state
- `vani_legacy/p4_wake_word.py` — Wake word Python controller
- `src/vani/app.py` — Added `/stream`, `/wake/*`, `/p4/state` endpoints
