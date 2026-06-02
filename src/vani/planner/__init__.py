"""
vani/planner/__init__.py

Twin Brain — Worker Side.

Architecture:
    Twin A (Talker)  = Gemini Realtime session  → speaks, never blocks
    Twin B (Worker)  = PlannerBrain             → thinks, plans, executes silently

Twin B slots into thinking_capability() BEFORE Qwen.
If Twin B handles the task → Qwen never wakes up (faster, cheaper).
If Twin B can't handle it  → falls through to Qwen as normal.
Twin A is never aware of this switch — it just receives the result and speaks it.
"""

from vani.planner.brain import PlannerBrain

__all__ = ["PlannerBrain"]
