# CLI Agent Prompt — SIYA Latency Optimization

## Your Goal
Apply all voice latency optimizations to the SIYA/Vani codebase so that Gemini Realtime responses feel as fast as Siri. You will make precise, targeted edits across 3 files and create/update 1 config file. Do not touch anything else.

---

## Context
SIYA is a voice assistant using LiveKit + Gemini Realtime for voice. The current latency is 800ms–1.5s perceived. The target is 300–400ms (the physical minimum for Gemini Realtime over a network). The slowdowns are caused by:
1. VAD endpointing delays set too high
2. A deliberate 50ms sleep before filler audio
3. Indic-TTS being tried first even for short replies (adds synthesis latency)
4. Tool sync timeout of 2s (too long for simple tasks)
5. Indic-TTS model not pre-warmed on startup

---

## Files to Edit

### FILE 1: `src/vani/app.py`

#### Change 1 — Lower AgentSession endpointing defaults
Find this block inside `_new_agent_session()`:
```python
session_kwargs = {
    "allow_interruptions": True,
    "min_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MIN_DELAY", "0.08")),
    "max_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MAX_DELAY", "0.25")),
    "min_interruption_duration": float(os.getenv("VANI_INTERRUPT_MIN_DURATION", "0.12")),
}
```
Replace the default values only (keep the env var overrides so `.env` still works):
```python
session_kwargs = {
    "allow_interruptions": True,
    "min_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MIN_DELAY", "0.05")),
    "max_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MAX_DELAY", "0.15")),
    "min_interruption_duration": float(os.getenv("VANI_INTERRUPT_MIN_DURATION", "0.08")),
}
```

#### Change 2 — Pre-warm Indic-TTS on startup
Find this block inside `main()`, after the background workers are started:
```python
    try:
        from vani.workers import start_background_workers
        start_background_workers()
        log.info("[workers] Background workers started")
    except Exception as _worker_err:
        log.warning(f"[workers] Worker startup failed (non-fatal): {_worker_err}")
```
Add the following block immediately after it:
```python
    # Pre-warm Indic-TTS so first voice reply has no model-load delay
    def _prewarm_tts():
        try:
            import asyncio as _asyncio
            from vani.audio import synthesize_and_play as _synth
            _loop = _asyncio.new_event_loop()
            _loop.run_until_complete(_synth(" "))
            _loop.close()
            log.info("[tts] Indic-TTS pre-warmed successfully")
        except Exception as _e:
            log.warning(f"[tts] Pre-warm failed (non-fatal): {_e}")
    threading.Thread(target=_prewarm_tts, daemon=True, name="tts-prewarm").start()
```

---

### FILE 2: `src/vani/reasoning/worker.py`

#### Change 3 — Remove the blocking sleep before filler audio
Find this block inside `say_to_user()`:
```python
        # ── FILLER — plays instantly before TTS synthesis starts ─────────────
        try:
            from vani.audio.indic_tts_adapter import play_filler
            asyncio.create_task(play_filler(
                filler_type="auto",
                response_len=len(speech_text)
            ))
            await asyncio.sleep(0.05)   # yield so filler Popen starts before CPU load
        except Exception:
            pass   # never block on filler failure
        # ── END FILLER ───────────────────────────────────────────────────────
```
Replace with (remove the sleep, keep filler as fire-and-forget):
```python
        # ── FILLER — plays instantly before TTS synthesis starts ─────────────
        try:
            from vani.audio.indic_tts_adapter import play_filler
            asyncio.create_task(play_filler(
                filler_type="auto",
                response_len=len(speech_text)
            ))
        except Exception:
            pass   # never block on filler failure
        # ── END FILLER ───────────────────────────────────────────────────────
```

#### Change 4 — Skip Indic-TTS for short replies, let Gemini Realtime speak them natively
Find this block inside `say_to_user()`:
```python
        # ── INDIC-TTS — speaks ALL replies in one consistent voice ──────────
        try:
            from vani.audio import synthesize_and_play, synthesize_and_play_chunked
            if len(speech_text) > 120:
                spoke = await synthesize_and_play_chunked(speech_text)
            else:
                spoke = await synthesize_and_play(speech_text)
            if spoke:
                return   # ✅ TTS spoke it — done
        except ImportError:
            pass
        except Exception as _ke:
            logger.warning(f"[MESSAGING] TTS error: {_ke}")
```
Replace with:
```python
        # ── INDIC-TTS — only for longer Hinglish replies (60+ chars) ────────
        # Short replies go straight to Gemini Realtime native audio (already
        # streaming), avoiding synthesis latency on quick responses.
        try:
            from vani.audio import synthesize_and_play, synthesize_and_play_chunked
            if len(speech_text) > 60 and not is_english(speech_text):
                if len(speech_text) > 120:
                    spoke = await synthesize_and_play_chunked(speech_text)
                else:
                    spoke = await synthesize_and_play(speech_text)
                if spoke:
                    return   # ✅ TTS spoke it — done
        except ImportError:
            pass
        except Exception as _ke:
            logger.warning(f"[MESSAGING] TTS error: {_ke}")
```

Note: `is_english` is already defined in `app.py`. Add this import at the top of the `say_to_user` function body (inside the try block) so it resolves correctly:
```python
        try:
            from vani.app import is_english
        except Exception:
            def is_english(t): return False
```
Add those 3 lines at the very start of the `say_to_user` async function body, before the `speech_text = _speech_safe_text(...)` line.

#### Change 5 — Lower the tool sync timeout default
Find this line inside `thinking_capability()`:
```python
        result = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=float(os.getenv("VANI_TOOL_SYNC_TIMEOUT", "2.0"))
        )
```
Change the default from `"2.0"` to `"0.5"`:
```python
        result = await asyncio.wait_for(
            asyncio.shield(future),
            timeout=float(os.getenv("VANI_TOOL_SYNC_TIMEOUT", "0.5"))
        )
```

---

### FILE 3: `.env.example` (and apply to `.env` if it exists)

#### Change 6 — Add optimized latency defaults to env config
Open `.env.example`. Find the section that contains VAD or endpointing settings (search for `VANI_ENDPOINT` or `VANI_VAD`). If no such section exists, append the following block at the end of the file:

```dotenv
# ── Voice latency optimizations ────────────────────────────────────────────
# Lower endpointing = Vani stops waiting for silence sooner → feels faster
VANI_ENDPOINT_MIN_DELAY=0.05
VANI_ENDPOINT_MAX_DELAY=0.15
VANI_INTERRUPT_MIN_DURATION=0.08

# VAD (Silero) tuning — faster silence detection
VANI_VAD_MIN_SILENCE=0.06
VANI_VAD_PREFIX_PADDING=0.05
VANI_VAD_MIN_SPEECH=0.04
VANI_VAD_THRESHOLD=0.45

# Tool sync timeout — how long Gemini waits for a tool result before speaking
# 0.5s is enough for simple tasks; complex tasks fall back to async speak
VANI_TOOL_SYNC_TIMEOUT=0.5

# TTS routing — set to 1 to let short replies go to Gemini Realtime native audio
# (already streaming, zero synthesis delay) instead of Indic-TTS
VANI_TEXT_TO_REALTIME=1
```

Then apply the same values to `.env` if that file exists (preserve all existing keys, only add the ones above that are missing).

---

## Verification Steps

After making all edits, run the following checks:

```bash
# 1. Confirm the endpointing defaults changed in app.py
grep -n "VANI_ENDPOINT_MAX_DELAY" src/vani/app.py
# Expected: should show "0.15" as the default value

# 2. Confirm the sleep is removed from worker.py
grep -n "asyncio.sleep(0.05)" src/vani/reasoning/worker.py
# Expected: no output (line should be gone)

# 3. Confirm the TTS length gate was added
grep -n "len(speech_text) > 60" src/vani/reasoning/worker.py
# Expected: one match inside say_to_user

# 4. Confirm tool sync timeout changed
grep -n "VANI_TOOL_SYNC_TIMEOUT" src/vani/reasoning/worker.py
# Expected: should show "0.5" as the default value

# 5. Confirm TTS prewarm thread was added to main()
grep -n "tts-prewarm" src/vani/app.py
# Expected: one match

# 6. Syntax check both files
python -m py_compile src/vani/app.py && echo "app.py OK"
python -m py_compile src/vani/reasoning/worker.py && echo "worker.py OK"
```

All 6 checks must pass. If `py_compile` fails, fix the syntax error before finishing.

---

## What NOT to Touch
- Do not modify any memory, security, or plugin files
- Do not change the LiveKit session model or voice (`Aoede`)
- Do not touch `VANI_USE_SILERO` — leave it as the user has it
- Do not change `VANI_PREWARM_OLLAMA` — that's separate from TTS prewarm
- Do not reformat or reorganize any file — surgical edits only

---

## Summary of Changes Made
When done, print a summary like this:

```
SIYA Latency Optimization — Changes Applied
============================================
[✓] app.py         — Endpointing defaults lowered (0.25s → 0.15s max)
[✓] app.py         — Indic-TTS pre-warm thread added to startup
[✓] worker.py      — Removed 50ms filler sleep
[✓] worker.py      — Short replies (<60 chars) now use Gemini native audio
[✓] worker.py      — Tool sync timeout lowered (2.0s → 0.5s)
[✓] .env.example   — Latency optimization vars documented
[✓] .env           — Latency vars applied (or skipped if file not found)

Expected latency improvement: 800–1500ms → 300–400ms perceived response time
```
