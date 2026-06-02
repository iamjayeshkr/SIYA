"""
vani/reasoning/tools/messaging.py
WhatsApp, Telegram, and notification tools — send, read, call, shortcuts.
"""

import re
import time
import logging
import asyncio
from langchain_core.tools import tool

from vani.reasoning.shared import logger

# ── WhatsApp noise word sets ──────────────────────────────────────────────────

_WA_COMMAND_WORDS = {
    "whatsapp", "wa", "message", "msg", "send", "bhejo", "b भेजो",
    "call", "voice", "video", "phone", "lagao", "laga", "milao",
    "karo", "kar", "please", "pls", "to", "ko", "pe", "par",
}

_WA_MESSAGE_STARTERS = {
    "hi", "hii", "hey", "hello", "helo", "namaste", "gm", "gn",
    "kal", "aaj", "abhi", "ok", "okay", "thanks", "thank", "sorry",
    "meeting", "meet", "call", "aa", "aaja", "aja", "sun", "suno",
}

_WA_SURNAME_NOISE = {
    "upadhyay", "upadhaya", "upadhyaya", "sharma", "verma", "varma",
    "singh", "kumar", "kumari", "gupta", "agarwal", "agrawal", "jain",
    "patel", "yadav", "pandey", "pande", "tiwari", "trivedi", "mehta",
    "shah", "rao", "reddy", "nair", "iyer", "khan", "shaikh", "sheikh",
}


def _normalize_whatsapp_contact(contact: str) -> str:
    """Keep WhatsApp search cheap: use first-name query unless user gave only one word."""
    words = [
        w.strip(".,!?;:'\"()[]{}")
        .lower()
        for w in (contact or "").split()
        if w.strip(".,!?;:'\"()[]{}")
    ]
    words = [w for w in words if w not in _WA_COMMAND_WORDS]
    return words[0] if words else ""


def _clean_whatsapp_message(message: str) -> str:
    words = [
        w.strip(".,!?;:'\"()[]{}")
        for w in (message or "").split()
        if w.strip(".,!?;:'\"()[]{}")
    ]
    while words and words[0].lower() in {"bhejo", "send", "message", "msg", "whatsapp", "pe", "par", "ko"}:
        words.pop(0)
    return " ".join(words).strip()


def _split_contact_and_message_after_prefix(text: str) -> tuple[str, str]:
    """
    Prefix commands are ambiguous: "message shrey upadhaya hii".
    For speed/token efficiency, search by first name and drop likely surname words
    before the actual message.
    """
    words = [w.strip(".,!?;:'\"()[]{}") for w in text.split() if w.strip(".,!?;:'\"()[]{}")]
    if not words:
        return "", ""

    contact = words[0]
    rest = words[1:]
    while rest and rest[0].lower() in _WA_SURNAME_NOISE:
        rest.pop(0)

    if rest and rest[0].lower() not in _WA_MESSAGE_STARTERS and len(rest) >= 2:
        rest.pop(0)

    return contact, _clean_whatsapp_message(" ".join(rest))


def _parse_fast_whatsapp_command(query: str):
    """
    Deterministic WhatsApp parser. Avoids Qwen for common voice commands.
    """
    raw = " ".join((query or "").strip().split())
    q = raw.lower()
    if not raw:
        return None

    video = bool(re.search(r"\b(video|vc)\b", q))

    m = re.match(
        r"^(?:whatsapp\s+)?(?:(video|voice)\s+)?call(?:\s+to)?\s+(.+?)(?:\s+(?:ko\s+)?(?:call|lagao|laga|milao|karo|kar))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if m:
        call_type = "video" if video or (m.group(1) and m.group(1).lower() == "video") else "voice"
        contact = _normalize_whatsapp_contact(m.group(2))
        return {"intent": "WHATSAPP_CALL", "contact": contact, "message": "", "call_type": call_type}

    m = re.match(
        r"^(.+?)\s+(?:ko\s+)?(?:(video|voice)\s+)?(?:whatsapp\s+)?call\s*(?:karo|kar|lagao|laga|milao)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if m:
        call_type = "video" if video or (m.group(2) and m.group(2).lower() == "video") else "voice"
        contact = _normalize_whatsapp_contact(m.group(1))
        return {"intent": "WHATSAPP_CALL", "contact": contact, "message": "", "call_type": call_type}

    m = re.match(r"^(?:whatsapp\s+)?(?:message|msg|send)\s+(?:to\s+)?(.+)$", raw, flags=re.IGNORECASE)
    if m:
        contact, message = _split_contact_and_message_after_prefix(m.group(1))
        return {"intent": "WHATSAPP_SEND", "contact": contact, "message": message, "call_type": ""}

    m = re.match(
        r"^(.+?)\s+ko\s+(?:whatsapp\s+)?(?:(?:message|msg)\s+)?(.+?)\s*(?:bhejo|send|kar do|kardo)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if m and re.search(r"\b(message|msg|bhejo|send|whatsapp)\b", q):
        contact = _normalize_whatsapp_contact(m.group(1))
        message = _clean_whatsapp_message(m.group(2))
        return {"intent": "WHATSAPP_SEND", "contact": contact, "message": message, "call_type": ""}

    return None


def _classify_whatsapp_shortcut(query: str) -> str | None:
    q = (query or "").lower().strip()
    if "whatsapp" not in q and not any(x in q for x in ["end call", "mute mic", "unmute mic"]):
        return None

    checks = [
        ("NEW_CHAT", ["new chat", "naya chat", "new whatsapp chat"]),
        ("NEXT_CHAT", ["next chat", "agla chat"]),
        ("PREVIOUS_CHAT", ["previous chat", "pichla chat", "prev chat"]),
        ("SEARCH_CHAT", ["search chat", "chat search", "find chat"]),
        ("SEARCH_WITHIN_CHAT", ["search within chat", "chat ke andar search"]),
        ("CLOSE_CHAT", ["close chat", "chat close"]),
        ("ARCHIVE_CHAT", ["archive chat"]),
        ("MUTE_CHAT", ["mute chat"]),
        ("MARK_UNREAD", ["mark unread", "unread kar"]),
        ("DELETE_CHAT", ["delete chat"]),
        ("PIN_CHAT", ["pin chat", "unpin chat"]),
        ("MUTE_MIC", ["mute mic", "unmute mic", "mic mute", "mic unmute"]),
        ("TOGGLE_CAMERA", ["camera on", "camera off", "toggle camera"]),
        ("END_CALL", ["end call", "decline call", "call cut", "call end"]),
    ]
    for action, phrases in checks:
        if any(p in q for p in phrases):
            return action
    return None


def extract_contact_and_payload(query: str):
    """
    Clean extraction pipeline for WhatsApp/Messaging.
    Uses regex to strip noise and isolate contact + payload.
    """
    fast = _parse_fast_whatsapp_command(query)
    if fast:
        logger.info(f"[WA_FAST_PARSE] {fast}")
        return fast

    q = query.strip()

    intent = ""
    if any(x in q.lower() for x in ["read", "padho"]):
        intent = "WHATSAPP_READ"
    elif any(x in q.lower() for x in ["call", "milao", "lagao", "laga"]):
        intent = "WHATSAPP_CALL"
    elif any(x in q.lower() for x in ["bhejo", "send", "message"]):
        intent = "WHATSAPP_SEND"
    elif any(x in q.lower() for x in ["chat", "kholo", "open"]):
        intent = "WHATSAPP_OPEN_CHAT"

    if intent == "WHATSAPP_OPEN_CHAT":
        messaging_hint = any(x in q.lower() for x in ["whatsapp", "telegram", "wa", "chat"])
        if not messaging_hint:
            intent = ""

    if intent == "WHATSAPP_OPEN_CHAT":
        non_messaging_apps = {
            "youtube", "chrome", "google", "safari", "spotify", "music", "vscode",
            "terminal", "finder", "notes", "calculator", "settings", "browser", "code",
            "intellij", "word", "excel", "powerpoint", "photoshop", "slack", "discord",
            "zoom", "teams", "mail", "gmail", "calendar"
        }
        if any(app in q.lower() for app in non_messaging_apps):
            if not any(x in q.lower() for x in ["whatsapp", "telegram", "chat"]):
                intent = ""

    if intent == "WHATSAPP_CALL":
        media_keywords = {"song", "music", "gana", "geet", "play", "bajao", "baja"}
        if any(w in q.lower() for w in media_keywords):
            if not any(x in q.lower() for x in ["call", "phone", "whatsapp", "wa"]):
                intent = ""

    if intent == "WHATSAPP_SEND":
        non_whatsapp_sends = {"email", "mail", "file", "code"}
        if any(w in q.lower() for w in non_whatsapp_sends):
            if not any(x in q.lower() for x in ["whatsapp", "wa", "message", "msg"]):
                intent = ""

    if intent == "WHATSAPP_READ":
        non_messaging_reads = {"screen", "file", "book", "page", "text", "code", "doc", "document"}
        if any(w in q.lower() for w in non_messaging_reads):
            if not any(x in q.lower() for x in ["whatsapp", "wa", "message", "msg", "chat"]):
                intent = ""

    message = ""
    contact_part = q
    if intent == "WHATSAPP_SEND" and " ko " in q.lower():
        parts = re.split(r'\bko\b', q, maxsplit=1, flags=re.IGNORECASE)
        contact_part = parts[0]
        message = parts[1].strip()
    elif " ko " in q.lower():
        contact_part = re.split(r'\bko\b', q, maxsplit=1, flags=re.IGNORECASE)[0]
    elif " ki chat" in q.lower():
        contact_part = re.split(r'\bki chat\b', q, maxsplit=1, flags=re.IGNORECASE)[0]
    elif " ka chat" in q.lower():
        contact_part = re.split(r'\bka chat\b', q, maxsplit=1, flags=re.IGNORECASE)[0]
    elif " ke message" in q.lower():
        contact_part = re.split(r'\bke message\b', q, maxsplit=1, flags=re.IGNORECASE)[0]

    noise = [
        "ko", "ki", "ke", "ka", "par", "pe", "call", "lagao", "laga", "milao",
        "message", "bhejo", "chat", "open", "whatsapp", "send", "video", "voice",
        "please", "karo", "karke", "wala", "wali", "kholo", "kholna", "padhna", "padho", "read",
        "of", "with", "from", "to", "and", "a", "an", "the"
    ]

    contact = contact_part
    for word in noise:
        contact = re.sub(rf'\b{word}\b', '', contact, flags=re.IGNORECASE)

    contact = _normalize_whatsapp_contact(' '.join(contact.split()).strip())
    message = ' '.join(message.split()).strip()

    for word in ["bhejo", "send", "message", "whatsapp", "karo", "please"]:
        message = re.sub(rf'\b{word}\b', '', message, flags=re.IGNORECASE)
    message = _clean_whatsapp_message(message)

    res = {
        "intent": intent,
        "contact": contact,
        "message": message
    }

    logger.info(f"[RAW_QUERY] {query}")
    logger.info(f"[INTENT] {res['intent']}")
    logger.info(f"[EXTRACTED_CONTACT] {res['contact']}")
    logger.info(f"[MESSAGE] {res['message']}")

    return res


# ── WhatsApp disambiguation — session cache (30m) ─────────────────────────────

_wa_selection_cache = {}
_WA_CACHE_TTL = 1800.0


def _get_wa_cache(query: str):
    entry = _wa_selection_cache.get(query.lower())
    if entry and (time.monotonic() - entry["ts"]) < _WA_CACHE_TTL:
        return entry["name"]
    return None


def _set_wa_cache(query: str, actual: str):
    _wa_selection_cache[query.lower()] = {
        "name": actual,
        "ts": time.monotonic()
    }


async def _resolve_whatsapp_contact(contact: str, action: str) -> tuple[str | None, int, bool]:
    """Returns actual name, count, skip_search."""
    cached = _get_wa_cache(contact)
    if cached:
        return cached, 1, False

    matches = await whatsapp_get_contacts(contact)
    logger.info(f"[WHATSAPP] Results: {matches}")

    if not matches:
        logger.info(f"[WHATSAPP] Contact list empty for '{contact}', using direct search fallback")
        _set_wa_cache(contact, contact)
        return contact, 1, False

    if len(matches) == 1:
        _set_wa_cache(contact, matches[0])
        return matches[0], 1, True

    logger.info(f"[WHATSAPP] Duplicate detected: {len(matches)} matches for {contact}")
    return None, len(matches), True


async def whatsapp_get_contacts(contact: str):
    try:
        from vani.messaging.client import whatsapp_get_contacts as _get
        return await _get(contact)
    except ImportError:
        return []


@tool
async def whatsapp_read(contact: str, limit: int = 10, selection: str = "") -> str:
    """WhatsApp chat padhta hai. contact: jis se chat padhni hai, limit: messages, selection: first/second/1/2 etc."""
    try:
        from vani.messaging.client import whatsapp_read_chat, whatsapp_get_contacts
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."

    idx = 1
    if selection:
        s = selection.lower()
        if "first" in s or "pehla" in s or "pehli" in s or "1" in s: idx = 1
        elif "second" in s or "dusra" in s or "doosri" in s or "2" in s: idx = 2
        elif "third" in s or "teesra" in s or "teesri" in s or "3" in s: idx = 3

    actual_name, count, skip_search = await _resolve_whatsapp_contact(contact, "read")
    if not actual_name:
        if count == 0:
            return f"Mujhe '{contact}' nahi mila."
        matches = await whatsapp_get_contacts(contact)
        names = "\n".join(f"  {i+1}. {m}" for i, m in enumerate(matches[:5]))
        return (f"Mujhe {len(matches)} '{contact}' mile hain:\n{names}\n\n"
                f"Kaunsi open karun? Pehli ya doosri?")

    return await whatsapp_read_chat(actual_name, limit, index=idx, skip_search=skip_search)


@tool
async def whatsapp_send(contact: str, message: str, selection: str = "") -> str:
    """WhatsApp pe message bhejta hai. contact: recipient ka naam, message: text, selection: selection index."""
    try:
        from vani.messaging.client import whatsapp_send_message, whatsapp_get_contacts
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."

    idx = 1
    if selection:
        s = selection.lower()
        if "first" in s or "pehla" in s or "pehli" in s or "1" in s: idx = 1
        elif "second" in s or "dusra" in s or "doosri" in s or "2" in s: idx = 2

    actual_name, count, skip_search = await _resolve_whatsapp_contact(contact, "send")
    if not actual_name:
        if count == 0:
            return f"Mujhe '{contact}' nahi mila."
        matches = await whatsapp_get_contacts(contact)
        names = "\n".join(f"  {i+1}. {m}" for i, m in enumerate(matches[:5]))
        return (f"Mujhe {len(matches)} '{contact}' mile hain. Kisko bhejun? Pehla ya dusra?\n\n{names}")

    return await whatsapp_send_message(actual_name, message, index=idx, skip_search=skip_search)


@tool
async def whatsapp_call(contact: str, call_type: str = "voice", selection: str = "") -> str:
    """WhatsApp call. Calls force the first WhatsApp search result instead of asking on duplicates."""
    try:
        from vani.messaging.client import whatsapp_call as _whatsapp_call_raw
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."

    idx = 1
    if selection:
        s = selection.lower()
        if "first" in s or "pehla" in s or "pehli" in s or "1" in s: idx = 1
        elif "second" in s or "dusra" in s or "doosri" in s or "2" in s: idx = 2

    video = call_type.lower() in ("video", "vid", "v")
    contact_query = _normalize_whatsapp_contact(contact)
    if not contact_query:
        return "Kisko call karna hai?"

    logger.info(f"[WHATSAPP_CALL_FAST] Forcing first result for '{contact_query}'")
    return await _whatsapp_call_raw(contact_query, video, index=idx, skip_search=False)


@tool
async def whatsapp_open_chat(contact: str, selection: str = "") -> str:
    """WhatsApp pe kisi ka chat kholta hai (search + click)."""
    try:
        from vani.messaging.client import whatsapp_get_contacts, whatsapp_open_chat_only
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."

    idx = 1
    if selection:
        s = selection.lower()
        if "first" in s or "pehla" in s or "pehli" in s or "1" in s: idx = 1
        elif "second" in s or "dusra" in s or "doosri" in s or "2" in s: idx = 2

    actual_name, count, skip_search = await _resolve_whatsapp_contact(contact, "open")
    if not actual_name:
        if count == 0:
            return f"Mujhe '{contact}' nahi mila."
        matches = await whatsapp_get_contacts(contact)
        names = "\n".join(f"  {i+1}. {m}" for i, m in enumerate(matches[:5]))
        return f"Mujhe {len(matches)} '{contact}' mile hain. Kaunsa chat kholun?\n\n{names}"

    return await whatsapp_open_chat_only(actual_name, index=idx, skip_search=skip_search)


@tool
async def whatsapp_shortcut(action: str) -> str:
    """WhatsApp Web shortcut automation: next_chat, end_call, mute_mic, archive_chat, etc."""
    try:
        from vani.messaging.client import whatsapp_shortcut as _whatsapp_shortcut
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."
    return await _whatsapp_shortcut(action, target="web")


@tool
async def telegram_read(contact: str, limit: int = 10) -> str:
    """Telegram chat padhta hai. contact: @username ya naam, limit: kitne messages."""
    try:
        from vani.messaging.client import telegram_read_chat
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."
    return await telegram_read_chat(contact, limit)


@tool
async def telegram_send(contact: str, message: str) -> str:
    """Telegram pe message bhejta hai. contact: @username ya naam, message: text."""
    try:
        from vani.messaging.client import telegram_send_message
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."
    return await telegram_send_message(contact, message)


@tool
async def telegram_chats() -> str:
    """Recent Telegram chats aur unka last message dikhata hai."""
    try:
        from vani.messaging.client import telegram_list_chats
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."
    return await telegram_list_chats()


@tool
async def notifications_read(app: str = "all") -> str:
    """Mac notifications padhta hai. app: 'whatsapp', 'telegram', ya 'all'."""
    try:
        from vani.messaging.client import read_whatsapp_notifications, read_mac_notifications
    except ImportError:
        return "❌ vani_messaging.py load nahi hua."
    if app.lower() == "whatsapp":
        return await read_whatsapp_notifications()
    return await read_mac_notifications()


@tool
async def instagram_read(contact: str, limit: int = 10) -> str:
    """Instagram DM padhta hai. contact: username ya display name, limit: kitne messages."""
    try:
        from vani.messaging.client import instagram_read_dm
    except ImportError:
        return "❌ Instagram client load nahi hua."
    return await instagram_read_dm(contact, limit)


@tool
async def instagram_send(contact: str, message: str) -> str:
    """Instagram DM bhejta hai. contact: username ya naam, message: text."""
    try:
        from vani.messaging.client import instagram_send_dm_improved
    except ImportError:
        return "❌ Instagram client load nahi hua."
    return await instagram_send_dm_improved(contact, message)


@tool
async def instagram_send_last(message: str) -> str:
    """
    Instagram ki LAST/LATEST conversation mein message bhejta hai.
    Koi contact name ya ID nahi chahiye — seedha last chat mein bhejta hai.
    Example: 'last Instagram conversation mein hello bhejo'
    """
    try:
        from vani.messaging.client import instagram_send_dm_to_last
    except ImportError:
        return "❌ Instagram client load nahi hua."
    return await instagram_send_dm_to_last(message)


@tool
async def instagram_dms(limit: int = 10) -> str:
    """Recent Instagram DMs dikhata hai."""
    try:
        from vani.messaging.client import instagram_list_dms
    except ImportError:
        return "❌ Instagram client load nahi hua."
    return await instagram_list_dms(limit)