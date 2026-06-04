"""
vani/browser/crawler.py — Completely local web page crawler and scraper

Fetches HTML, converts to clean Markdown, and segments content.
Inspired by Crawl4AI design patterns, fully free and local.
"""

from __future__ import annotations

import re
import html
import logging
import asyncio
from typing import List

logger = logging.getLogger("vani.browser.crawler")


def clean_html_to_markdown(html_content: str) -> str:
    """Strip HTML boilerplate and convert useful structures to clean Markdown."""
    if not html_content:
        return ""

    # 1. Remove comments
    text = re.sub(r"<!--.*?-->", "", html_content, flags=re.DOTALL)

    # 2. Remove script, style, nav, footer, header elements
    for tag in ["script", "style", "header", "footer", "nav", "aside", "noscript", "iframe"]:
        text = re.sub(rf"<{tag}.*?>.*?</{tag}>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Format header elements
    for i in range(1, 7):
        text = re.sub(rf"<h{i}.*?>(.*?)</h{i}>", rf"\n\n{'#' * i} \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)

    # 4. Format link elements
    text = re.sub(r'<a\s+[^>]*?href=["\'](.*?)["\'][^>]*?>(.*?)</a>', r" [\2](\1) ", text, flags=re.IGNORECASE | re.DOTALL)

    # 5. Format paragraphs, lists, and line breaks
    text = re.sub(r"</?(?:p|div|li|br|tr|ul|ol).*?>", "\n", text, flags=re.IGNORECASE)

    # 6. Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # 7. Unescape HTML entities
    text = html.unescape(text)

    # 8. Compress spacing and layout whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


def chunk_markdown(text: str, chunk_size: int = 1200, overlap: int = 150) -> List[str]:
    """Segment Markdown text into chunks of given size with overlap."""
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # Shift start window back by overlap amount
        start = max(end - overlap, start + 1)
    return chunks


async def fetch_and_clean_webpage(url: str) -> str:
    """Fetch HTML page asynchronously and return clean Markdown."""
    # Check crawl_cache first
    try:
        from vani.core.cache import crawl_cache
        cached_result = crawl_cache.get(url)
        if cached_result:
            logger.info("Crawl cache hit for url: %s", url)
            return cached_result
    except Exception as e:
        logger.warning(f"Could not access crawl cache: {e}")

    def _sync_fetch() -> str:
        import requests
        # Generic Chrome User-Agent header to prevent simple anti-bot blocking
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                return r.text
            else:
                logger.warning(f"URL {url} returned status code: {r.status_code}")
        except Exception as e:
            logger.error(f"Error fetching URL {url} from network: {e}")
        return ""

    loop = asyncio.get_running_loop()
    html_data = await loop.run_in_executor(None, _sync_fetch)
    if not html_data:
        return ""

    markdown = clean_html_to_markdown(html_data)
    if markdown:
        try:
            crawl_cache.set(url, markdown, ttl_seconds=86400)  # 24 hours
        except Exception as e:
            logger.warning(f"Could not save to crawl cache: {e}")
    return markdown
