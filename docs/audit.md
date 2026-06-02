# Vani AI Assistant - Audit Report

> Updated: 2026-05-21  
> Scope: latency/debug pass on current checkout  
> Verification: `venv311/bin/python -m py_compile ...`, `venv311/bin/python tests/test_optimization.py`

## Executive Summary

The previous audit was partly correct about recent fixes, but it was not fully reliable:

- It referenced `agent.py`, but this checkout has no `agent.py`.
- It claimed `.env` was committed. In this checkout, `git ls-files .env` returns nothing, so `.env` is present locally but not tracked.
- It reported `vani_reasoning` cold import around `0.3s`; measured value before this pass was `1.366s`.
- It left the `/send_text` latency issue open. That has now been fixed.

Current health is better than the old report says in some places, but the cold import path still has measurable latency.

## Changes Applied In This Pass

| File | Change | Why |
|---|---|---|
| `vani_app.py` | Switched local UI server from `HTTPServer` to `ThreadingHTTPServer` | A slow `/send_text` request can no longer block `/state` polling or asset serving. |
| `vani_app.py` | Removed per-request `ThreadPoolExecutor` from `/send_text` | Avoids spawning OS threads for every text command. |
| `vani_app.py` | Added `_run_text_command()` with `asyncio.wait_for(..., timeout=30)` | Keeps the timeout behavior without executor churn. |
| `vani_reasoning.py` | Made LiveKit `function_tool` wrapping lazy via `get_thinking_capability_tool()` | Text-only routing no longer imports heavy LiveKit/OpenAI machinery at module import time. |
| `vani_reasoning.py` | Deferred top-level `requests` import | Avoids paying HTTP client import cost until a network/model call is made. |
| `vani_reasoning.py` | Fixed `json={{...}}` in `_ollama_beautify()` | The old code created an invalid set containing a dict and failed before calling Ollama. |
| `vani_app.py` | Tuned Silero VAD and LiveKit `turn_handling` | Reduces end-of-user-speech wait and enables preemptive response generation. |
| `requirements/base.txt`, `requirements/mac.txt`, `bin/run_vani.sh` | Pinned `numpy==1.26.4` and ensured Silero is installed | Fixes the NumPy 2.x / onnxruntime ABI failure that prevented Silero VAD from reliably loading. |
| `bin/run_vani.sh` | Detects `venv311` as well as `.venv` | Makes the launcher work with the environment present in this checkout. |
| `vani_launcher.py` | Added login autostart guard, single-instance lock, process/port running checks, and `--autostart` LaunchAgent mode | User login/manual/hotkey launches now avoid duplicate Vani instances. |
| `vani_app.py` | Added first-voice gated greeting: says `Welcome boss` once after the first user speech event | Vani stays silent at startup and only greets after hearing the user's voice. |

## Latency Status

Measured with `venv311` on 2026-05-21:

| Check | Before | After | Status |
|---|---:|---:|---|
| `vani_reasoning` import | `1.366s` | `0.463s` | Improved, still above the test's optimistic `<0.2s` target |
| LiveKit tool wrapping | Included in import | `0.798s` when realtime agent asks for it | Deferred from text-only path |
| `/send_text` executor overhead | New executor per request | No per-request executor | Fixed |
| `/state` during slow text command | Blocked by single-threaded server | Served by separate handler thread | Fixed |
| Voice VAD silence wait | `0.400s` | `0.250s` | Saves about `150ms` after the user stops speaking |
| LiveKit endpointing delay | Default/implicit | fixed `0.200s` min, `0.600s` max | Caps endpointing delay and starts generation earlier |
| Silero VAD availability | Broken by `numpy==2.3.1` ABI mismatch | Loads with `numpy==1.26.4` | Restores local VAD path |
| Startup duplicate launch risk | Launch paths could start another worker/UI | launcher lock + port/process checks | Fixed for LaunchAgent/manual launcher path |

The remaining import latency mostly comes from LangChain tool decoration and related Pydantic imports. A deeper reduction would require lazily wrapping the LangChain `@tool` objects too, which is a larger refactor because many call sites depend on `.ainvoke()`.

## Bug Status

| ID | Area | Status | Notes |
|---|---|---|---|
| BUG-01 | `keyboard_mouse_control.py` pyautogui lazy import | Fixed before this pass | Current `_pyautogui` sentinel + `importlib.import_module()` is correct. |
| BUG-02 | Realtime Gemini model route | Fixed/current | Current text model is `gemini-3.1-flash`; realtime route uses `gemini-2.5-flash-native-audio-preview-12-2025`. |
| BUG-03 | `vani_file_opener.py` unbounded walk | Fixed before this pass | Current file opener has bounded search/cache behavior. |
| BUG-04 | `vani_messaging.py` `_time`/`_sp` import order | Fixed before this pass | Imports are now top-level. |
| BUG-05 | `vani_app.py` retry/event handler clarity | Fixed before this pass | Handler registration is centralized per session. |
| BUG-06 | Prompt freshness | Fixed/current | `get_final_prompt()` reads dynamic context each call. |
| BUG-07 | Duplicate `agent.py` entrypoint | Invalid in current checkout | File does not exist; removed from remaining work. |
| NEW-01 | AppleScript URL string injection | Fixed before this pass | `_open_url()` percent-encodes `"` and `\`. |
| NEW-02 | `/send_text` per-request executor | Fixed in this pass | Replaced with direct bounded async run inside threaded HTTP handler. |
| NEW-03 | `_ollama_beautify()` malformed `json` argument | Fixed in this pass | Notes can now reach Ollama instead of failing locally. |
| NEW-04 | Duplicate startup instances | Fixed/current | LaunchAgent, manual launcher, tray, and hotkey path now check existing instance before launch. |
| NEW-05 | Premature startup greeting | Fixed/current | Greeting is gated on first user voice activity and says `Welcome boss` once. |

## Security Status

| Risk | Status | Recommendation |
|---|---|---|
| Local `.env` contains secrets | Present locally, not tracked by git in this checkout | Keep it untracked. Rotate keys if this folder was ever shared or zipped with `.env`. |
| AppleScript URL injection | Fixed | Keep sanitizing before interpolation. |
| App-name AppleScript injection in close/switch paths | Partially mitigated | `close_application()` and `switch_application()` sanitize names. Audit any future AppleScript interpolation the same way. |
| CORS | Acceptable for local UI | Current origin is restricted to `http://127.0.0.1:5500`. |

## Future Bug Risks

These are gaps that are not all immediate crashes, but they are likely to create intermittent failures or security bugs as usage grows.

| Priority | Gap / Future Bug Risk | Evidence | Why It Matters | Recommended Fix |
|---|---|---|---|---|
| P1 | WhatsApp AppleScript string injection remains in search/send paths | `vani_messaging.py:704`, `vani_messaging.py:1034` interpolate user-controlled text into `set the clipboard to "..."` | Contact names/messages containing `"`, `\`, newlines, or AppleScript syntax can break automation or execute unintended AppleScript | Replace inline AppleScript string literals with `pbcopy`/stdin clipboard writes, or add one shared AppleScript literal escaping helper and use it everywhere |
| P1 | `/send_text` has no request size or concurrency guard | `vani_app.py:95-101`, `vani_app.py:203-206` now uses `ThreadingHTTPServer` | A large POST body or many parallel requests can spawn many handler threads and run many model/tool calls at once | Enforce max `Content-Length`, reject oversized JSON, and gate `/send_text` with a bounded semaphore |
| P1 | `state` is mutated from LiveKit callbacks and read from HTTP threads without a lock | `vani_app.py:108-129`, `vani_app.py:367-383` | Today values are simple booleans/strings, but future nested state or multi-field reads can become inconsistent | Wrap state reads/writes in a small lock-backed helper or publish immutable state snapshots |
| P1 | Silero VAD can silently disable itself again if dependency pins drift | `vani_app.py:332-342`, `requirements/base.txt:63`, `requirements/mac.txt:91` | If `numpy` upgrades back to 2.x or onnxruntime changes ABI, voice endpointing falls back to no local VAD and speaking latency regresses | Add a startup health check that fails loudly when Silero cannot load, and add a CI smoke test for `silero.VAD.load()` |
| P2 | Aggressive endpointing may cut off slow speakers | `vani_app.py:333-338`, `vani_app.py:387-408` | `min_silence_duration=0.25` and fixed endpointing are faster, but can misfire for pauses in natural speech | Make VAD/endpointing values environment-configurable, e.g. `VANI_FAST_VOICE=1`, with a safer default profile |
| P2 | Background worker lifecycle is tied to the active event loop and has no shutdown hook | `vani_reasoning.py:1556-1603`, `vani_app.py:473-509` | Reconnects or loop shutdowns can leave queued futures unresolved or make follow-up speech use a stale `_session_ref` | Register a shutdown callback that cancels `_worker_task`, drains/marks queued futures, and clears `_session_ref` |
| P2 | Local UI server has no explicit shutdown or port conflict handling | `vani_app.py:203-206`, `vani_app.py:539` | Restarting quickly can leave port `5500` occupied; app currently starts the server thread without handling bind failure | Keep a server reference, catch `OSError` on bind, and either reuse/fail clearly or choose a configured fallback port |
| P2 | `_patch_html()` injects raw LiveKit URL/token into HTML attributes | `vani_app.py:250-257` | Tokens usually do not contain quotes, but future token formats or URL values could break HTML or enable injection | Use `html.escape(..., quote=True)` for all meta attribute values before writing `_ui_patched.html` |
| P2 | Cache file writes are not atomic and not locked | `context_cache.py:39-48` | Concurrent city/weather fetch threads can interleave writes and leave partial JSON, causing future cache load failures | Write to a temp file and `os.replace()`, with a `threading.Lock` around cache mutation/save |
| P2 | Broad `except Exception: pass` hides degraded runtime behavior | `vani_app.py:533-555`, `context_cache.py:27-50`, several automation modules | Silent failures make future regressions look like latency or model issues rather than clear operational errors | Replace silent passes on startup/runtime paths with structured warning logs that include the subsystem and action |
| P3 | Dependency files and launcher install list can diverge | `requirements/base.txt`, `requirements/mac.txt`, `bin/run_vani.sh` all carry overlapping dependency pins | Future fixes may update one file but not the others, recreating environment-only bugs | Make `bin/run_vani.sh` install from `requirements/mac.txt` on macOS instead of duplicating package names |

## Verification Results

Commands run:

```bash
venv311/bin/python -m py_compile vani_app.py vani_reasoning.py context_cache.py vani_prompts.py keyboard_mouse_control.py vani_browser_control.py vani_messaging.py
venv311/bin/python tests/test_optimization.py
```

Results:

- Syntax check: passed.
- Optimization test: passed.
- `vani_reasoning` import timing after fix: `0.4634s` in `tests/test_optimization.py`; direct one-line import check measured `0.4426s`.
- Silero VAD smoke test: passed after downgrading `venv311` to `numpy==1.26.4`.
- LaunchAgent installed at `/Users/rudra/Library/LaunchAgents/com.rudra.vani.plist` and points to `venv311/bin/python vani_launcher.py --autostart`.
- Duplicate-launch smoke test: `venv311/bin/python vani_launcher.py --autostart` exited with "already running" and did not launch a second instance.
- Note: system `python3` cannot run the test in this shell because it lacks `requests`; use `venv311/bin/python`.

## Remaining Work

1. Reduce `vani_reasoning` import below `0.2s` only if cold text-command startup matters. This likely means replacing top-level LangChain `@tool` decoration with lazy wrappers.
2. Dependency hygiene: remove unused/duplicated packages after confirming runtime needs. `requirements/base.txt` still includes both fuzzy matching stacks.
