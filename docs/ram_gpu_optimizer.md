# Vani RAM/GPU Optimizer

Goal: reduce RAM, GPU, CPU, disk, and battery usage as much as possible without paying for external services. This document is specific to the current Vani codebase.

## Current Heavy Areas

The biggest local weight found in this repo:

| Area | Current issue | Why it hurts |
|---|---|---|
| `listening.gif` | ~80 MB animated GIF | GIF decoding is memory-heavy and can keep CPU/GPU busy continuously. |
| `opening2.mp4`, `talking1.mp4`, `vani_avatar.mp4` | Multiple video assets loaded by UI | Browser/app compositor uses RAM/GPU to decode and blend layers. |
| `venv311` | ~1.2 GB | Disk heavy; many packages also increase import time and memory if loaded. |
| LiveKit + realtime Gemini | Always-on voice pipeline | Keeps network/audio/LLM session active and can consume RAM continuously. |
| `livekit-plugins-silero`, noise cancellation, `onnxruntime` | ML/audio processing dependencies | CPU/RAM heavy; may use accelerated backends. |
| Ollama/Qwen | Local model process | Can use several GB RAM depending on model and keep memory resident. |
| LangChain `@tool` wrappers | Imported across many modules | Pydantic/LangChain import graph adds startup memory. |
| Screen/document analysis | Images/base64/text prompts | Large screenshots/docs can create temporary high-memory spikes. |
| Browser automation | Chrome app mode + JS extraction | Browser itself can use hundreds of MB. |
| WhatsApp/Telegram automation | Repeated AppleScript/subprocess calls | CPU spikes and slower interactions when repeated often. |

## Priority 0: Measure Before and After

Do this before changing anything major.

### macOS Activity Monitor

Check these processes:

- `Python`
- `Vani` / `Codex` / browser app window
- `Google Chrome` or `Safari`
- `ollama`
- `python3`

Watch:

- Memory
- Energy Impact
- GPU History
- CPU

### Terminal checks

```bash
ps aux | egrep 'python|ollama|Chrome|Safari|LiveKit|Vani' | sort -nrk 4 | head -20
```

```bash
du -sh * | sort -h | tail -20
```

```bash
venv311/bin/python -X importtime -c "import vani.reasoning as vani_reasoning" 2> importtime.log
tail -80 importtime.log
```

Optional runtime memory:

```bash
venv311/bin/python - <<'PY'
import os, psutil
p = psutil.Process(os.getpid())
print("RSS MB:", round(p.memory_info().rss / 1024 / 1024, 1))
import vani_app
print("After vani_app RSS MB:", round(p.memory_info().rss / 1024 / 1024, 1))
PY
```

## Priority 1: Replace Heavy Animated GIF

`listening.gif` is the largest asset at roughly 80 MB. Animated GIF is inefficient because every frame is large and decoded poorly compared with video.

### Best free fix

Convert `listening.gif` to a compressed MP4 or WebM.

```bash
ffmpeg -i listening.gif -vf "fps=24,scale=720:-2" -c:v libx264 -pix_fmt yuv420p -crf 28 listening.mp4
```

If `ffmpeg` is not installed:

```bash
brew install ffmpeg
```

Then update `ui.html` and `_ui_patched.html`:

Current:

```html
<img id="vid-listening" class="avatar-video" src="listening.gif" />
```

Better:

```html
<video id="vid-listening" class="avatar-video" src="listening.mp4" loop muted playsinline preload="metadata"></video>
```

And in JS:

```js
vidListening.play().catch(() => {});
```

Expected impact:

- Much lower disk size.
- Lower RAM spikes during decode.
- Lower CPU/GPU during animation.

## Priority 2: Stop Preloading All Video Assets

Current UI loads:

- `listening.gif`
- `talking1.mp4`
- `opening2.mp4`

Current video tags use `preload="auto"`, which encourages the browser to load/decode videos early.

Change:

```html
preload="auto"
```

to:

```html
preload="metadata"
```

For talking video, lazy-load only when speaking starts:

```html
<video id="vid-talking" class="avatar-video" data-src="talking1.mp4" loop muted playsinline preload="none"></video>
```

```js
function ensureTalkingLoaded() {
  if (!vidTalking.src) vidTalking.src = vidTalking.dataset.src;
}

function setAvatarState(newState) {
  if (newState === 'talking') {
    ensureTalkingLoaded();
    vidTalking.play().catch(() => {});
  }
}
```

Expected impact:

- Faster startup.
- Less initial RAM/GPU use.
- Less video decode pressure.

## Priority 3: Add Low Power UI Mode

Create an environment flag:

```bash
export VANI_LOW_POWER_UI=1
```

When enabled:

- Do not load opening video.
- Use static `vani_idle.png`.
- Disable animated scanline overlay.
- Disable talking video overlay.
- Use CSS opacity only for status changes.

Suggested HTML logic:

```js
const lowPowerUI = new URLSearchParams(location.search).get('lowPower') === '1'
  || localStorage.getItem('VANI_LOW_POWER_UI') === '1';

if (lowPowerUI) {
  document.body.classList.add('low-power');
}
```

Suggested CSS:

```css
body.low-power #vid-opening2,
body.low-power #vid-talking,
body.low-power #video-overlay::after {
  display: none;
}
```

Expected impact:

- Major GPU reduction.
- Better battery.
- Useful on older MacBooks.

## Priority 4: Do Not Start Ollama Warmup by Default

In `vani_app.py`, `_prewarm_ollama()` runs during startup:

```python
asyncio.create_task(_prewarm_ollama())
```

This can wake Ollama and load model memory even if user only wants voice/chat first.

Change to:

```python
if os.getenv("VANI_PREWARM_OLLAMA", "0") == "1":
    asyncio.create_task(_prewarm_ollama())
```

Expected impact:

- Avoids loading Qwen into RAM unnecessarily.
- Lower startup RAM.
- Less background CPU.

Tradeoff:

- First local tool dispatch may be slower.

## Priority 5: Use Smaller Local Ollama Model

Current:

```python
OLLAMA_MODEL = "qwen2.5:3b"
```

Lower-RAM options:

```python
OLLAMA_MODEL = os.getenv("VANI_OLLAMA_MODEL", "qwen2.5:1.5b")
```

Then install a smaller model:

```bash
ollama pull qwen2.5:1.5b
```

Even smaller:

```bash
ollama pull llama3.2:1b
```

Expected impact:

- Several GB less RAM depending on model.
- Faster local routing.

Tradeoff:

- Slightly weaker tool selection. Use deterministic routing for common tasks to compensate.

## Priority 6: Stop Keeping Multiple Brains Active

Current architecture:

- LiveKit realtime Gemini for voice.
- Qwen/Ollama for tool routing.
- Gemini HTTP for document/screen feedback.

This is powerful but heavy. Use modes.

### Suggested modes

| Mode | Realtime voice | Ollama | Gemini document/screen | Best for |
|---|---:|---:|---:|---|
| `voice` | on | lazy | off | normal talking |
| `tools` | off | on | off | local tasks |
| `document` | off | lazy | on or Ollama | document review |
| `low_power` | off or push-to-talk | lazy | off | battery saving |

Add environment flag:

```bash
export VANI_MODE=low_power
```

In `vani_app.py`, only start LiveKit agent if mode needs realtime voice.

## Priority 7: Make Document Feedback Non-Voice by Default

Document reviews are long. Speaking them aloud causes cutoffs and memory/audio pressure.

Already improved:

- UI renders Markdown.
- `say_to_user()` now shortens long tool results.

Recommended next step:

In document upload endpoint, return:

```json
{
  "reply": "full markdown",
  "speak": "Short summary only"
}
```

Then UI shows `reply`, but voice only says `speak`.

Example:

```python
return {
    "reply": markdown,
    "speak": "Document review ready. Main issue: intro needs clarity. Details are in the text panel."
}
```

Expected impact:

- Prevents TTS from reading 900-word reviews.
- Lower audio queue pressure.
- Better UX.

## Priority 8: Cap Document Text Size Earlier

Current document extraction compact limit is around 18,000 chars. That is okay, but can still create large prompts.

Use:

```python
def _compact_document_text(text: str, limit: int = 10000) -> str:
```

For detailed mode:

```bash
export VANI_DOC_CHARS=18000
```

Code:

```python
limit = int(os.getenv("VANI_DOC_CHARS", "10000"))
```

Expected impact:

- Lower prompt memory.
- Faster feedback.
- Fewer model timeouts.

Tradeoff:

- Very long documents need chunking.

## Priority 9: Chunk Long Documents Instead of One Giant Prompt

For long files:

1. Extract text.
2. Split into chunks of 3,000 to 5,000 chars.
3. Summarize each chunk.
4. Produce final feedback from summaries.

Pseudo-code:

```python
def chunks(text, size=4000):
    for i in range(0, len(text), size):
        yield text[i:i+size]
```

Do not feed a 50-page document into one prompt.

Expected impact:

- Lower peak RAM.
- Fewer model failures.
- Better output for large files.

## Priority 10: Avoid Gemini Vision Unless Needed

Screen reading can be expensive because it:

- Captures screenshot.
- Encodes image to base64.
- Sends image to Gemini.
- Keeps image bytes in memory.

Use local context first:

```bash
export VANI_SCREEN_USE_GEMINI=0
```

Only use Gemini vision when user says:

- "screen detail mein dekho"
- "image analyze karo"
- "screenshot se batao"

Suggested router behavior:

```python
if "detail" in query or "image" in query or "screenshot" in query:
    use_gemini = True
else:
    use_gemini = False
```

Expected impact:

- Lower RAM spikes.
- Less network/model work.
- Faster screen answers.

## Priority 11: Reduce Screenshot Size

Current screen code resizes to max width 1280. For low power:

```python
max_width = int(os.getenv("VANI_SCREEN_MAX_WIDTH", "900"))
```

Use JPEG quality:

```python
quality = int(os.getenv("VANI_SCREEN_JPEG_QUALITY", "55"))
```

Expected impact:

- Smaller base64 payload.
- Lower memory.
- Faster vision requests.

## Priority 12: Remove or Optionalize Noise Cancellation

Current imports:

```python
from livekit.plugins import google, noise_cancellation, silero
```

Noise cancellation can add CPU/RAM. Make it optional:

```bash
export VANI_NOISE_CANCEL=0
```

Code:

```python
if os.getenv("VANI_NOISE_CANCEL", "0") == "1":
    from livekit.plugins import noise_cancellation
else:
    noise_cancellation = None
```

Expected impact:

- Less CPU during voice.
- Less audio pipeline memory.

Tradeoff:

- Worse mic quality in noisy rooms.

## Priority 13: Make Silero Optional

Silero VAD uses ONNX runtime. That adds memory and startup cost.

If LiveKit/Gemini native audio endpointing is good enough, disable Silero:

```bash
export VANI_USE_SILERO=0
```

Code pattern:

```python
vad = None
if os.getenv("VANI_USE_SILERO", "0") == "1":
    from livekit.plugins import silero
    vad = silero.VAD.load()
```

Expected impact:

- Avoids `onnxruntime` load.
- Lower startup RAM.

## Priority 14: Lazy Import LangChain Tool Decorators

Many files import:

```python
from langchain_core.tools import tool
```

This can load Pydantic/LangChain on startup.

Best improvement:

- Replace direct `@tool` usage with a lightweight wrapper.
- Only create LangChain tools when the dispatcher needs `.ainvoke()`.

Minimal compatibility wrapper:

```python
class SimpleTool:
    def __init__(self, fn):
        self.fn = fn
    async def ainvoke(self, arg):
        if isinstance(arg, dict):
            return await self.fn(**arg)
        return await self.fn(arg)

def light_tool(fn):
    return SimpleTool(fn)
```

Then replace:

```python
from langchain_core.tools import tool
```

with:

```python
from vani_light_tool import light_tool as tool
```

Expected impact:

- Lower import memory.
- Faster startup.
- Fewer dependency chains.

Tradeoff:

- If external LangChain features are required later, keep compatibility carefully.

## Priority 15: Split Heavy Tools into On-Demand Modules

Keep `vani_reasoning.py` small. Move heavy areas into modules:

- `vani_screen_tools.py`
- `vani_whatsapp_tools.py`
- `vani_document_tools.py`
- `vani_media_tools.py`
- `vani_system_tools.py`

Only import when needed:

```python
async def read_screen(query):
    from vani_screen_tools import read_screen_impl
    return await read_screen_impl(query)
```

Expected impact:

- Lower baseline RAM.
- Faster cold command routing.

## Priority 16: Reduce Browser Usage

The UI currently opens Chrome app mode if available.

Chrome is heavy. For low power, prefer Safari WebView or pywebview.

Add:

```bash
export VANI_UI_BROWSER=safari
```

Or:

```bash
export VANI_UI_BROWSER=default
```

In `_open_ui()`:

```python
browser = os.getenv("VANI_UI_BROWSER", "chrome")
if browser == "safari":
    subprocess.Popen(["open", "-a", "Safari", url])
elif browser == "default":
    subprocess.Popen(["open", url])
else:
    # Chrome app mode
```

Expected impact:

- Safari may use less memory on macOS.
- Default browser avoids launching a new Chrome instance.

## Priority 17: Avoid Duplicate UI Files

Both `ui.html` and `_ui_patched.html` exist. `_ui_patched.html` is generated from `ui.html` with tokens/meta.

Keep only one source of truth:

- Edit `ui.html`.
- Generate `_ui_patched.html` at runtime only.
- Do not commit large patched variants if avoidable.

Expected impact:

- Small disk improvement.
- Less confusion.
- Fewer duplicate UI bugs.

## Priority 18: Disable Opening Video

`opening2.mp4` is ~12 MB and plays at startup. It is decorative.

Low-power behavior:

```js
if (lowPowerUI) {
  _enterRuntime();
} else {
  vidOpening2.play().catch(() => {});
}
```

Expected impact:

- Faster UI usable time.
- Lower startup GPU spike.

## Priority 19: Reduce CSS Overdraw

Current UI layers:

- Full-screen animated avatar.
- Talking overlay video.
- Opening overlay video.
- Radial gradient overlays.
- Repeating scanline overlay.
- Glow/ring box-shadows.
- Backdrop blur.

Each layer costs GPU/compositor work.

Low-power CSS:

```css
body.low-power #video-overlay,
body.low-power .speak-ring {
  display: none;
}

body.low-power #text-panel,
body.low-power .status-pill,
body.low-power #panel-toggle {
  backdrop-filter: none;
}
```

Expected impact:

- Lower GPU use.
- Less battery drain.

## Priority 20: Use Static Avatar While Idle

Idle state should be static. Animate only when:

- User is speaking.
- Vani is speaking.
- User explicitly enables animated mode.

Suggested assets:

- `vani_idle.webp` or optimized `vani_idle.png`
- `talking1.mp4` only during speech

Convert PNG to WebP:

```bash
ffmpeg -i vani_idle.png -compression_level 6 -quality 80 vani_idle.webp
```

Expected impact:

- Lower RAM/GPU in idle.

## Priority 21: Reduce ThreadingHTTPServer Risk

`ThreadingHTTPServer` can spawn many handler threads under repeated `/send_text` or `/analyze_document` calls.

Add a global semaphore:

```python
REQUEST_SEM = threading.BoundedSemaphore(2)
```

In `do_POST`:

```python
if not REQUEST_SEM.acquire(blocking=False):
    self._send_json(429, {"reply": "Vani abhi busy hai. Thoda ruk ke try karo."})
    return
try:
    ...
finally:
    REQUEST_SEM.release()
```

Expected impact:

- Prevents RAM spikes from parallel requests.
- Better stability on low-memory systems.

## Priority 22: Do Not Read Huge Request Bodies

Current document upload limit is 12 MB. Keep it or reduce:

```python
MAX_DOC_UPLOAD_MB = int(os.getenv("VANI_MAX_DOC_UPLOAD_MB", "6"))
```

Reject early:

```python
if length > MAX_DOC_UPLOAD_MB * 1024 * 1024:
    ...
```

Expected impact:

- Prevents accidental giant PDF/doc upload memory spikes.

## Priority 23: Cache Less Contact/UI Data

WhatsApp contact caches are useful, but do not let caches grow forever.

Use max size:

```python
if len(_contacts_cache) > 50:
    _contacts_cache.clear()
```

Expected impact:

- Small RAM improvement.
- Avoids long-running memory growth.

## Priority 24: Avoid Repeated AppleScript Calls

AppleScript calls are slow and CPU-spiky. Current WhatsApp flows call many scripts.

Optimize by:

- Batch multiple key actions into one script.
- Avoid reading whole UI trees repeatedly.
- Cache frontmost/browser app.
- Prefer direct URL opens where possible.

Example:

Instead of:

```python
_wa_keystroke_target("CLOSE_CHAT")
_wa_keystroke_target("SEARCH_CHAT")
_wa_type_text(contact)
```

Batch:

```applescript
tell application "System Events"
  key code 53
  keystroke "/" using {command down, control down}
  keystroke "contact"
end tell
```

Expected impact:

- Faster WhatsApp actions.
- Lower CPU bursts.

## Priority 25: Minimize Dependencies

Review `requirements/mac.txt`.

Potentially optional/heavy:

| Package/group | Keep only if needed |
|---|---|
| `livekit-plugins-openai` | Remove if not using OpenAI LiveKit plugin. |
| `livekit-plugins-noise-cancellation` | Make optional. |
| `livekit-plugins-silero` + `onnxruntime` | Make optional. |
| `langchain-community` | Remove if unused. |
| `langchain-text-splitters` | Remove if unused. |
| `duckduckgo-search` | Keep only if local search tool uses it. |
| `watchfiles` | Remove if no dev watcher. |
| OpenTelemetry exporters | Remove if not using observability. |
| `SQLAlchemy` | Remove if not used. |
| `zstandard` | Remove if not used. |

Create two requirement files:

```text
requirements_core.txt
requirements_full.txt
```

Core should include only:

- LiveKit essentials
- Google plugin if voice uses Gemini
- dotenv
- requests/httpx
- rapidfuzz
- pillow only if screen features enabled

Expected impact:

- Smaller venv.
- Faster install.
- Less accidental import memory.

## Priority 26: Remove Unused Media Files

Current large files:

- `listening.gif` ~80 MB
- `opening2.mp4` ~12 MB
- `talking1.mp4` ~8.4 MB
- `vani_avatar.mp4` ~5.9 MB
- `vani_idle.png` ~1.8 MB

If not used:

- Remove `vani_avatar.mp4`.
- Remove old `opening.mp4` references.
- Keep one idle asset and one talking asset.

Before deleting:

```bash
rg -n "vani_avatar|opening2|talking1|listening.gif|opening.mp4"
```

Expected impact:

- Less disk.
- Less accidental preload risk.

## Priority 27: Use WebP/AVIF for Static Images

Convert `vani_idle.png`:

```bash
ffmpeg -i vani_idle.png -quality 75 vani_idle.webp
```

Update HTML:

```html
<img src="vani_idle.webp">
```

Expected impact:

- Smaller asset.
- Faster UI startup.

## Priority 28: Use Push-To-Talk Mode

Always-listening realtime voice consumes resources. Add push-to-talk:

```bash
export VANI_PUSH_TO_TALK=1
```

Behavior:

- Do not keep mic pipeline active.
- Start listening only when user presses a button/hotkey.
- Stop after command.

Expected impact:

- Big CPU/audio savings.
- Better battery.

Tradeoff:

- Less natural continuous conversation.

## Priority 29: Reduce Realtime Model Cost Locally

Current:

```python
REALTIME_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
```

Make configurable:

```python
REALTIME_MODEL = os.getenv("VANI_REALTIME_MODEL", "gemini-2.0-flash-live-001")
```

Use the lightest compatible model that works with your LiveKit plugin.

Expected impact:

- Less latency.
- Potentially less network/realtime overhead.

Note:

- This affects cloud/API usage more than local RAM/GPU, but shorter sessions reduce local pipeline load too.

## Priority 30: Stop Background Memory Loop Unless Needed

`memory_loop.py` and memory extraction can create background work.

Add:

```bash
export VANI_MEMORY_LOOP=0
```

Only run memory extraction when:

- Conversation ends.
- User says "yaad rakhna".
- App is idle and charging.

Expected impact:

- Less background CPU.
- Less model/tool calls.

## Priority 31: Avoid Importing Audio Libraries Until Talking Tom Mode

`vani_talking_tom.py` imports:

- `numpy`
- `sounddevice`
- `librosa`

This should never be imported during normal startup.

Current wrapper already imports it only inside `talking_tom_control()`. Keep it that way.

Do not add top-level imports of `vani_talking_tom` anywhere.

## Priority 32: Avoid PyAutoGUI at Startup

`keyboard_mouse_control.py` already lazy-loads `pyautogui` via `_ensure_pyautogui()`.

Keep this pattern. Do not add:

```python
import pyautogui
```

at module top-level.

Expected impact:

- Faster startup.
- Avoids display/screen probing until needed.

## Priority 33: Make Telethon Lazy

Telegram functions already import Telethon inside function bodies. Keep it there.

Do not import Telethon at module top-level.

Expected impact:

- Lower baseline RAM.

## Priority 34: Use `__pycache__` Cleanup for Disk Only

This does not reduce active RAM much, but cleans repo:

```bash
find . -type d -name __pycache__ -prune -exec rm -rf {} +
```

Only run if you are okay deleting generated cache files.

## Priority 35: Limit Browser Text Extraction

Current browser text extraction can read up to thousands of characters. Keep limits tight:

```python
document.body.innerText.slice(0, 1500)
```

instead of:

```python
slice(0, 3000)
```

Expected impact:

- Less AppleScript/browser data transfer.
- Faster screen context.

## Priority 36: Use One HTTP Client Pattern

The code uses `requests` in several places. That is fine, but import it lazily inside functions.

Do not import `requests` at top-level.

Expected impact:

- Lower import memory when only UI/server starts.

## Priority 37: Add Runtime Flags Summary

Recommended `.env` low-power profile:

```bash
VANI_LOW_POWER_UI=1
VANI_PREWARM_OLLAMA=0
VANI_OLLAMA_MODEL=qwen2.5:1.5b
VANI_SCREEN_USE_GEMINI=0
VANI_SCREEN_MAX_WIDTH=900
VANI_SCREEN_JPEG_QUALITY=55
VANI_NOISE_CANCEL=0
VANI_USE_SILERO=0
VANI_MEMORY_LOOP=0
VANI_MAX_DOC_UPLOAD_MB=6
VANI_DOC_CHARS=10000
VANI_UI_BROWSER=default
```

High quality profile:

```bash
VANI_LOW_POWER_UI=0
VANI_PREWARM_OLLAMA=1
VANI_OLLAMA_MODEL=qwen2.5:3b
VANI_SCREEN_USE_GEMINI=1
VANI_NOISE_CANCEL=1
VANI_USE_SILERO=1
VANI_MEMORY_LOOP=1
VANI_MAX_DOC_UPLOAD_MB=12
VANI_DOC_CHARS=18000
VANI_UI_BROWSER=chrome
```

## Priority 38: Suggested Implementation Order

Do these first for maximum RAM/GPU reduction:

1. Convert `listening.gif` to `listening.mp4` or `listening.webm`.
2. Add `VANI_LOW_POWER_UI=1` mode.
3. Change video preload from `auto` to `metadata` or `none`.
4. Disable Ollama warmup by default.
5. Use smaller Ollama model.
6. Make Silero and noise cancellation optional.
7. Cap document text at 10,000 chars.
8. Keep document feedback mostly text-panel only, voice summary only.
9. Add request semaphore to prevent parallel heavy requests.
10. Split `vani_reasoning.py` into smaller lazy modules.

## Priority 39: Quick Patch Checklist

### UI media

- [ ] Convert `listening.gif`.
- [ ] Replace GIF tag with video or static image.
- [ ] Set `preload="metadata"` or `preload="none"`.
- [ ] Add low power CSS.
- [ ] Disable opening video in low power mode.

### Backend

- [ ] Disable `_prewarm_ollama()` unless `VANI_PREWARM_OLLAMA=1`.
- [ ] Add request semaphore.
- [ ] Add env caps for document upload and document chars.
- [ ] Add `speak` short response for document endpoint.
- [ ] Keep `requests`, `Vision`, `PIL`, `pyautogui`, `Telethon`, `sounddevice` lazy.

### Voice

- [ ] Make realtime voice optional.
- [ ] Add push-to-talk.
- [ ] Make Silero optional.
- [ ] Make noise cancellation optional.
- [ ] Stop speaking long Markdown.

### Dependencies

- [ ] Create `requirements_core.txt`.
- [ ] Move optional ML/audio/dev packages to `requirements_full.txt`.
- [ ] Remove unused OpenTelemetry exporters if not needed.
- [ ] Remove unused `watchfiles`, `SQLAlchemy`, and unused LangChain packages if confirmed.

## Priority 40: Expected Results

If the top changes are implemented:

- UI GPU use should drop noticeably.
- Startup memory should drop because media and Ollama no longer preload.
- Idle memory should drop if realtime voice/push-to-talk mode is used.
- Document review should stop causing voice cutoffs.
- Browser/app responsiveness should improve.
- Disk usage can drop significantly after media conversion and dependency cleanup.

## Important Tradeoffs

Maximum savings require losing some polish:

- Static avatar instead of animated idle.
- Push-to-talk instead of always-listening.
- No noise cancellation unless needed.
- Smaller local model with slightly weaker reasoning.
- Short document context unless user asks for detailed review.

Best practical balance:

- Keep animated talking only.
- Static idle.
- Lazy Ollama.
- Smaller model.
- Voice summary only for long outputs.
- Full Markdown details in UI.

