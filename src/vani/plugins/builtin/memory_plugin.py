"""
vani/plugins/builtin/memory_plugin.py

Conversation Memory Plugin — Vani's persistent memory store.

What it does:
  • Stores conversation summaries in a local JSON memory bank
  • Indexes by date, topic, and entities (people, places, tasks)
  • On "what did we talk about X" → searches the memory bank
  • Auto-saves every session (if enabled)
  • Memory file: ~/Library/Application Support/Vani/memory.json (Mac)
               : %APPDATA%/Vani/memory.json (Windows)

This is the lightweight alternative to Obsidian — no external app needed.
"""

from __future__ import annotations
import os
import re
import json
import sys
import logging
from datetime import datetime
from pathlib import Path

from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

logger = logging.getLogger("vani.plugins.memory")


def _memory_dir() -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "Vani"
    elif sys.platform == "win32":
        d = Path(os.environ.get("APPDATA", Path.home())) / "Vani"
    else:
        d = Path.home() / ".vani"
    d.mkdir(parents=True, exist_ok=True)
    return d


MEMORY_FILE = _memory_dir() / "memory.json"


def _load_memory() -> dict:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"sessions": [], "facts": {}, "version": 1}


def _save_memory(data: dict) -> None:
    MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class ConversationMemoryPlugin(VaniPlugin):
    name = "memory"
    icon = "💾"
    description = "Persistent memory — Vani remembers conversations across sessions."
    category = "memory"
    enabled = True   # ON by default — core feature
    triggers = [
        "yaad karo", "kya hua tha", "last time", "pehle kya baat ki thi",
        "remember", "memory", "what did we discuss", "past conversation",
        "save memory", "remember this fact", "mujhe yaad dilao",
        "hamare baat yaad hai", "recall", "history dikhao",
    ]

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        q = query.lower()

        # Search mode
        if any(x in q for x in ["kya hua", "what did", "recall", "history", "last time", "pehle"]):
            return await self._search_memory(query, context)

        # Save mode
        return await self._save_to_memory(query, context)

    async def _save_to_memory(self, query: str, context: PluginContext) -> PluginResult:
        data = _load_memory()
        recent = context.recent_messages[-20:]

        topics = self._extract_topics(recent)
        entities = self._extract_entities(recent)
        summary = self._build_summary(recent)

        session = {
            "id": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "topics": topics,
            "entities": entities,
            "summary": summary,
            "message_count": len(recent),
        }
        data["sessions"].append(session)

        # Extract and store facts (e.g. "my name is Rudra", "I work at X")
        facts = self._extract_facts(recent)
        data["facts"].update(facts)

        _save_memory(data)

        return PluginResult(
            success=True,
            message=f"💾 Memory saved! Topics: {', '.join(topics[:3]) if topics else 'General conversation'}. Main abhi se yeh remember karungi.",
            ui_payload={
                "session": session,
                "total_sessions": len(data["sessions"]),
                "facts_count": len(data["facts"]),
            }
        )

    async def _search_memory(self, query: str, context: PluginContext) -> PluginResult:
        data = _load_memory()
        sessions = data.get("sessions", [])

        if not sessions:
            return PluginResult(
                success=True,
                message="Abhi tak koi memory save nahi hai. Pehle baat karke save karo! 💾",
            )

        # Search by keyword
        keywords = re.findall(r'\b[a-z]{4,}\b', query.lower())
        scored = []
        for s in sessions:
            score = 0
            s_text = " ".join([
                s.get("summary", ""),
                " ".join(s.get("topics", [])),
                " ".join(s.get("entities", [])),
            ]).lower()
            for kw in keywords:
                if kw in s_text:
                    score += 1
            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: -x[0])
        top = [s for _, s in scored[:3]]

        if not top:
            # Return most recent
            top = sessions[-3:]
            message = f"Specific topic nahi mila, but last {len(top)} sessions yeh the:\n"
        else:
            message = f"Memory search results:\n"

        for s in top:
            message += f"• {s['date']} — {', '.join(s.get('topics', ['Chat']))}: {s.get('summary', '')[:80]}...\n"

        facts = data.get("facts", {})
        if facts:
            fact_str = ", ".join(f"{k}: {v}" for k, v in list(facts.items())[:5])
            message += f"\n📌 Known facts: {fact_str}"

        return PluginResult(
            success=True,
            message=message.strip(),
            ui_payload={"results": top, "facts": facts}
        )

    async def on_memory_save(self, messages: list[dict]) -> str | None:
        """Auto-save at session end."""
        if not messages:
            return None
        data = _load_memory()
        topics = self._extract_topics(messages)
        session = {
            "id": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "topics": topics,
            "entities": self._extract_entities(messages),
            "summary": self._build_summary(messages),
            "message_count": len(messages),
            "auto_saved": True,
        }
        data["sessions"].append(session)
        _save_memory(data)
        return f"💾 Memory auto-saved: {', '.join(topics[:2]) if topics else 'session'}"

    def _extract_topics(self, messages: list[dict]) -> list[str]:
        text = " ".join(m.get("content", "") for m in messages).lower()
        stop = {"the", "is", "a", "and", "to", "of", "in", "it", "you", "i", "we", "that",
                "me", "my", "this", "can", "vani", "ok", "yes", "no", "hi", "hai", "karo",
                "mein", "se", "ke", "ki", "ka", "aur", "nahi", "hain", "kya", "toh"}
        words = re.findall(r'\b[a-z]{4,}\b', text)
        freq: dict[str, int] = {}
        for w in words:
            if w not in stop:
                freq[w] = freq.get(w, 0) + 1
        return [w.title() for w in sorted(freq, key=lambda x: -freq[x])[:5]]

    def _extract_entities(self, messages: list[dict]) -> list[str]:
        text = " ".join(m.get("content", "") for m in messages)
        # Capitalized words (likely names/places)
        entities = re.findall(r'\b[A-Z][a-z]{2,15}\b', text)
        return list(dict.fromkeys(entities))[:10]

    def _extract_facts(self, messages: list[dict]) -> dict:
        """Extract user facts like name, job, location."""
        text = " ".join(m.get("content", "") for m in messages if m.get("role") == "user")
        facts = {}
        patterns = [
            (r'my name is ([A-Za-z]+)', 'name'),
            (r'i(?:\'m| am) ([A-Za-z\s]+?) (?:years old|yr)', 'age'),
            (r'i work (?:at|in|for) ([A-Za-z\s]+?)[\.,]', 'employer'),
            (r'i live in ([A-Za-z\s]+?)[\.,]', 'location'),
            (r'i(?:\'m| am) (?:a|an) ([A-Za-z\s]+?)[\.,]', 'profession'),
        ]
        for pattern, key in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                facts[key] = m.group(1).strip()
        return facts

    def _build_summary(self, messages: list[dict]) -> str:
        topics = self._extract_topics(messages)
        n = len(messages)
        topic_str = ", ".join(topics[:3]) if topics else "various topics"
        return f"Discussed {topic_str} in {n} messages."
