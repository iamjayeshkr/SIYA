"""
vani/p4_streaming.py  —  P4 Streaming Replies
───────────────────────────────────────────────
Adds token streaming from LLM → FastAPI SSE endpoint → React UI.

Words appear in the chat bubble as they're generated, instead of
waiting for the full reply.

Two backends supported:
  1. Ollama (local)   — /api/generate with stream=True
  2. Gemini (cloud)   — GenerativeModel.generate_content_async (streaming)

Usage (Python backend side):
    from vani.p4_streaming import stream_response
    async for chunk in stream_response(prompt, model="qwen2.5:7b"):
        # chunk is a plain string token/word fragment
        print(chunk, end="", flush=True)

FastAPI SSE endpoint (added to app.py):
    GET /stream?text=...  →  text/event-stream
"""

import asyncio
import json
from typing import AsyncIterator, Optional

import aiohttp

from vani.logging_config import get_logger
from vani.secrets import get_ollama_host, get_gemini_key

log = get_logger("p4.streaming")


# ── Ollama streaming ──────────────────────────────────────────────────────────

async def _stream_ollama(
    prompt: str,
    model: str,
    system: str = "",
    host: Optional[str] = None,
) -> AsyncIterator[str]:
    """Stream tokens from Ollama's /api/generate endpoint."""
    ollama_host = host or get_ollama_host() or "http://127.0.0.1:11434"
    url = f"{ollama_host}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": 512, "temperature": 0.7},
    }
    if system:
        payload["system"] = system

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                resp.raise_for_status()
                async for raw_line in resp.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        token = obj.get("response", "")
                        if token:
                            yield token
                        if obj.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        log.error("ollama_stream_error", error=str(e), model=model)
        yield f"[streaming error: {e}]"


# ── Gemini streaming ──────────────────────────────────────────────────────────

async def _stream_gemini(
    prompt: str,
    model: str = "gemini-2.0-flash",
    system: str = "",
) -> AsyncIterator[str]:
    """Stream tokens from Google Gemini."""
    try:
        import google.generativeai as genai
        api_key = get_gemini_key()
        if not api_key:
            yield "[Gemini API key not found]"
            return

        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(
            model_name=model,
            system_instruction=system if system else None,
        )
        # Gemini streaming is sync; run in executor
        loop = asyncio.get_event_loop()

        def _sync_stream():
            return gmodel.generate_content(prompt, stream=True)

        response = await loop.run_in_executor(None, _sync_stream)
        for chunk in response:
            text = chunk.text if hasattr(chunk, "text") else ""
            if text:
                yield text
                # small yield to let other tasks breathe
                await asyncio.sleep(0)

    except ImportError:
        yield "[google-generativeai not installed]"
    except Exception as e:
        log.error("gemini_stream_error", error=str(e), model=model)
        yield f"[streaming error: {e}]"


# ── Public API ────────────────────────────────────────────────────────────────

async def stream_response(
    prompt: str,
    model: str = "qwen2.5:7b",
    system: str = "",
    provider: Optional[str] = None,   # "ollama" | "gemini" | None (auto-detect)
) -> AsyncIterator[str]:
    """
    Stream LLM tokens. Auto-detects provider from model name if not specified.

    Yields:
        str chunks (token fragments, typically 1-4 words)
    """
    # Auto-detect provider
    if provider is None:
        if any(x in model for x in ("gemini", "flash", "pro")):
            provider = "gemini"
        else:
            provider = "ollama"

    log.info("stream_start", model=model, provider=provider)

    if provider == "gemini":
        async for chunk in _stream_gemini(prompt, model=model, system=system):
            yield chunk
    else:
        async for chunk in _stream_ollama(prompt, model=model, system=system):
            yield chunk


# ── FastAPI SSE helper ────────────────────────────────────────────────────────

async def sse_stream_generator(
    prompt: str,
    model: str = "qwen2.5:7b",
    system: str = "",
) -> AsyncIterator[str]:
    """
    Wraps stream_response in Server-Sent Events format.
    Use with FastAPI's StreamingResponse.

    Each yielded string is a complete SSE line.
    """
    full_text = []
    try:
        async for chunk in stream_response(prompt, model=model, system=system):
            full_text.append(chunk)
            payload = json.dumps({"token": chunk, "done": False})
            yield f"data: {payload}\n\n"

        # Final event with full assembled text
        complete = json.dumps({"token": "", "done": True, "full_text": "".join(full_text)})
        yield f"data: {complete}\n\n"

    except asyncio.CancelledError:
        yield f"data: {json.dumps({'token': '', 'done': True, 'cancelled': True})}\n\n"
        raise
