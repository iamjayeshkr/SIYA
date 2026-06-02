"""
vani/memory_ingestion.py
────────────────────────
Auto-extracts memorable facts from conversations and tool results,
then stores them in semantic memory.

The ingestion pipeline runs AFTER every assistant turn:
  • Extracts facts worth remembering (decisions, preferences, names, deadlines)
  • Skips trivial exchanges ("ok", "thanks", etc.)
  • Tags memories by category automatically
  • Assigns importance scores

Usage:
    from vani.memory_ingestion import MemoryIngestion

    ingestion = MemoryIngestion(router=memory_router, ollama_host=...)

    # After each conversation turn:
    await ingestion.ingest_turn(
        user_message="I want the UI to use dark mode by default",
        assistant_message="Got it, I'll make dark mode the default.",
    )

    # After a tool result:
    await ingestion.ingest_tool_result(
        tool_name="web_search",
        query="Rust async runtime options",
        result_summary="Tokio is the most popular, Async-std is alternative",
    )
"""

import asyncio
import json
import re
from typing import Optional

import aiohttp

from vani.logging_config import get_logger
from vani.memory_router import MemoryRouter
from vani.secrets import get_ollama_host

log = get_logger("memory.ingestion")

# Minimum message length to bother extracting from
MIN_CONTENT_LENGTH = 30

# Trivial responses that never contain memorable facts
TRIVIAL_PATTERNS = [
    r"^(ok|okay|got it|sure|yes|no|thanks|thank you|alright|cool|nice|great)\.?$",
    r"^(understood|noted|will do|done|on it)\.?$",
]

_TRIVIAL_RE = re.compile("|".join(TRIVIAL_PATTERNS), re.IGNORECASE)


class MemoryIngestion:
    """
    Extracts and stores memorable facts from conversations.

    Uses a lightweight Ollama call (Qwen2.5 3B or similar) to extract
    facts. Falls back to rule-based extraction if Ollama is unavailable.
    """

    def __init__(
        self,
        router: MemoryRouter,
        model: str = "qwen2.5:3b",    # small, fast local model
        enabled: bool = True,
    ):
        self.router = router
        self.model = model
        self.enabled = enabled
        self._ollama_url = f"{get_ollama_host().rstrip('/')}/api/generate"

    # ── Public API ────────────────────────────────────────────────────────────

    async def ingest_turn(
        self,
        user_message: str,
        assistant_message: str,
        source: str = "conversation",
    ) -> int:
        """
        Extract and store facts from one conversation turn.
        Returns number of memories stored.
        """
        if not self.enabled:
            return 0

        combined = f"User: {user_message}\nAssistant: {assistant_message}"

        if len(combined) < MIN_CONTENT_LENGTH:
            return 0
        if _TRIVIAL_RE.match(user_message.strip()) and _TRIVIAL_RE.match(assistant_message.strip()):
            return 0

        facts = await self._extract_facts(combined)
        if not facts:
            return 0

        entries = [
            {
                "text": f["text"],
                "source": source,
                "tags": f.get("tags", []),
                "importance": f.get("importance", 1.0),
            }
            for f in facts
        ]

        ids = await self.router.semantic.store_batch(entries)
        log.info("ingested_turn", facts=len(ids))
        return len(ids)

    async def ingest_tool_result(
        self,
        tool_name: str,
        query: str,
        result_summary: str,
        importance: float = 0.8,
    ) -> bool:
        """
        Store a notable tool result as a memory.
        Only stores if the result contains meaningful information.
        """
        if not self.enabled or not result_summary or len(result_summary) < 20:
            return False

        text = f"Tool '{tool_name}' result for '{query}': {result_summary[:500]}"
        await self.router.store(
            text,
            source="tool",
            tags=[tool_name, "tool_result"],
            importance=importance,
        )
        return True

    async def ingest_manual(
        self,
        text: str,
        tags: list[str] | None = None,
        importance: float = 1.5,
    ) -> None:
        """
        Manually store an important fact (called from tools like 'remember this').
        High importance by default since user explicitly asked to remember.
        """
        await self.router.store(
            text,
            source="manual",
            tags=tags or ["manual"],
            importance=importance,
        )
        log.info("manual_memory_stored", text_preview=text[:60])

    # ── Extraction ────────────────────────────────────────────────────────────

    async def _extract_facts(self, text: str) -> list[dict]:
        """
        Extract memorable facts from text.
        Tries LLM extraction first, falls back to rule-based.
        """
        try:
            return await self._llm_extract(text)
        except Exception as e:
            log.warning("llm_extraction_failed", error=str(e), fallback="rules")
            return self._rule_extract(text)

    async def _llm_extract(self, text: str) -> list[dict]:
        """Use a small local LLM to extract structured facts."""
        prompt = f"""Extract memorable facts from this conversation. Only extract facts worth remembering long-term (decisions, preferences, names, deadlines, important info). Skip small talk and trivial acknowledgements.

Conversation:
{text[:1500]}

Respond with a JSON array only. Each item has:
- "text": the fact as a short clear statement (max 150 chars)  
- "tags": array of 1-3 relevant tags from: [preference, decision, deadline, person, project, tool, fact, goal]
- "importance": float 0.5-2.0 (2.0 = critical, 1.0 = normal, 0.5 = minor)

If nothing worth remembering, return [].
JSON only, no explanation:"""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 400},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._ollama_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                raw = data.get("response", "").strip()

        # Parse JSON — strip markdown fences if present
        raw = re.sub(r"```json|```", "", raw).strip()
        facts = json.loads(raw)
        if not isinstance(facts, list):
            return []

        # Validate and sanitise
        valid = []
        for f in facts:
            if isinstance(f, dict) and "text" in f and len(f["text"]) > 10:
                valid.append({
                    "text": str(f["text"])[:200],
                    "tags": [str(t) for t in f.get("tags", [])][:5],
                    "importance": float(f.get("importance", 1.0)),
                })
        return valid

    def _rule_extract(self, text: str) -> list[dict]:
        """
        Fallback rule-based extractor. Catches common patterns without LLM.
        Less precise but always works.
        """
        facts = []
        lower = text.lower()

        # Preference patterns
        pref_patterns = [
            r"(?:i prefer|i like|i want|i always|rudra (?:prefers?|likes?|wants?)) (.{10,80})",
            r"(?:default|always use|set .+ to) (.{10,80})",
        ]
        for pat in pref_patterns:
            for m in re.finditer(pat, lower):
                facts.append({"text": m.group(0)[:150], "tags": ["preference"], "importance": 1.2})

        # Decision patterns
        decision_patterns = [
            r"(?:decided?|going with|we'll use|chosen?|picked?) (.{10,80})",
        ]
        for pat in decision_patterns:
            for m in re.finditer(pat, lower):
                facts.append({"text": m.group(0)[:150], "tags": ["decision"], "importance": 1.5})

        # Deadline patterns
        deadline_patterns = [
            r"(?:deadline|due|by|before|until) (?:is |the )?(.{5,50})",
        ]
        for pat in deadline_patterns:
            for m in re.finditer(pat, lower):
                facts.append({"text": m.group(0)[:150], "tags": ["deadline"], "importance": 1.8})

        return facts[:5]  # cap at 5 facts per turn
