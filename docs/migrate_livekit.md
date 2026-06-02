# Migrate LiveKit To Pluggable Voice Backends

## Goal

Make Vani stop depending on LiveKit Cloud by default, while keeping LiveKit as an optional backend. The new default should be free, low-RAM, and usable on 2 GB to 4 GB devices.

Target result:

```text
UI / hotkey
  -> selected voice backend
  -> same Vani reasoning, tools, memory, browser, files, messaging
```

## Backend Modes

Add this environment variable:

```env
VANI_VOICE_BACKEND=local_low_ram
```

Supported modes:

```text
local_low_ram   Free default for 2 GB to 4 GB RAM devices
local_full      Better local models for stronger machines
gemini_direct   Direct Gemini voice/realtime path without LiveKit
livekit         Current LiveKit behavior, optional fallback
none            Text-only mode
```

Recommended low-RAM defaults:

```env
VANI_VOICE_BACKEND=local_low_ram
VANI_PREWARM_OLLAMA=0
VANI_USE_SILERO=0
VANI_LOW_POWER_UI=1
VANI_ANIMATED_AVATAR=0
```

## Architecture

Create a backend boundary:

```text
vani_app.py
  - starts local UI/server
  - selects voice backend from env
  - exposes shared HTTP endpoints

voice_backends/
  base.py
  local_low_ram.py
  livekit_backend.py
  local_full.py
  gemini_direct.py

vani_reasoning.py
  - remains the shared brain/tool layer
```

Backend contract:

```python
class VoiceBackend:
    async def start(self): ...
    async def stop(self): ...
    async def handle_text(self, text: str) -> str: ...
    async def handle_audio_file(self, path: str) -> str: ...
```

## Phase 1: Prepare Configuration

1. Add `VANI_VOICE_BACKEND` to `.env.example`.
2. Default it to `local_low_ram`.
3. Keep existing LiveKit variables in `.env.example`, but mark them optional.
4. Add low-RAM flags:

```env
VANI_PREWARM_OLLAMA=0
VANI_USE_SILERO=0
VANI_LOW_POWER_UI=1
VANI_ANIMATED_AVATAR=0
```

5. Update `bin/run_vani.sh` so it prints the selected backend at startup.

## Phase 2: Create Backend Folder

1. Create:

```text
voice_backends/
  __init__.py
  base.py
  selector.py
```

2. `base.py` defines the common backend interface.
3. `selector.py` reads `VANI_VOICE_BACKEND` and returns the correct backend.
4. For unknown backend names, fail clearly with a helpful message.

Example:

```python
def get_voice_backend(name: str):
    if name == "local_low_ram":
        from .local_low_ram import LocalLowRamVoiceBackend
        return LocalLowRamVoiceBackend()
    if name == "livekit":
        from .livekit_backend import LiveKitVoiceBackend
        return LiveKitVoiceBackend()
    if name == "none":
        from .none_backend import NoneVoiceBackend
        return NoneVoiceBackend()
    raise ValueError(f"Unknown VANI_VOICE_BACKEND: {name}")
```

## Phase 3: Move LiveKit Behind A Backend

1. Move LiveKit token generation, room setup, agent dispatch, and session startup into `voice_backends/livekit_backend.py`.
2. Keep existing behavior working when:

```env
VANI_VOICE_BACKEND=livekit
```

3. `vani_app.py` should no longer assume LiveKit is always active.
4. Only inject LiveKit meta tags into `_ui_patched.html` when the selected backend is `livekit`.
5. UI should show generic backend status instead of LiveKit-specific status when not using LiveKit.

Acceptance check:

```bash
VANI_VOICE_BACKEND=livekit bin/run_vani.sh
```

Expected:

```text
registered worker
received job request
realtime session started OK
```

## Phase 4: Add Text-Only Backend

Before local voice, add a simple no-voice backend.

1. Create `voice_backends/none_backend.py`.
2. It should support `/send_text` only.
3. No microphone, no LiveKit, no STT, no TTS.
4. This gives a stable baseline for weak machines.

Acceptance check:

```bash
VANI_VOICE_BACKEND=none bin/run_vani.sh
```

Expected:

```text
Vani starts
UI opens
Text chat works
No LiveKit room is created
No LiveKit worker starts
```

## Phase 5: Add Local Low-RAM Voice

This is the free replacement for LiveKit.

Recommended flow:

```text
Cmd+Shift+V or UI mic button
  -> record short audio
  -> POST audio to local Python endpoint
  -> transcribe with whisper.cpp tiny/base
  -> send transcript to vani_reasoning.py
  -> speak reply with system TTS
  -> return transcript/reply to UI
```

Do not start with continuous listening. Use push-to-talk first because it is cheaper, simpler, and safer on 2 GB to 4 GB RAM devices.

### STT

Use `whisper.cpp` CLI for low RAM.

Models:

```text
2 GB RAM: ggml-tiny.en
4 GB RAM: ggml-base.en
```

Add env vars:

```env
VANI_WHISPER_CPP_BIN=/path/to/whisper-cli
VANI_WHISPER_MODEL=/path/to/ggml-tiny.en.bin
VANI_MAX_RECORD_SECONDS=8
```

### TTS

Use system TTS first.

macOS:

```bash
say "Hello Rudra"
```

Windows later:

```text
Use SAPI / PowerShell speech synthesis
```

Linux later:

```text
Use espeak-ng or Piper
```

## Phase 6: Add Local Audio Endpoint

Add a local endpoint in `vani_app.py`:

```text
POST /voice_record
```

Request:

```text
multipart/form-data
file: recorded audio
```

Response:

```json
{
  "transcript": "open browser",
  "reply": "Opening browser."
}
```

Rules:

1. Reject files over a small size limit.
2. Reject recordings longer than `VANI_MAX_RECORD_SECONDS`.
3. Store temporary audio in `/tmp` or `tempfile`.
4. Delete temp files after transcription.
5. Do not load a large model into Python memory if using `whisper.cpp` CLI.

## Phase 7: Update UI For Local Voice

1. Add a backend-aware mic button.
2. In `local_low_ram` mode, the button records short audio chunks.
3. Send the recording to `/voice_record`.
4. Show:

```text
Listening
Transcribing
Thinking
Speaking
Ready
```

5. Hide LiveKit-specific messages unless backend is `livekit`.
6. Keep text chat working in every backend mode.

## Phase 8: Avoid Low-End Device Problems

Apply these rules in `local_low_ram`:

1. No always-on microphone.
2. No LiveKit worker.
3. No Gemini realtime session.
4. No Silero VAD.
5. No Ollama prewarm.
6. No large GIF/video avatar by default.
7. No full memory load into every prompt.
8. Use summaries and recent context only.
9. Run STT only when the user records.
10. Run local LLM only when rules/tools cannot answer.

## Phase 9: Add Lightweight Routing

Before calling an LLM, route simple commands directly.

Examples:

```text
"open chrome"      -> browser tool
"what time is it"  -> system time
"open downloads"   -> file opener
"send message"     -> messaging flow
```

Only use Ollama/Qwen when:

1. The command is ambiguous.
2. The user asks for writing, planning, explanation, or reasoning.
3. A tool needs structured intent extraction.

This keeps low-end devices usable.

## Phase 10: Add Local Full Backend Later

After `local_low_ram` works, add:

```env
VANI_VOICE_BACKEND=local_full
```

Possible upgrades:

```text
faster-whisper small/base
Piper TTS
Ollama qwen2.5:1.5b or llama3.2:1b
optional continuous listen
optional VAD
```

This should reuse the same backend interface.

## Phase 11: Add Gemini Direct Later

Optional mode:

```env
VANI_VOICE_BACKEND=gemini_direct
```

Purpose:

```text
No LiveKit Cloud
No LiveKit room dispatch
Direct Gemini realtime connection
Better realtime voice than local_low_ram
Still depends on Gemini API quota/key
```

This is not the free default.

## Phase 12: Deprecate LiveKit Default

Once `local_low_ram` is stable:

1. Change default backend to `local_low_ram`.
2. Keep LiveKit documented as optional.
3. Move LiveKit setup instructions to a separate section.
4. Remove LiveKit key requirement from first-run setup.
5. Make missing LiveKit keys a warning only when `VANI_VOICE_BACKEND=livekit`.

## Testing Checklist

Run these before considering migration complete:

```bash
VANI_VOICE_BACKEND=none bin/run_vani.sh
VANI_VOICE_BACKEND=local_low_ram bin/run_vani.sh
VANI_VOICE_BACKEND=livekit bin/run_vani.sh
```

For `none`:

```text
Text chat works
No LiveKit worker starts
No room is created
```

For `local_low_ram`:

```text
Mic button records
Audio transcribes
Vani replies
System TTS speaks
Memory does not balloon
CPU returns idle after speaking
```

For `livekit`:

```text
Existing LiveKit behavior still works
No startup greeting warning
Connection errors are not mislabeled as rate limits
```

## Suggested Final File Names

Current file:

```text
docs/migrate_livekit.md
```

Better long-term name:

```text
migrate_livekit_to_voice_backends.md
```

Reason: the better name makes the destination clear. The project is not just removing LiveKit; it is moving Vani to a scalable backend system.

## Recommended First Implementation Order

1. Add `VANI_VOICE_BACKEND`.
2. Add `voice_backends/base.py` and `selector.py`.
3. Add `none` backend.
4. Make `vani_app.py` run without LiveKit.
5. Move current LiveKit behavior into `livekit_backend.py`.
6. Add `/voice_record`.
7. Add `local_low_ram` using `whisper.cpp` and `say`.
8. Update UI mic button for local backend.
9. Make `local_low_ram` the default.
10. Keep LiveKit only as optional fallback.
