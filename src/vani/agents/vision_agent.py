"""
vani/agents/vision_agent.py — Phase 3

Handles all visual-domain intents:
  screen reading (screenshot + OCR + Gemini vision), image analysis,
  document vision, active-window context extraction.

Wraps:
  - reasoning/screen.py      → read_screen, learn_this, learn_name, google_search
  - services/image_chat.py   → image analysis (called from app.py; agent hooks in future)
  - services/document_service.py → PDF/document vision (future integration point)

Phase 3: delegates to _dispatch_intent — zero behavior change.
Future:  add smart cropping, repeated-screen dedup, vision context caching
         across turns so Vani doesn't re-screenshot for follow-up questions.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class VisionAgent(BaseAgent):
    name = "vision"
    description = "Screen reading, OCR, image analysis, document vision"
    owned_tools = [
        "read_screen",
        "learn_this",
        "learn_name",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route vision intents through the existing deterministic dispatcher.

        Intents handled:
          SCREEN_READ, LEARN_THIS, LEARN_NAME, VISION_*

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.

        Note on image_chat: uploaded image analysis is handled directly in app.py
        via /analyze_image endpoint. This agent will integrate that path in Phase 5.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)
