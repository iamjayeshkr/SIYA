"""
vani/agents/browser_agent.py — Evolved Browser Agent

Handles all browser-domain tasks statefully:
  web search, URL navigation, tab control, YouTube playback, and semantic crawling.
"""

from __future__ import annotations

from typing import Any
from vani.agents.base_agent import BaseAgent


class BrowserAgent(BaseAgent):
    name = "browser"
    description = (
        "Handles web search, website crawling, tab navigation, and YouTube playback. "
        "Can crawl websites using crawl_url to save page content to memory for semantic Q&A."
    )
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
        "crawl_url",
    ]

    def __init__(self) -> None:
        super().__init__()
        # Dynamically register the crawl_url tool at initialization
        try:
            from vani.reasoning.registry import register_tool
            register_tool(
                "crawl_url",
                self.crawl_url,
                "crawl_url(url) - Web page content read karo (convert to markdown and clean HTML boilerplate)"
            )
        except Exception as e:
            self.logger.warning(f"Could not register crawl_url dynamically: {e}")

    async def crawl_url(self, url: str) -> str:
        """
        Crawl a webpage, clean HTML structures, convert to Markdown, and 
        index chunks inside Vani's local vector store for semantic context retrieval.
        """
        from vani.browser.crawler import fetch_and_clean_webpage, chunk_markdown
        self.logger.info(f"Starting crawl for target URL: {url}")
        
        cleaned_markdown = await fetch_and_clean_webpage(url)
        if not cleaned_markdown:
            return "❌ URL fetch failed. Could not retrieve text content from webpage."

        # Chunk the markdown content for retrieval
        chunks = chunk_markdown(cleaned_markdown, chunk_size=1200, overlap=150)
        
        # Index chunks in our local SQLite Vector Store
        try:
            from vani.memory.vector_store import SQLiteVectorStore
            store = SQLiteVectorStore()
            for idx, chunk in enumerate(chunks):
                await store.add_memory(
                    chunk,
                    {"source": "web_crawl", "url": url, "chunk_index": idx}
                )
            self.logger.info(f"Indexed {len(chunks)} page chunks into vector database successfully")
        except Exception as e:
            self.logger.error(f"Failed to index crawled page chunks into database: {e}")

        # Return a text preview for immediate thinking context
        preview = cleaned_markdown[:1500]
        if len(cleaned_markdown) > 1500:
            preview += "\n\n... [remaining content indexed in local vector memory for Q&A] ..."
        return f"✅ Content crawled successfully:\n\n{preview}"

    async def handle(self, intent: str, data: Any, query: str) -> str:
        """
        Legacy entry point: routes browser intents directly to dispatcher.
        """
        from vani.reasoning.router import _dispatch_intent
        return await _dispatch_intent(intent, data, query)