"""
vani/planner/models.py

Data models for the Worker Twin's planning system.
These are pure data containers — no logic, no imports from other vani modules.
Safe to import anywhere without circular dependency risk.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SubTask:
    """
    A single unit of work the Worker Twin will execute.

    Examples:
        SubTask("t0", "open YouTube", agent="browser",
                intent="YOUTUBE_PLAY", data="shape of you")

        SubTask("t0", "send whatsapp to Rudra", agent="communication",
                intent="WHATSAPP_SEND", data=("Rudra", "hey"))
    """
    task_id: str
    description: str
    agent: str                          # which agent handles this
    intent: str | None = None           # router intent string (fast path)
    data: Any = None                    # intent payload (contact, query, etc.)
    query: str = ""                     # original user query fragment

    # Execution state — updated by executor
    status: str = "pending"             # pending | running | done | failed | stale
    result: str | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class TaskPlan:
    """
    A complete execution plan for a user request.

    Single-step plan:   subtasks = [SubTask(...)]
    Multi-step plan:    subtasks = [SubTask(...), SubTask(...), ...]
    LLM-needed plan:    requires_llm = True, subtasks = []  → Qwen handles it
    """
    raw_query: str
    intent: str | None                  # top-level intent label
    subtasks: list[SubTask] = field(default_factory=list)
    requires_llm: bool = False          # True → skip planner, go straight to Qwen

    @property
    def is_compound(self) -> bool:
        return len(self.subtasks) > 1

    @property
    def all_done(self) -> bool:
        return all(t.status in ("done", "failed", "stale") for t in self.subtasks)

    @property
    def any_failed(self) -> bool:
        return any(t.status == "failed" for t in self.subtasks)

    def summary(self) -> str:
        parts = [f"[{t.status.upper()}] {t.description}" for t in self.subtasks]
        return " | ".join(parts)
