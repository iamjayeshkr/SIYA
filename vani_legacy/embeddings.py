"""
vani/embeddings.py
──────────────────
Generates text embeddings using nomic-embed-text via Ollama.
Runs 100% locally — zero API cost, zero network dependency.

Model: nomic-embed-text (768-dimensional vectors)
Pull once: ollama pull nomic-embed-text

Usage:
    from vani.embeddings import embed, embed_batch

    vector = await embed("remind me about the project meeting")
    vectors = await embed_batch(["text one", "text two"])
"""

import asyncio
import json
from typing import Optional

import aiohttp

from vani.logging_config import get_logger
from vani.secrets import get_ollama_host

log = get_logger("embeddings")

EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text output dimension


def _ollama_embed_url() -> str:
    host = get_ollama_host().rstrip("/")
    return f"{host}/api/embeddings"


async def embed(text: str, session: Optional[aiohttp.ClientSession] = None) -> list[float]:
    """
    Generate a 768-dim embedding vector for a single text string.

    Args:
        text:    Input text (will be truncated to ~2000 chars if too long).
        session: Optional shared aiohttp session (reuse for batch calls).

    Returns:
        List of 768 floats.
    """
    # nomic-embed-text has an 8192 token context; ~4 chars/token → ~32k chars safe
    # Truncate conservatively to avoid silent failures
    text = text[:8000].strip()
    if not text:
        return [0.0] * EMBED_DIM

    payload = {"model": EMBED_MODEL, "prompt": text}

    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession()

    try:
        async with session.post(
            _ollama_embed_url(),
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                log.error("embed_failed", status=resp.status, body=body[:200])
                return [0.0] * EMBED_DIM
            data = await resp.json()
            return data["embedding"]
    except Exception as e:
        log.error("embed_error", error=str(e))
        return [0.0] * EMBED_DIM
    finally:
        if owns_session:
            await session.close()


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed multiple texts concurrently (up to 8 at once to avoid overwhelming Ollama).

    Returns list of vectors in same order as input texts.
    """
    CONCURRENCY = 8
    sem = asyncio.Semaphore(CONCURRENCY)

    async with aiohttp.ClientSession() as session:
        async def _embed_one(text: str) -> list[float]:
            async with sem:
                return await embed(text, session=session)

        results = await asyncio.gather(*[_embed_one(t) for t in texts])
    return list(results)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. Used for quick checks without sqlite-vec."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
