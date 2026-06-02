# Vani OS — P1 Integration Guide
# Semantic memory: sqlite-vec + nomic-embed-text

## 0. Prerequisites

```bash
# Pull the embedding model (one time, ~270MB)
ollama pull nomic-embed-text

# Install P1 deps
pip install -r requirements-p1.txt
```

---

## 1. app.py — initialise the memory stack at startup

```python
from vani.memory_semantic import SemanticMemory
from vani.memory_router import MemoryRouter
from vani.memory_ingestion import MemoryIngestion

# Your existing permanent memory object (whatever class you use)
# from memory.permanent_memory import PermanentMemory
# permanent_mem = PermanentMemory()

semantic_mem = SemanticMemory()
memory_router = MemoryRouter(
    semantic=semantic_mem,
    permanent=permanent_mem,  # or None if not wiring yet
)
ingestion = MemoryIngestion(router=memory_router)

async def startup():
    await init_db()           # from P0
    await semantic_mem.init() # creates tables + loads sqlite-vec
    log.info("memory_stack_ready")
```

---

## 2. planner.py — inject memory context into every LLM prompt

```python
# Before building your Ollama prompt, get memory context:
memory_context = await memory_router.get_context(query, max_tokens=600)

# Inject into prompt:
system_prompt = f"""You are Vani, Rudra's personal AI assistant.

{memory_context}

Respond naturally in the same language Rudra uses."""

# Then call Ollama as usual with system_prompt
```

---

## 3. planner.py — store memories after each turn

```python
# After the assistant responds, ingest the turn asynchronously:
asyncio.create_task(
    ingestion.ingest_turn(
        user_message=user_query,
        assistant_message=assistant_response,
    )
)
# fire-and-forget — never blocks the response
```

---

## 4. Add a "remember this" tool

```python
# In your tool registry, add:
async def tool_remember(text: str) -> str:
    await ingestion.ingest_manual(text, importance=2.0)
    return f"Remembered: {text}"

TOOL_REGISTRY["remember"] = tool_remember
```

Now Rudra can say: *"Remember that I prefer dark mode"* and it's stored permanently.

---

## 5. Add a "what do you remember about X" tool

```python
async def tool_recall(query: str) -> str:
    results = await memory_router.search(query, top_k=5)
    if not results:
        return "I don't have any memories about that."
    lines = [f"• ({r['score']:.2f}) {r['text']}" for r in results]
    return "Here's what I remember:\n" + "\n".join(lines)

TOOL_REGISTRY["recall"] = tool_recall
```

---

## 6. Check memory stats

```python
stats = await memory_router.stats()
# {"semantic_memories": 247, "working_entries": 3, "has_permanent": True}
```

---

## What changes immediately after P1

| Before P1 | After P1 |
|-----------|----------|
| Memory search is keyword-only | Full semantic search |
| Forgets context after session | Weeks/months of context |
| "What did we decide?" fails | Works across any timeframe |
| Preferences reset each session | Persisted and searchable |
| No "remember this" command | Built-in tool |
| LLM has no personal context | Relevant memories injected automatically |
