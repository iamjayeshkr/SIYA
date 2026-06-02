# Vani OS — Merged Codebase (Main + P0 + P1 + P2 + P3)

## What's in here

| Folder | What |
|--------|------|
| `src/vani/` | Original Vani Python backend |
| `vani_legacy/` | P0 + P1 + P2 new modules |
| `src-tauri/` | P3 — Rust/Tauri desktop app backend |
| `ui/` | P3 — React 18 frontend (Chat / Memory / Tools / Models) |
| `docs/INTEGRATE_P0.md` | How to wire P0 into app.py |
| `docs/INTEGRATE_P1.md` | How to wire P1 into planner |
| `docs/INTEGRATE_P2.md` | How to wire P2 into voice stack |
| `docs/INTEGRATE_P3.md` | How to build and run the Tauri desktop app |
| `requirements/requirements-all.txt` | All Python dependencies combined |

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
# docs/INTEGRATE_P0.md → P1 → P2 → P3

# 6. Development (two terminals):
#   Terminal 1: python -m vani.app        (Python backend)
#   Terminal 2: cargo tauri dev           (Tauri window)
```

## New modules added (vani_legacy/ folder)

### P0 — Stability
- `vani_legacy/logging_config.py` — Structured logging (structlog)
- `vani_legacy/tool_runner.py` — Timeout enforcement for all tools
- `vani_legacy/tokenjuice.py` — LLM context compression (30-60% reduction)
- `vani_legacy/db.py` — Tool audit SQLite table
- `vani_legacy/secrets.py` — macOS Keychain secret management
- `vani_legacy/migrate_secrets.py` — One-time .env → Keychain migration

### P1 — Semantic Memory
- `vani_legacy/embeddings.py` — Local embeddings via nomic-embed-text (Ollama)
- `vani_legacy/memory_semantic.py` — sqlite-vec vector memory store
- `vani_legacy/memory_router.py` — Unified memory context assembler
- `vani_legacy/memory_ingestion.py` — Background turn ingestion

### P2 — Offline & Multi-model
- `vani_legacy/model_registry.py` — Model catalogue with fallback chains
- `vani_legacy/model_router.py` — Smart routing (Gemini → Flash → Qwen local)
- `vani_legacy/stt_whisper.py` — Offline STT via faster-whisper
- `vani_legacy/voice_stack.py` — Hybrid voice (LiveKit primary, offline fallback)

## New files added (P3 — Tauri desktop app)

### Rust backend (`src-tauri/`)
- `src-tauri/src/main.rs` — Window management, system tray, global hotkey, IPC commands
- `src-tauri/Cargo.toml` — Rust dependencies (tauri 2, reqwest, serde_json, tokio)
- `src-tauri/tauri.conf.json` — Window config, tray icon, shortcuts
- `src-tauri/build.rs` — Tauri build script
- `src-tauri/icons/tray.png` — Tray icon (replace with real art)

### React UI (`ui/`)
- `ui/src/App.tsx` — Complete 4-view UI (Chat, Memory, Tools, Models)
- `ui/src/store/index.ts` — Zustand global state
- `ui/src/hooks/useTauri.ts` — Typed invoke() wrappers with browser mock fallbacks
- `ui/src/main.tsx` — React 18 entry point
- `ui/index.html` — Vite root HTML
- `ui/vite.config.ts` — Vite config (port 1420, Tauri env prefix)
- `ui/package.json` — npm deps (React 18, zustand, @tauri-apps/api v2)

### Python bridge (`src/vani/app.py` changes)
- `_start_tauri_api_server()` — FastAPI server on port 8765 (auto-started in `main()`)
  - `POST /query` — routes text through Vani's reasoning stack
  - `GET /memory/stats` — memory counts
  - `POST /memory/search` — semantic search
  - `GET /tools/history` — tool audit log
  - `GET /models/status` — model router health
  - `GET /state` — mirrors existing state dict
