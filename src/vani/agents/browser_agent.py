"""
vani/agents/browser_agent.py — Phase 3

Handles all browser-domain intents:
  web search, URL navigation, tab control, YouTube playback/control.

Wraps:
  - browser/search.py     → google_search
  - reasoning/tools/apps  → open_url, open_url_in_browser, open_youtube_and_play,
                             close_active_tab, next_tab, previous_tab
  - reasoning/tools/youtube → youtube_control
  - reasoning/screen      → browser-context screen reads (delegated via router)

Phase 3: delegates to _dispatch_intent (existing router) — zero behavior change.
Future:  add caching for repeated searches, smart tab management, history context.
"""

from __future__ import annotations

from vani.agents.base_agent import BaseAgent


class BrowserAgent(BaseAgent):
    name = "browser"
    description = "Web search, URL navigation, browser tab control, YouTube playback"
    owned_tools = [
        "google_search",
        "open_url",
        "open_url_in_browser",
        "open_youtube_and_play",
        "youtube_control",
        "close_active_tab",
        "close_tab_by_name",
        "close_all_tabs_by_name",
        "switch_tab_by_name",
        "next_tab",
        "previous_tab",
        "app_search",
    ]

    async def handle(self, intent: str, data, query: str) -> str:
        """
        Route browser intents through the existing deterministic dispatcher.

        Intents handled:
          GOOGLE_SEARCH, OPEN_URL, BROWSER_TAB_*, YOUTUBE_PLAY, YOUTUBE_CONTROL,
          APP_SEARCH, BROWSER_CONTROL_*

        Falls through to _dispatch_intent — identical behavior to pre-Phase-3.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)