"""
vani/plugins/registry.py

Plugin Registry — the central hub that powers Vani's superpower system.

Architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │  Plugin (base class)                                        │
  │    name, icon, description, enabled                         │
  │    on_activate(query, context) → PluginResult               │
  │    on_conversation_end(messages) → summary str              │
  │                                                             │
  │  PluginRegistry                                             │
  │    register(plugin)  ← called at startup                    │
  │    enable(name)  /  disable(name)                           │
  │    list_plugins()  → [{name, icon, description, enabled}]   │
  │    route_to_plugin(query, context) → PluginResult | None    │
  └─────────────────────────────────────────────────────────────┘

Flow:
  1. Backend HTTP handler receives /plugin/* requests from UI
  2. Routes through PluginRegistry.route_to_plugin(query)
  3. Plugin.on_activate() runs the action (open app, write file, etc.)
  4. Returns PluginResult with message + optional artifact path
  5. UI renders result in plugin panel
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("vani.plugins")


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class PluginResult:
    """Returned by a plugin after it handles a request."""
    success: bool
    message: str                        # Human-readable result for Vani to speak
    artifact_path: str | None = None    # File created (note, xlsx, diagram…)
    artifact_type: str | None = None    # "markdown" | "xlsx" | "png" | "html"
    ui_payload: dict = field(default_factory=dict)  # Extra data for the UI panel


@dataclass
class PluginContext:
    """Conversation context passed into every plugin call."""
    recent_messages: list[dict]   # [{role, content}, …] last N turns
    user_name: str = "Rudra"
    session_id: str = ""


# ── Base plugin ────────────────────────────────────────────────────────────────

class VaniPlugin:
    """
    Base class for all Vani plugins.

    Subclass this and implement:
      • triggers        — list of keyword/regex hints for auto-routing
      • on_activate()   — main action
      • on_memory_save() — optional: called when user says "save our talk"
    """

    name: str = "unnamed"
    icon: str = "🔌"
    description: str = "A Vani plugin"
    category: str = "general"         # "memory" | "visual" | "finance" | "canvas"
    enabled: bool = False             # disabled until user turns it on in UI
    triggers: list[str] = []          # keywords that auto-route to this plugin

    # Called when user enables the plugin via the UI toggle
    async def on_enable(self) -> str:
        return f"✅ {self.name} plugin enabled"

    # Called when user disables the plugin
    async def on_disable(self) -> str:
        return f"🔴 {self.name} plugin disabled"

    # Main handler — override this
    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        raise NotImplementedError

    # Called at end of conversation to persist memory
    async def on_memory_save(self, messages: list[dict]) -> str | None:
        return None

    def matches(self, query: str) -> bool:
        """Check if this plugin should handle the given query."""
        if not self.enabled:
            return False
        q = query.lower()
        return any(t.lower() in q for t in self.triggers)


# ── Registry ───────────────────────────────────────────────────────────────────

class PluginRegistry:
    """
    Singleton registry that holds all installed plugins.
    """

    def __init__(self):
        self._plugins: dict[str, VaniPlugin] = {}

    def register(self, plugin: VaniPlugin) -> None:
        """Register a plugin. Called at startup or dynamically."""
        self._plugins[plugin.name] = plugin
        logger.info(f"[plugins] Registered: {plugin.icon} {plugin.name}")

    def enable(self, name: str) -> str:
        p = self._plugins.get(name)
        if not p:
            return f"Plugin '{name}' not found"
        p.enabled = True
        return f"✅ {p.icon} {p.name} enabled"

    def disable(self, name: str) -> str:
        p = self._plugins.get(name)
        if not p:
            return f"Plugin '{name}' not found"
        p.enabled = False
        return f"🔴 {p.name} disabled"

    def list_plugins(self) -> list[dict]:
        """Return serializable list for the UI."""
        return [
            {
                "name": p.name,
                "icon": p.icon,
                "description": p.description,
                "category": p.category,
                "enabled": p.enabled,
                "triggers": p.triggers,
            }
            for p in self._plugins.values()
        ]

    def get(self, name: str) -> VaniPlugin | None:
        return self._plugins.get(name)

    async def route_to_plugin(
        self, query: str, context: PluginContext
    ) -> PluginResult | None:
        """
        Find the first matching plugin and run it.
        Returns None if no plugin matches (falls through to Qwen/Gemini).
        """
        for p in self._plugins.values():
            if p.matches(query):
                logger.info(f"[plugins] Routing to {p.name}: '{query}'")
                try:
                    return await p.on_activate(query, context)
                except Exception as e:
                    logger.error(f"[plugins] {p.name} error: {e}")
                    return PluginResult(
                        success=False,
                        message=f"Plugin error in {p.name}: {e}"
                    )
        return None

    async def broadcast_memory_save(self, messages: list[dict]) -> list[str]:
        """Tell all enabled memory plugins to save the conversation."""
        results = []
        for p in self._plugins.values():
            if p.enabled:
                try:
                    r = await p.on_memory_save(messages)
                    if r:
                        results.append(r)
                except Exception as e:
                    logger.error(f"[plugins] memory save error in {p.name}: {e}")
        return results


# ── Singleton ──────────────────────────────────────────────────────────────────

_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
        _bootstrap_plugins(_registry)
    return _registry


def _bootstrap_plugins(registry: PluginRegistry) -> None:
    """Register all built-in plugins at startup."""
    from .builtin.obsidian_plugin import ObsidianPlugin
    from .builtin.excel_plugin import ExcelPlugin
    from .builtin.diagram_plugin import DiagramPlugin
    from .builtin.memory_plugin import ConversationMemoryPlugin
    from .builtin.whiteboard_plugin import WhiteboardPlugin

    registry.register(ObsidianPlugin())
    registry.register(ExcelPlugin())
    registry.register(DiagramPlugin())
    registry.register(ConversationMemoryPlugin())
    registry.register(WhiteboardPlugin())
    logger.info(f"[plugins] {len(registry._plugins)} plugins registered")
