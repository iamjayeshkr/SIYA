"""
vani/agents/learning_agent.py — Phase 3

Handles all learning-domain intents:
  fact storage, quiz scheduling, pronunciation learning,
  "remember this", "ask me later", teaching sessions.

Wraps:
  - memory/learning_memory.py   → store_learned, get_learned_block, get_quiz_items
  - reasoning/screen.py         → learn_this, learn_name (screen-to-memory path)
  - reasoning/teaching_tool.py  → teaching session management

Phase 3: delegates to _dispatch_intent for router-classified intents.
         Also exposes direct learning API for MemoryAgent / Planner coordination.
Future:  spaced repetition scheduling, topic-aware quiz injection mid-conversation,
         cross-session learning arc tracking.
"""

from __future__ import annotations
import logging

from vani.agents.base_agent import BaseAgent

logger = logging.getLogger("vani.agents.learning")


class LearningAgent(BaseAgent):
    name = "learning"
    description = (
        "Fact storage, quiz scheduling, pronunciation learning, "
        "teaching sessions, spaced repetition"
    )
    owned_tools = [
        "learn_this",
        "learn_name",
        "start_study_session",
        "end_study_session",
        "study_status",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route learning intents through the existing deterministic dispatcher.

        Intents handled:
          LEARN_THIS, LEARN_NAME, STUDY_*, QUIZ_*, TEACHING_*

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)

    # ── Direct learning API ───────────────────────────────────────────────────

    def get_quiz_due(self, limit: int = 3) -> list[dict]:
        """
        Returns quiz items that are due for review.
        Called by Phase 7 ReminderWorker to inject quizzes proactively.
        Returns empty list on failure — never raises.
        """
        try:
            from vani.memory.learning_memory import get_quiz_items
            return get_quiz_items(limit=limit)
        except Exception as e:
            logger.warning(f"[LEARNING] get_quiz_due failed: {e}")
            return []

    def get_learned_summary(self) -> str:
        """
        Returns a compact summary of everything Vani has learned.
        Injected into prompts to give Vani context without full memory dump.
        Returns empty string on failure.
        """
        try:
            from vani.memory.learning_memory import get_learned_block
            return get_learned_block()
        except Exception as e:
            logger.warning(f"[LEARNING] get_learned_summary failed: {e}")
            return ""

    def store_fact(self, content: str, raw: str = "", category: str = "knowledge") -> bool:
        """
        Stores a fact directly into learning memory.
        Returns True on success, False on failure — never raises.
        """
        try:
            from vani.memory.learning_memory import store_learned
            store_learned(content=content, raw=raw or content,
                          item_type="fact", category=category)
            return True
        except Exception as e:
            logger.warning(f"[LEARNING] store_fact failed: {e}")
            return False
