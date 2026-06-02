"""
vani/model_router.py
────────────────────
Intelligent model routing with health checks and automatic fallback.

The router:
  1. Classifies the request into LIGHTWEIGHT / MEDIUM / HEAVY
  2. Picks the first healthy model in the fallback chain for that tier
  3. Executes the request
  4. On failure → retries next model in chain transparently
  5. Logs every routing decision and failure

Usage:
    from vani.model_router import ModelRouter

    router = ModelRouter()
    await router.start()   # begins background health checks

    response = await router.complete(
        prompt="Summarise this code review",
        tier=ModelTier.MEDIUM,
        system="You are a senior engineer.",
    )
    print(response.text)
    print(response.model_used)  # which model actually handled it
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

from vani.logging_config import get_logger
from vani.model_registry import (
    FALLBACK_CHAINS, MODELS, ModelConfig, ModelProvider, ModelTier
)
from vani.secrets import get_gemini_key, get_ollama_host

log = get_logger("model_router")

HEALTH_CHECK_INTERVAL = 60   # seconds between health pings
HEALTH_CHECK_TIMEOUT  = 5    # seconds before marking model unhealthy


@dataclass
class ModelResponse:
    text: str
    model_used: str
    tier: ModelTier
    provider: ModelProvider
    duration_ms: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fallback_count: int = 0   # how many models failed before this one


# ── Health tracker ────────────────────────────────────────────────────────────

class HealthTracker:
    """Tracks which models are currently healthy."""

    def __init__(self):
        self._healthy: dict[str, bool] = {mid: True for mid in MODELS}
        self._last_check: dict[str, float] = {}
        self._failures: dict[str, int] = {mid: 0 for mid in MODELS}

    def is_healthy(self, model_id: str) -> bool:
        return self._healthy.get(model_id, False)

    def mark_failed(self, model_id: str) -> None:
        self._failures[model_id] = self._failures.get(model_id, 0) + 1
        if self._failures[model_id] >= 2:
            self._healthy[model_id] = False
            log.warning("model_marked_unhealthy", model=model_id,
                        failures=self._failures[model_id])

    def mark_healthy(self, model_id: str) -> None:
        self._healthy[model_id] = True
        self._failures[model_id] = 0

    def healthy_models(self) -> list[str]:
        return [mid for mid, ok in self._healthy.items() if ok]


# ── Model clients ─────────────────────────────────────────────────────────────

class OllamaClient:
    def __init__(self, host: str):
        self.host = host.rstrip("/")

    async def complete(
        self,
        model_name: str,
        prompt: str,
        system: str = "",
        timeout: int = 30,
    ) -> tuple[str, int, int]:
        """Returns (text, prompt_tokens, completion_tokens)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Ollama {resp.status}: {body[:200]}")
                data = await resp.json()

        text = data["message"]["content"]
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        return text, prompt_tokens, completion_tokens

    async def health_check(self, model_name: str) -> bool:
        """Quick ping to see if the model is loaded and responding."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.host}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        return False
                    data = await resp.json()
                    pulled = [m["name"] for m in data.get("models", [])]
                    return any(model_name in p for p in pulled)
        except Exception:
            return False


class GeminiClient:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(
        self,
        model_name: str,
        prompt: str,
        system: str = "",
        timeout: int = 30,
    ) -> tuple[str, int, int]:
        """Returns (text, prompt_tokens, completion_tokens)."""
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        url = f"{self.BASE_URL}/{model_name}:generateContent?key={self.api_key}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 429:
                    raise RuntimeError("Gemini rate limited (429)")
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Gemini {resp.status}: {body[:200]}")
                data = await resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        return text, usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)

    async def health_check(self, model_name: str) -> bool:
        """Ping Gemini with a tiny request."""
        try:
            text, _, _ = await self.complete(model_name, "hi", timeout=HEALTH_CHECK_TIMEOUT)
            return bool(text)
        except Exception:
            return False


# ── Task classifier ───────────────────────────────────────────────────────────

def classify_tier(
    prompt: str,
    needs_vision: bool = False,
    needs_tools: bool = False,
    force_tier: Optional[ModelTier] = None,
) -> ModelTier:
    """
    Classify a prompt into the cheapest tier that can handle it.

    Rules (in priority order):
    - force_tier overrides everything
    - Vision → at least MEDIUM (needs multimodal)
    - Long prompt (>4000 chars) → HEAVY
    - Complex keywords → HEAVY or MEDIUM
    - Everything else → LIGHTWEIGHT
    """
    if force_tier:
        return force_tier

    if needs_vision:
        return ModelTier.HEAVY

    length = len(prompt)

    # Keyword signals for heavy tasks
    heavy_keywords = [
        "analyse", "analyze", "review", "compare", "explain in detail",
        "write a report", "summarise this document", "translate",
        "debug this", "refactor", "architecture",
    ]
    medium_keywords = [
        "summarise", "summarize", "rewrite", "improve", "fix",
        "search for", "find", "research",
    ]

    lower = prompt.lower()

    if length > 4000 or any(kw in lower for kw in heavy_keywords):
        return ModelTier.HEAVY

    if length > 1000 or any(kw in lower for kw in medium_keywords):
        return ModelTier.MEDIUM

    return ModelTier.LIGHTWEIGHT


# ── Main router ───────────────────────────────────────────────────────────────

class ModelRouter:
    """
    Central model routing and fallback engine.

    Create one instance at startup, call start() to begin health checks,
    then use complete() for all LLM calls.
    """

    def __init__(self):
        self.health = HealthTracker()
        self._ollama = OllamaClient(get_ollama_host())
        self._gemini: Optional[GeminiClient] = None
        self._health_task: Optional[asyncio.Task] = None

        gemini_key = get_gemini_key()
        if gemini_key:
            self._gemini = GeminiClient(gemini_key)
        else:
            log.warning("gemini_key_missing", message="Gemini models will be skipped")

    async def start(self) -> None:
        """Start background health checks. Call once at app startup."""
        await self._run_health_checks()   # initial check
        self._health_task = asyncio.create_task(self._health_loop())
        log.info("model_router_started",
                 healthy=self.health.healthy_models())

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()

    # ── Main API ──────────────────────────────────────────────────────────────

    async def complete(
        self,
        prompt: str,
        system: str = "",
        tier: Optional[ModelTier] = None,
        needs_vision: bool = False,
        needs_tools: bool = False,
        force_model: Optional[str] = None,
    ) -> ModelResponse:
        """
        Complete a prompt using the best available model.

        Args:
            prompt:       User / planner prompt text.
            system:       System prompt (optional).
            tier:         Force a specific tier (None = auto-classify).
            needs_vision: Require a vision-capable model.
            needs_tools:  Require a tool-calling model.
            force_model:  Bypass routing and use a specific model id.

        Returns:
            ModelResponse with text + metadata.

        Raises:
            RuntimeError if ALL models in the chain fail.
        """
        if force_model:
            config = MODELS.get(force_model)
            if not config:
                raise ValueError(f"Unknown model id: {force_model}")
            chain = [force_model]
        else:
            resolved_tier = tier or classify_tier(prompt, needs_vision, needs_tools)
            chain = FALLBACK_CHAINS[resolved_tier]

        log.info("model_routing",
                 tier=resolved_tier if not force_model else "forced",
                 chain=chain,
                 prompt_len=len(prompt))

        last_error: Optional[Exception] = None
        fallback_count = 0

        for model_id in chain:
            config = MODELS.get(model_id)
            if not config or not config.enabled:
                continue
            if not self.health.is_healthy(model_id):
                log.info("model_skipped_unhealthy", model=model_id)
                continue

            # Skip Gemini models if no API key
            if config.provider == ModelProvider.GEMINI and not self._gemini:
                continue

            try:
                result = await self._call_model(config, prompt, system)
                result.fallback_count = fallback_count
                self.health.mark_healthy(model_id)

                log.info("model_success",
                         model=model_id,
                         duration_ms=result.duration_ms,
                         prompt_tokens=result.prompt_tokens,
                         completion_tokens=result.completion_tokens,
                         fallbacks_used=fallback_count)
                return result

            except Exception as e:
                last_error = e
                fallback_count += 1
                self.health.mark_failed(model_id)
                log.warning("model_failed",
                            model=model_id,
                            error=str(e),
                            trying_next=True)

        raise RuntimeError(
            f"All models in chain failed. Last error: {last_error}"
        )

    async def _call_model(
        self, config: ModelConfig, prompt: str, system: str
    ) -> ModelResponse:
        t0 = time.monotonic()

        if config.provider == ModelProvider.OLLAMA:
            text, pt, ct = await self._ollama.complete(
                config.model_name, prompt, system, timeout=config.timeout_s
            )
        elif config.provider == ModelProvider.GEMINI:
            text, pt, ct = await self._gemini.complete(
                config.model_name, prompt, system, timeout=config.timeout_s
            )
        else:
            raise RuntimeError(f"Unsupported provider: {config.provider}")

        return ModelResponse(
            text=text,
            model_used=config.id,
            tier=config.tier,
            provider=config.provider,
            duration_ms=int((time.monotonic() - t0) * 1000),
            prompt_tokens=pt,
            completion_tokens=ct,
        )

    # ── Health checks ─────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            await self._run_health_checks()

    async def _run_health_checks(self) -> None:
        tasks = []
        for model_id, config in MODELS.items():
            if not config.enabled or config.id == "gemini-realtime":
                continue
            if config.provider == ModelProvider.GEMINI and not self._gemini:
                continue
            tasks.append(self._check_one(model_id, config))

        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("health_check_done", healthy=self.health.healthy_models())

    async def _check_one(self, model_id: str, config: ModelConfig) -> None:
        try:
            if config.provider == ModelProvider.OLLAMA:
                ok = await self._ollama.health_check(config.model_name)
            elif config.provider == ModelProvider.GEMINI:
                ok = await self._gemini.health_check(config.model_name)
            else:
                ok = False

            if ok:
                self.health.mark_healthy(model_id)
            else:
                self.health.mark_failed(model_id)
        except Exception as e:
            log.debug("health_check_error", model=model_id, error=str(e))
            self.health.mark_failed(model_id)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            mid: {
                "healthy": self.health.is_healthy(mid),
                "provider": MODELS[mid].provider,
                "tier": MODELS[mid].tier,
            }
            for mid in MODELS
            if mid != "gemini-realtime"
        }
