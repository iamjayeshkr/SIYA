"""
vani/agents/file_agent.py — Phase 3

Handles all file-system-domain intents:
  folder/file operations, note saving, file playback (media files),
  Spotlight/Windows Search.

Wraps:
  - reasoning/tools/apps.py  → folder_file, Play_file, close_active_tab
  - reasoning/tools/notes.py → save_note

Phase 3: delegates to _dispatch_intent — zero behavior change.
Future:  add file-type awareness (open PDF → VisionAgent handoff),
         recent-files context injection, note retrieval for memory layer,
         integration with relationship_memory for shared file context.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class FileAgent(BaseAgent):
    name = "file"
    description = "File/folder operations, note saving, file playback, Spotlight search"
    owned_tools = [
        "folder_file",
        "Play_file",
        "save_note",
        "app_search",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route file intents through the existing deterministic dispatcher.

        Intents handled:
          FOLDER_FILE, PLAY_FILE, SAVE_NOTE, FILE_*, NOTE_*

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)
