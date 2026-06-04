"""
vani/agents/__init__.py — Phase 3

Agent registry — maps agent name strings to agent instances.

All agents are lazily instantiated on first access so import time stays fast
and circular import risk is eliminated. The registry is a singleton.

Usage:
    from vani.agents import get_agent, list_agents, AGENT_REGISTRY

    agent = get_agent("browser")
    result = await agent.safe_handle("GOOGLE_SEARCH", "python tutorial", query)

    # List all registered agents
    for name, agent in AGENT_REGISTRY.items():
        print(agent.summary())

Agent → Tool domain mapping (for reference):
    browser       → google_search, open_url, open_youtube_and_play, youtube_control, tabs
    communication → whatsapp_*, telegram_*, notifications_read
    coding        → code_assist, write_code_to_file
    vision        → read_screen, learn_this, learn_name
    system        → open_application, close_application, media_control, volume, cursor/keyboard
    file          → folder_file, Play_file, save_note, app_search
    automation    → start_study_session, end_study_session, study_status
    memory        → working_memory, human_memory, context retrieval
    learning      → learning_memory, quizzes, pronunciation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vani.agents.base_agent import BaseAgent

logger = logging.getLogger("vani.agents")

# ── Lazy registry ─────────────────────────────────────────────────────────────
# Agents are instantiated on first import of this module.
# Import errors for any single agent are caught and logged — the rest still load.

def _build_registry() -> dict[str, "BaseAgent"]:
    registry: dict[str, "BaseAgent"] = {}
    _agent_classes = [
        ("vani.agents.browser_agent",       "BrowserAgent",       "browser"),
        ("vani.agents.communication_agent", "CommunicationAgent", "communication"),
        ("vani.agents.coding_agent",        "CodingAgent",        "coding"),
        ("vani.agents.vision_agent",        "VisionAgent",        "vision"),
        ("vani.agents.system_agent",        "SystemAgent",        "system"),
        ("vani.agents.file_agent",          "FileAgent",          "file"),
        ("vani.agents.automation_agent",    "AutomationAgent",    "automation"),
        ("vani.agents.memory_agent",        "MemoryAgent",        "memory"),
        ("vani.agents.learning_agent",      "LearningAgent",      "learning"),
        ("vani.agents.finance_agent",       "FinanceAgent",       "finance"),
    ]
    for module_path, class_name, key in _agent_classes:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            registry[key] = cls()
            logger.debug(f"[AGENTS] Registered: {key} ({class_name})")
        except Exception as e:
            logger.error(f"[AGENTS] Failed to load {class_name} from {module_path}: {e}")
            
    # Bootstrap specialized Domain Modules
    try:
        from vani.domains.manager import DomainManager
        DomainManager.load_domains()
    except Exception as e:
        logger.error(f"[AGENTS] Failed to load Domain Modules: {e}")
        
    return registry


AGENT_REGISTRY: dict[str, "BaseAgent"] = _build_registry()


# ── Public API ────────────────────────────────────────────────────────────────

def get_agent(name: str) -> "BaseAgent | None":
    """
    Look up an agent by name.

    Args:
        name: Agent key — "browser", "communication", "coding", "vision",
              "system", "file", "automation", "memory", "learning"

    Returns:
        Agent instance, or None if not found / failed to load.

    Example:
        agent = get_agent("browser")
        if agent:
            result = await agent.safe_handle(intent, data, query)
    """
    return AGENT_REGISTRY.get(name)


def list_agents() -> list[str]:
    """Returns list of all registered agent names."""
    return list(AGENT_REGISTRY.keys())


def agent_summary() -> str:
    """
    Returns a multi-line summary of all registered agents.
    Useful for debugging, prompt injection, and admin endpoints.
    """
    if not AGENT_REGISTRY:
        return "No agents registered."
    lines = ["VANI Agent Registry:"]
    for name, agent in AGENT_REGISTRY.items():
        lines.append(f"  {agent.summary()}")
    return "\n".join(lines)


def get_agent_for_intent(intent: str) -> "BaseAgent | None":
    """
    Maps a router intent string to the responsible agent.
    Mirrors the intent_to_agent mapping in TaskPlanner._intent_to_agent().

    Used by executor when bypassing the planner for direct agent dispatch.

    Args:
        intent: Router intent string, e.g. "WHATSAPP_SEND", "GOOGLE_SEARCH"

    Returns:
        The matching agent instance, or None (caller falls back to Qwen).
    """
    _INTENT_PREFIX_MAP: list[tuple[str, str]] = [
        # (prefix, agent_key) — checked in order; first match wins
        ("GOOGLE_SEARCH",    "browser"),
        ("OPEN_URL",         "browser"),
        ("BROWSER_",         "browser"),
        ("YOUTUBE_",         "browser"),
        ("APP_SEARCH",       "browser"),
        ("WHATSAPP_",        "communication"),
        ("TELEGRAM_",        "communication"),
        ("INSTAGRAM_",       "communication"),
        ("NOTIFICATIONS_",   "communication"),
        ("CODE_",            "coding"),
        ("WRITE_CODE",       "coding"),
        ("SCREEN_READ",      "vision"),
        ("LEARN_NAME",       "vision"),
        ("LEARN_THIS",       "vision"),
        ("APP_OPEN",         "system"),
        ("APP_CLOSE",        "system"),
        ("APP_SWITCH",       "system"),
        ("MEDIA_",           "system"),
        ("VOLUME_",          "system"),
        ("CURSOR_",          "system"),
        ("MOUSE_",           "system"),
        ("KEY_",             "system"),
        ("HOTKEY_",          "system"),
        ("SWIPE_",           "system"),
        ("TALKING_TOM",      "system"),
        ("VOICE_",           "system"),
        ("FOLDER_",          "file"),
        ("PLAY_FILE",        "file"),
        ("SAVE_NOTE",        "file"),
        ("STUDY_",           "automation"),
        ("REMINDER_",        "automation"),
        ("FINANCE_",         "finance"),
    ]
    intent_upper = (intent or "").upper()
    for prefix, agent_key in _INTENT_PREFIX_MAP:
        if intent_upper.startswith(prefix):
            return get_agent(agent_key)
    return None


__all__ = [
    "AGENT_REGISTRY",
    "get_agent",
    "list_agents",
    "agent_summary",
    "get_agent_for_intent",
]
