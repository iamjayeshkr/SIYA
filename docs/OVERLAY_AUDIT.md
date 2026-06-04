# Vani Dynamic Island — Audit & Migration Plan

## 1. Current State Inventory

### 1.1 Window Architecture (tauri.conf.json)

Two windows are already declared:

| Label    | Role                    | Visible at boot | URL                               |
|----------|-------------------------|-----------------|-----------------------------------|
| `main`   | Full avatar UI          | Depends on persisted state | `http://127.0.0.1:5500/ui`      |
| `overlay`| Dynamic Island widget   | `false`         | `http://127.0.0.1:5500/ui?overlay=true` |

**Problem:** Both windows load the **same** `ui.html` and the overlay mode is controlled by the query-string `?overlay=true`. This means:

- The 3223-line avatar UI loads in full inside the tiny 420×100 overlay window.
- LiveKit audio, videos, mentor mode, plugins, and all chat history are loaded and then hidden with CSS inside the overlay window — wasting memory and causing flickers.
- The overlay has no independent lifecycle; it depends entirely on CSS overrides of the avatar shell.

### 1.2 Overlay Module in ui.html (lines 2802–3223)

A self-contained IIFE at the bottom of ui.html handles overlay mode:

**State sources (in priority order):**
1. Tauri `vani-state` event (emitted every 250 ms from `start_wake_word_listener` in `main.rs`)
2. WebSocket push at `ws://127.0.0.1:5500/ws` — Python pushes instantly on any state change
3. HTTP polling fallback (legacy, `window.pywebview.api.get_state()`)

**State fields consumed:**
```
speaking    bool    → body.speaking class
listening   bool    → body.listening class
processing  bool    → body.thinking class (also inferred from status string)
status      string  → overlay text, tool label, "Thinking..." etc.
transcript  string  → streamed response text (speaking state)
```

**Auto-hide logic:**
```
Short response  (<60 chars)   → 8 s
Medium response (<200 chars)  → 15 s
Long response   (≥200 chars)  → 25 s
```
Hover pauses the timer. Stored in `_lastResponseLength`.

**Window commands called:**
- `set_overlay_visible(visible)` — show/hide the overlay window
- `expand_to_full_ui()` — hide overlay, show main
- `collapse_to_overlay()` — hide main, show overlay

**Known bugs in the current overlay module:**
1. `window.tauriInvoke` is called with `set_overlay_visible` even when the overlay is not the active window — the main window can call this, causing race conditions.
2. `enableOverlayMode()` is called on `isOverlayWindow`, but `LiveKit.connectLiveKit` is patched *after* the IIFE finishes — if the main page DOMContentLoaded fires LiveKit before the patch is applied, both windows connect audio.
3. The overlay width is hard-coded in Rust (`420`) but CSS morphs to `180px` or `380px` — the window never resizes dynamically so transcript text clips.

### 1.3 Rust Backend (src-tauri/src/main.rs)

**State poller:** `start_wake_word_listener` polls `GET /state` every 250 ms and emits `vani-state` Tauri events to all webviews. This is the bridge between Python state and the overlay.

**Commands relevant to overlay:**
| Command | What it does |
|---------|-------------|
| `set_overlay_visible(visible)` | Positions overlay top-center, shows/hides it |
| `expand_to_full_ui()` | Shows main, hides overlay, persists flag |
| `collapse_to_overlay()` | Shows overlay, hides main, persists flag |

**Hotkey:** `Cmd+Shift+K` toggles main↔overlay↔both-hidden.

**Tray:** Left-click toggles main visibility; always hides overlay on show-main.

### 1.4 Python Backend State Machine (src/vani/app.py)

State dict (global, thread-safe via `_patched_state_update`):
```python
state = {
    "speaking":   bool,
    "listening":  bool,
    "processing": bool,
    "connected":  bool,
    "text_ready": bool,
    "status":     str,   # human label, also carries tool names
    "transcript": str,   # streamed TTS text
}
```

State transitions:
- `speaking=True` → `app.py` line 1578 (LiveKit agent speech start)
- `listening=True` → line 1583, 1588, 1758 (agent ready / wake word)
- `processing=True, status="Thinking..."` → line 1593
- `status="Searching"/"Reading PDF"/"Opening Browser"` → `worker.py` line 259
- `transcript=text` → lines 1601, 1613, 409 (streamed TTS tokens)

**Push mechanism:** `_patched_state_update` calls `_ws_push_state` which sends JSON to all connected WebSocket clients at `ws://127.0.0.1:5500/ws`.

---

## 2. Problems Summary

| # | Problem | Impact |
|---|---------|--------|
| 1 | Overlay window loads full 3223-line avatar UI | Memory waste, flickers, LiveKit audio in overlay |
| 2 | Overlay window width never resizes dynamically | Transcript text clips in speaking state |
| 3 | `skipTaskbar` not set in tauri.conf.json overlay | Overlay appears in Cmd+Tab and Dock |
| 4 | No `focusable: false` on overlay | Overlay steals keyboard focus |
| 5 | Overlay is hidden by default but main also starts hidden — confusing boot sequence | First-run experience broken |
| 6 | Tool status only set for query keywords in worker.py, never cleared | Status can persist stale tool labels |
| 7 | `vani-state` polling is 250 ms on Rust side, WS push is instant on Python — double delivery | Duplicate `updateState` calls |

---

## 3. Migration Plan

### Phase 1 — Dedicated Overlay HTML (No Regression Risk)

**Goal:** Replace the overlay window's URL with a standalone `overlay.html` that is tiny, purpose-built, and imports no avatar code.

**Files changed:**
- `src-tauri/tauri.conf.json` — point overlay `url` to `http://127.0.0.1:5500/overlay`
- `src/vani/app.py` — add `/overlay` route serving `overlay.html`
- `src/vani/ui/overlay.html` — **new file**, the Dynamic Island UI

**No regression:** `ui.html` and the main window are untouched.

### Phase 2 — Overlay Window Sizing (Rust)

**Goal:** Add a `resize_overlay` Tauri command so the overlay window can grow/shrink dynamically as state changes (listening=180px, speaking=420px).

**Files changed:**
- `src-tauri/src/main.rs` — add `resize_overlay` command
- `src/vani/ui/overlay.html` — call `resize_overlay` on state change

### Phase 3 — Window Properties (tauri.conf.json)

**Goal:** Set `skipTaskbar: true` on overlay. Add `contentProtected` for security.

**Files changed:**
- `src-tauri/tauri.conf.json`

### Phase 4 — Hotkey Refinement

**Goal:** `Cmd+Shift+K` should always open Full Assistant Mode (main window). Currently it toggles between main and overlay depending on visibility. Change to: if hidden → show main. If main visible → hide to tray (clean desktop).

**Files changed:**
- `src-tauri/src/main.rs` — hotkey handler logic

### Phase 5 — Tool Status Broadcast (Python)

**Goal:** Clear tool status after tool execution completes. Add `tool_active` field to state.

**Files changed:**
- `src/vani/reasoning/worker.py` — clear status after task done

---

## 4. Implementation Order

```
Phase 1 (now)  → overlay.html + /overlay route
Phase 2 (now)  → resize_overlay Rust command
Phase 3 (now)  → tauri.conf.json properties
Phase 4 (now)  → hotkey refinement
Phase 5 (later) → Python tool status cleanup
```

Phases 1–4 can land together as they are additive (no deletions from ui.html or app.py logic).

---

## 5. Feature Preservation Checklist

| Feature | Preserved? | Verification |
|---------|------------|-------------|
| File upload (ui.html) | ✅ | ui.html untouched |
| Image upload | ✅ | ui.html untouched |
| Document upload | ✅ | ui.html untouched |
| Mentor mode | ✅ | ui.html untouched |
| Chat history | ✅ | ui.html untouched |
| Settings | ✅ | ui.html untouched |
| Plugins | ✅ | ui.html untouched |
| LiveKit voice | ✅ | overlay bypasses LiveKit entirely |
| Avatar videos | ✅ | Only in main window |
| Wake word detection | ✅ | Python + Rust poller unchanged |
| Tray icon | ✅ | main.rs tray unchanged |
| Cmd+Shift+K | ✅ | Refined, not removed |
