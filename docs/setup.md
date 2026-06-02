# Vani System Debugging & Optimization Guide

This document catalogs all the architectural updates, critical bug fixes, and performance/latency optimizations implemented during the pairing sessions to make Vani highly stable, fast, and robust.

---

## 1. Latency & Startup Optimization (Current Phase)

### The Problem
*   Importing `vani_reasoning.py` was taking too long (often > 1.5 seconds) on startup, occasionally causing LiveKit workers to timeout or experience excessive latency.
*   **Cause**: Top-level imports of heavy/hardware-scanning modules like `pyautogui`, `sounddevice`, `pynput`, Telethon, and Playwright triggered hardware scans (e.g. searching audio drivers or screen bounds) immediately when Python parsed the file.
*   Also, Vani's system prompts were monolithically bundled, making personality tuning difficult without risk of breaking other functionalities.

### The Fix
1.  **Lazy Dynamic Imports**:
    *   Moved all module-level imports of external packages inside their respective `@tool` definitions or local async helpers.
    *   Examples: `sounddevice` / `pyautogui` / `pillow` are only imported inside the specific tools that capture screenshots or control voice interfaces.
    *   **Result**: Warm import latency dropped to **under 0.15s** (specifically ~0.13s), bypassing all timeout bottlenecks.
2.  **Prompt Modularization**:
    *   Created a `modes/` directory with 6 granular, isolated configurations:
        *   `core_mode.txt`: Establishes the Hinglish persona, friend parameters, witty humor rules, clean code guidelines, and the strict relationship constraint (never addressing Rudra with sibling terms like "bhai").
        *   `call_mode.txt`: Sets voice guidelines (no markdown symbols, short phrasing).
        *   `live_mode.txt`: Dynamic conversational interruption fillers ("Achaa...", "Hmm...").
        *   `tool_mode.txt`: Safe tool execution rules (run silently).
        *   `realtime_mode.txt`: Real-time verbal response optimization.
        *   `conversation_mode.txt`: Entry greeting routing using recent memories vs warm first-time welcoming.
3.  **Indentation Repair**:
    *   Restored a missing code block in the `whatsapp_call` dynamic wrapper that caused an unindent syntax error.

---

## 2. Core LLM & LiveKit Fixes (Phase 3 Debugging)

### Model Existence & Live Preview
*   **Bug**: The agent was configured to use `gemini-3.1-flash-live-preview`, which is non-existent.
*   **Fix**: Modified `agent.py` to point to a stable valid model target (`gemini-2.0-flash-live-001` or `gemini-1.5-flash`), preventing API connection crashes.

### AgentSession Parameter Deprecation
*   **Bug**: The session initialization in `agent.py` passed `preemptive_generation=True` to `AgentSession.start()`. This parameter does not exist in `livekit-agents` v1.2.1 and threw a `TypeError`.
*   **Fix**: Removed `preemptive_generation` from the parameters, letting LiveKit agents handle session streams natively.

### Thread/Event Loop Blocking in Memory Processing
*   **Bug**: `memory_loop.run()` represents an infinite background processing loop. When invoked, it would block the main execution context forever, preventing Vani from shutting down cleanly or accepting new audio connections.
*   **Fix**: Wrapped `memory_loop.run()` in an asynchronous task manager (`asyncio.create_task`) bounded by `ctx.wait_for_disconnect()`. When the session finishes, the task is safely cancelled using `memory_task.cancel()`.

---

## 3. Tool Routing & App Launching Bugs

### The YouTube & Web-App Interception Failure
*   **Bug**: When the user said *"play Duro Duro se on Youtube"*, the media classifier `_classify_media_intent` would intercept it as a media-control button press because it contained the word "play", blocking Qwen from searching and playing the song.
*   **Fix**: Enhanced the media classifier in `vani_reasoning.py` to filter out specific queries containing words that aren't simple play/pause state controls (e.g. containing specific search titles or browser destinations like Youtube).

### Desktop Routing Fallback
*   **Bug**: Opening common cross-platform targets like YouTube or Netflix failed on macOS because `open -a` tried to look for native Applications instead of using Chrome or browser redirections.
*   **Fix**: Configured `open_application` to delegate directly to `open_app_smart` inside `vani_browser_control.py`. This ensures full support for fuzzy matching, specific browser redirections, and Spotlight-based scanning with multi-tier fallbacks.

---

## 4. Run & Execution

To run Vani locally on your Mac environment:
1.  Activate your Python virtual environment:
    ```bash
    source venv311/bin/activate
    ```
2.  Start the LiveKit agent:
    ```bash
    python3 agent.py dev
    ```
3.  To run verification checks on import latency and prompt compiling:
    ```bash
    python3 tests/test_optimization.py
    ```
