"""
working_memory.py - compact persistent memory for useful continuity.

This is deliberately not full conversation history. It stores small durable
signals: pending reminders, active topics, repeated songs/searches, and files
the user appears to be working on.
"""

import json
import os
import re
import uuid
import asyncio
from datetime import datetime
from pathlib import Path

from vani.config import PROJECT_ROOT

try:
    from vani.memory.human_memory import (
        get_permanent_memory_block,
        remember_permanent,
        search_permanent_memory,
    )
except Exception:
    def get_permanent_memory_block(*_, **__): return ""
    def remember_permanent(*_, **__): return {}
    def search_permanent_memory(*_, **__): return []

_MEMORY_FILE = PROJECT_ROOT / "conversations" / "vani_working_memory.json"
_MAX_REMINDERS = 25
_MAX_TOPICS = 12
_MAX_ITEMS = 20

_state = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_state() -> dict:
    return {
        "version": 1,
        "updated": _now(),
        "pending_reminders": [],
        "preferences": [],
        "frequent_songs": [],
        "frequent_searches": [],
        "working_files": [],
        "active_topics": [],
    }


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    _MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _MEMORY_FILE.exists():
        try:
            with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _state = {**_default_state(), **data}
                return _state
        except Exception:
            pass
    _state = _default_state()
    return _state


def _save():
    data = _load()
    data["updated"] = _now()
    tmp = str(_MEMORY_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _MEMORY_FILE)
    except Exception as e:
        import logging as _logging
        _logging.getLogger(__name__).error(f"[WORKING_MEMORY] Save failed: {e}")
        try: os.unlink(tmp)
        except OSError: pass


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _upsert_capped(bucket: str, text: str, meta: dict | None = None, limit: int = _MAX_ITEMS):
    text = _norm(text)
    if not text:
        return
    data = _load()
    items = data.setdefault(bucket, [])
    key = text.lower()
    for item in items:
        if item.get("text", "").lower() == key:
            item["count"] = int(item.get("count", 1)) + 1
            item["last_seen"] = _now()
            if meta:
                item.update(meta)
            break
    else:
        item = {
            "id": uuid.uuid4().hex[:8],
            "text": text[:240],
            "count": 1,
            "created": _now(),
            "last_seen": _now(),
        }
        if meta:
            item.update(meta)
        items.insert(0, item)
    items.sort(key=lambda x: (int(x.get("count", 1)), x.get("last_seen", "")), reverse=True)
    del items[limit:]
    _save()


def add_reminder(text: str, raw: str = ""):
    _upsert_capped(
        "pending_reminders",
        text,
        {"raw": raw[:300], "status": "pending"},
        _MAX_REMINDERS,
    )


def mark_reminder_done(text: str) -> bool:
    data = _load()
    q = text.lower()
    changed = False
    for item in data.get("pending_reminders", []):
        if q in item.get("text", "").lower() or item.get("text", "").lower() in q:
            item["status"] = "done"
            item["done_at"] = _now()
            changed = True
    if changed:
        _save()
    return changed


def record_preference(text: str):
    _upsert_capped("preferences", text, limit=_MAX_ITEMS)
    remember_permanent(text, raw=text, kind="preference", category="preference", importance=8)


def record_song(song: str):
    _upsert_capped("frequent_songs", song, limit=_MAX_ITEMS)


def record_search(query: str):
    _upsert_capped("frequent_searches", query, limit=_MAX_ITEMS)


def record_working_file(path_or_name: str):
    _upsert_capped("working_files", path_or_name, limit=_MAX_ITEMS)


def record_topic(topic: str):
    _upsert_capped("active_topics", topic, limit=_MAX_TOPICS)


def _extract_after_patterns(query: str, patterns: list[str]) -> str:
    q = _norm(query)
    low = q.lower()
    for pattern in patterns:
        m = re.search(pattern, low, flags=re.IGNORECASE)
        if m:
            start = m.end()
            return q[start:].strip(" :-.,")
    return ""


def record_user_signal(query: str):
    """Cheap heuristic extraction from a user command."""
    q = _norm(query)
    low = q.lower()
    if not q:
        return

    if any(p in low for p in [
        "kya reminder", "what reminder", "which reminder", "pending reminder",
        "kya yaad", "what do you remember", "last topic", "working on kya",
    ]):
        return

    if re.search(r"\b(done|completed|ho gaya|kar liya|finished)\b", low):
        if mark_reminder_done(q):
            return

    if any(p in low for p in ["remind", "reminder", "yaad dil", "yaad rakh", "don't forget", "dont forget"]):
        reminder = _extract_after_patterns(q, [
            r"\bset\s+(?:a\s+)?reminder\s+(?:for|to|of)?\s*",
            r"\bremind\s+me\s+(?:to|for|of)?\s*",
            r"\byaad\s+(?:dilana|dila|rakhna|rakh)\s*(?:ki|ke|to)?\s*",
        ]) or q
        add_reminder(reminder, raw=q)
        if any(w in low for w in ["learn", "learning", "java", "python", "topic", "course"]):
            record_topic(reminder)

    if any(p in low for p in ["favorite", "favourite", "favouriate", "pasand", "regular", "usually", "often"]):
        record_preference(q)

    song = _extract_after_patterns(q, [
        r"\bplay\s+",
        r"\bbajao\s+",
        r"\bgana\s+",
        r"\bsong\s+",
    ])
    if song and any(w in low for w in ["song", "gana", "music", "youtube", "bajao", "play"]):
        record_song(song)

    search = _extract_after_patterns(q, [
        r"\bgoogle\s+",
        r"\bsearch\s+",
        r"\bfind\s+",
        r"\blook\s+up\s+",
    ])
    if search:
        record_search(search)

    for match in re.findall(r"(?:(?:/|~\/|[A-Za-z]:\\)[^\s]+|[\w.-]+\.(?:py|js|ts|java|html|css|md|txt|json|pdf|docx))", q):
        record_working_file(match)

    topic = _extract_after_patterns(q, [
        r"\b(?:discuss|discussion|topic|learning|learn|study|padh)\s+(?:about|of|on)?\s*",
        r"\b(?:kaam|work)\s+(?:kar raha|kar rha|on)?\s*",
    ])
    if topic:
        record_topic(topic)


def record_tool_signal(tool_name: str, args) -> None:
    if isinstance(args, dict):
        if tool_name == "open_youtube_and_play":
            record_song(str(args.get("song_or_query", "")).strip())
        elif tool_name == "google_search":
            record_search(str(args.get("query", "")).strip())
        elif tool_name in {"code_assist", "folder_file"}:
            raw = " ".join(str(v) for v in args.values())
            record_user_signal(raw)


async def answer_memory_query(query: str) -> str:
    low = (query or "").lower()
    if not any(p in low for p in ["reminder", "yaad", "remember", "memory", "topic", "working on", "kaam"]):
        return ""
    data = _load()
    lines = []
    pending = [r for r in data.get("pending_reminders", []) if r.get("status", "pending") == "pending"]
    if pending:
        lines.append("Pending reminders:")
        lines.extend(f"- {r['text']}" for r in pending[:8])
    if data.get("active_topics"):
        lines.append("Recent topics:")
        lines.extend(f"- {t['text']}" for t in data["active_topics"][:5])
    if data.get("working_files"):
        lines.append("Recent working files:")
        lines.extend(f"- {f['text']}" for f in data["working_files"][:5])
    permanent = search_permanent_memory(query, limit=6)
    if permanent:
        lines.append("Permanent memory:")
        lines.extend(f"- {m['content']}" for m in permanent[:6] if m.get("content"))

    # SQLite vector store local semantic memory search
    try:
        from vani.memory.vector_store import SQLiteVectorStore
        store = SQLiteVectorStore()
        semantic_matches = await store.search_memory(query, limit=5)
        if semantic_matches:
            lines.append("Semantic memories (local search):")
            lines.extend(f"- {m['content']} (similarity: {m['score']:.2f})" for m in semantic_matches)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to query semantic vector store: {e}")

    return "\n".join(lines).strip()


async def extract_and_store_facts(query: str) -> None:
    """Mem0-style local background fact extraction using Ollama."""
    if not query.strip():
        return

    from vani.memory.vector_store import SQLiteVectorStore
    store = SQLiteVectorStore()

    prompt = f"""You are a memory processor. Given the user's message, identify if it contains any facts about the user, their preferences, reminders, or permanent information.
Extract these facts as clear sentences.
Message: "{query}"

Respond ONLY with a JSON list of strings, e.g. ["User's favorite stock is AAPL", "User has a meeting tomorrow at 3 PM"].
If no facts are present, respond with []. No explanation, no markdown fences."""

    try:
        from vani.reasoning.shared import OLLAMA_URL, OLLAMA_MODEL
        import requests
        
        def _call_ollama():
            try:
                r = requests.post(OLLAMA_URL, json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, timeout=10)
                if r.status_code == 200:
                    resp_text = r.json().get("response", "").strip()
                    for fence in ["```json", "```"]:
                        resp_text = resp_text.replace(fence, "")
                    resp_text = resp_text.strip()
                    match = re.search(r"(\[.*\])", resp_text, re.DOTALL)
                    if match:
                        return json.loads(match.group(1))
            except Exception:
                pass
            return []

        loop = asyncio.get_running_loop()
        facts = await loop.run_in_executor(None, _call_ollama)

        for fact in facts:
            if isinstance(fact, str) and fact.strip():
                await store.add_memory(fact.strip(), {"source": "extracted_fact"})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Fact extraction failed: {e}")



def get_working_memory_block() -> str:
    data = _load()
    sections = []
    pending = [r for r in data.get("pending_reminders", []) if r.get("status", "pending") == "pending"]
    if pending:
        sections.append("Pending reminders: " + "; ".join(r["text"][:90] for r in pending[:5]))
    if data.get("preferences"):
        sections.append("Preferences/habits: " + "; ".join(p["text"][:90] for p in data["preferences"][:5]))
    if data.get("frequent_songs"):
        sections.append("Frequent songs/searches: " + "; ".join(s["text"][:70] for s in data["frequent_songs"][:5]))
    if data.get("working_files"):
        sections.append("Recent working files: " + "; ".join(f["text"][:90] for f in data["working_files"][:5]))
    if data.get("active_topics"):
        sections.append("Active topics: " + "; ".join(t["text"][:90] for t in data["active_topics"][:5]))
    permanent = get_permanent_memory_block(limit=10)
    if permanent:
        sections.append(permanent.strip())
    if not sections:
        return ""
    return (
        "\n\nCOMPACT WORKING MEMORY (persistent, small; use naturally, do not mention unless relevant):\n"
        + "\n".join(f"- {line}" for line in sections)
    )


def get_startup_memory_brief() -> str:
    data = _load()
    pending = [r for r in data.get("pending_reminders", []) if r.get("status", "pending") == "pending"]
    topic = data.get("active_topics", [])[:1]
    parts = []
    if pending:
        parts.append(f"Reminder yaad hai: {pending[0]['text']}")
    if topic:
        parts.append(f"Last topic: {topic[0]['text']}")
    return ". ".join(parts)[:260]


def clear_working_memory() -> None:
    global _state
    _state = _default_state()
    _save()

