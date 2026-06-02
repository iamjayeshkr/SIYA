"""
vani/agents/automation_agent.py — Phase 3

Handles all automation/scheduling-domain intents:
  study sessions (start/end/status), future reminder triggers,
  scheduled task execution.

Wraps:
  - reasoning/tools/study_mode.py → start_study_session, end_study_session, study_status
  - memory/working_memory.py      → reminder checks (future — Phase 7 worker will own this)

Phase 3: delegates to _dispatch_intent — zero behavior change.
Future:  own the reminder execution path when Phase 7 (WorkerManager) lands;
         add calendar integration, recurring tasks, smart scheduling based on
         Rudra's activity patterns from working_memory.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class AutomationAgent(BaseAgent):
    name = "automation"
    description = "Study sessions, reminders, scheduled tasks, DND automation"
    owned_tools = [
        "start_study_session",
        "end_study_session",
        "study_status",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route automation intents through the existing deterministic dispatcher.

        Intents handled:
          STUDY_START, STUDY_END, STUDY_STATUS, REMINDER_*, SCHEDULE_*

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)
