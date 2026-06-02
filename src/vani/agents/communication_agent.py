"""
vani/agents/communication_agent.py — Phase 3

Handles all messaging-domain intents:
  WhatsApp (send/read/call/open), Telegram (send/read/list),
  Instagram (DM send/read/list), system notifications.

Wraps:
  - reasoning/tools/messaging.py  → whatsapp_*, telegram_*, notifications_read
  - future: instagram_* (when implemented)

Phase 3: delegates to _dispatch_intent — zero behavior change.
Future:  add retry logic for send failures, contact caching, thread context injection.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class CommunicationAgent(BaseAgent):
    name = "communication"
    description = "WhatsApp, Telegram, Instagram messages, calls, and notifications"
    owned_tools = [
        "whatsapp_send",
        "whatsapp_read",
        "whatsapp_call",
        "whatsapp_open_chat",
        "whatsapp_shortcut",
        "telegram_send",
        "telegram_read",
        "telegram_chats",
        "notifications_read",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route communication intents through the existing deterministic dispatcher.

        Intents handled:
          WHATSAPP_SEND, WHATSAPP_READ, WHATSAPP_CALL, WHATSAPP_OPEN_CHAT,
          WHATSAPP_SHORTCUT, TELEGRAM_SEND, TELEGRAM_READ, TELEGRAM_CHATS,
          INSTAGRAM_SEND, INSTAGRAM_READ, INSTAGRAM_LIST, NOTIFICATIONS_READ

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)
