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

    def _get_best_ollama_model(self) -> str:
        """Query local Ollama and return the fastest available/installed model."""
        import requests
        preferred = ["qwen2.5:1.5b", "llama3.2:1b", "qwen2.5:3b", "llama3.2:latest"]
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=1.5)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                for p in preferred:
                    if p in models:
                        return p
                for p in preferred:
                    p_base = p.split(":")[0]
                    for m in models:
                        if m.startswith(p_base):
                            return m
                if models:
                    return models[0]
        except Exception:
            pass
        return "qwen2.5:3b"  # Default fallback


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
                    res = await p.on_activate(query, context)
                    await send_plugin_signal(p.name, res)
                    return res
                except Exception as e:
                    logger.error(f"[plugins] {p.name} error: {e}")
                    res = PluginResult(
                        success=False,
                        message=f"Plugin error in {p.name}: {e}"
                    )
                    await send_plugin_signal(p.name, res)
                    return res
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
    """Register all built-in plugins at startup, then load custom ones."""
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

    # Custom plugins from PROJECT_ROOT / "plugins"
    from vani.config import PROJECT_ROOT
    custom_dir = PROJECT_ROOT / "plugins"
    if not custom_dir.exists():
        try:
            custom_dir.mkdir(parents=True, exist_ok=True)
            template_code = '''"""
Template Plugin for Vani OS.
Save this file as `plugins/my_custom_plugin.py` to auto-load.
"""
from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

class MyCustomPlugin(VaniPlugin):
    name = "custom"
    icon = "⚡"
    description = "Custom superpower plugin for Vani"
    category = "general"
    enabled = True  # Enabled by default for custom plugins
    triggers = ["run custom test", "my custom feature"]

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        # Perform any custom Python actions here (e.g. call an API, write to a file, etc.)
        return PluginResult(
            success=True,
            message="Custom plugin successfully executed! I can do anything now.",
            ui_payload={"data": "Custom payload"}
        )
'''
            (custom_dir / "template_plugin.py.example").write_text(template_code, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not create custom plugins dir: {e}")

    # Load custom plugins dynamically
    import importlib.util
    import sys
    for py_file in custom_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        try:
            module_name = f"vani_custom_plugin_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Scan for VaniPlugin subclasses in this module
                registered_any = False
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, VaniPlugin)
                        and attr is not VaniPlugin
                    ):
                        plugin_instance = attr()
                        plugin_instance.enabled = True
                        registry.register(plugin_instance)
                        registered_any = True
                if registered_any:
                    logger.info(f"[plugins] Loaded custom plugin file: {py_file.name}")
        except Exception as e:
            logger.error(f"[plugins] Failed to load custom plugin {py_file.name}: {e}")

    logger.info(f"[plugins] {len(registry._plugins)} plugins registered")


async def send_plugin_signal(plugin_name: str, result: PluginResult) -> None:
    from vani.config import PACKAGE_ROOT
    import pathlib
    import time
    import json

    plugin_signal_path = PACKAGE_ROOT / "ui" / "plugin_signal.json"
    payload = {
        "ts": time.time(),
        "plugin_name": plugin_name,
        "success": result.success,
        "message": result.message,
        "artifact_path": result.artifact_path,
        "artifact_type": result.artifact_type,
        "ui_payload": result.ui_payload,
    }
    def _write():
        try:
            tmp = plugin_signal_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(plugin_signal_path)
        except Exception as e:
            logger.warning("PLUGIN_SIGNAL write failed: %s", e)

    import asyncio
    await asyncio.get_event_loop().run_in_executor(None, _write)
