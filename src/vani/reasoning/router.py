"""
vani/reasoning/router.py
Deterministic intent classifier and dispatcher — runs before Ollama to save tokens.
"""

import re
import asyncio
import logging

from vani.reasoning.shared import logger
from vani.reasoning.registry import _TOOLS
from vani.reasoning.tools.apps import _classify_app_intent, _looks_like_url, _clean_spoken_domain
from vani.reasoning.tools.messaging import (
    _classify_whatsapp_shortcut,
    _parse_fast_whatsapp_command,
    _normalize_whatsapp_contact,
    _clean_whatsapp_message,
    extract_contact_and_payload,
)
from vani.reasoning.tools.media import _classify_media_intent
from vani.reasoning.tools.youtube import youtube_control
# v3 browser_regex: replaces the old per-file classify_youtube_query with the
# unified classify_browser_intent covering browser, YouTube AND search intents.
from vani.reasoning.browser_regex import (
    classify_browser_intent,
    classify_youtube_query as _classify_youtube_query_compat,
)
# Line 21 — change karo:
from vani.reasoning.screen import _is_screen_intent as _is_screen_read_intent
from vani.browser.search import classify_hinglish_question_as_search as _classify_hinglish_search


# ── Teach/Learn intent pattern ────────────────────────────────────────────────
# Triggers Vanni's visual teaching mode.
# Matches: "teach me X", "explain X", "samjhao X", "padha X", "what is X",
#          "how does X work", "diagram of X", "flowchart of X", "sikha X"
#          "mujhe X samajhna hai", "X kya hota hai", "X ka concept"
_TEACH_RE = re.compile(
    r"(?:"
    r"(?:teach|explain|describe|define|summarize)\s+(?:me\s+)?(?:about\s+)?"
    r"|(?:samjhao|samjha|padha|padh|sikha|sikho|bata|batao)\s+(?:mujhe\s+)?"
    r"|(?:mujhe|mujhe)\s+.{0,30}(?:samajhna|seekhna|pata|jaanna)\s*(?:hai|he)?"
    r"|(?:what\s+is|what\s+are|what\s+was|who\s+is|who\s+was|how\s+does|how\s+do|why\s+is|why\s+does)\s+"
    r"|(?:kya\s+hai|kya\s+hota|kaise\s+kaam|kaise\s+hota|kyun\s+hota)\s+"
    r"|(?:diagram|flowchart|mindmap|timeline|visual)\s+(?:of|for|banao|bana|dikhao)\s+"
    r"|(?:concept\s+of|theory\s+of|meaning\s+of|definition\s+of)\s+"
    r"|(?:X\s+)?(?:ka|ki|ke)\s+concept\s*(?:kya|batao|samjhao)?"
    r")",
    re.IGNORECASE,
)

_STUDY_START_RE = __import__("re").compile(
    r"(study.*(shuru|start|karte|chalao|lagao)|padhai.*(shuru|start|karte|lagao)|"
    r"focus.*(mode|on|karo|shuru)|pomodoro.*(start|shuru|lagao)|\b(study session|padhai session)\b|"
    r"\d+\s*min.*padh|padh.*\d+\s*min)", __import__("re").IGNORECASE
)
_STUDY_END_RE = __import__("re").compile(
    r"(study.*(khatam|band|end|stop|rok)|session.*(khatam|end|stop)|break.*(lete|lo|karte)|padhai.*(band|rok|khatam))",
    __import__("re").IGNORECASE
)
_STUDY_STATUS_RE = __import__("re").compile(
    r"(kitna.*(time|bcha|hua)|timer.*(check|dekh|kya)|session.*(status|kitna|time))",
    __import__("re").IGNORECASE
)
# ── Finance CA intent patterns ────────────────────────────────────────────────
_FINANCE_EMI_RE = re.compile(
    r"(emi\s*(calculate|nikalo|kya|batao)|loan.*(emi|calculate|monthly|installment)|"
    r"home\s*loan.*emi|car\s*loan.*emi|personal\s*loan.*emi|"
    r"emi.*kya\s*(hoga|hai)|kitna\s*emi|monthly\s*(installment|payment).*loan)",
    re.IGNORECASE,
)
_FINANCE_SIP_RE = re.compile(
    r"(sip.*(calculate|returns?|kitna|future|value|result)|"
    r"sip.*\d+.*year|mutual\s*fund.*return.*calculate)",
    re.IGNORECASE,
)
_FINANCE_CALENDAR_RE = re.compile(
    r"(gst.*(deadline|date|kab|filing)|itr.*(deadline|last\s*date|kab)|"
    r"advance\s*tax.*(date|kab|deadline)|tds.*(return|deadline|kab)|"
    r"compliance.*(calendar|dates?)|tax\s*(deadline|due\s*date)|"
    r"filing.*(deadline|date))",
    re.IGNORECASE,
)
_FINANCE_TAX_RE = re.compile(
    r"(income\s*tax\s*(slab|rate|kya|kitna)|tax\s*(slab|bracket|rate)|"
    r"itr.*(kab|kaise|file|types?|deadline)|80c|80d|hra\s*(deduction|exempt)|"
    r"old\s*(vs|or)\s*new\s*regime|new\s*regime|tax\s*saving|"
    r"section\s*8[0-9][a-z]|tax.*bachao|tax.*save|kitna\s*tax)",
    re.IGNORECASE,
)
_FINANCE_INVEST_RE = re.compile(
    r"(elss|ppf|nps|fd\s*(vs|or)|fixed\s*deposit\s*(vs|or)|"
    r"invest.*(kahan|kaise|best|where|recommend)|"
    r"mutual\s*fund.*(kaise|kharidna|recommend|types)|"
    r"sip\s*vs\s*(fd|lumpsum|ppf)|"
    r"portfolio.*(banao|suggest|help)|financial\s*planning|wealth.*creation|"
    r"best.*investment|investment.*options?|demat\s*account|paise.*kahan\s*lagao)",
    re.IGNORECASE,
)
_FINANCE_RATIO_RE = re.compile(
    r"(p/?e\s*(ratio|kya|explain|matlab)|roe\s*(kya|explain|ratio)|"
    r"ebitda\s*(margin|kya|explain)|debt.*(equity|ratio|kya)|"
    r"current\s*ratio|eps\s*(kya|explain|ratio)|roce\s*(kya|explain)|"
    r"financial\s*ratio|stock.*ratio|balance\s*sheet.*ratio)",
    re.IGNORECASE,
)
_FINANCE_QUERY_RE = re.compile(
    r"(ca\s*(ban|hai|bano|hoja|ki\s*tarah)|chartered\s*accountant|"
    r"gst.*(kya|explain|kaise|rate|input|credit)|tds.*(kya|kaise|rate|explain)|"
    r"balance\s*sheet.*(explain|kya|samjhao)|"
    r"profit.*(loss|kya|statement)|cash\s*flow|depreciation\s*(kya|explain)|"
    r"accounting.*(explain|basics?|kya)|journal\s*entry|"
    r"financial\s*(statement|planning|advice|help|goal)|"
    r"retirement.*(plan|savings?)|emergency\s*fund|"
    r"capital\s*gain|ltcg|stcg|"
    r"mujhe.*finance.*samjhao|finance.*gyaan|paise.*manage)",
    re.IGNORECASE,
)


# ── Voice enrollment intent patterns ─────────────────────────────────────────
# Matches English + Hinglish variants:
#   "register my voice", "enroll my voice", "save my voice"
#   "meri awaaz register karo", "meri voice save karo"
#   "voice register karo", "awaaz enroll karo"
#   "delete my voice", "voice hatao", "voiceprint delete karo"
#   "voice registered hai kya", "kya main enrolled hoon"
_VOICE_ENROLL_RE = re.compile(
    r"(?:"
    # English: register/enroll/save/record + my/the + voice
    r"(?:register|enroll|save|record)\s+(?:my\s+)?(?:voice|voiceprint)"
    r"|(?:my\s+)?voice\s+(?:register|enroll|save|record)\s*(?:karo|kar|do|please)?"
    # Hinglish: meri/mera + awaaz/voice + action
    r"|(?:meri|mera)\s+(?:awaaz|aawaz|voice)\s+(?:register|enroll|save|record)\s*(?:karo|kar|do)?"
    r"|(?:awaaz|aawaz)\s+(?:register|enroll|save|record)\s*(?:karo|kar|do)?"
    # Hinglish reversed: action + awaaz
    r"|(?:register|enroll|save|record)\s+(?:karo\s+)?(?:meri\s+)?(?:awaaz|aawaz|voice)"
    r")",
    re.IGNORECASE,
)

_VOICE_DELETE_RE = re.compile(
    r"(?:"
    r"(?:delete|remove|reset|clear|hata|hatao|mita|mitao)\s+(?:my\s+)?(?:voice|voiceprint|enrollment)"
    r"|(?:my\s+)?voice\s+(?:delete|remove|reset|clear|hatao|mitao)\s*(?:karo|kar|do)?"
    r"|(?:meri|mera)\s+(?:awaaz|aawaz|voice)\s+(?:delete|remove|hatao|mitao)\s*(?:karo|kar|do)?"
    r"|voice\s+(?:enrollment\s+)?(?:hatao|mitao|band\s+karo|delete\s+karo)"
    r")",
    re.IGNORECASE,
)

_VOICE_STATUS_RE = re.compile(
    r"(?:"
    r"(?:am\s+i|is\s+(?:my\s+)?voice)\s+(?:enrolled|registered|saved)"
    r"|voice\s+(?:enrolled|registered|status)\s*(?:hai|hua|kya)?"
    r"|(?:meri|mera)\s+(?:awaaz|voice)\s+(?:register|enroll|save)\s*(?:hui|hua|hai)\s*(?:kya)?"
    r"|(?:check|dekho?)\s+(?:voice\s+)?(?:enrollment|registration)\s*(?:status)?"
    r")",
    re.IGNORECASE,
)

# ── Instagram intent patterns ─────────────────────────────────────────────────
_INSTAGRAM_SEND_RE = re.compile(
    r"(?:"
    r"instagram\s+(?:pe\s+)?(?:message|dm|send)\s+(?:to\s+)?(?P<contact1>\w+)(?:\s+(?P<msg1>.+))?"
    r"|(?P<contact2>\w+)\s+ko\s+instagram\s+(?:pe\s+)?(?:message|dm)\s*(?:bhejo|bhej|send)?\s*(?P<msg2>.+)?"
    r"|instagram\s+(?P<contact3>\w+)\s+ko\s+(?P<msg3>.+)"
    r")",
    re.IGNORECASE,
)

_INSTAGRAM_READ_RE = re.compile(
    r"(?:"
    r"instagram\s+(?:pe\s+)?(?:(?P<contact1>\w+)\s+)?(?:ke?\s+)?(?:dm|message|chat)\s*(?:padh|read|dekh|dikha)?"
    r"|(?:padh|read|dikha)\s+(?:meri\s+)?instagram\s+(?:dm|messages?|chat)"
    r")",
    re.IGNORECASE,
)

_INSTAGRAM_LIST_RE = re.compile(
    r"(?:"
    r"instagram\s+(?:dm|inbox|messages?|chats?)\s*(?:list|dikha|dikhao|show|open|kholo|kholao)?"
    r"|(?:show|dikha|dikhao|open|kholo|launch)\s+(?:meri\s+)?instagram\s+(?:dm|inbox|messages?|chats?)"
    r"|(?:open|kholo|launch)\s+insta(?:gram)?\s+(?:chats?|inbox|dms?|messages?)"
    r"|insta(?:gram)?\s+(?:chats?|inbox|dms?)\s+(?:open|kholo|dikha|dikhao)"
    r"|(?:open|kholo|launch)\s+insta(?:gram)?$"
    r")",
    re.IGNORECASE,
)

# Instagram profile open pattern
_INSTAGRAM_PROFILE_RE = re.compile(
    r"(?:"
    r"(?P<contact1>\w+)\s+(?:ka\s+)?instagram\s+(?:profile|account|page)\s*(?:kholo|open|dekh|dikha)?"
    r"|instagram\s+(?:pe\s+)?(?P<contact2>\w+)\s+(?:ka\s+)?(?:profile|account|page)\s*(?:kholo|open|dekh|dikha)?"
    r"|open\s+(?P<contact3>\w+)\s+(?:ka\s+)?instagram\s+(?:profile|account|page)"
    r"|(?P<contact4>\w+)\s+instagram\s+(?:profile|page)\s+(?:open|kholo|dekh)"
    r")",
    re.IGNORECASE,
)

# Precompile search intent patterns once at module load
_SEARCH_PATTERNS: list[re.Pattern] = [
    re.compile(r"^(?:google|search|find|look up|lookup)\s+(?:(?:karo|kar|for)\s+)(.+)$", re.I),
    re.compile(r"^(?:google|search|find|look up|lookup)\s+(?!karo\b|kar\b|for\b)(.+)$", re.I),
    re.compile(r"^(.+?)\s+(?:google\s+karo|search\s+karo|dhundo|dhoondo|khojo)$", re.I),
]


def _classify_search_intent(query: str):
    q = query.strip()
    for pat in _SEARCH_PATTERNS:
        m = pat.match(q)
        if m:
            cleaned = m.group(1).strip()
            if cleaned and not _looks_like_url(cleaned):
                return cleaned
    return None


def _router_classify_many(query: str):
    try:
        from vani.router.intent_classifier import router_classify_many
        return router_classify_many(query)
    except ImportError:
        return []


def _is_learn_intent(q: str) -> bool:
    try:
        from vani.memory.learning_memory import is_learn_intent
        return is_learn_intent(q)
    except ImportError:
        return False


def _router_classify(query: str):
    """
    Deterministic fast router. Returns (intent_str, data) or (None, None).
    Keeps Ollama out of the loop for common voice commands.
    """
    try:
        from vani.router.intent_classifier import router_classify
        return router_classify(query)
    except ImportError:
        pass

    # Fallback: built-in classification
    q = query.strip()
    ql = q.lower()

    # ── Voice enrollment intents (checked early — high priority) ──────────────
    if _VOICE_DELETE_RE.search(q):
        return "VOICE_DELETE", {}
    if _VOICE_STATUS_RE.search(q):
        return "VOICE_STATUS", {}
    if _VOICE_ENROLL_RE.search(q):
        return "VOICE_ENROLL", {}

    # Study mode intents
    if _STUDY_START_RE.search(q):
        subject_m = re.search(r"(maths?|physics|chemistry|biology|java|python|c\+\+|javascript|history|english|accounts?|economics)", q, re.IGNORECASE)
        dur_m = re.search(r"(\d+)\s*min", q, re.IGNORECASE)
        return "STUDY_START", {"subject": subject_m.group(0) if subject_m else "", "duration_min": int(dur_m.group(1)) if dur_m else 50}
    if _STUDY_END_RE.search(q):
        return "STUDY_END", {}
    if _STUDY_STATUS_RE.search(q):
        return "STUDY_STATUS", {}

    # ── Finance CA intents (EMI/SIP/Calendar before Tax to avoid prefix conflicts)
    if _FINANCE_EMI_RE.search(q):
        return "FINANCE_EMI", {"query": q}
    if _FINANCE_SIP_RE.search(q):
        return "FINANCE_SIP", {"query": q}
    if _FINANCE_CALENDAR_RE.search(q):
        return "FINANCE_CALENDAR", {"query": q}
    if _FINANCE_TAX_RE.search(q):
        return "FINANCE_TAX", {"query": q}
    if _FINANCE_INVEST_RE.search(q):
        return "FINANCE_INVEST", {"query": q}
    if _FINANCE_RATIO_RE.search(q):
        return "FINANCE_RATIO", {"query": q}
    if _FINANCE_QUERY_RE.search(q):
        return "FINANCE_QUERY", {"query": q}

    # Screen read
    if _is_screen_read_intent(q):
        return "SCREEN_READ", {"query": q}

    # WhatsApp shortcut
    shortcut = _classify_whatsapp_shortcut(q)
    if shortcut:
        return "WHATSAPP_SHORTCUT", shortcut

    # WhatsApp fast parse
    wa = _parse_fast_whatsapp_command(q)
    if wa:
        intent = wa.get("intent", "")
        if intent == "WHATSAPP_CALL":
            return "WHATSAPP_CALL", (wa["contact"], wa.get("call_type", "voice"))
        elif intent == "WHATSAPP_SEND":
            return "WHATSAPP_SEND", (wa["contact"], wa["message"])
        elif intent == "WHATSAPP_READ":
            return "WHATSAPP_READ", wa["contact"]
        elif intent == "WHATSAPP_OPEN_CHAT":
            return "WHATSAPP_OPEN_CHAT", wa["contact"]

    # Instagram intents (checked before generic WhatsApp/media)
    if _INSTAGRAM_SEND_RE.search(q):
        m = _INSTAGRAM_SEND_RE.search(q)
        contact = (m.group("contact1") or m.group("contact2") or m.group("contact3") or "").strip()
        message = (m.group("msg1") or m.group("msg2") or m.group("msg3") or "").strip()
        return "INSTAGRAM_SEND", (contact, message)
    if _INSTAGRAM_LIST_RE.search(q):
        return "INSTAGRAM_LIST", {}
    if _INSTAGRAM_PROFILE_RE.search(q):
        m = _INSTAGRAM_PROFILE_RE.search(q)
        contact = (m.group("contact1") or m.group("contact2") or m.group("contact3") or m.group("contact4") or "").strip()
        return "INSTAGRAM_PROFILE", contact
    if _INSTAGRAM_READ_RE.search(q):
        m = _INSTAGRAM_READ_RE.search(q)
        contact = (m.group("contact1") or "").strip()
        return "INSTAGRAM_READ", contact

    # ── Browser / YouTube / Search — unified v3 regex classifier ──────────────
    # classify_browser_intent covers: BROWSER_*, YT_*, SEARCH_* intents
    # It runs BEFORE Ollama and BEFORE the old per-tool classifiers.
    browser_result = classify_browser_intent(q)
    if browser_result:
        bi_intent, bi_data = browser_result
        # Map new intent names to existing router intent names where needed
        _COMPAT = {
            "YT_PLAY":        "YOUTUBE_PLAY",
            "YT_PAUSE":       "YOUTUBE_PAUSE",
            "YT_SEEK_FWD":    "YOUTUBE_SEEK_FORWARD",
            "YT_SEEK_BWD":    "YOUTUBE_SEEK_BACKWARD",
            "YT_NEXT":        "YOUTUBE_NEXT",
            "YT_PREV":        "YOUTUBE_PREVIOUS",
            "YT_PLAY_SONG":   "YOUTUBE_PLAY_SONG",
            "YT_CLOSE_TAB":   "YOUTUBE_CLOSE_TAB",
            "YT_FULLSCREEN":  "YOUTUBE_FULLSCREEN",
            "YT_MUTE":        "YOUTUBE_MUTE",
            "YT_SPEED_UP":    "YOUTUBE_SPEED_UP",
            "YT_SPEED_DOWN":  "YOUTUBE_SPEED_DOWN",
            "YT_SPEED_RESET": "YOUTUBE_SPEED_RESET",
            "YT_LOOP":        "YOUTUBE_LOOP",
            "YT_CAPTIONS":    "YOUTUBE_CAPTIONS",
            "YT_QUALITY":     "YOUTUBE_QUALITY",
            "YT_LIKE":        "YOUTUBE_LIKE",
            "YT_DISLIKE":     "YOUTUBE_DISLIKE",
            "YT_SUBSCRIBE":   "YOUTUBE_SUBSCRIBE",
            "YT_PLAYLIST":    "YOUTUBE_PLAYLIST",
            "YT_THEATER":     "YOUTUBE_THEATER",
            "YT_MINIPLAYER":  "YOUTUBE_MINIPLAYER",
            "SEARCH_GOOGLE":  "GOOGLE_SEARCH",
            "BROWSER_URL":    "OPEN_URL",
            "BROWSER_OPEN":   "APP_OPEN",
            "BROWSER_CLOSE_TAB":  "TAB_CLOSE",
            "BROWSER_NEXT_TAB":   "TAB_NEXT",
            "BROWSER_PREV_TAB":   "TAB_PREVIOUS",
            "SEARCH_YOUTUBE": "YOUTUBE_PLAY_SONG",
        }
        mapped = _COMPAT.get(bi_intent, bi_intent)
        return mapped, bi_data

    # Generic media (Spotify / Apple Music / system)
    media_action = _classify_media_intent(q)
    if media_action:
        return "MEDIA_CONTROL", media_action

    # Google search
    search_query = _classify_search_intent(q)
    if search_query:
        return "GOOGLE_SEARCH", search_query

    # App / tab / URL intents
    app_intent = _classify_app_intent(q)
    if app_intent:
        intent_type, data = app_intent
        return intent_type, data

    # Hinglish question forms: "kya hai X", "kaise karte hain X", "batao X"
    # These have no leading 'google/search' trigger so _classify_search_intent misses them.
    hinglish_q = _classify_hinglish_search(q)
    if hinglish_q:
        return "GOOGLE_SEARCH", hinglish_q

    # ── Teach intent — must come AFTER search/browser classifiers ────────────
    # Only fires when no other intent matched, preventing "what is the weather"
    # from being swallowed by teach mode instead of SEARCH_WEATHER.
    if _TEACH_RE.search(q):
        return "TEACH", {"query": q}

    return None, None


# ── Voice enrollment handler ──────────────────────────────────────────────────

async def _handle_voice_enroll() -> str:
    """
    Full voice enrollment flow triggered by voice command.

    Steps:
      1. Announce — tell the user to speak for 5 seconds.
      2. Record  — capture 5s of mic audio at 16kHz using sounddevice.
      3. Enroll  — pass the audio to voice_enrollment.enroll_from_audio().
      4. Reload  — refresh wake_verifier's in-memory voiceprint cache.
      5. Reply   — return a Hinglish confirmation / error message.

    Uses run_in_executor so the blocking sounddevice.rec() call never blocks
    the asyncio event loop.

    Returns a Hinglish response string. Never raises.
    """
    log = logging.getLogger("vani.router.voice_enroll")

    # ── 0. Check sounddevice availability ────────────────────────────────────
    try:
        import sounddevice as sd
    except ImportError:
        msg = (
            "sounddevice library install nahi hai. "
            "Terminal mein chalao: pip install sounddevice"
        )
        log.warning("VOICE_ENROLL: sounddevice not available")
        return msg

    import numpy as np

    # ── 1. Announce ───────────────────────────────────────────────────────────
    _RECORD_SECONDS = 5
    _SAMPLE_RATE = 16000

    announce_msg = (
        f"Theek hai! {_RECORD_SECONDS} second ke liye clearly bolo. "
        "Main teri awaaz sun rahi hoon..."
    )

    # Speak announcement asynchronously — don't block recording
    try:
        from vani.reasoning.worker import say_to_user
        asyncio.create_task(say_to_user(announce_msg))
    except Exception as exc:
        log.debug("VOICE_ENROLL: announce speak failed (non-fatal): %s", exc)

    # Small sleep so TTS has started before mic opens
    await asyncio.sleep(0.8)

    # ── 2. Record ─────────────────────────────────────────────────────────────
    def _blocking_record() -> np.ndarray:
        """Runs in executor thread — sounddevice.rec() is blocking."""
        audio = sd.rec(
            frames=int(_RECORD_SECONDS * _SAMPLE_RATE),
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="float32",
        )
        sd.wait()                        # blocks until recording is done
        return audio.flatten()

    try:
        loop = asyncio.get_event_loop()
        wav: np.ndarray = await loop.run_in_executor(None, _blocking_record)
        log.info(
            "VOICE_ENROLL: recorded %.2fs of audio (%d samples)",
            len(wav) / _SAMPLE_RATE, len(wav),
        )
    except Exception as exc:
        log.warning("VOICE_ENROLL: recording failed: %s", exc)
        return (
            "Mic se recording nahi ho payi. "
            "Kripya mic permission check karo aur dobara try karo."
        )

    # ── 3. Enroll ─────────────────────────────────────────────────────────────
    try:
        from vani.services.voice_enrollment import enroll_from_audio
        result: dict = enroll_from_audio([wav], sr=_SAMPLE_RATE)
    except Exception as exc:
        log.warning("VOICE_ENROLL: enroll_from_audio() raised: %s", exc)
        return f"Voice enrollment mein error aaya: {exc}"

    # ── 4. Reply ──────────────────────────────────────────────────────────────
    if result.get("ok"):
        seconds = result.get("seconds", _RECORD_SECONDS)
        msg = (
            f"Teri awaaz successfully register ho gayi! "
            f"{seconds:.1f} seconds ka voiceprint save ho gaya. "
            "Ab sirf teri awaaz pe respond karungi."
        )
        log.info("VOICE_ENROLL: enrollment successful (%.2fs)", seconds)

        # ── 5. Refresh in-memory voiceprint cache immediately ─────────────────
        # Without this, wake_verifier keeps the pre-enrollment None in its cache
        # for the rest of the session, so the gate stays fail-open until restart.
        try:
            from vani.audio.wake_verifier import reload_voiceprint
            reload_voiceprint()
            log.info("VOICE_ENROLL: wake_verifier cache refreshed")
        except Exception as _exc:
            log.debug("VOICE_ENROLL: reload_voiceprint() skipped (non-fatal): %s", _exc)

        return msg

    reason = result.get("reason", "unknown")

    if reason == "too_short":
        secs = result.get("seconds", 0.0)
        return (
            f"Audio bahut chhota tha — sirf {secs:.1f} seconds mila. "
            "Kam se kam 4 second clearly bolna zaroori hai. Dobara try karo."
        )
    elif reason == "embed_failed":
        return (
            "Awaaz ka pattern extract nahi ho paya. "
            "Thodi der baad dobara try karo ya mic check karo."
        )
    elif reason == "save_failed":
        return (
            "Voiceprint file save nahi ho payi. "
            "Disk space ya permissions check karo."
        )
    else:
        return f"Voice register nahi ho payi. Reason: {reason}. Dobara try karo."


async def _handle_voice_delete() -> str:
    """
    Delete the enrolled voiceprint via voice command.
    Clears the wake_verifier in-memory cache so the gate goes fail-open immediately.
    Returns a Hinglish confirmation string. Never raises.
    """
    log = logging.getLogger("vani.router.voice_enroll")
    try:
        from vani.services.voice_enrollment import delete_voiceprint, is_enrolled
        if not is_enrolled():
            return "Koi voiceprint registered nahi tha. Kuch delete karne ki zaroorat nahi."
        ok = delete_voiceprint()
        if ok:
            log.info("VOICE_DELETE: voiceprint deleted via voice command")

            # Clear in-memory cache so the gate goes fail-open right now.
            # Without this, the deleted voiceprint stays active until restart.
            try:
                from vani.audio.wake_verifier import reload_voiceprint
                reload_voiceprint()
                log.info("VOICE_DELETE: wake_verifier cache cleared")
            except Exception as _exc:
                log.debug("VOICE_DELETE: reload_voiceprint() skipped (non-fatal): %s", _exc)

            return (
                "Teri awaaz ki registration delete ho gayi. "
                "Ab Vani bina voice verification ke respond karegi."
            )
        return "Voiceprint delete nahi ho paya. Dobara try karo."
    except Exception as exc:
        log.warning("VOICE_DELETE: failed: %s", exc)
        return f"Delete mein error: {exc}"


async def _handle_voice_status() -> str:
    """
    Report current enrollment status via voice command.
    Returns a Hinglish status string. Never raises.
    """
    log = logging.getLogger("vani.router.voice_enroll")
    try:
        from vani.services.voice_enrollment import get_enrollment_status
        status = get_enrollment_status()
        if status.get("enrolled"):
            size_kb = (status.get("size_bytes") or 0) / 1024
            return (
                f"Haan, teri awaaz registered hai. "
                f"Voiceprint file {size_kb:.1f} KB ki hai."
            )
        return (
            "Abhi tak koi awaaz register nahi hai. "
            "Bol 'Vani, register my voice' aur main teri awaaz save kar lungi."
        )
    except Exception as exc:
        log.warning("VOICE_STATUS: failed: %s", exc)
        return f"Enrollment status check nahi ho paya: {exc}"


# ── Main dispatcher ───────────────────────────────────────────────────────────

async def _dispatch_intent(intent: str, data, query: str) -> str:
    """Execute a pre-classified intent directly without going through Ollama."""
    from vani.reasoning.tools.apps import (
        open_application, close_application, switch_application,
        close_active_tab, next_tab, previous_tab,
        switch_tab_by_name, close_tab_by_name, close_all_tabs_by_name,
        open_url_in_browser, open_youtube_and_play, folder_file,
    )
    from vani.reasoning.tools.messaging import (
        whatsapp_send, whatsapp_read, whatsapp_call,
        whatsapp_open_chat, whatsapp_shortcut,
    )
    from vani.reasoning.tools.media import media_control
    from vani.reasoning.tools.code import code_assist
    from vani.reasoning.tools.youtube import youtube_control
    from vani.reasoning.screen import read_screen, google_search

    if intent == "WHATSAPP_SEND":
        contact, message = data
        return await whatsapp_send.ainvoke({"contact": contact, "message": message})
    elif intent == "WHATSAPP_READ":
        return await whatsapp_read.ainvoke({"contact": data})
    elif intent == "WHATSAPP_CALL":
        contact, call_type = data
        return await whatsapp_call.ainvoke({"contact": contact, "call_type": call_type})
    elif intent == "WHATSAPP_OPEN_CHAT":
        return await whatsapp_open_chat.ainvoke({"contact": data})
    elif intent == "WHATSAPP_SHORTCUT":
        return await whatsapp_shortcut.ainvoke({"action": data})
    elif intent == "SCREEN_READ":
        return await read_screen.ainvoke(data)
    elif intent == "GOOGLE_SEARCH":
        return await google_search.ainvoke({"query": data})
    elif intent == "MEDIA_CONTROL":
        return await media_control.ainvoke({"action": data, "query": query})
    elif intent == "YOUTUBE_PLAY":
        return await open_youtube_and_play.ainvoke({"song_or_query": data})
    elif intent in {
        "YOUTUBE_SEEK_FORWARD", "YOUTUBE_SEEK_BACKWARD",
        "YOUTUBE_PAUSE",
        "YOUTUBE_NEXT", "YOUTUBE_PREVIOUS",
        "YOUTUBE_PLAY_SONG", "YOUTUBE_CLOSE_TAB",
        "YOUTUBE_FULLSCREEN", "YOUTUBE_MUTE",
        # v3 new YT intents — all routed through youtube_control
        "YOUTUBE_SPEED_UP", "YOUTUBE_SPEED_DOWN", "YOUTUBE_SPEED_RESET",
        "YOUTUBE_LOOP", "YOUTUBE_CAPTIONS", "YOUTUBE_QUALITY",
        "YOUTUBE_LIKE", "YOUTUBE_DISLIKE", "YOUTUBE_SUBSCRIBE",
        "YOUTUBE_PLAYLIST", "YOUTUBE_THEATER", "YOUTUBE_MINIPLAYER",
    }:
        return await youtube_control.ainvoke({"query": data if data else query})
    # ── v3 Browser control intents ─────────────────────────────────────────────
    elif intent in {
        "BROWSER_NEW_TAB", "BROWSER_CLOSE_TAB", "BROWSER_REOPEN_TAB",
        "BROWSER_NEXT_TAB", "BROWSER_PREV_TAB", "BROWSER_TAB_N",
        "BROWSER_BACK", "BROWSER_FORWARD", "BROWSER_REFRESH", "BROWSER_HARD_REFRESH",
        "BROWSER_ZOOM_IN", "BROWSER_ZOOM_OUT", "BROWSER_ZOOM_RESET",
        "BROWSER_FULLSCREEN", "BROWSER_FIND",
        "BROWSER_SCROLL_DOWN", "BROWSER_SCROLL_UP", "BROWSER_SCROLL_TOP", "BROWSER_SCROLL_BOTTOM",
        "BROWSER_BOOKMARK", "BROWSER_HISTORY", "BROWSER_DOWNLOADS", "BROWSER_DEVTOOLS",
        "BROWSER_INCOGNITO", "BROWSER_MUTE_TAB", "BROWSER_PIN_TAB",
        "BROWSER_SCREENSHOT", "BROWSER_COPY_URL", "BROWSER_FOCUS_BAR",
        "BROWSER_SPLIT_SCREEN", "BROWSER_READING_MODE", "BROWSER_CLEAR_CACHE",
        "BROWSER_PRINT", "BROWSER_SAVE_PAGE", "BROWSER_EXTENSIONS",
    }:
        from vani.browser.control import browser_action
        return await browser_action.ainvoke({"intent": intent, "data": data, "query": query})
    # ── v3 Search intents ──────────────────────────────────────────────────────
    elif intent in {
        "SEARCH_MAPS", "SEARCH_IMAGES", "SEARCH_NEWS", "SEARCH_SHOPPING",
        "SEARCH_TRANSLATE", "SEARCH_WEATHER", "SEARCH_CALCULATOR",
        "SEARCH_DEFINE", "SEARCH_TIMER", "SEARCH_FLIGHT", "SEARCH_STOCK",
    }:
        return await google_search.ainvoke({"query": str(data) if data else query})
    elif intent == "APP_OPEN":
        return await open_application.ainvoke({"app_name": data})
    elif intent == "FOLDER_FILE":
        return await folder_file.ainvoke({"command": data})
    elif intent == "CODE_ASSIST":
        return await code_assist.ainvoke({"command": data})
    elif intent == "OPEN_URL":
        return await open_url_in_browser.ainvoke({"url": data, "browser": "default"})
    elif intent == "APP_CLOSE":
        return await close_application.ainvoke({"app_name": data})
    elif intent == "APP_SWITCH":
        return await switch_application.ainvoke({"app_name": data})
    elif intent == "TAB_CLOSE":
        return await close_active_tab.ainvoke({})
    elif intent in ("TAB_CLOSE_BY_NAME", "BROWSER_CLOSE_BY_NAME"):
        return await close_tab_by_name.ainvoke({"query": data or query})
    elif intent in ("TAB_CLOSE_ALL_BY_NAME", "BROWSER_CLOSE_ALL_BY_NAME"):
        return await close_all_tabs_by_name.ainvoke({"query": data or query})
    elif intent in ("TAB_SWITCH_BY_NAME", "BROWSER_SWITCH_BY_NAME"):
        return await switch_tab_by_name.ainvoke({"query": data or query})
    elif intent == "TAB_NEXT":
        return await next_tab.ainvoke({})
    elif intent == "TAB_PREVIOUS":
        return await previous_tab.ainvoke({})
    elif intent == "STUDY_BLOCK":
        # Distraction blocked during study mode — just speak the daant, return it
        from vani.reasoning.worker import say_to_user
        asyncio.create_task(say_to_user(str(data)))
        return str(data)
    elif intent == "STUDY_START":
        from vani.reasoning.tools.study_mode import start_study_session
        return await start_study_session.ainvoke(data)
    elif intent == "STUDY_END":
        from vani.reasoning.tools.study_mode import end_study_session
        return await end_study_session.ainvoke({})
    elif intent == "STUDY_STATUS":
        from vani.reasoning.tools.study_mode import study_status
        return await study_status.ainvoke({})
    # ── Finance CA intents ────────────────────────────────────────────────────
    elif intent.startswith("FINANCE_"):
        from vani.reasoning.tools.finance_ca import handle_finance_intent
        return await handle_finance_intent(intent, query, data if isinstance(data, dict) else {})
    # ── Voice enrollment intents ───────────────────────────────────────────────
    elif intent == "VOICE_ENROLL":
        return await _handle_voice_enroll()
    elif intent == "VOICE_DELETE":
        return await _handle_voice_delete()
    elif intent == "VOICE_STATUS":
        return await _handle_voice_status()
    elif intent == "INSTAGRAM_SEND":
        contact, message = data
        from vani.reasoning.tools.messaging import instagram_send
        return await instagram_send.ainvoke({"contact": contact, "message": message})
    elif intent == "INSTAGRAM_READ":
        from vani.reasoning.tools.messaging import instagram_read
        return await instagram_read.ainvoke({"contact": data or "", "limit": 10})
    elif intent == "INSTAGRAM_LIST":
        # Open Instagram Direct inbox directly in browser
        from vani.messaging.client import _ig_open_inbox
        import asyncio
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, _ig_open_inbox)
        return "✅ Instagram inbox khul gaya." if ok else "❌ Instagram inbox nahi khula. Browser mein login check karo."
    elif intent == "INSTAGRAM_LIST_TEXT":
        from vani.reasoning.tools.messaging import instagram_dms
        return await instagram_dms.ainvoke({"limit": 10})
    elif intent == "INSTAGRAM_PROFILE":
        contact = data or ""
        if not contact:
            return "❌ Kiska Instagram profile kholun? Naam batao."
        from vani.messaging.client import _ig_resolve_username, _ig_open_profile_by_username, _ig_open_inbox
        import asyncio
        loop = asyncio.get_running_loop()

        def _open():
            # Resolve nickname → real username (SK → hey_imsk11)
            username = _ig_resolve_username(contact)
            # Make sure Instagram is open first
            _ig_open_inbox()
            import time as _t
            _t.sleep(1.5)
            result = _ig_open_profile_by_username(username)
            return result, username

        result, username = await loop.run_in_executor(None, _open)
        if "OPENED" in result or "SEARCH_DONE" in result:
            return f"✅ '{contact}' (@{username}) ka Instagram profile khul gaya."
        return f"❌ Instagram profile nahi khula: {result}"

    elif intent == "TEACH":
        from vani.reasoning.teaching_tool import TeachingEngine, build_visual_lesson
        engine = TeachingEngine()
        query = data.get("query", "") if isinstance(data, dict) else str(data)
        lesson = build_visual_lesson(engine, query)
        # Fire visual panel in browser UI via websocket/IPC signal
        try:
            from vani.ui.teach_bridge import send_teach_visual
            await send_teach_visual(lesson)
        except Exception:
            pass  # UI bridge optional — lesson spoken regardless
        return lesson.get("spoken_response", f"{query} ke baare mein samjhate hain!")