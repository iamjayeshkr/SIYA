# Vani OS — P3 Integration Guide
# Tauri v2 Native Desktop App

P3 wraps the existing Python backend (p0–p2) inside a Tauri v2 desktop app.
The result is a native macOS/Windows window with a React UI, system tray,
and a global hotkey — with zero changes to your existing voice/model/memory code.

---

## What was added

```
src-tauri/
  build.rs                  ← required by tauri-build
  Cargo.toml                ← Rust deps (tauri 2, reqwest, serde_json, tokio)
  tauri.conf.json           ← window size, tray, hotkey config
  icons/tray.png            ← placeholder tray icon (replace with real art)
  src/
    main.rs                 ← Rust backend: IPC, tray, global hotkey
ui/
  index.html                ← Vite root HTML
  vite.config.ts            ← Vite config (port 1420, Tauri env prefix)
  tsconfig.json             ← TypeScript config
  tsconfig.node.json        ← Vite-specific TS config
  package.json              ← React 18, zustand, tauri-apps/api v2
  src/
    main.tsx                ← React entry point
    App.tsx                 ← Complete 4-view UI (Chat / Memory / Tools / Models)
    store/index.ts          ← Zustand global state
    hooks/useTauri.ts       ← Typed invoke() wrappers + browser mocks
requirements/
  requirements-p3.txt       ← fastapi + uvicorn (Tauri IPC server)
```

Changes to **existing** files:
- `src/vani/app.py` — `_start_tauri_api_server()` added (port 8765 FastAPI),
  called inside `main()` right after the state server thread starts.
- `requirements/requirements-all.txt` — includes `-r requirements-p3.txt`.

---

## Prerequisites

```bash
# 1. Python deps
pip install -r requirements/requirements-p3.txt

# 2. Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# 3. Tauri CLI v2
cargo install tauri-cli --version "^2.0" --locked

# 4. Node.js ≥ 18
brew install node   # macOS
# or: https://nodejs.org

# 5. UI npm deps
cd ui && npm install && cd ..

# 6. macOS: Xcode CLT (if not already)
xcode-select --install
```

---

## Development

```bash
# Terminal 1 — Python backend (existing command, unchanged)
python -m vani.app        # or: python src/vani/app.py

# Terminal 2 — Tauri dev window
cargo tauri dev
```

Tauri opens a native window at `http://localhost:1420`.
The global hotkey `Cmd+Shift+Space` toggles show/hide.
React hot-reloads on UI changes.
The Python backend must be running for real data; the UI falls back to mock
data automatically when running in a plain browser.

---

## Production build

```bash
cargo tauri build
# Output: src-tauri/target/release/bundle/macos/Vani.app  (~8MB)
```

Copy to `/Applications`. Set to launch at login:

```bash
osascript -e 'tell application "System Events" to make login item at end \
  with properties {path:"/Applications/Vani.app", hidden:false}'
```

---

## The 4 UI views

| View    | What it shows |
|---------|--------------|
| Chat    | Full conversation history, tool call badges, model attribution, push-to-talk mic |
| Memory  | Semantic memory browser: live search, importance scores, source/tag filters |
| Tools   | Tool audit table: success/fail rates, duration (yellow = slow, red = timeout) |
| Models  | Model router status grid: health, tier, provider for every model in chain |

---

## Python API endpoints (port 8765)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/query` | Route text through Vani's reasoning stack |
| GET  | `/memory/stats` | semantic_memories + working_entries count |
| POST | `/memory/search` | Semantic search, returns ranked MemEntry list |
| GET  | `/tools/history` | Recent tool audit rows (filter by `?tool=name`) |
| GET  | `/models/status` | Model router health dict |
| GET  | `/state` | Mirror of existing state dict (speaking/listening/…) |

All endpoints return JSON. CORS is open to `tauri://localhost` and
`http://localhost:1420` only.

---

## Tray icon

Replace `src-tauri/icons/tray.png` with a 32×32 or 16×16 PNG (template-style
monochrome works best on macOS). Rebuild after replacing:

```bash
cargo tauri build
```

---

## Troubleshooting

**`fastapi` / `uvicorn` not found** — install P3 requirements:
```bash
pip install -r requirements/requirements-p3.txt
```

**Port 8765 already in use** — kill the old process:
```bash
lsof -ti:8765 | xargs kill -9
```

**Tauri window blank / "Failed to connect"** — ensure Python backend is running
and port 8765 is reachable:
```bash
curl http://127.0.0.1:8765/state
```

**`cargo tauri dev` fails on Rust compile** — ensure Tauri CLI v2 is installed:
```bash
cargo tauri --version   # should print tauri-cli 2.x.x
```
