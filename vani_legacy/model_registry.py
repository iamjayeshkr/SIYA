"""
vani/model_registry.py
──────────────────────
Defines all models Vani can route to, their capabilities, cost tiers,
and health state.

Three tiers:
  LIGHTWEIGHT  → local Ollama (free, fast, ~1-4B params)
  MEDIUM       → local Ollama or Gemini Flash (cheap, capable)
  HEAVY        → Gemini Pro / GPT-4o (expensive, best quality)

The router picks the cheapest model that can handle the task,
automatically falling back up the chain on failure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ModelTier(str, Enum):
    LIGHTWEIGHT = "lightweight"   # local, free, fast
    MEDIUM      = "medium"        # local or cheap API
    HEAVY       = "heavy"         # best API models


class ModelProvider(str, Enum):
    OLLAMA  = "ollama"
    GEMINI  = "gemini"
    OPENAI  = "openai"   # optional fallback


@dataclass
class ModelConfig:
    id: str                          # internal name used in code
    provider: ModelProvider
    model_name: str                  # actual model string sent to API
    tier: ModelTier
    context_window: int              # max input tokens
    supports_tools: bool = False     # can do function/tool calling
    supports_vision: bool = False    # can process images
    supports_audio: bool = False     # native audio (Gemini Realtime only)
    cost_per_1k_tokens: float = 0.0  # USD, 0 = free local
    max_retries: int = 2
    timeout_s: int = 30
    enabled: bool = True
    notes: str = ""


# ── Model catalogue ───────────────────────────────────────────────────────────

MODELS: dict[str, ModelConfig] = {

    # ── Lightweight (free, local) ─────────────────────────────────────────────
    "qwen2.5-3b": ModelConfig(
        id="qwen2.5-3b",
        provider=ModelProvider.OLLAMA,
        model_name="qwen2.5:3b",
        tier=ModelTier.LIGHTWEIGHT,
        context_window=32_000,
        supports_tools=True,
        cost_per_1k_tokens=0.0,
        timeout_s=20,
        notes="Fast local model. Intent classification, simple Q&A, extraction.",
    ),
    "qwen2.5-7b": ModelConfig(
        id="qwen2.5-7b",
        provider=ModelProvider.OLLAMA,
        model_name="qwen2.5:7b",
        tier=ModelTier.LIGHTWEIGHT,
        context_window=32_000,
        supports_tools=True,
        cost_per_1k_tokens=0.0,
        timeout_s=25,
        notes="Better reasoning than 3B. Primary local workhorse.",
    ),
    "llama3.2-3b": ModelConfig(
        id="llama3.2-3b",
        provider=ModelProvider.OLLAMA,
        model_name="llama3.2:3b",
        tier=ModelTier.LIGHTWEIGHT,
        context_window=128_000,
        supports_tools=True,
        cost_per_1k_tokens=0.0,
        timeout_s=20,
        notes="Fallback lightweight if Qwen unavailable.",
    ),

    # ── Medium ────────────────────────────────────────────────────────────────
    "qwen2.5-14b": ModelConfig(
        id="qwen2.5-14b",
        provider=ModelProvider.OLLAMA,
        model_name="qwen2.5:14b",
        tier=ModelTier.MEDIUM,
        context_window=32_000,
        supports_tools=True,
        cost_per_1k_tokens=0.0,
        timeout_s=40,
        notes="Strong local model. Complex reasoning, code generation.",
    ),
    "gemini-flash": ModelConfig(
        id="gemini-flash",
        provider=ModelProvider.GEMINI,
        model_name="gemini-1.5-flash",
        tier=ModelTier.MEDIUM,
        context_window=1_000_000,
        supports_tools=True,
        supports_vision=True,
        cost_per_1k_tokens=0.000075,
        timeout_s=30,
        notes="Fast, cheap Gemini. Great for tool-heavy medium tasks.",
    ),

    # ── Heavy ─────────────────────────────────────────────────────────────────
    "gemini-pro": ModelConfig(
        id="gemini-pro",
        provider=ModelProvider.GEMINI,
        model_name="gemini-1.5-pro",
        tier=ModelTier.HEAVY,
        context_window=2_000_000,
        supports_tools=True,
        supports_vision=True,
        cost_per_1k_tokens=0.00125,
        timeout_s=60,
        notes="Best quality. Complex analysis, long documents.",
    ),
    "gemini-realtime": ModelConfig(
        id="gemini-realtime",
        provider=ModelProvider.GEMINI,
        model_name="gemini-2.0-flash-exp",
        tier=ModelTier.HEAVY,
        context_window=128_000,
        supports_tools=True,
        supports_audio=True,
        cost_per_1k_tokens=0.0,   # billed per audio minute
        timeout_s=0,              # streaming, no timeout
        notes="Talker Twin — Gemini Realtime voice. Never used for text routing.",
    ),
}

# ── Fallback chains per tier ──────────────────────────────────────────────────
# Ordered: try each in sequence until one succeeds.

FALLBACK_CHAINS: dict[ModelTier, list[str]] = {
    ModelTier.LIGHTWEIGHT: [
        "qwen2.5-7b",
        "qwen2.5-3b",
        "llama3.2-3b",
    ],
    ModelTier.MEDIUM: [
        "qwen2.5-14b",
        "qwen2.5-7b",      # degrade to local if API down
        "gemini-flash",    # try API if local 14B not pulled
    ],
    ModelTier.HEAVY: [
        "gemini-pro",
        "gemini-flash",    # degrade to flash if pro rate-limited
        "qwen2.5-14b",    # last resort: local
    ],
}
