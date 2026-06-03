import asyncio
import os
import logging

from vani.memory.book_memory import answer_from_books, list_learned_books
from vani.services.wake import WAKE_ACK_REPLY, is_wake_command

log = logging.getLogger("vani.text_chat")

BOOK_LIST_PHRASES = (
    "learned books",
    "learnt books",
    "uploaded books",
    "book memory",
    "pdf memory",
)


async def _gemini_conversational_reply(message: str) -> str:
    """
    Direct Gemini text reply for conversational messages where Ollama
    decided no tool is needed. This is the fix for Vani going silent.
    """
    try:
        import google.generativeai as genai  # type: ignore
        from vani.prompts import get_realtime_prompt

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            log.warning("[TEXT_CHAT] GOOGLE_API_KEY missing — cannot use Gemini fallback")
            return "Google API key set nahi hai. Baat karne ke liye voice mode use karo."

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=os.getenv("VANI_TEXT_MODEL", "gemini-2.0-flash"),
            system_instruction=get_realtime_prompt(),
        )
        response = model.generate_content(message, stream=True)
        parts = []
        for chunk in response:
            if chunk.text:
                parts.append(chunk.text)
        text = "".join(parts).strip()
        if text:
            return text
    except ImportError:
        log.warning("[TEXT_CHAT] google-generativeai not installed — pip install google-generativeai")
    except Exception as e:
        log.warning(f"[TEXT_CHAT] Gemini fallback failed: {e}")

    # Last resort: try langchain-google-genai
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from vani.prompts import get_realtime_prompt

        llm = ChatGoogleGenerativeAI(
            model=os.getenv("VANI_TEXT_MODEL", "gemini-2.0-flash"),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        )
        from langchain_core.messages import SystemMessage, HumanMessage
        msgs = [SystemMessage(content=get_realtime_prompt()), HumanMessage(content=message)]
        result = llm.invoke(msgs)
        text = (result.content or "").strip()
        if text:
            return text
    except Exception as e:
        log.warning(f"[TEXT_CHAT] LangChain Gemini also failed: {e}")

    return "Kuch hua. Dobara bol sakte ho?"


async def handle_text_command(message: str) -> str:
    lowered = message.lower()
    if is_wake_command(message):
        return WAKE_ACK_REPLY

    if any(phrase in lowered for phrase in BOOK_LIST_PHRASES):
        return list_learned_books()

    try:
        from vani.memory.working_memory import answer_memory_query, record_user_signal
        memory_question = any(
            phrase in lowered
            for phrase in (
                "kya yaad", "what do you remember", "which reminder", "what reminder",
                "kaunsa reminder", "kya reminder", "pending",
                "last topic", "working on", "kaam kar raha", "kaam kar rha",
            )
        )
        # Only record signal for real user queries, not wake-word echos or memory queries
        if not memory_question and len(message.split()) > 1:
            record_user_signal(message)
        memory_reply = answer_memory_query(message)
        if memory_reply and memory_question:
            return memory_reply
        if any(phrase in lowered for phrase in ("set reminder", "remind me", "yaad dil", "yaad rakh")):
            return "Yaad rakh liya. Restart ke baad bhi mujhe ye reminder yaad rahega."
    except Exception:
        pass

    try:
        from vani.router.intent_classifier import router_classify
        intent, _ = router_classify(message)
    except Exception:
        intent = None

    if not intent:
        book_reply = answer_from_books(message)
        if book_reply:
            return book_reply

    from vani.reasoning.ollama import _qwen_decide_and_run

    timeout = float(os.getenv("VANI_TEXT_TIMEOUT", "8"))
    try:
        reply = await asyncio.wait_for(_qwen_decide_and_run(message), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning(f"[TEXT_CHAT] Ollama timed out after {timeout}s for: {message!r}")
        reply = ""

    if reply and reply.strip():
        return reply

    # ── FIX: Ollama returned empty (null tool = conversational query) ──────────
    # Route to Gemini for a real text answer instead of going silent.
    log.info(f"[TEXT_CHAT] using direct Ollama for conversational reply")
    import requests
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen2.5:3b", "prompt": message, "stream": False},
            timeout=10
        )
        return r.json().get("response", "Kuch samajh nahi aaya.").strip()
    except Exception as e:
        return f"Error: {e}"