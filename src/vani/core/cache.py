"""
vani/core/cache.py — Thread-safe local cache manager with size caps and TTL expiration.

Used to avoid redundant network calls for web searches, page crawls, and stock quotes.
"""

from __future__ import annotations

import time
import threading
from collections import OrderedDict
from typing import Any, Optional


class CacheItem:
    """A single cache record with expiration tracking."""

    def __init__(self, value: Any, ttl_seconds: Optional[float] = None) -> None:
        self.value = value
        self.expires_at = time.time() + ttl_seconds if ttl_seconds is not None else None

    def is_expired(self) -> bool:
        """Check if this item has passed its expiration time."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class CacheManager:
    """Thread-safe LRU Cache with TTL support."""

    def __init__(self, max_size: int = 100) -> None:
        self.max_size = max_size
        self._cache: OrderedDict[Any, CacheItem] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[Any]:
        """Retrieve a value from the cache, evicting it if expired."""
        with self._lock:
            if key not in self._cache:
                return None
            item = self._cache[key]
            if item.is_expired():
                del self._cache[key]
                return None
            # Move to end to mark as recently used
            self._cache.move_to_end(key)
            return item.value

    def set(self, key: Any, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Add or update a cache value, maintaining the size limit."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self.max_size:
                # Evict the oldest (first) item in the OrderedDict
                self._cache.popitem(last=False)
            self._cache[key] = CacheItem(value, ttl_seconds)

    def clear(self) -> None:
        """Evict all cached entries."""
        with self._lock:
            self._cache.clear()


# ── Global Cache Instances ───────────────────────────────────────────────────

# Web searches: 1 hour expiration
search_cache = CacheManager(max_size=200)

# Scraped web page markdown: 24 hours expiration
crawl_cache = CacheManager(max_size=50)

# Stock quotes: 1 minute expiration
stock_cache = CacheManager(max_size=100)
