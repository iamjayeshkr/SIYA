"""
vani/reasoning/ollama.py
Ollama HTTP client, LRU response cache, and Qwen decide-and-run loop.
"""

import json
import re
import asyncio
import logging
import threading
from collections import OrderedDict

from vani.reasoning.shared import logger, OLLAMA_URL, OLLAMA_MODEL
from vani.reasoning.registry import get_tool, get_all_tool_descriptions
from vani.reasoning.router import _router_classify, _router_classify_many, _dispatch_intent, _is_learn_intent

_OLLAMA_RESPONSE_CACHE: OrderedDict = OrderedDict()
_OLLAMA_CACHE_MAX = 30

# Cap concurrent Ollama calls to 1 — bound to the current event loop
_ollama_semaphore: "asyncio.Semaphore | None" = None
_ollama_semaphore_loop: "asyncio.AbstractEventLoop | None" = None


def _dispatch_intent_in_thread(intent: str, data, query: str) -> None:
    def _run():
        try:
            asyncio.run(_dispatch_intent(intent, data, query))
        except Exception as e:
            logger.error(f"[ROUTER] Background intent failed: {intent} {data} -> {e}")

    threading.Thread(
        target=_run,
        daemon=True,
        name=f"vani-compound-{intent.lower()}",
    ).start()


def _call_ollama_sync(prompt: str) -> str:
    """Synchronous streaming HTTP call — lower TTFT than stream=False."""
    import requests

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": True},
            timeout=30,
            stream=True,
        )
        resp.raise_for_status()
        parts = []
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                parts.append(chunk.get("response", ""))
                if chunk.get("done", False):
                    break
            except json.JSONDecodeError:
                continue
        return "".join(parts).strip()
    except requests.exceptions.ConnectionError:
        logger.error("[Qwen] Ollama not running! Start it: ollama serve")
        return '{"tool": null, "args": {}}'
    except Exception as e:
        logger.error(f"[Qwen] Ollama error: {e}")
        return '{"tool": null, "args": {}}'


def _build_qwen_prompt(query: str) -> str:
    return f"""You are a task dispatcher for a voice assistant named Vani.
Given the user's request, decide which tool to call and with what arguments.

Available tools:
{get_all_tool_descriptions()}

IMPORTANT RULES:
- Respond ONLY with valid JSON, no explanation, no markdown fences
- Format: {{"tool": "tool_name", "args": {{"param": "value"}}}}
- If no tool needed: {{"tool": null, "args": {{}}}}
- For save_note: always use "title" and "content" keys
- For open_youtube_and_play: use "song_or_query" key
- For websites/domains like "open example.com", "github.com kholo", use open_url_in_browser with browser="default"
- For search requests, clean filler words and use google_search with the real query only

MESSAGING RULES (very important):
- "X ke chats padhao", "X ka WhatsApp padho", "X ne kya bheja" → whatsapp_read with contact=X
- "X ko WhatsApp karo", "X ko message bhejo WhatsApp pe" → whatsapp_send with contact=X
- "X ko call karo", "call X", "X ko WhatsApp call karo" → whatsapp_call with contact=X, call_type='voice'
- "X ko video call karo", "X se video pe baat karo" → whatsapp_call with contact=X, call_type='video'
- "WhatsApp next chat", "end call", "mute mic" → whatsapp_shortcut with matching action
- "X ka Telegram padho", "X ke Telegram messages" → telegram_read with contact=X
- "X ko Telegram pe bhejo" → telegram_send with contact=X
- "recent chats", "Telegram chats dikhao" → telegram_chats
- "WhatsApp messages padho", "recent WhatsApp" → notifications_read with app='whatsapp'
- NEVER use tool name "whatsapp_chats" — use notifications_read or whatsapp_read instead.
- NEVER use tool name "open_whatsapp" — use open_application with app_name='WhatsApp' instead.
- "notifications padho", "kya aaya hai" → notifications_read
- "gana pause kar", "play music", "next song" → media_control with action='pause'/'play'/'next'
- NEVER use open_youtube_and_play for messaging requests
- NEVER use google_search for messaging requests
- "screen dekho", "read my screen", "yeh kya hai", "isko explain kar" → read_screen
- "what am I watching", "current page kya hai", "active tab batao" → read_screen

Examples:
- "open example.com" → {{"tool": "open_url_in_browser", "args": {{"url": "example.com", "browser": "default"}}}}
- "AI tools google karo" → {{"tool": "google_search", "args": {{"query": "AI tools"}}}}
- "Harshit ke WhatsApp chats padhao" → {{"tool": "whatsapp_read", "args": {{"contact": "Harshit"}}}}
- "Shrey ko call karo" → {{"tool": "whatsapp_call", "args": {{"contact": "Shrey", "call_type": "voice"}}}}
- "shape of you bajao" → {{"tool": "open_youtube_and_play", "args": {{"song_or_query": "shape of you"}}}}

User request: {query}"""


async def _qwen_decide_and_run(query: str) -> str:
    """Ask Qwen which tool to call, parse response, execute tool."""
    global _ollama_semaphore, _ollama_semaphore_loop
    logger.info(f"[ROUTER] Raw: {query}")

    # Instant filler — skip in text mode (no realtime session active)
    pass

    try:
        from vani.memory.working_memory import answer_memory_query, record_user_signal, extract_and_store_facts
        record_user_signal(query)
        asyncio.create_task(extract_and_store_facts(query))
        memory_reply = await answer_memory_query(query)
        if memory_reply and any(p in query.lower() for p in [
            "kya yaad", "what do you remember", "reminder", "pending", "last topic", "working on"
        ]):
            return memory_reply
    except Exception as e:
        logger.warning(f"[WORKING_MEMORY] signal failed: {e}")

    compound_actions = _router_classify_many(query)
    if compound_actions:
        logger.info(f"[ROUTER] Compound actions: {compound_actions}")
        for intent, data, part in compound_actions:
            _dispatch_intent_in_thread(intent, data, part)
        return f"✅ {len(compound_actions)} kaam parallel start ho gaye."

    intent, data = _router_classify(query)
    if intent:
        logger.info(f"[ROUTER] Intent: {intent} -> dispatching directly, no Ollama needed")
        return await _dispatch_intent(intent, data, query)

    try:
        from vani.memory.book_memory import answer_from_books, list_learned_books
        lowered = query.lower()
        if any(phrase in lowered for phrase in ["learned books", "learnt books", "uploaded books", "book memory", "pdf memory"]):
            return list_learned_books()
        book_reply = answer_from_books(query)
        if book_reply:
            return book_reply
    except Exception as e:
        logger.warning(f"[BOOK_MEMORY] lookup failed: {e}")

    if _is_learn_intent(query):
        logger.info(f"[LEARN] Intent detected: {query!r}")
        from vani.reasoning.screen import learn_this
        return await learn_this.ainvoke({"content": query, "raw": query})

    # ── Ollama path — check cache first ──────────────────────────────────────
    cache_key = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", query.lower())).strip()
    if cache_key in _OLLAMA_RESPONSE_CACHE:
        raw = _OLLAMA_RESPONSE_CACHE[cache_key]
        logger.info(f"[Qwen] Cache hit: {cache_key!r}")
    else:
        prompt = _build_qwen_prompt(query)
        loop = asyncio.get_running_loop()
        loop = asyncio.get_running_loop()
        if _ollama_semaphore is None or _ollama_semaphore_loop is not loop:
            _ollama_semaphore = asyncio.Semaphore(1)
            _ollama_semaphore_loop = loop
        async with _ollama_semaphore:
            raw = await loop.run_in_executor(None, _call_ollama_sync, prompt)
            await asyncio.sleep(0.1)
        if len(_OLLAMA_RESPONSE_CACHE) >= _OLLAMA_CACHE_MAX:
            _OLLAMA_RESPONSE_CACHE.popitem(last=False)
        _OLLAMA_RESPONSE_CACHE[cache_key] = raw

    logger.info(f"[Qwen] Raw response: {raw}")

    try:
        clean = raw.strip()
        for fence in ["```json", "```"]:
            clean = clean.replace(fence, "")
        try:
            decision = json.loads(clean.strip())
        except json.JSONDecodeError:
            # Fallback AST parsing if Ollama outputs Python tool call syntax (e.g. tool_name(key=val))
            import ast
            parsed = None
            try:
                node = ast.parse(clean.strip(), mode='eval').body
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    tool_name = node.func.id
                    args = {}
                    for kw in node.keywords:
                        if isinstance(kw.value, ast.Constant):
                            args[kw.arg] = kw.value.value
                        elif hasattr(kw.value, 'value'):
                            args[kw.arg] = kw.value.value
                        elif isinstance(kw.value, ast.Str):
                            args[kw.arg] = kw.value.s
                        elif isinstance(kw.value, ast.Num):
                            args[kw.arg] = kw.value.n
                    parsed = {"tool": tool_name, "args": args}
            except Exception:
                pass
            
            if parsed:
                decision = parsed
                logger.info(f"[Qwen] Parsed Python tool call format via AST: {decision}")
            else:
                raise
    except Exception as exc:
        logger.warning(f"[Qwen] Could not parse decision: {raw} -> {exc}")
        # Ollama returned garbage — don't leave Vani silent
        return "Ek second, kuch issue hua. Dobara bol sakte ho?"

    tool_name = decision.get("tool")
    args = decision.get("args", {})

    if not tool_name or tool_name == "null":
        # Ollama decided no tool needed — text_chat.py will route to Gemini for a reply.
        # This is the normal conversational path; returning "" signals "no tool ran".
        logger.info(f"[Qwen] No tool needed for: {query!r} — text_chat will call Gemini directly")
        return ""

    tool_fn = get_tool(tool_name)
    if not tool_fn:
        logger.warning(f"[Qwen] Unknown tool requested: {tool_name}")
        return f"Tool '{tool_name}' nahi mila."

    logger.info(f"[Qwen] Executing: {tool_name}({args})")
    try:
        try:
            from vani.memory.working_memory import record_tool_signal
            record_tool_signal(tool_name, args)
        except Exception:
            pass
        if hasattr(tool_fn, "ainvoke"):
            result = await tool_fn.ainvoke(args or {})
        else:
            result = await tool_fn(**args) if args else await tool_fn()
        return str(result)
    except Exception as e:
        logger.error(f"[Qwen] Tool '{tool_name}' failed: {e}")
        return f"❌ {tool_name} error: {e}"