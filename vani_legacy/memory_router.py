"""
vani/memory_router.py
─────────────────────
Unified memory interface for the Vani planner.

Routes reads to the right memory layer automatically:
  1. Working memory   — in-process dict, current session, instant
  2. Semantic memory  — sqlite-vec vector search, weeks/months of context
  3. Permanent memory — existing SQLite keyword search (your current system)

The planner calls ONE function:

    from vani.memory_router import MemoryRouter

    router = MemoryRouter(semantic=semantic_mem, permanent=permanent_mem)

    # Store anything
    await router.store("Rudra prefers dark mode", importance=1.5)

    # Get context block for LLM (auto-searches all layers)
    context = await router.get_context("what are Rudra's preferences?")

    # Inject into prompt
    prompt = f"{context}\n\nUser: {query}"
"""

import asyncio
import time
from typing import Any, Optional

from vani.logging_config import get_logger
from vani.memory_semantic import SemanticMemory

log = get_logger("memory.router")


class MemoryRouter:
    """
    Unified memory access layer.

    Pass your existing permanent memory object (whatever class handles
    your current SQLite memory) as `permanent`. It only needs a
    `get_full_context(query)` method — or pass None to skip it.
    """

    def __init__(
        self,
        semantic: SemanticMemory,
        permanent: Any = None,            # your existing PermanentMemory object
        working_ttl_seconds: int = 3600,  # working memory expires after 1h
    ):
        self.semantic = semantic
        self.permanent = permanent
        self._working: dict[str, dict] = {}  # key → {value, expires_at}
        self._working_ttl = working_ttl_seconds

    # ── Working memory (in-process, current session) ──────────────────────────

    def set_working(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store a value in working memory (expires after ttl seconds)."""
        expires_at = time.monotonic() + (ttl or self._working_ttl)
        self._working[key] = {"value": value, "expires_at": expires_at}
        log.debug("working_memory_set", key=key)

    def get_working(self, key: str) -> Optional[Any]:
        """Get a value from working memory. Returns None if expired or missing."""
        entry = self._working.get(key)
        if not entry:
            return None
        if time.monotonic() > entry["expires_at"]:
            del self._working[key]
            return None
        return entry["value"]

    def clear_working(self) -> None:
        """Clear all working memory (call at session end)."""
        self._working.clear()
        log.info("working_memory_cleared")

    # ── Store (semantic + permanent) ──────────────────────────────────────────

    async def store(
        self,
        text: str,
        source: str = "conversation",
        tags: list[str] | None = None,
        importance: float = 1.0,
        also_permanent: bool = False,
    ) -> None:
        """
        Store a memory in the semantic layer (and optionally permanent layer).

        Args:
            text:           Memory text.
            source:         'conversation' | 'tool' | 'manual'
            tags:           Tags for filtering (e.g. ["project", "preference"])
            importance:     Ranking weight (1.0 = normal, 2.0 = critical)
            also_permanent: If True, also write to existing permanent memory
        """
        tasks = [self.semantic.store(text, source=source, tags=tags, importance=importance)]

        if also_permanent and self.permanent:
            try:
                # Adapt to your existing permanent memory API
                if hasattr(self.permanent, "store"):
                    tasks.append(self.permanent.store(text))
                elif hasattr(self.permanent, "add_memory"):
                    tasks.append(self.permanent.add_memory(text))
            except Exception as e:
                log.warning("permanent_store_failed", error=str(e))

        await asyncio.gather(*tasks, return_exceptions=True)

    # ── Context builder (the main function the planner uses) ──────────────────

    async def get_context(
        self,
        query: str,
        max_tokens: int = 800,
        include_working: bool = True,
        include_semantic: bool = True,
        include_permanent: bool = True,
        semantic_top_k: int = 6,
    ) -> str:
        """
        Build a complete memory context block for the LLM.

        Queries all enabled layers concurrently and assembles a single
        token-budget-aware string ready for injection into the prompt.

        Returns "" if no relevant memories found.
        """
        t0 = time.monotonic()
        blocks = []
        token_budget = max_tokens

        # ── 1. Working memory (instant, no async needed) ──────────────────────
        if include_working and self._working:
            active = {
                k: v["value"] for k, v in self._working.items()
                if time.monotonic() < v["expires_at"]
            }
            if active:
                lines = ["[Current session]"]
                for k, v in active.items():
                    lines.append(f"• {k}: {v}")
                block = "\n".join(lines)
                blocks.append(block)
                token_budget -= len(block) // 4

        # ── 2. Semantic + permanent memory (concurrent) ───────────────────────
        sem_task = (
            self.semantic.build_context(query, max_tokens=token_budget // 2, top_k=semantic_top_k)
            if include_semantic else asyncio.sleep(0, result="")
        )

        perm_task = (
            self._get_permanent_context(query)
            if include_permanent and self.permanent else asyncio.sleep(0, result="")
        )

        sem_block, perm_block = await asyncio.gather(sem_task, perm_task, return_exceptions=True)

        if isinstance(sem_block, str) and sem_block:
            blocks.append(sem_block)
        if isinstance(perm_block, str) and perm_block:
            blocks.append(perm_block)

        if not blocks:
            return ""

        result = "\n\n".join(blocks)
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info("memory_context_built",
                 layers=len(blocks),
                 tokens_approx=len(result) // 4,
                 duration_ms=duration_ms)
        return result

    async def _get_permanent_context(self, query: str) -> str:
        """Adapter for existing permanent memory — handles different API shapes."""
        try:
            if hasattr(self.permanent, "get_full_context"):
                return await self.permanent.get_full_context(query) or ""
            elif hasattr(self.permanent, "search"):
                results = await self.permanent.search(query)
                if isinstance(results, list):
                    return "\n".join(str(r) for r in results[:5])
            return ""
        except Exception as e:
            log.warning("permanent_context_failed", error=str(e))
            return ""

    # ── Convenience search ────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        tag_filter: Optional[str] = None,
        days_limit: Optional[int] = None,
    ) -> list[dict]:
        """Direct semantic search — returns raw result dicts with scores."""
        return await self.semantic.search(
            query, top_k=top_k, tag_filter=tag_filter, days_limit=days_limit
        )

    async def stats(self) -> dict:
        """Return memory stats for debugging / dashboard."""
        count = await self.semantic.count()
        working_count = sum(
            1 for v in self._working.values()
            if time.monotonic() < v["expires_at"]
        )
        return {
            "semantic_memories": count,
            "working_entries": working_count,
            "has_permanent": self.permanent is not None,
        }
