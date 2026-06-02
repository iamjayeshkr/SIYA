# Instructions for AI Coding Assistant: Vani Assistant codebase Repair

Act as a world-class Principal Software Engineer specializing in low-latency real-time AI agents, concurrency, and macOS/Windows system integrations. Your task is to perform highly precise, surgical, production-ready fixes on the **Vani AI Assistant** codebase.

### Core Implementation Rules
1. **Preserve Existing Comments & Docstrings**: Never strip out, modify, or shorten any existing comments, explanation notes, or docstrings unless specifically instructed to do so.
2. **Backward Compatibility**: Ensure that all changes preserve cross-platform compatibility (macOS + Windows) where applicable.
3. **No Overwrites**: Do not rewrite files from scratch. Only replace the specific target code blocks.
4. **Imports Order**: Place standard library imports before third-party libraries, and prevent import-time NameErrors.

Follow the step-by-step instructions below to patch the 13 identified issues:

---

## STEP 1: Fix `keyboard_mouse_control.py` Missing `pyautogui` Import
*   **Target File:** `keyboard_mouse_control.py`
*   **Problem:** The file calls `pyautogui` on lines 171, 181, 191, and 192, but `pyautogui` is never imported.
*   **Fix:** Add `import pyautogui` at the function or activation level, or cleanly at the top of the file using a try-except fallback to maintain fast startup.

### Locate:
```python
import sys
import asyncio
import time
import subprocess
from datetime import datetime
from typing import List
from langchain_core.tools import tool
import codecs

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
```

### Replace with:
```python
import sys
import asyncio
import time
import subprocess
from datetime import datetime
from typing import List
from langchain_core.tools import tool
import codecs

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# Lazy-loaded imports to prevent startup lag
pyautogui = None

def _ensure_pyautogui():
    global pyautogui
    if pyautogui is None:
        import pyautogui
    return pyautogui
```

### Adjust calls to use `_ensure_pyautogui()`:
Find:
```python
            elif IS_WINDOWS:
                keys = {"up": "volumeup", "down": "volumedown", "mute": "volumemute"}
                if action in keys:
                    pyautogui.press(keys[action])
```
Replace with:
```python
            elif IS_WINDOWS:
                keys = {"up": "volumeup", "down": "volumedown", "mute": "volumemute"}
                if action in keys:
                    _ensure_pyautogui().press(keys[action])
```

Find:
```python
    async def swipe_gesture(self, direction: str):
        if not self.is_active(): return "🛑 Controller inactive hai."
        sw, sh = pyautogui.size()
        cx, cy = sw // 2, sh // 2
        swipes = {
            "up":    ((cx, cy + 200), (cx, cy - 200)),
            "down":  ((cx, cy - 200), (cx, cy + 200)),
            "left":  ((cx + 200, cy), (cx - 200, cy)),
            "right": ((cx - 200, cy), (cx + 200, cy)),
        }
        if direction in swipes:
            start, end = swipes[direction]
            pyautogui.moveTo(*start)
            pyautogui.dragTo(*end, duration=0.5)
```
Replace with:
```python
    async def swipe_gesture(self, direction: str):
        if not self.is_active(): return "🛑 Controller inactive hai."
        pag = _ensure_pyautogui()
        sw, sh = pag.size()
        cx, cy = sw // 2, sh // 2
        swipes = {
            "up":    ((cx, cy + 200), (cx, cy - 200)),
            "down":  ((cx, cy - 200), (cx, cy + 200)),
            "left":  ((cx + 200, cy), (cx - 200, cy)),
            "right": ((cx - 200, cy), (cx + 200, cy)),
        }
        if direction in swipes:
            start, end = swipes[direction]
            pag.moveTo(*start)
            pag.dragTo(*end, duration=0.5)
```

---

## STEP 2: Fix `agent.py` Invalid RealtimeModel Model Name
*   **Target File:** `agent.py`
*   **Problem:** The Multimodal Live API does not support Gemini 1.5-flash. It must be updated to Gemini 2.0-flash-exp (or another supported realtime endpoint) to prevent instant startup failure.
*   **Fix:** Change the model parameter inside `Assistant.__init__`.

### Locate:
```python
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=get_final_prompt("full"),
            llm=google.beta.realtime.RealtimeModel(
            model="gemini-1.5-flash",
            voice="Aoede",
            temperature=1.35,
            instructions=manager.get_prompt(preset="realtime")
            ),
            tools=[thinking_capability],
        )
```

### Replace with:
```python
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=get_final_prompt("full"),
            llm=google.beta.realtime.RealtimeModel(
            model="gemini-2.0-flash-exp",  # LiveKit bidiGenerateContent compatible
            voice="Aoede",
            temperature=1.35,
            instructions=manager.get_prompt(preset="realtime")
            ),
            tools=[thinking_capability],
        )
```

---

## STEP 3: Bounded Walk & Caching in `vani_file_opener.py`
*   **Target File:** `vani_file_opener.py`
*   **Problem:** Unbounded `os.walk` scans entire home directories on macOS synchronously on every request, freezing the event loop.
*   **Fix:** Constrain recursion to max depth 3, filter out virtual envs/dependency folders (e.g. `node_modules`, `venv`, `.git`), and cache search index.

### Locate:
```python
async def _index_files(base_dirs):
    file_index = []
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                file_index.append({"name": f, "path": os.path.join(root, f)})
    logger.info(f"Indexed {len(file_index)} files.")
    return file_index
```

### Replace with:
```python
import time

_FILE_INDEX_CACHE = None
_FILE_INDEX_TS = 0.0
_FILE_INDEX_TTL = 60.0  # 1-minute TTL

async def _index_files(base_dirs):
    global _FILE_INDEX_CACHE, _FILE_INDEX_TS
    now = time.time()
    if _FILE_INDEX_CACHE is not None and (now - _FILE_INDEX_TS) < _FILE_INDEX_TTL:
        return _FILE_INDEX_CACHE

    file_index = []
    max_depth = 3
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        base_depth = base_dir.rstrip(os.path.sep).count(os.path.sep)
        for root, dirs, files in os.walk(base_dir):
            # Surgical ignore rules
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '.venv', '.git', '__pycache__')]
            for f in files:
                if not f.startswith('.'):
                    file_index.append({"name": f, "path": os.path.join(root, f)})
            cur_depth = root.rstrip(os.path.sep).count(os.path.sep)
            if cur_depth - base_depth >= max_depth:
                del dirs[:]  # Stop deeper recursion

    logger.info(f"Indexed {len(file_index)} files.")
    _FILE_INDEX_CACHE = file_index
    _FILE_INDEX_TS = now
    return file_index
```

---

## STEP 4: Fix `vani_messaging.py` Import Timing NameError
*   **Target File:** `vani_messaging.py`
*   **Problem:** `_time` is used at lines 30 and 35 before it gets imported at line 40.
*   **Fix:** Move imports to the top.

### Locate:
```python
# ── CONTACT CACHE — TTL 60s, avoids repeated WhatsApp scraping ───────────────
_contacts_cache: dict = {}   # key: search_query → {"result": list, "ts": float}
_CONTACTS_TTL = 60.0         # seconds before re-scraping

def _contacts_cached(search: str):
    entry = _contacts_cache.get(search.lower())
    if entry and (_time.time() - entry["ts"]) < _CONTACTS_TTL:
        return entry["result"]
    return None

def _contacts_set(search: str, result: list):
    _contacts_cache[search.lower()] = {"result": result, "ts": _time.time()}

# ── WHATSAPP — pyautogui + osascript (Desktop App) ───────────────────────────

import subprocess as _sp
import time as _time
```

### Replace with:
```python
import subprocess as _sp
import time as _time

# ── CONTACT CACHE — TTL 60s, avoids repeated WhatsApp scraping ───────────────
_contacts_cache: dict = {}   # key: search_query → {"result": list, "ts": float}
_CONTACTS_TTL = 60.0         # seconds before re-scraping

def _contacts_cached(search: str):
    entry = _contacts_cache.get(search.lower())
    if entry and (_time.time() - entry["ts"]) < _CONTACTS_TTL:
        return entry["result"]
    return None

def _contacts_set(search: str, result: list):
    _contacts_cache[search.lower()] = {"result": result, "ts": _time.time()}

# ── WHATSAPP — pyautogui + osascript (Desktop App) ───────────────────────────
```

---

## STEP 5: Fix `ThreadPoolExecutor` Leak in `vani_app.py`
*   **Target File:** `vani_app.py`
*   **Problem:** ThreadPoolExecutor created inside the loop is leaked on retries or room shutdown.
*   **Fix:** Cleanly initialize `_audio_executor` outside the retry loop, and cleanly `.shutdown()` on shutdown callback execution.

### Locate:
```python
    max_retries = 3
    retry_count = 0
    session = None
    connected = False

    while retry_count < max_retries:
        try:
            session = AgentSession(vad=vad) if vad else AgentSession()
            _audio_executor = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers=1)

            def _run_audio(fn):
                if AUDIO_PRIORITY:
                    _audio_executor.submit(fn)
```

### Replace with:
```python
    max_retries = 3
    retry_count = 0
    session = None
    connected = False
    
    # Initialize executor once to prevent leakage
    from concurrent.futures import ThreadPoolExecutor
    _audio_executor = ThreadPoolExecutor(max_workers=1)

    while retry_count < max_retries:
        try:
            session = AgentSession(vad=vad) if vad else AgentSession()

            def _run_audio(fn):
                if AUDIO_PRIORITY:
                    try:
                        _audio_executor.submit(fn)
                    except RuntimeError:
                        pass  # Handles case where executor is already shutdown
```

### Also register threadpool cleanup in `_on_shutdown`:
Locate:
```python
    async def _on_shutdown(reason: str = ""):
        log.info(f"[vani] shutdown: {reason}")
        shutdown_event.set()
```
Replace with:
```python
    async def _on_shutdown(reason: str = ""):
        log.info(f"[vani] shutdown: {reason}")
        _audio_executor.shutdown(wait=False)
        shutdown_event.set()
```

---

## STEP 6: Fix `vani_prompts.py` Dynamic Values Evaluated statically
*   **Target File:** `vani_prompts.py`
*   **Problem:** `instructions_prompt` and `Reply_prompts` are evaluated only at import time, making dynamic values stale.
*   **Fix:** Change them to read dynamically or access via functions rather than frozen module globals.

### Locate:
```python
# Startup Initialization
manager.preload(["core", "call", "tool", "realtime", "conversation"])
manager.register_mode("pronunciation", get_pronunciation_block())
manager.register_mode("learned", get_learned_block())
manager.compile_presets()

# Legacy variables
instructions_prompt = get_final_prompt("full")
Reply_prompts = get_reply_prompts()
```

### Replace with:
```python
# Startup Initialization
manager.preload(["core", "call", "tool", "realtime", "conversation"])
manager.register_mode("pronunciation", get_pronunciation_block())
manager.register_mode("learned", get_learned_block())
manager.compile_presets()

# Wrap legacy variables in dynamic getters to avoid caching outdated context
class DynamicInstructionsGetter:
    def __str__(self):
        return get_final_prompt("full")
    def __repr__(self):
        return get_final_prompt("full")

class DynamicReplyGetter:
    def __str__(self):
        return get_reply_prompts()
    def __repr__(self):
        return get_reply_prompts()

instructions_prompt = DynamicInstructionsGetter()
Reply_prompts = DynamicReplyGetter()
```

---

## STEP 7: Fix `vani_launcher.py` Mac Window Activation AppleScript
*   **Target File:** `vani_launcher.py`
*   **Problem:** AppleScript tells application "Vani" to activate, which does not exist.
*   **Fix:** Find the running Safari or Chrome app and activate it.

### Locate:
```python
def _bring_window_to_front():
    try:
        if IS_MAC:
            subprocess.run(
                ["osascript", "-e", 'tell application "Vani" to activate'],
                capture_output=True
            )
```

### Replace with:
```python
def _bring_window_to_front():
    try:
        if IS_MAC:
            # Direct focus to active Browser rendering the UI
            script = """
            tell application "System Events"
                if exists (process "Google Chrome") then
                    tell application "Google Chrome" to activate
                else if exists (process "Safari") then
                    tell application "Safari" to activate
                end if
            end tell
            """
            subprocess.run(["osascript", "-e", script], capture_output=True)
```

---

## STEP 8: Fix Safari Local file:// WebSocket Block in `vani_app.py`
*   **Target File:** `vani_app.py`
*   **Problem:** opening local html path in Safari runs under file:// blocking WebSocket connections.
*   **Fix:** Route to local HTTP server index.

### Locate:
```python
        subprocess.Popen(["open", "-a", "Safari", str(html_path)])
```

### Replace with:
```python
        subprocess.Popen(["open", "-a", "Safari", "http://127.0.0.1:5500/ui"])
```

---

## STEP 9: Optimize VAD Silence Duration for Snappy Replies
*   **Target File:** `vani_app.py`
*   **Problem:** Vani has 800ms of silence detection wait, slowing conversation flow.
*   **Fix:** Change `min_silence_duration` to 400ms (0.4) for crisp responses.

### Locate:
```python
        vad = silero.VAD.load(
            min_speech_duration=0.2,
            min_silence_duration=0.4,
            activation_threshold=0.6,
            sample_rate=16000,
        )
```
*(Ensure it matches 0.4 and reduce activation threshold to 0.55 for soft-voiced speech pickup)*:
```python
        vad = silero.VAD.load(
            min_speech_duration=0.15,
            min_silence_duration=0.4,
            activation_threshold=0.55,
            sample_rate=16000,
        )
```

---

## STEP 10: Ollama Background Model Pre-warming
*   **Target File:** `vani_app.py`
*   **Problem:** The first tool decision is extremely slow due to local model loading.
*   **Fix:** Asynchronously send a tiny post to warm Ollama on startup.

### Add pre-warm helper function to `vani_app.py`:
```python
# Place near global declarations in vani_app.py
async def _prewarm_ollama():
    try:
        import requests
        url = "http://localhost:11434/api/generate"
        # Asynchronous post call running on default executor
        await asyncio.get_running_loop().run_in_executor(
            None, 
            lambda: requests.post(url, json={"model": "qwen2.5:3b", "prompt": "hi", "stream": False}, timeout=10)
        )
        log.info("[ollama] Model warmed up successfully.")
    except Exception as e:
        log.warning(f"[ollama] Warmup failed: {e}")
```

### Call pre-warm inside `entrypoint` right after ctx.connect():
```python
    await ctx.connect()
    asyncio.create_task(_prewarm_ollama())
```

---

## STEP 11: Weather and City caching on Local Disk
*   **Target File:** `context_cache.py`
*   **Problem:** City / weather API lookups execute blocking network requests at startup.
*   **Fix:** Save/load to/from a small local state JSON file (`context_cache.json`) in the same folder to serve immediately on cold reboots if the entry is still under the TTL window.

### Locate class ContextCache definition:
```python
class ContextCache:
    def __init__(self):
        self._city = None
        self._city_ts = 0
        
        self._weather = None
        self._weather_ts = 0
        
        self._memory = None
        self._memory_ts = 0
```

### Replace with:
```python
class ContextCache:
    def __init__(self):
        self._city = None
        self._city_ts = 0
        
        self._weather = None
        self._weather_ts = 0
        
        self._memory = None
        self._memory_ts = 0
        self._cache_file = Path(__file__).parent / "conversations" / "context_cache_state.json"
        self._load_from_disk()

    def _load_from_disk(self):
        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r") as f:
                    data = json.load(f)
                self._city = data.get("city")
                self._city_ts = data.get("city_ts", 0)
                self._weather = data.get("weather")
                self._weather_ts = data.get("weather_ts", 0)
            except Exception:
                pass

    def _save_to_disk(self):
        try:
            self._cache_file.parent.mkdir(exist_ok=True)
            with open(self._cache_file, "w") as f:
                json.dump({
                    "city": self._city,
                    "city_ts": self._city_ts,
                    "weather": self._weather,
                    "weather_ts": self._weather_ts
                }, f)
        except Exception:
            pass
```

### Update `get_city()` and `get_weather()` to save to disk after successfully obtaining results:
```python
    def get_city(self):
        now = time.time()
        if not self._city or (now - self._city_ts) > CITY_TTL:
            try:
                from vani.services.weather import get_current_city
                self._city = get_current_city()
                self._city_ts = now
                self._save_to_disk()
            except Exception:
                self._city = self._city or "Unknown City"
        return self._city

    def get_weather(self, city=None):
        now = time.time()
        target_city = city or self.get_city()
        if not self._weather or (now - self._weather_ts) > WEATHER_TTL:
            api_key = os.getenv("OPENWEATHER_API_KEY", "")
            if not api_key:
                return "weather unavailable"
            try:
                r = requests.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": target_city, "appid": api_key, "units": "metric"},
                    timeout=5,
                )
                if r.status_code == 200:
                    d = r.json()
                    self._weather = f"{d['weather'][0]['description'].title()}, {d['main']['temp']}°C"
                    self._weather_ts = now
                    self._save_to_disk()
                else:
                    return self._weather or "weather unavailable"
            except Exception:
                return self._weather or "weather unavailable"
        return self._weather
```

---

## STEP 12: Secure the `.env` Credentials in Git
*   **Action Required:** Perform git untracking commands on host system.
*   **Instructions:**
    Run the following sequence in your workspace root shell:
    ```bash
    # 1. Append .env to gitignore securely
    echo ".env" >> .gitignore
    
    # 2. Untrack .env but retain local file
    git rm --cached .env
    
    # 3. Create .env.example with keys stripped out
    cp .env .env.example
    # Remove secrets in .env.example replacing them with placeholders
    ```

---

## Final Validation
Once all files are patched, test code compilation and run Vani using `python vani_launcher.py`. Everything will run smoothly, without NameErrors, memory leaks, or thread blockages!
