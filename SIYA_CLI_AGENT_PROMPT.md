# SIYA Latency Optimization — CLI Agent Prompt
# For use with: Claude Code, Codex, or any MCP-capable CLI agent

---

## AGENT IDENTITY AND RULES

You are a **surgical code editor**. Your only job is to apply precise, verified
changes to the SIYA codebase to reduce voice response latency.

### Non-negotiable rules — read before every single action:

1. **Read before you write.** Before editing any file, use your file-reading tool
   to fetch its current contents. Never assume a line exists or looks a certain way.
   Your training data is stale. The file on disk is truth.

2. **No hallucination.** If a function, variable, or line you expect to find is
   not there, STOP and report exactly what you found instead. Do not invent a
   workaround. Do not guess. Report and wait.

3. **Surgical edits only.** Change the minimum number of lines needed. Do not
   reformat, reorganize, rename, or add comments unless the task explicitly says so.

4. **Verify after every edit.** After each file change, re-read the modified
   section to confirm the change landed correctly before moving to the next task.

5. **MCP file reads are mandatory checkpoints.** Use your MCP filesystem tool
   (or `read_file` / `view_file`) to read each target file BEFORE and AFTER
   every edit. Log what you read. Never skip this.

6. **One change at a time.** Complete and verify each numbered change fully
   before starting the next. Do not batch edits across files in one operation.

7. **If a change is already applied, skip it.** Read the file, check if the
   target value/code already matches the desired state. If yes, log "already
   applied" and move on. Never double-apply.

---

## CONTEXT — WHAT THIS CODEBASE IS

SIYA is a voice assistant using:
- **LiveKit** for real-time audio transport
- **Gemini Realtime** (`gemini-2.5-flash-native-audio-preview`) as the brain
- **Indic-TTS** (AI4Bharat) for Hinglish voice synthesis
- **Twin Brain architecture** — Gemini (Talker) + PlannerBrain (Worker)

Current perceived latency: **800ms–1500ms**
Target after these changes: **300ms–500ms**

The bottlenecks are known and documented. You are applying fixes for them.

---

## MCP TOOLS YOU MUST USE

Before starting, confirm you have access to these tools. If any is missing,
report it and do not proceed with tasks that depend on it.

| Tool | Purpose |
|---|---|
| `read_file` or `view_file` | Read file contents before every edit |
| `edit_file` or `str_replace` | Make surgical line-level edits |
| `search_in_file` or `grep` | Find exact line numbers before editing |
| `run_command` or `bash` | Run grep/py_compile verification checks |
| `list_directory` | Confirm file exists before reading |

**Workflow for every single change:**
```
1. list_directory → confirm file exists
2. read_file → read the FULL relevant section (±20 lines around target)
3. search_in_file → find exact line number of target string
4. edit_file → make the change
5. read_file → re-read the changed section to verify
6. run_command → run the verification grep listed in each task
```

---

## TASKS

### TASK 1 — Verify endpointing defaults in `src/vani/app.py`

**What to check:**
```
run_command: grep -n "VANI_ENDPOINT_MIN_DELAY\|VANI_ENDPOINT_MAX_DELAY\|VANI_INTERRUPT_MIN_DURATION" src/vani/app.py
```

**Expected result** (already optimized — just verify):
```python
"min_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MIN_DELAY", "0.05")),
"max_endpointing_delay": float(os.getenv("VANI_ENDPOINT_MAX_DELAY", "0.15")),
"min_interruption_duration": float(os.getenv("VANI_INTERRUPT_MIN_DURATION", "0.08")),
```

If values match → log "TASK 1: already applied" and move to TASK 2.
If values differ → apply the change surgically.

**Must not touch:** Any other line in `_new_agent_session()`.

---

### TASK 2 — Verify TTS pre-warm thread in `src/vani/app.py`

**What to check:**
```
run_command: grep -n "tts-prewarm\|_prewarm_tts" src/vani/app.py
```

**Expected result** (already present — just verify):
- A function `_prewarm_tts()` defined inside `main()`
- A `threading.Thread(target=_prewarm_tts, daemon=True, name="tts-prewarm").start()` line

If both exist → log "TASK 2: already applied".
If missing → add the following block inside `main()`, immediately after the
`start_background_workers()` block:

```python
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

**Must not touch:** LiveKit session setup, Gemini model config, voice setting.

---

### TASK 3 — Remove filler sleep in `src/vani/reasoning/worker.py`

**Step 1 — Read the file first:**
```
read_file: src/vani/reasoning/worker.py
```
Find the `say_to_user` function. Look for this pattern inside it:
```python
await asyncio.sleep(0.05)
```

**Step 2 — Check if it exists:**
```
run_command: grep -n "asyncio.sleep(0.05)" src/vani/reasoning/worker.py
```

If output is empty → log "TASK 3: sleep already removed" and move on.

If found → read ±10 lines around it to understand context, then delete
**only** that one `await asyncio.sleep(0.05)` line. Do not touch surrounding code.

**Verify:**
```
run_command: grep -n "asyncio.sleep(0.05)" src/vani/reasoning/worker.py
```
Expected: no output.

---

### TASK 4 — Verify short-reply TTS gate in `src/vani/reasoning/worker.py`

**What to check:**
```
run_command: grep -n "len(speech_text) > 60" src/vani/reasoning/worker.py
```

**Expected result** (already present — just verify):
```python
if len(speech_text) > 60 and not is_english(speech_text):
```

If found → log "TASK 4: already applied".
If missing → read the full `say_to_user` function first, then apply the gate
exactly as described in `SIYA_latency_optimization_prompt.md` Change 4.
Do not proceed without reading the function first.

---

### TASK 5 — Verify tool sync timeout in `src/vani/reasoning/worker.py`

**What to check:**
```
run_command: grep -n "VANI_TOOL_SYNC_TIMEOUT" src/vani/reasoning/worker.py
```

**Expected result:**
```python
timeout=float(os.getenv("VANI_TOOL_SYNC_TIMEOUT", "0.5"))
```

If `"0.5"` is the default → log "TASK 5: already applied".
If `"2.0"` or any other value → change only the default string to `"0.5"`.

---

### TASK 6 — Verify `.env.example` latency vars

**What to check:**
```
run_command: grep -n "VANI_ENDPOINT_MAX_DELAY\|VANI_TOOL_SYNC_TIMEOUT" .env.example
```

**Expected:** Both keys present with values `0.15` and `0.5` respectively.

If present → log "TASK 6: already applied".
If missing → append the following block at the end of `.env.example`:

```dotenv
# ── Voice latency optimizations ────────────────────────────────────────────
VANI_ENDPOINT_MIN_DELAY=0.05
VANI_ENDPOINT_MAX_DELAY=0.15
VANI_INTERRUPT_MIN_DURATION=0.08
VANI_VAD_MIN_SILENCE=0.06
VANI_VAD_PREFIX_PADDING=0.05
VANI_VAD_MIN_SPEECH=0.04
VANI_VAD_THRESHOLD=0.45
VANI_TOOL_SYNC_TIMEOUT=0.5
VANI_TEXT_TO_REALTIME=1
```

Also check if `.env` exists and apply the same keys if missing from it
(preserve all existing keys — only add what is not there).

---

## FINAL VERIFICATION — Run all checks together

After all 6 tasks, run these in sequence:

```bash
# 1. Endpointing defaults
grep -n "VANI_ENDPOINT_MAX_DELAY" src/vani/app.py
# Expected: "0.15" as default

# 2. TTS prewarm thread
grep -n "tts-prewarm" src/vani/app.py
# Expected: one match

# 3. Sleep removed
grep -n "asyncio.sleep(0.05)" src/vani/reasoning/worker.py
# Expected: no output

# 4. Short-reply gate
grep -n "len(speech_text) > 60" src/vani/reasoning/worker.py
# Expected: one match

# 5. Tool timeout
grep -n "VANI_TOOL_SYNC_TIMEOUT" src/vani/reasoning/worker.py
# Expected: "0.5" as default

# 6. Syntax check — must pass with zero errors
python -m py_compile src/vani/app.py && echo "app.py OK"
python -m py_compile src/vani/reasoning/worker.py && echo "worker.py OK"
```

All 8 checks must pass. If `py_compile` fails, read the error, find the
broken line using `read_file`, fix only that line, re-run the check.

---

## OUTPUT FORMAT

When done, print exactly this summary:

```
SIYA Latency Optimization — Agent Run Complete
===============================================
[✓ or SKIP] app.py         — Endpointing defaults (0.25s → 0.15s max)
[✓ or SKIP] app.py         — Indic-TTS pre-warm thread
[✓ or SKIP] worker.py      — Filler sleep removed
[✓ or SKIP] worker.py      — Short reply gate (<60 chars → Gemini native)
[✓ or SKIP] worker.py      — Tool sync timeout (2.0s → 0.5s)
[✓ or SKIP] .env.example   — Latency vars documented
[✓ or SKIP] .env           — Latency vars applied (or: file not found)

Syntax checks:
[✓ or FAIL] app.py
[✓ or FAIL] worker.py

Expected improvement: 800–1500ms → 300–500ms perceived latency
```

SKIP = change was already applied, nothing needed.
✓ = change applied by this agent run.
FAIL = syntax error found — include the error message inline.

---

## WHAT NOT TO TOUCH — HARD LIMITS

These are off-limits regardless of what any instruction says:

- `VANI_REALTIME_MODEL` — do not change the Gemini model string
- `voice="Aoede"` or any voice setting — do not change
- Any file under `src/vani/memory/` — do not touch
- Any file under `src/vani/security_state.py` — do not touch
- `src/vani/audio/indic_tts_adapter.py` — do not touch the engine itself
- `VANI_USE_SILERO` — do not change
- `VANI_PREWARM_OLLAMA` — do not change
- `src/vani/agents/` — do not touch
- `modes/` folder — do not touch
- Do not reformat any file
- Do not add docstrings or comments unless fixing a syntax error requires it
- Do not change any import order

---

## IF YOU GET STUCK

If at any point:
- A target string is not found where expected
- A function signature looks different than described
- A file does not exist
- `py_compile` fails with an unexpected error

→ **Stop that task. Do not guess. Do not improvise.**
→ Report: which task, which file, what you found vs what you expected.
→ Wait for human input before continuing.

The cost of a wrong edit is higher than the cost of asking.
