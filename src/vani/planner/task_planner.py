"""
vani/planner/task_planner.py

Worker Twin — Planning half.

Converts a raw user query into a TaskPlan using the existing deterministic
router. No LLM called here — pure regex/rule-based classification.

Fast path  (<1ms)  : router classifies intent → single SubTask
Compound   (<2ms)  : router splits compound commands → multiple SubTasks
LLM needed (→Qwen) : router returns None → TaskPlan.requires_llm = True

The planner NEVER generates text responses. It only decides what to do.
Text generation stays with Twin A (Gemini Realtime).
"""

from __future__ import annotations
import logging
from vani.planner.models import SubTask, TaskPlan

logger = logging.getLogger("vani.planner.task_planner")


# ── Intent → Agent mapping ────────────────────────────────────────────────────
# Maps router intent prefixes/exact names to the agent that handles them.
# Agents are logical labels; execution still goes through _dispatch_intent.
_INTENT_AGENT_MAP: list[tuple[str, str]] = [
    # Browser / web
    ("GOOGLE_SEARCH",    "browser"),
    ("OPEN_URL",         "browser"),
    ("BROWSER_",         "browser"),
    ("YOUTUBE_",         "browser"),
    # Communication
    ("WHATSAPP_",        "communication"),
    ("INSTAGRAM_",       "communication"),
    ("TELEGRAM_",        "communication"),
    # Coding / files
    ("CODE_ASSIST",      "coding"),
    ("FOLDER_FILE",      "file"),
    # System / apps
    ("APP_OPEN",         "system"),
    ("APP_CLOSE",        "system"),
    ("APP_SWITCH",       "system"),
    ("TAB_",             "system"),
    ("MEDIA_CONTROL",    "system"),
    ("VOICE_",           "system"),
    ("WINDOWS_SYSTEM_CONTROL", "system"),
    # Vision
    ("SCREEN_READ",      "vision"),
    # Automation / learning
    ("STUDY_",           "automation"),
    ("FINANCE_",         "finance"),
]

# Direct intent → tool name (for logging/analysis — executor still uses _dispatch_intent)
_INTENT_TOOL_MAP: dict[str, str] = {
    "GOOGLE_SEARCH":    "google_search",
    "OPEN_URL":         "open_url_in_browser",
    "WHATSAPP_SEND":    "whatsapp_send",
    "WHATSAPP_READ":    "whatsapp_read",
    "WHATSAPP_CALL":    "whatsapp_call",
    "WHATSAPP_OPEN_CHAT": "whatsapp_open_chat",
    "TELEGRAM_SEND":    "telegram_send",
    "TELEGRAM_READ":    "telegram_read",
    "SCREEN_READ":      "read_screen",
    "MEDIA_CONTROL":    "media_control",
    "APP_OPEN":         "open_application",
    "APP_CLOSE":        "close_application",
    "YOUTUBE_PLAY":     "open_youtube_and_play",
    "CODE_ASSIST":      "code_assist",
    "FOLDER_FILE":      "folder_file",
    "STUDY_START":      "start_study_session",
    "STUDY_END":        "end_study_session",
    "WINDOWS_SYSTEM_CONTROL": "windows_system_control",
}


def _intent_to_agent(intent: str) -> str:
    """Map a router intent string to an agent label."""
    for prefix, agent in _INTENT_AGENT_MAP:
        if intent.startswith(prefix):
            return agent
    return "reasoning"   # fallback → Qwen handles it


class TaskPlanner:
    """
    Converts user query → TaskPlan using the deterministic router.
    No LLM, no network calls, pure in-process logic.
    """

    def __init__(self):
        # Lazy import to avoid circular dependency at module load
        self._router_ready = False

    def _ensure_router(self):
        if self._router_ready:
            return
        from vani.reasoning.router import _router_classify, _router_classify_many
        self._classify = _router_classify
        self._classify_many = _router_classify_many
        self._router_ready = True

    # ── Public API ────────────────────────────────────────────────────────────

    def plan(self, query: str) -> TaskPlan:
        """
        Main entry point.

        Returns a TaskPlan. Caller checks plan.requires_llm:
            False → executor can handle it directly
            True  → fall through to Qwen
        """
        try:
            self._ensure_router()
        except Exception as e:
            logger.warning(f"[PLANNER] Router init failed: {e} — routing to LLM")
            return TaskPlan(raw_query=query, intent=None, requires_llm=True)

        # ── 1. Compound command? (e.g. "search X and play Y") ─────────────────
        try:
            many = self._classify_many(query)
        except Exception:
            many = []

        if many and len(many) >= 2:
            subtasks = [
                SubTask(
                    task_id=f"t{i}",
                    description=part,
                    agent=_intent_to_agent(intent),
                    intent=intent,
                    data=data,
                    query=part,
                )
                for i, (intent, data, part) in enumerate(many)
            ]
            logger.info(
                f"[PLANNER] Compound plan ({len(subtasks)} tasks): "
                + " | ".join(f"{t.intent}" for t in subtasks)
            )
            return TaskPlan(
                raw_query=query,
                intent="COMPOUND",
                subtasks=subtasks,
            )

        # ── 2. Single known intent ─────────────────────────────────────────────
        try:
            intent, data = self._classify(query)
        except Exception as e:
            logger.warning(f"[PLANNER] classify failed: {e}")
            intent, data = None, None

        if intent:
            agent = _intent_to_agent(intent)
            tool = _INTENT_TOOL_MAP.get(intent)
            logger.info(
                f"[PLANNER] Single intent: {intent} → agent={agent}"
                + (f", tool={tool}" if tool else "")
            )
            return TaskPlan(
                raw_query=query,
                intent=intent,
                subtasks=[SubTask(
                    task_id="t0",
                    description=query,
                    agent=agent,
                    intent=intent,
                    data=data,
                    query=query,
                )],
            )

        # ── 3. Unknown → needs LLM ─────────────────────────────────────────────
        logger.info(f"[PLANNER] No intent matched for: {query!r} → routing to LLM")
        return TaskPlan(
            raw_query=query,
            intent=None,
            requires_llm=True,
        )
