"""
vani/agents/base_agent.py — Phase 3

Abstract base class for every VANI specialized agent.

Contract:
  - Agents EXECUTE tasks and return a raw result string.
  - Agents NEVER generate user-facing responses.
  - Response text is always produced by the personality layer.
  - Every agent wraps existing tools via _dispatch_intent — no logic is duplicated.
  - Every subclass must implement handle(intent, data, query) → str.

Safety:
  - safe_handle() wraps handle() with timing + structured error logging.
  - Failures are re-raised so the executor can decide retry / Qwen fallback.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """
    Superclass for all VANI domain agents.

    Subclasses only need to implement handle().
    All plumbing (logging, timing, error bubbling) lives here.
    """

    #: Short slug — used in logging and the AGENT_REGISTRY key.
    name: str = "base"

    #: Human-readable description of what this agent handles.
    #: Injected into agent_summary() for debugging and prompt injection.
    description: str = ""

    #: Tool names this agent is responsible for (informational — for registry queries).
    owned_tools: list[str] = []

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"vani.agents.{self.name}")

    # ── Public interface ──────────────────────────────────────────────────────

    @abstractmethod
    async def handle(self, intent: str, data: Any, query: str) -> str:
        """
        Execute the task described by (intent, data, query).

        Args:
            intent: Router intent string, e.g. "WHATSAPP_SEND", "GOOGLE_SEARCH"
            data:   Payload extracted by the router (contact tuple, search query, etc.)
            query:  Original raw user query fragment (used as fallback context)

        Returns:
            Raw result string — e.g. "✅ WhatsApp sent to Rudra" or search results.
            Never returns None; return "" to signal empty success.

        Raises:
            Exception: on tool failure — executor decides retry / Qwen fallback.
        """
        ...

    async def safe_handle(self, intent: str, data: Any, query: str) -> str:
        """
        Public entry point used by the executor.

        Wraps handle() with:
          - wall-clock timing (logged at DEBUG)
          - structured error logging (ERROR with agent name + intent)
          - re-raise so executor can handle fallback

        Never suppress exceptions here — the executor needs them.
        """
        t0 = time.perf_counter()
        try:
            result = await self.handle(intent, data, query)
            elapsed = (time.perf_counter() - t0) * 1000
            self.logger.debug(
                f"[{self.name.upper()}] {intent} → done in {elapsed:.1f}ms"
            )
            return result
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self.logger.error(
                f"[{self.name.upper()}] {intent} failed after {elapsed:.1f}ms: {exc}"
            )
            raise

    # ── Utility ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """One-line summary for debugging / agent list display."""
        tools = ", ".join(self.owned_tools) if self.owned_tools else "via router"
        return f"{self.name}: {self.description} [{tools}]"

    def __repr__(self) -> str:
        return f"<Agent:{self.name}>"
