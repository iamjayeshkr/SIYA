# Vani OS — P2 Integration Guide
# Model fallback chain + Whisper offline STT

## 0. Install dependencies

```bash
pip install -r requirements-p2.txt

# Pull Whisper model (one time, ~244MB for 'small')
# Happens automatically on first transcription, or force it:
python -c "from vani.stt_whisper import WhisperSTT; import asyncio; asyncio.run(WhisperSTT().load())"

# Install Piper TTS (macOS)
brew install piper-tts
# Pull a voice (choose one):
# en_US-lessac-medium  — natural American English
# en_GB-alan-medium    — British accent
# hi-         — Hindi (for Hinglish)
piper --download-dir ~/.local/share/piper-voices --model en_US-lessac-medium
```

---

## 1. app.py — wire up model router and voice stack

```python
from vani.model_router import ModelRouter
from vani.voice_stack import VoiceStack

# Replace your existing Ollama call setup with:
model_router = ModelRouter()

# Pass your existing LiveKit session (keep it exactly as-is):
# from your_livekit_module import livekit_session
voice_stack = VoiceStack(
    model_router=model_router,
    livekit_session=livekit_session,   # None = always offline
    whisper_model="small",             # or "medium" for better Hinglish
    on_mode_change=lambda mode: log.info("voice_mode_changed", mode=mode),
)

async def startup():
    await init_db()
    await semantic_mem.init()
    await model_router.start()         # begins health checks
    await voice_stack.start()          # pre-loads Whisper, checks Piper
    log.info("vani_ready")
```

---

## 2. planner.py — replace direct Ollama calls with model router

```python
# BEFORE (single Ollama call, no fallback):
async def call_llm(prompt: str) -> str:
    response = await ollama_client.chat(model="qwen2.5:7b", prompt=prompt)
    return response.text

# AFTER (automatic tier routing + fallback chain):
from vani.model_router import ModelRouter, ModelTier

async def call_llm(prompt: str, tier: ModelTier = None) -> str:
    response = await model_router.complete(
        prompt=prompt,
        system=VANI_SYSTEM_PROMPT,
        tier=tier,   # None = auto-classify from prompt content
    )
    log.info("llm_response",
             model=response.model_used,
             fallbacks=response.fallback_count,
             duration_ms=response.duration_ms)
    return response.text

# For heavy tasks (summarise doc, complex analysis):
response = await model_router.complete(prompt, tier=ModelTier.HEAVY)

# For quick intents (after regex router misses):
response = await model_router.complete(prompt, tier=ModelTier.LIGHTWEIGHT)
```

---

## 3. Set VANI_FORCE_OFFLINE=true to test offline mode

```bash
VANI_FORCE_OFFLINE=true python app.py
# Vani now uses Whisper + Piper for all voice, Ollama for all LLM
# Verify it works completely without internet
```

---

## 4. Customise the model fallback chain

Edit `vani/model_registry.py` to add/remove models:

```python
# Add a new local model:
"mistral-7b": ModelConfig(
    id="mistral-7b",
    provider=ModelProvider.OLLAMA,
    model_name="mistral:7b",
    tier=ModelTier.MEDIUM,
    context_window=32_000,
    supports_tools=True,
    cost_per_1k_tokens=0.0,
    timeout_s=35,
),

# Add it to the fallback chain:
FALLBACK_CHAINS[ModelTier.MEDIUM] = [
    "qwen2.5-14b",
    "mistral-7b",     # new model in chain
    "gemini-flash",
]
```

---

## 5. Check model router status

```python
status = model_router.status()
# {
#   "qwen2.5-7b":  {"healthy": True,  "provider": "ollama",  "tier": "lightweight"},
#   "gemini-pro":  {"healthy": True,  "provider": "gemini",  "tier": "heavy"},
#   "qwen2.5-14b": {"healthy": False, "provider": "ollama",  "tier": "medium"},  # not pulled yet
# }
```

---

## What P2 gives Vani immediately

| Before P2 | After P2 |
|-----------|----------|
| Single Ollama model, no fallback | 6+ models, auto-fallback chain |
| Gemini down = Vani broken | Gemini down = silently uses Ollama |
| No internet = no voice at all | Full offline mode (Whisper + Piper + Ollama) |
| All queries hit same model | Cheap queries → local, heavy → Gemini |
| Manual model switching | Automatic health checks every 60s |
| API costs unpredictable | Predictable: most queries are free |

---

## Whisper model guide (pick based on Mac RAM)

| Model  | Size   | Speed        | Hinglish accuracy | Recommended for    |
|--------|--------|--------------|-------------------|--------------------|
| tiny   | 75MB   | Very fast    | OK                | Testing only       |
| base   | 142MB  | Fast         | Good              | 8GB RAM Macs       |
| small  | 244MB  | Fast         | Very good         | **Default choice** |
| medium | 769MB  | Moderate     | Excellent         | 16GB RAM Macs      |
| large  | 1.5GB  | ~Realtime    | Best              | M2/M3 Pro/Max      |
