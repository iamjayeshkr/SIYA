"""
tests/test_performance.py — Performance & Cache Unit Tests
"""

from __future__ import annotations

import time
import pytest
from vani.core.cache import CacheManager, search_cache, crawl_cache, stock_cache


def test_cache_hits_and_misses():
    cache = CacheManager(max_size=5)
    
    # Key not in cache should be None
    assert cache.get("nonexistent") is None
    
    # Setting and getting a key
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"


def test_cache_ttl_expiration():
    cache = CacheManager(max_size=5)
    
    # Set key with 0.2 seconds TTL
    cache.set("short_lived", "data", ttl_seconds=0.2)
    assert cache.get("short_lived") == "data"
    
    # Wait for TTL to expire
    time.sleep(0.3)
    assert cache.get("short_lived") is None


def test_cache_lru_eviction():
    # Cache with capacity 2
    cache = CacheManager(max_size=2)
    
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    
    # Accessing "a" makes it the most recently used.
    # Now "b" is the least recently used.
    cache.set("c", 3)  # Eviction triggered, should evict "b"
    
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.get("b") is None


def test_global_caches():
    # Verify the global caches exist and work
    assert search_cache.max_size == 200
    assert crawl_cache.max_size == 50
    assert stock_cache.max_size == 100
    
    search_cache.set("query_test", "result_test", ttl_seconds=5)
    assert search_cache.get("query_test") == "result_test"
    search_cache.clear()
    assert search_cache.get("query_test") is None
