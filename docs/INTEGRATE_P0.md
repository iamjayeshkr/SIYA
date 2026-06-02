# Vani OS — P0 Integration Guide
# How to wire the new modules into your existing app.py / planner.py

## 1. Install dependencies

```bash
pip install -r requirements-p0.txt
```

---

## 2. app.py — startup wiring (add near the top)

```python
# ── P0: Logging + DB init ─────────────────────────────────────────────────
from vani.logging_config import configure_logging, get_logger
configure_logging()                          # must be first
log = get_logger("app")

from vani.secrets import get_gemini_key, get_livekit_url, get_livekit_token, get_ollama_host
from vani.db import init_db

# Replace os.getenv() calls with secrets module:
GEMINI_API_KEY = get_gemini_key()
LIVEKIT_URL    = get_livekit_url()
LIVEKIT_TOKEN  = get_livekit_token()
OLLAMA_HOST    = get_ollama_host()

async def startup():
    await init_db()          # creates tool_audit table if not exists
    log.info("vani_starting", version="p0")
```

---

## 3. planner.py — replace direct tool calls

### Before (anywhere you call a tool directly):
```python
result = await whatsapp_send(to=number, message=text)
```

### After:
```python
from vani.tool_runner import execute_tool
from vani.registry import TOOL_REGISTRY   # your existing registry dict

result = await execute_tool(
    name="whatsapp_send",
    fn=TOOL_REGISTRY["whatsapp_send"],
    args={"to": number, "message": text},
)
```

If you call tools via a generic dispatcher, wrap it once:
```python
# In your generic tool dispatcher:
async def dispatch_tool(name: str, args: dict):
    fn = TOOL_REGISTRY.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    return await execute_tool(name, fn, args)
```

---

## 4. router.py — add logging to intent classification

```python
from vani.logging_config import get_logger
import time

log = get_logger("router")

def classify(query: str) -> tuple[str, str]:
    """Returns (intent, method) where method is 'regex' or 'llm'."""
    start = time.monotonic()

    # ... your existing regex matching logic ...
    for pattern, intent in PATTERNS.items():
        if re.search(pattern, query, re.IGNORECASE):
            duration_ms = int((time.monotonic() - start) * 1000)
            log.info("intent_classified",
                     intent=intent,
                     method="regex",
                     duration_ms=duration_ms,
                     query_len=len(query))
            return intent, "regex"

    # Fell through to LLM
    duration_ms = int((time.monotonic() - start) * 1000)
    log.info("intent_classified",
             intent="llm_route",
             method="llm",
             duration_ms=duration_ms,
             query_len=len(query))
    return "llm_route", "llm"
```

---

## 5. One-time: migrate API keys to keychain

```bash
# Preview first (no writes):
python -m vani.migrate_secrets --dry-run

# Then actually migrate:
python -m vani.migrate_secrets

# Test Vani still starts:
python app.py

# Only after confirming it works — optionally delete .env:
# rm .env   (or just add .env to .gitignore)
```

---

## 6. Check tool audit data

```python
from vani.db import get_tool_history, get_tool_stats

# Recent calls to whatsapp_send:
rows = await get_tool_history(tool_name="whatsapp_send", limit=20)

# All failures in last run:
failures = await get_tool_history(only_failures=True, limit=50)

# Stats per tool over last 7 days:
stats = await get_tool_stats(days=7)
for s in stats:
    print(f"{s['tool_name']}: {s['call_count']} calls, "
          f"{s['success_rate']}% success, "
          f"{s['avg_duration_ms']}ms avg")
```

---

## What P0 gives you immediately

| Problem before P0          | Fixed by              |
|----------------------------|-----------------------|
| WhatsApp tool hangs Vani   | tool_runner timeouts  |
| Can't debug what failed    | structlog + audit DB  |
| API keys in .env (git risk)| keyring + migrate     |
| LLM prompt 2000+ tokens    | TokenJuice compress   |
| No execution history       | tool_audit SQLite     |
