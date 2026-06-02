"""
vani/agents/memory_agent.py — Phase 3

Handles all memory-domain intents and provides a unified interface
for reading/writing across all of VANI's memory layers.

Memory layers owned:
  - working_memory.py    → reminders, active topics, repeated songs/searches
  - human_memory.py      → permanent SQLite + document memory (PDFs, notes)
  - learning_memory.py   → facts, preferences, quiz items (owned by LearningAgent)
  - context_cache.py     → city/weather/short-session cache

This agent does NOT own learning_memory — LearningAgent handles that.
MemoryAgent is the general-purpose layer: retrieve context, store preferences,
answer "do you remember when..." queries.

Phase 3: delegates to _dispatch_intent for router-classified intents.
         Also exposes direct memory API for other agents to call.
Future:  add relationship_memory integration (Phase 6), semantic search across
         all memory layers, proactive memory injection into Planner context.
"""

from __future__ import annotations
import logging

from vani.agents.base_agent import BaseAgent

logger = logging.getLogger("vani.agents.memory")


class MemoryAgent(BaseAgent):
    name = "memory"
    description = (
        "Working memory, permanent memory, document context, "
        "reminders, preferences, conversation history"
    )
    owned_tools: list[str] = []  # memory is accessed via direct API, not _dispatch_intent

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route memory intents.

        For router-classified intents (LEARN_THIS, LEARN_NAME, REMINDER_*):
          delegates to _dispatch_intent.

        For raw queries asking about memory ("do you remember X"):
          reads from permanent memory and returns the relevant block.

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)

    # ── Direct memory API (called by other agents / planner) ─────────────────

    def get_working_context(self) -> str:
        """
        Returns the current working memory block as a formatted string.
        Used by Planner to inject fresh context into each planning cycle.
        """
        try:
            from vani.memory.working_memory import get_working_memory_block
            return get_working_memory_block()
        except Exception as e:
            logger.warning(f"[MEMORY] get_working_context failed: {e}")
            return ""

    def get_permanent_context(self, query: str = "") -> str:
        """
        Returns the permanent memory block, optionally filtered by query.
        Used by Planner for long-term preference injection.
        """
        try:
            from vani.memory.human_memory import (
                get_permanent_memory_block,
                search_permanent_memory,
            )
            if query:
                results = search_permanent_memory(query)
                if results:
                    return "\n".join(str(r) for r in results[:5])
            return get_permanent_memory_block()
        except Exception as e:
            logger.warning(f"[MEMORY] get_permanent_context failed: {e}")
            return ""

    def get_full_context(self) -> str:
        """
        Unified memory context: working + permanent combined.
        Called by MemoryAgent and future Phase 6 get_full_context() in memory/__init__.py.
        Returns empty string on any failure — never raises.
        """
        parts: list[str] = []
        try:
            wm = self.get_working_context()
            if wm:
                parts.append(f"[Working Memory]\n{wm}")
        except Exception:
            pass
        try:
            pm = self.get_permanent_context()
            if pm:
                parts.append(f"[Permanent Memory]\n{pm}")
        except Exception:
            pass
        return "\n\n".join(parts)

    def store_preference(self, content: str, raw: str = "") -> bool:
        """
        Stores a user preference into learning_memory (fact/preference type).
        Returns True on success, False on failure — never raises.
        """
        try:
            from vani.memory.learning_memory import store_learned
            store_learned(content=content, raw=raw or content, item_type="preference")
            return True
        except Exception as e:
            logger.warning(f"[MEMORY] store_preference failed: {e}")
            return False
