"""
vani/agents/coding_agent.py — Phase 3

Handles all coding-domain intents:
  code assistance (read + generate + explain), writing code to files,
  language detection, VS Code integration.

Wraps:
  - reasoning/tools/code.py  → code_assist, write_code_to_file

Phase 3: delegates to _dispatch_intent — zero behavior change.
Future:  add active file context injection, diff-based editing, GitHub integration,
         multi-file project awareness via file_agent coordination.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class CodingAgent(BaseAgent):
    name = "coding"
    description = "Code assistance, file writing, debugging, VS Code integration"
    owned_tools = [
        "code_assist",
        "write_code_to_file",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route coding intents through the existing deterministic dispatcher.

        Intents handled:
          CODE_ASSIST, WRITE_CODE_TO_FILE, CODE_*

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)
