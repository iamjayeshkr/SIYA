# Vani OS — P4 Integration Guide
# Streaming + Async Tools + Persistent Tray + Wake Word

P4 makes Vani meaningfully faster and more reliable. Four pillars:

| Pillar | What it does |
|--------|-------------|
| **Streaming replies** | Words appear in the chat bubble as the LLM generates them — no more waiting for the full response |
| **Async tool runner** | WhatsApp/browser tools auto-retry once on timeout with an expanded window; parallel tool execution |
| **Persistent tray** | Window position, last mode, and feature flags survive across restarts (`~/vani_tray_state.json`) |
| **Wake word in Rust** | Lightweight state poller in Rust emits real-time `vani-state` events to React; hook for future mic energy detection |

---

## New files (P4)

```
vani_legacy/
  p4_streaming.py     ← SSE token streaming from Ollama + Gemini
  p4_state.py         ← Persistent tray state manager
  p4_wake_word.py     ← Wake word state machine + Python controller

src-tauri/src/
  main.rs             ← Updated: send_query_stream, persist state,
                         wake word poller, new tray menu items

src-tauri/
  Cargo.toml          ← Added: futures-util, dirs-next, urlencoding
```

Modified existing files:
- `src/vani/app.py` — Added `/stream`, `/wake/status`, `/wake/trigger`,
  `/wake/set_enabled`, `/p4/state` endpoints to the FastAPI server
- `ui/src/App.tsx` — Streaming chat (SSE listener + cursor animation)

---

## Install

```bash
# Python (streaming)
pip install aiohttp   # already in base.txt, just verify

# Rust new deps (auto-installed on cargo build)
# dirs-next, futures-util, urlencoding added to Cargo.toml

# No new Node deps needed
```

---

## Development

```bash
# Terminal 1
python -m vani.app   # or bin/run_vani.sh

# Terminal 2
cargo tauri dev
```

Test streaming directly:
```bash
curl -N "http://127.0.0.1:8765/stream?text=hello+vani"
# Should print SSE events with tokens appearing one by one
```

Test wake word:
```bash
curl -X POST http://127.0.0.1:8765/wake/trigger \
  -H "Content-Type: application/json" \
  -d '{"confidence": 0.9}'
# Should return: {"acted": true, "reason": "ok"}
```

Test persistent state:
```bash
curl http://127.0.0.1:8765/p4/state
# Returns session count, last mode, feature flags
```

---

## Streaming flow

```
User types message in React
  → tauriInvoke("send_query_stream", { query })
    → Rust: reqwest streaming GET /stream?text=...
      → Python: FastAPI SSE → p4_streaming.py → Ollama/Gemini
        → tokens flow back as SSE events
          → Rust: app.emit("stream-token", token)
            → React: listen("stream-token") → appends to bubble
```

When streaming is disabled (tray menu) or in browser mode, falls back
to the existing non-streaming `/query` endpoint automatically.

---

## Persistent tray state

State file: `~/vani_tray_state.json`

```json
{
  "window_x": 200,
  "window_y": 100,
  "window_visible": true,
  "last_mode": "voice",
  "wake_word_enabled": true,
  "streaming_enabled": true,
  "session_count": 5,
  "notifications_enabled": true
}
```

Rust reads this on startup and restores the window position.
Auto-saved every 60 seconds and on clean exit (quit from tray menu).
Tray menu now has "Toggle Wake Word" and "Toggle Streaming" items.

---

## Wake word

The Rust process polls `/state` every 250ms and emits `vani-state` events
to React (so the UI always shows live speaking/listening indicators).

Full mic-based wake word requires adding `cpal` to Cargo.toml:
```toml
cpal = { version = "0.15", features = ["default"] }
```
And implementing the `_start_mic_listener()` function in main.rs using
cpal's input stream. The Python controller (`p4_wake_word.py`) is
already wired and ready to receive triggers via POST `/wake/trigger`.

---

## What changed across phases

| | Before P4 | After P4 |
|-|-----------|---------|
| Response latency | Full reply arrives at once | Words stream in real time |
| WhatsApp timeout | Fails hard on timeout | Auto-retries once |
| Tool parallelism | Sequential only | `run_tools_parallel()` available |
| Tray state | Reset on every launch | Persists across restarts |
| Window position | Always centre | Remembers last position |
| Session tracking | None | Session count in state file |
| Rust ↔ React events | None | `vani-state` events every 250ms |

