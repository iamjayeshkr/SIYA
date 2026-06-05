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
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        log.warning("[TEXT_CHAT] GOOGLE_API_KEY missing — cannot use Gemini fallback")
        return "Google API key set nahi hai. Baat karne ke liye voice mode use karo."

    # Try modern google-genai SDK first
    try:
        from google import genai
        from vani.prompts import get_realtime_prompt

        client = genai.Client(api_key=api_key)
        model_name = os.getenv("VANI_TEXT_MODEL", "gemini-flash-lite-latest")
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model_name,
                contents=message,
                config={
                    "system_instruction": get_realtime_prompt(),
                }
            )
        )
        text = (response.text or "").strip()
        if text:
            return text
    except Exception as e:
        log.warning(f"[TEXT_CHAT] google-genai Client failed: {e}")

    # Fallback to langchain-google-genai
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from vani.prompts import get_realtime_prompt

        model_name = os.getenv("VANI_TEXT_MODEL", "gemini-flash-lite-latest")
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
        )
        from langchain_core.messages import SystemMessage, HumanMessage
        msgs = [SystemMessage(content=get_realtime_prompt()), HumanMessage(content=message)]
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: llm.invoke(msgs))
        text = (result.content or "").strip()
        if text:
            return text
    except Exception as e:
        log.warning(f"[TEXT_CHAT] LangChain Gemini also failed: {e}")

    return "Kuch hua. Dobara bol sakte ho?"


import re

CONVERSATIONAL_KEYWORDS_EXCLUDE = {
    "open", "kholo", "khol", "play", "bajao", "chalao", "search", "google", "karo", "kardo", "krdo",
    "bhejo", "bhej", "bhejna", "send", "call", "padho", "padhao", "padh", "read", "screen",
    "screenshot", "zoom", "minimize", "close", "band", "delete", "hatao", "hata", "register",
    "enroll", "status", "reminder", "remind", "yaad"
}

def is_conversational_only(message: str) -> bool:
    words = re.findall(r"[a-zA-Z0-9_]{3,}", message.lower())
    if any(w in CONVERSATIONAL_KEYWORDS_EXCLUDE for w in words):
        return False
    return True


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
        memory_reply = await answer_memory_query(message)
        if memory_reply and memory_question:
            return memory_reply
        if any(phrase in lowered for phrase in ("set reminder", "remind me", "yaad dil", "yaad rakh")):
            return "Yaad rakh liya. Restart ke baad bhi mujhe ye reminder yaad rahega."
    except Exception:
        pass

    # First check book memory so that PDF queries aren't bypassed
    book_reply = answer_from_books(message)
    if book_reply:
        return book_reply

    # If not matched in book, and it's conversational only, use direct fast-path Gemini response
    if is_conversational_only(message):
        log.info(f"[TEXT_CHAT] direct route to Gemini for conversational query: {message!r}")
        return await _gemini_conversational_reply(message)

    try:
        from vani.router.intent_classifier import router_classify
        intent, _ = router_classify(message)
    except Exception:
        intent = None

    from vani.reasoning.ollama import _qwen_decide_and_run

    timeout = float(os.getenv("VANI_TEXT_TIMEOUT", "8"))
    try:
        reply = await asyncio.wait_for(_qwen_decide_and_run(message), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning(f"[TEXT_CHAT] Ollama timed out after {timeout}s for: {message!r}")
        reply = ""

    if reply and reply.strip():
        return reply

    # ── Route conversational query to Gemini ──────────────────────────────────
    log.info(f"[TEXT_CHAT] routing to Gemini for conversational reply")
    gemini_reply = await _gemini_conversational_reply(message)
    if gemini_reply and not gemini_reply.startswith("Google API key set") and not gemini_reply.startswith("Kuch hua."):
        return gemini_reply

    log.info(f"[TEXT_CHAT] Gemini failed or key missing — using local Ollama fallback")
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