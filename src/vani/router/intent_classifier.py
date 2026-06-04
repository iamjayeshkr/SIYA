"""Pure intent classifiers for Vani's deterministic router."""

from __future__ import annotations

import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)

WA_COMMAND_WORDS = {
    "whatsapp", "wa", "message", "msg", "send", "bhejo", "b भेजो",
    "call", "voice", "video", "phone", "lagao", "laga", "milao",
    "karo", "kar", "please", "pls", "to", "ko", "pe", "par",
}

WA_MESSAGE_STARTERS = {
    "hi", "hii", "hey", "hello", "helo", "namaste", "gm", "gn",
    "kal", "aaj", "abhi", "ok", "okay", "thanks", "thank", "sorry",
    "meeting", "meet", "call", "aa", "aaja", "aja", "sun", "suno",
}

WA_SURNAME_NOISE = {
    "upadhyay", "upadhaya", "upadhyaya", "sharma", "verma", "varma",
    "singh", "kumar", "kumari", "gupta", "agarwal", "agrawal", "jain",
    "patel", "yadav", "pandey", "pande", "tiwari", "trivedi", "mehta",
    "shah", "rao", "reddy", "nair", "iyer", "khan", "shaikh", "sheikh",
}

URL_RE = re.compile(
    r"^(?:https?://)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+(?::\d+)?(?:/\S*)?$",
    re.IGNORECASE,
)

SITE_HOME_URLS = {
    "udemy.com": "https://www.udemy.com",
    "udemy": "https://www.udemy.com",
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "leetcode": "https://leetcode.com",
    "leet code": "https://leetcode.com",
    "hackerrank": "https://www.hackerrank.com",
    "hacker rank": "https://www.hackerrank.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "web whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "openai chat": "https://chatgpt.com",
    "google": "https://www.google.com",
    "google.com": "https://www.google.com",
    "amazon": "https://www.amazon.in",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "linkedln": "https://www.linkedin.com",
    "linked in": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "x.com": "https://twitter.com",
}

SITE_SEARCH_URLS = {
    "udemy.com": "https://www.udemy.com/courses/search/?q={query}",
    "udemy": "https://www.udemy.com/courses/search/?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "yt": "https://www.youtube.com/results?search_query={query}",
    "leetcode": "https://leetcode.com/problemset/?search={query}",
    "leet code": "https://leetcode.com/problemset/?search={query}",
    "hackerrank": "https://www.hackerrank.com/search?term={query}",
    "hacker rank": "https://www.hackerrank.com/search?term={query}",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "web whatsapp": "https://web.whatsapp.com",
    "chatgpt": "https://chatgpt.com/?q={query}",
    "chat gpt": "https://chatgpt.com/?q={query}",
    "openai chat": "https://chatgpt.com/?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "google.com": "https://www.google.com/search?q={query}",
    "amazon": "https://www.amazon.in/s?k={query}",
    "github": "https://github.com/search?q={query}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "linkedln": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "linked in": "https://www.linkedin.com/search/results/all/?keywords={query}",
    "instagram": "https://www.instagram.com/explore/search/keyword/?q={query}",
    "insta": "https://www.instagram.com/explore/search/keyword/?q={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
    "twitter": "https://twitter.com/search?q={query}",
    "x": "https://twitter.com/search?q={query}",
    "x.com": "https://twitter.com/search?q={query}",
}

SITE_QUERY_NOISE = {
    "and", "aur", "then", "phir", "search", "search karo", "find", "dhundo",
    "dhoondo", "pe", "par", "mein", "me", "on", "for", "karo", "kar",
}

SITE_BROWSER_ONLY = {
    "leetcode", "leet code", "hackerrank", "hacker rank",
    "whatsapp", "whatsapp web", "web whatsapp",
    "chatgpt", "chat gpt", "openai chat",
    "linkedin", "linkedln", "linked in",
    "instagram", "insta",
}

SITE_NAME_PATTERN = (
    r"udemy(?:\.com)?|youtube|yt|leetcode|leet\s*code|hackerrank|hacker\s*rank|"
    r"whatsapp(?:\s*web)?|web\s*whatsapp|chatgpt|chat\s*gpt|openai\s*chat|"
    r"google(?:\.com)?|amazon|github|reddit|linkedin|linkedln|linked\s*in|"
    r"instagram|insta|twitter|x(?:\.com)?"
)

SITE_ALIAS_NORMALIZATIONS = (
    (re.compile(r"\bleet\s+code\b", re.IGNORECASE), "leet code"),
    (re.compile(r"\bhacker\s+rank\b", re.IGNORECASE), "hacker rank"),
    (re.compile(r"\blinked\s+in\b", re.IGNORECASE), "linked in"),
    (re.compile(r"\bchat\s+gpt\b", re.IGNORECASE), "chat gpt"),
    (re.compile(r"\bopenai\s+chat\b", re.IGNORECASE), "openai chat"),
    (re.compile(r"\bweb\s+whatsapp\b", re.IGNORECASE), "web whatsapp"),
    (re.compile(r"\bx\s+com\b", re.IGNORECASE), "x.com"),
)


def normalize_user_command(text: str) -> str:
    q = " ".join((text or "").strip().lower().split())
    if not q:
        return ""
    # Voice transcripts often include attention words before the actual command.
    # Strip repeatedly so "aree wani please open google" becomes "open google".
    prefix = r"(?:arey|aree|arre|are|ary|hey|hello|hi|suno|sun|ok|okay|please|pls|bhai|bro|yaar)"
    assistant = r"(?:vani|vaani|wani|waani|vanni|wanni)"
    changed = True
    while changed and q:
        before = q
        q = re.sub(rf"^(?:{prefix})[\s,]+", "", q).strip()
        q = re.sub(rf"^(?:{assistant})[\s,]+", "", q).strip()
        q = re.sub(rf"^(?:{prefix})[\s,]+(?:{assistant})[\s,]+", "", q).strip()
        q = re.sub(rf"^(?:{assistant})[\s,]+(?:{prefix})[\s,]+", "", q).strip()
        changed = q != before
    return q


def clean_spoken_domain(text: str) -> str:
    text = normalize_user_command(text)
    text = re.sub(r"^(open|kholo|launch|visit|go to|open website)\s+", "", text).strip()
    text = re.sub(r"\s+(kholo|open karo|open kar|pe jao|par jao)$", "", text).strip()
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+", "", text)
    return text.strip("., ")


def looks_like_url(text: str) -> bool:
    lowered = (text or "").lower()
    non_url_words = {
        "file", "folder", "vscode", "vs code", "code", "banao", "bana",
        "create", "new", "naya", "nayi", "rename", "delete", "hata",
    }
    if any(word in lowered for word in non_url_words):
        return False
    if re.search(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\s+\S", lowered):
        return False
    return bool(URL_RE.match(clean_spoken_domain(text)))


def _clean_site_query(text: str) -> str:
    query = " ".join((text or "").strip().split())
    query = re.sub(r"^(?:open|kholo|launch|visit|go to)\s+", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(
        r"^(?:and|aur|then|phir)?\s*(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s+(?:karo|kar|kar\s*do|kardo|for)?\s*",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    query = re.sub(r"^(?:pe|par|mein|me|on|for)\s+", "", query, flags=re.IGNORECASE).strip()
    query = re.sub(
        r"\s+(?:search|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo|find)\s*(?:karo|kar|kar\s*do|kardo|do)?$",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip()
    query = re.sub(r"\s+(?:karo|kar|kar\s*do|kardo|do|please|pls|batao|bata)$", "", query, flags=re.IGNORECASE).strip()
    return query.strip(".,!? ")


def _normalize_site_key(site: str) -> str:
    key = " ".join((site or "").lower().strip().split())
    for pattern, repl in SITE_ALIAS_NORMALIZATIONS:
        key = pattern.sub(repl, key)
    if key == "x":
        return "x"
    if key.endswith(".com") and key not in SITE_HOME_URLS:
        bare = key[:-4]
        if bare in SITE_HOME_URLS:
            return bare
    return key


def _site_search_url(site: str, query: str) -> str | None:
    site_key = _normalize_site_key(site)
    matched_site = None
    for key in sorted(SITE_HOME_URLS, key=len, reverse=True):
        if site_key == key or site_key.startswith(key) or key.startswith(site_key):
            matched_site = key
            break
    if not matched_site:
        return None
    search_text = _clean_site_query(query)
    if not search_text or search_text.lower() in SITE_QUERY_NOISE:
        return SITE_HOME_URLS[matched_site]
    template = SITE_SEARCH_URLS.get(matched_site, "")
    if "{query}" not in template:
        return SITE_HOME_URLS[matched_site]
    return template.format(query=urllib.parse.quote_plus(search_text))


def classify_site_search_intent(query: str) -> tuple[str, str] | None:
    q = normalize_user_command(query)
    if not q:
        return None

    patterns = [
        rf"^(?:open|kholo|launch|visit|go\s+to)?\s*(?P<site>{SITE_NAME_PATTERN})\s+(?:and|aur|then|phir)?\s*(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s+(?P<query>.+)$",
        rf"^(?:open|kholo|launch|visit|go\s+to)?\s*(?P<site>{SITE_NAME_PATTERN})\s+(?:pe|par|mein|me|on)\s+(?P<query>.+?)\s*(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)?\s*(?:karo|kar|kar\s*do|kardo|do)?$",
        rf"^(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s+(?P<query>.+?)\s+(?:on|pe|par|mein|me)\s+(?P<site>{SITE_NAME_PATTERN})$",
        rf"^(?P<query>.+?)\s+(?:search|find|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s*(?:karo|kar|kar\s*do|kardo|do)?\s+(?:on|pe|par|mein|me)\s+(?P<site>{SITE_NAME_PATTERN})$",
    ]
    for pattern in patterns:
        match = re.match(pattern, q, flags=re.IGNORECASE)
        if not match:
            continue
        query_val = match.group("query")
        if " & " in query_val or " and " in query_val or " aur " in query_val or " then " in query_val or " phir " in query_val:
            continue
        site_key = _normalize_site_key(match.group("site"))
        if site_key in {"google", "google.com", "udemy", "udemy.com"} and not q.startswith(("open ", "kholo ", "launch ", "visit ", "go to ")):
            return None
        url = _site_search_url(match.group("site"), match.group("query"))
        if url:
            return "OPEN_URL", url
    return None


def classify_site_open_intent(query: str) -> tuple[str, str] | None:
    raw = normalize_user_command(query)
    if not raw:
        return None

    search_intent = classify_site_search_intent(raw)
    if search_intent:
        return search_intent

    q = raw
    q = re.sub(r"^(?:open|kholo|launch|visit|go to|open website)\s+", "", q).strip()
    q = re.sub(r"\s+(?:kholo|open karo|open kar|pe jao|par jao)$", "", q).strip()
    if looks_like_url(q):
        return "OPEN_URL", clean_spoken_domain(q)

    for site in sorted(SITE_HOME_URLS, key=len, reverse=True):
        patterns = [
            rf"^{re.escape(site)}(?:\s+(.+))?$",
            rf"^{re.escape(site)}\s+(?:pe|par|mein|me|on)\s+(.+)$",
            rf"^{re.escape(site)}\s+(?:and|aur|then|phir)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, q, flags=re.IGNORECASE)
            if not match:
                continue
            search_text = _clean_site_query(match.group(1) or "")
            if search_text and search_text.lower() not in SITE_QUERY_NOISE and "{query}" in SITE_SEARCH_URLS[site]:
                encoded = urllib.parse.quote_plus(search_text)
                return "OPEN_URL", SITE_SEARCH_URLS[site].format(query=encoded)
            if site in SITE_BROWSER_ONLY:
                return "OPEN_URL", SITE_HOME_URLS[site]
            return "APP_OPEN", site

    return None


def classify_youtube_play_intent(query: str) -> str | None:
    q = normalize_user_command(query)
    if "youtube" not in q and "yt" not in q:
        return None

    patterns = [
        r"^open\s+(?:youtube|yt)\s+(?:and|aur|then|phir)?\s*(?:play|chalao|chala|bajao|baja|lagao|laga|sunao|suna)\s+(.+?)(?:\s+(?:karo|kar|kardo|kar do|karde|do|de))?$",
        r"^open\s+(?:youtube|yt)\s+(?:and|aur|then|phir)\s+(.+?)\s+(?:play|chalao|chala|bajao|baja|lagao|laga|sunao|suna)(?:\s+(?:karo|kar|kardo|kar do|karde|do|de))?$",
        r"^play\s+(.+?)\s+(?:on|par|pe)\s+(?:youtube|yt)(?:\s+(?:karo|kar|kardo|kar do|karde))?$",
        r"^(?:youtube|yt)\s+(?:par|pe|mein|me)?\s*(.+?)\s+(?:play|chalao|chala|bajao|baja|lagao|laga|sunao|suna)(?:\s+(?:karo|kar|kardo|kar do|karde|do|de))?$",
        r"^(?:youtube|yt)\s+(?:play|chalao|chala|bajao|baja|lagao|laga|sunao|suna)\s+(.+?)(?:\s+(?:karo|kar|kardo|kar do|karde|do|de))?$",
        r"^(.+?)\s+(?:youtube|yt)\s+(?:par|pe)?\s*(?:play|chalao|chala|bajao|baja|lagao|laga|sunao|suna)(?:\s+(?:karo|kar|kardo|kar do|karde|do|de))?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, q, flags=re.IGNORECASE)
        if match:
            song = _clean_site_query(match.group(1) or "")
            if song and not looks_like_url(song):
                return song
    return None


def is_file_operation_intent(query: str) -> bool:
    q = normalize_user_command(query)
    phrases = [
        "create file", "new file", "file banao", "file bana",
        "nayi file", "naya file", "vscode mein file", "vs code mein file",
        "vscode mein new file", "vs code mein new file",
        "create a file", "create a .", "new .", "newfile", "file name", "file naam",
    ]
    return any(p in q for p in phrases) or bool(re.search(r"\bcreate\s+(?:a\s+)?\.[a-z0-9+#]+\s+file\b", q))


def is_code_assist_intent(query: str) -> bool:
    q = normalize_user_command(query)
    if is_file_operation_intent(query):
        return False
    code_words = {
        "leetcode", "solve", "solution", "code likh", "code banao", "implement",
        "while loop", "for loop", "hashmap", "hash map", "graph", "backtracking",
        "dynamic programming", "dp", "recursion", "sliding window", "two pointer",
        "binary search", "stack", "queue", "tree", "linked list", "complex pattern",
        "comment", "comments", "approach", "complexity",
    }
    file_words = {"java", ".java", "python", ".py", "javascript", ".js", "typescript", ".ts", "cpp", ".cpp", "code", "file"}
    return any(w in q for w in code_words) and any(w in q for w in file_words | {"vscode", "vs code", "current"})


def classify_search_intent(query: str) -> str | None:
    q = normalize_user_command(query)

    domain_search = re.search(
        r"\b[\w.-]+\.(?:com|org|net|io|co\.in|edu|gov)\b.*\b(?:search|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\b",
        q,
    ) or re.search(
        r"\b(?:search|find|look up|lookup|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\b.*\b[\w.-]+\.(?:com|org|net|io|co\.in|edu|gov)\b",
        q,
    )
    if domain_search:
        return q

    patterns = [
        r"^(?:google)\s+(?:pe|par|mein|me|on)\s+(.+?)\s+(?:search|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s*(?:karo|kar|kar do|kardo)?$",
        r"^(?:search|find|look up|lookup|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s+(?:karo|kar|kar do|kardo|do|for)?\s*(.+?)\s+(?:on|par|pe|mein|me)\s+google(?:\.com)?$",
        r"^(?:search|find|look up|lookup)\s+(?:google\s+)?(?:pe|par|mein|me|on)?\s*(?:karo|kar|for)?\s*(.+)$",
        r"^(?:google)\s+(?:karo|kar|for)?\s*(.+)$",
        r"^(.+?)\s+(?:google karo|search karo|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)$",
        r"^(.+?)\s+(?:search|dhundo|dhundho|dhoondo|dhoondho|khoj|khojo)\s*(?:karo|kar|kar do|kardo)?\s+(?:on|par|pe|mein|me)\s+google(?:\.com)?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, q)
        if match:
            cleaned = _clean_site_query(match.group(1).strip())
            if cleaned and not looks_like_url(cleaned):
                return cleaned
    return None


def normalize_whatsapp_contact(contact: str) -> str:
    words = [
        w.strip(".,!?;:'\"()[]{}").lower()
        for w in (contact or "").split()
        if w.strip(".,!?;:'\"()[]{}")
    ]
    words = [w for w in words if w not in WA_COMMAND_WORDS]
    return words[0] if words else ""


def clean_whatsapp_message(message: str) -> str:
    words = [
        w.strip(".,!?;:'\"()[]{}")
        for w in (message or "").split()
        if w.strip(".,!?;:'\"()[]{}")
    ]
    while words and words[0].lower() in {"bhejo", "send", "message", "msg", "whatsapp", "pe", "par", "ko"}:
        words.pop(0)
    return " ".join(words).strip()


def split_contact_and_message_after_prefix(text: str) -> tuple[str, str]:
    words = [w.strip(".,!?;:'\"()[]{}") for w in text.split() if w.strip(".,!?;:'\"()[]{}")]
    if not words:
        return "", ""

    contact = words[0]
    rest = words[1:]
    while rest and rest[0].lower() in WA_SURNAME_NOISE:
        rest.pop(0)

    if rest and rest[0].lower() not in WA_MESSAGE_STARTERS and len(rest) >= 2:
        rest.pop(0)

    return contact, clean_whatsapp_message(" ".join(rest))


def parse_fast_whatsapp_command(query: str) -> dict[str, str] | None:
    raw = normalize_user_command(query)
    q = raw.lower()
    if not raw:
        return None

    video = bool(re.search(r"\b(video|vc)\b", q))

    match = re.match(
        r"^(?:whatsapp\s+)?(?:(video|voice)\s+)?call(?:\s+to)?\s+(.+?)(?:\s+(?:ko\s+)?(?:call|lagao|laga|milao|karo|kar))?$",
        raw,
        flags=re.IGNORECASE,
    )
    if match:
        call_type = "video" if video or (match.group(1) and match.group(1).lower() == "video") else "voice"
        contact = normalize_whatsapp_contact(match.group(2))
        return {"intent": "WHATSAPP_CALL", "contact": contact, "message": "", "call_type": call_type}

    match = re.match(
        r"^(.+?)\s+(?:ko\s+)?(?:(video|voice)\s+)?(?:whatsapp\s+)?call\s*(?:karo|kar|lagao|laga|milao)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if match:
        call_type = "video" if video or (match.group(2) and match.group(2).lower() == "video") else "voice"
        contact = normalize_whatsapp_contact(match.group(1))
        return {"intent": "WHATSAPP_CALL", "contact": contact, "message": "", "call_type": call_type}

    match = re.match(r"^(?:whatsapp\s+)?(?:message|msg|send)\s+(?:to\s+)?(.+)$", raw, flags=re.IGNORECASE)
    if match:
        contact, message = split_contact_and_message_after_prefix(match.group(1))
        return {"intent": "WHATSAPP_SEND", "contact": contact, "message": message, "call_type": ""}

    match = re.match(
        r"^(.+?)\s+ko\s+(?:whatsapp\s+)?(?:(?:message|msg)\s+)?(.+?)\s*(?:bhejo|send|kar do|kardo)?$",
        raw,
        flags=re.IGNORECASE,
    )
    if match and re.search(r"\b(message|msg|bhejo|send|whatsapp)\b", q):
        contact = normalize_whatsapp_contact(match.group(1))
        message = clean_whatsapp_message(match.group(2))
        return {"intent": "WHATSAPP_SEND", "contact": contact, "message": message, "call_type": ""}

    return None


def classify_whatsapp_shortcut(query: str) -> str | None:
    q = normalize_user_command(query)
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


def extract_contact_and_payload(query: str) -> dict[str, str]:
    fast = parse_fast_whatsapp_command(query)
    if fast:
        logger.info("[WA_FAST_PARSE] %s", fast)
        return fast

    q = normalize_user_command(query)
    lowered = q.lower()

    intent = ""
    if any(x in lowered for x in ["read", "padho"]):
        intent = "WHATSAPP_READ"
    elif any(x in lowered for x in ["call", "milao", "lagao", "laga"]):
        intent = "WHATSAPP_CALL"
    elif any(x in lowered for x in ["bhejo", "send", "message"]):
        intent = "WHATSAPP_SEND"
    elif any(x in lowered for x in ["chat", "kholo", "open"]):
        intent = "WHATSAPP_OPEN_CHAT"

    if intent == "WHATSAPP_OPEN_CHAT":
        messaging_hint = any(x in lowered for x in ["whatsapp", "telegram", "wa", "chat"])
        if not messaging_hint:
            intent = ""

    if intent == "WHATSAPP_OPEN_CHAT":
        non_messaging_apps = {
            "youtube", "chrome", "google", "safari", "spotify", "music", "vscode",
            "terminal", "finder", "notes", "calculator", "settings", "browser", "code",
            "intellij", "word", "excel", "powerpoint", "photoshop", "slack", "discord",
            "zoom", "teams", "mail", "gmail", "calendar",
        }
        if any(app in lowered for app in non_messaging_apps):
            if not any(x in lowered for x in ["whatsapp", "telegram", "chat"]):
                intent = ""

    if intent == "WHATSAPP_CALL":
        media_keywords = {"song", "music", "gana", "geet", "play", "bajao", "baja"}
        if any(w in lowered for w in media_keywords):
            if not any(x in lowered for x in ["call", "phone", "whatsapp", "wa"]):
                intent = ""

    if intent == "WHATSAPP_SEND":
        non_whatsapp_sends = {"email", "mail", "file", "code"}
        if any(w in lowered for w in non_whatsapp_sends):
            if not any(x in lowered for x in ["whatsapp", "wa", "message", "msg"]):
                intent = ""

    if intent == "WHATSAPP_READ":
        non_messaging_reads = {"screen", "file", "book", "page", "text", "code", "doc", "document"}
        if any(w in lowered for w in non_messaging_reads):
            if not any(x in lowered for x in ["whatsapp", "wa", "message", "msg", "chat"]):
                intent = ""

    message = ""
    contact_part = q
    if intent == "WHATSAPP_SEND" and " ko " in lowered:
        parts = re.split(r"\bko\b", q, maxsplit=1, flags=re.IGNORECASE)
        contact_part = parts[0]
        message = parts[1].strip()
    elif " ko " in lowered:
        contact_part = re.split(r"\bko\b", q, maxsplit=1, flags=re.IGNORECASE)[0]
    elif " ki chat" in lowered:
        contact_part = re.split(r"\bki chat\b", q, maxsplit=1, flags=re.IGNORECASE)[0]
    elif " ka chat" in lowered:
        contact_part = re.split(r"\bka chat\b", q, maxsplit=1, flags=re.IGNORECASE)[0]
    elif " ke message" in lowered:
        contact_part = re.split(r"\bke message\b", q, maxsplit=1, flags=re.IGNORECASE)[0]

    noise = [
        "ko", "ki", "ke", "ka", "par", "pe", "call", "lagao", "laga", "milao",
        "message", "bhejo", "chat", "open", "whatsapp", "send", "video", "voice",
        "please", "karo", "karke", "wala", "wali", "kholo", "kholna", "padhna", "padho", "read",
        "of", "with", "from", "to", "and", "a", "an", "the",
    ]

    contact = contact_part
    for word in noise:
        contact = re.sub(rf"\b{word}\b", "", contact, flags=re.IGNORECASE)

    contact = normalize_whatsapp_contact(" ".join(contact.split()).strip())
    message = " ".join(message.split()).strip()

    for word in ["bhejo", "send", "message", "whatsapp", "karo", "please"]:
        message = re.sub(rf"\b{word}\b", "", message, flags=re.IGNORECASE)
    message = clean_whatsapp_message(message)

    result = {"intent": intent, "contact": contact, "message": message}
    logger.info("[RAW_QUERY] %s", query)
    logger.info("[INTENT] %s", result["intent"])
    logger.info("[EXTRACTED_CONTACT] %s", result["contact"])
    logger.info("[MESSAGE] %s", result["message"])
    logger.info("[SEARCH_TEXT] %s", result["contact"])
    return result


MEDIA_HINTS = {
    "pause": [
        "gana stop kar", "music band kar", "gaana rok do", "pause kar",
        "song stop kar", "music pause kar", "stop music", "rok do", "band kar",
        "pause video", "video pause", "pause youtube", "youtube pause",
        "youtube rok", "youtube band", "video rok", "video stop",
    ],
    "play": [
        "play karo", "resume karo", "music chalu karo", "resume music",
        "chalu kar", "gana chalao", "song chalao",
        "play video", "resume video", "youtube play", "youtube resume",
    ],
    "next": [
        "agla gana", "next song", "next kar", "pudcha gana",
        "next video", "youtube next",
    ],
    "previous": [
        "pichla gana", "previous song", "prev song", "peeche wala gana",
        "previous video", "youtube previous", "prev video",
    ],
}


def classify_media_intent(query: str) -> str | None:
    q = normalize_user_command(query)

    for action, hints in MEDIA_HINTS.items():
        for hint in hints:
            if hint in q:
                return action

    media_words = {"gana", "music", "song", "audio", "gaana", "video", "youtube"}
    action_words = {
        "pause": {"pause", "stop", "rok", "band"},
        "play": {"play", "resume", "chalu", "start"},
        "next": {"next", "agla", "forward"},
        "previous": {"previous", "pichla", "back", "prev"},
    }
    generic_words = {
        "kar", "karo", "please", "kardena", "kardo", "do", "de", "na", "pe", "par", "ko", "se",
        "me", "mein", "on", "in", "at", "the", "a", "an",
    }

    tokens = set(q.split())
    all_allowed = media_words | generic_words
    for words in action_words.values():
        all_allowed |= words

    if tokens - all_allowed:
        return None

    has_media = bool(tokens & media_words)
    for action, words in action_words.items():
        if tokens & words:
            if has_media:
                return action
            if q.endswith(" kar") or q.endswith(" karo") or q.startswith(("pause", "play", "resume", "stop")):
                return action

    return None


def classify_app_intent(query: str) -> tuple[str, str] | None:
    q = normalize_user_command(query)

    tab_next = [
        "next tab", "agla tab", "tab aage", "forward tab",
        "next browser tab", "next chrome tab", "next vscode tab",
        "next editor tab", "agla vscode tab",
    ]
    tab_prev = [
        "previous tab", "pichla tab", "tab peeche", "back tab",
        "previous browser tab", "previous chrome tab", "previous vscode tab",
        "previous editor tab", "pichla vscode tab",
    ]
    tab_close = [
        "close tab", "tab close", "tab band", "close current tab", "current tab band",
        "close browser tab", "close this tab", "close current browser tab",
        "close vscode tab", "close editor tab", "close current file",
        "close file", "file close kar", "current file close",
    ]

    for text in tab_next:
        if text in q:
            return "TAB_NEXT", ""
    for text in tab_prev:
        if text in q:
            return "TAB_PREVIOUS", ""
    for text in tab_close:
        if text in q:
            return "TAB_CLOSE", ""

    if q.startswith("switch to "):
        return "APP_SWITCH", q.replace("switch to ", "").strip()
    if q.endswith(" pe jao") or q.endswith(" par jao"):
        app = q.replace(" pe jao", "").replace(" par jao", "").strip()
        return "APP_SWITCH", app

    if q in ["close current app", "current app band", "close app", "app band karo"]:
        return "APP_CLOSE", "current"

    if q.startswith("close "):
        target = q.replace("close ", "").strip()
        if target in {"this", "current", "current window", "window"}:
            return "APP_CLOSE", "current"
        return "APP_CLOSE", target
    if q.endswith(" band karo") or q.endswith(" close kar"):
        app = q.replace(" band karo", "").replace(" close kar", "").strip()
        return "APP_CLOSE", app

    if q.startswith("open "):
        target = q.replace("open ", "").strip()
        if looks_like_url(target):
            return "OPEN_URL", clean_spoken_domain(target)
        return "APP_OPEN", target
    if q.endswith(" kholo") or q.endswith(" open karo") or q.endswith(" open kar"):
        app = q.replace(" kholo", "").replace(" open karo", "").replace(" open kar", "").strip()
        if looks_like_url(app):
            return "OPEN_URL", clean_spoken_domain(app)
        return "APP_OPEN", app

    return None


SCREEN_READ_HINTS = [
    "read my screen", "read screen", "see my screen", "what is on my screen",
    "what's on my screen", "explain this", "help me here", "what am i doing",
    "analyze this", "analyze this page", "look at my screen", "check my screen",
    "what am i watching", "what i am watching", "active tab", "current page",
    "meri screen dekho", "screen dekho", "meri screen padh", "yeh kya hai",
    "main kya kar raha", "isko samjhao", "meri help karo", "isme kya problem",
    "code check karo", "yeh error kya hai", "screen pe kya dikh",
    "kya dikh raha hai", "isme kya ho raha",
    "screen dekh", "yeh kya chal raha", "isko explain kar", "code dekh",
    "meri screen check", "isme issue kya", "dekh kya galti", "screen check kar",
    "bhai screen", "zara screen", "screen pe dekh", "ye kya hai screen",
    "screen mein kya", "galti kya hai", "error kya hai", "problem kya hai screen",
]


def is_screen_read_intent(query: str) -> bool:
    q = normalize_user_command(query)

    for hint in SCREEN_READ_HINTS:
        if hint in q:
            return True

    screen_words = {"screen", "dekh", "padh", "check", "samjha", "explain",
                    "analyze", "read", "see", "look", "bata", "isko", "yeh", "ye"}
    action_words = {"dekho", "dekh", "padho", "padh", "check", "samjhao",
                    "explain", "analyze", "read", "see", "look", "kya", "hai",
                    "help", "galti", "error", "problem", "issue", "dikh"}
    tokens = set(q.split())
    has_screen = bool(tokens & screen_words & {"screen", "dekh"})
    has_action = bool(tokens & action_words)
    return bool(has_screen and has_action)


def _router_classify_single(query: str) -> tuple[str | None, object | None]:
    query = normalize_user_command(query)
    q = query

    # ── Study mode: distraction block (must be FIRST — overrides everything) ──
    try:
        from vani.reasoning.tools.study_mode import (
            is_study_mode_active, is_distraction_query, get_distraction_reply,
        )
        if is_study_mode_active():
            _is_dist, _topic = is_distraction_query(query)
            if _is_dist:
                return "STUDY_BLOCK", get_distraction_reply(_topic)
    except Exception:
        pass

    # ── Study session control intents ──
    _STUDY_START = re.compile(
        r"(study.*(shuru|start|karte|chalao|lagao)|padhai.*(shuru|start|karte|lagao)|"
        r"focus.*(mode|on|karo|shuru)|pomodoro.*(start|shuru|lagao)|\b(study session|padhai session)\b|"
        r"\d+\s*min.*padh|padh.*\d+\s*min)", re.IGNORECASE
    )
    _STUDY_END = re.compile(
        r"(study.*(khatam|band|end|stop|rok)|session.*(khatam|end|stop)|break.*(lete|lo|karte)|padhai.*(band|rok|khatam))",
        re.IGNORECASE
    )
    _STUDY_STATUS = re.compile(
        r"(kitna.*(time|bcha|hua)|timer.*(check|dekh|kya)|session.*(status|kitna|time))",
        re.IGNORECASE
    )
    if _STUDY_START.search(q):
        sm = re.search(r"(maths?|physics|chemistry|biology|java|python|c\+\+|javascript|history|english|accounts?|economics)", q, re.IGNORECASE)
        dm = re.search(r"(\d+)\s*min", q, re.IGNORECASE)
        return "STUDY_START", {"subject": sm.group(0) if sm else "", "duration_min": int(dm.group(1)) if dm else 50}
    if _STUDY_END.search(q):
        return "STUDY_END", {}
    if _STUDY_STATUS.search(q):
        return "STUDY_STATUS", {}

    if is_file_operation_intent(query):
        return "FOLDER_FILE", query

    youtube_query = classify_youtube_play_intent(query)
    if youtube_query:
        return "YOUTUBE_PLAY", youtube_query

    site_search = classify_site_search_intent(query)
    if site_search:
        return site_search

    if q.startswith(("open ", "launch ", "visit ", "go to ")) or q.endswith((" kholo", " open karo", " open kar")):
        site_intent = classify_site_open_intent(query)
        if site_intent:
            return site_intent

    search_query = classify_search_intent(query)
    if search_query:
        return "GOOGLE_SEARCH", search_query

    if is_code_assist_intent(query):
        return "CODE_ASSIST", query

    if "telegram" in q and any(w in q for w in ["open", "kholo", "launch", "app"]):
        return "APP_OPEN", "telegram"

    if looks_like_url(query):
        return "OPEN_URL", clean_spoken_domain(query)

    wa_shortcut = classify_whatsapp_shortcut(query)
    if wa_shortcut:
        return "WHATSAPP_SHORTCUT", wa_shortcut

    extracted = extract_contact_and_payload(query)

    if extracted["intent"] == "WHATSAPP_SEND" and extracted["contact"]:
        if extracted["message"]:
            return "WHATSAPP_SEND", (extracted["contact"], extracted["message"])
        return None, None

    if extracted["intent"] == "WHATSAPP_READ" and extracted["contact"]:
        return "WHATSAPP_READ", extracted["contact"]

    if extracted["intent"] == "WHATSAPP_CALL" and extracted["contact"]:
        call_type = extracted.get("call_type") or ("video" if "video" in q else "voice")
        return "WHATSAPP_CALL", (extracted["contact"], call_type)

    if extracted["intent"] == "WHATSAPP_OPEN_CHAT" and extracted["contact"]:
        return "WHATSAPP_OPEN_CHAT", extracted["contact"]

    if is_screen_read_intent(query):
        return "SCREEN_READ", query

    media_action = classify_media_intent(query)
    if media_action:
        return "MEDIA_CONTROL", media_action

    site_intent = classify_site_open_intent(query)
    if site_intent:
        return site_intent

    app_intent = classify_app_intent(query)
    if app_intent:
        return app_intent[0], app_intent[1]

    return None, None


def router_classify(query: str) -> tuple[str | None, object | None]:
    return _router_classify_single(query)


def split_compound_commands(query: str) -> list[str]:
    q = normalize_user_command(query)
    if not q:
        return []

    # Guard: don't split if the whole query is already a single
    # "open X and search/play Y" command. Splitting "open google and search
    # hackerrank" -> ["open google", "search hackerrank"] causes two browser tabs.
    if classify_site_search_intent(q):
        return []
    if classify_youtube_play_intent(q):
        return []

    parts = [
        part.strip(" ,.; ")
        for part in re.split(r"\s*(?:&|\band\b|\baur\b|\bthen\b|\bphir\b)\s*", q)
        if part.strip(" ,.; ")
    ]
    return parts if len(parts) > 1 else []


def router_classify_many(query: str) -> list[tuple[str, object, str]]:
    """
    Return independently actionable subcommands for compound requests.
    Example: "search hackerrank on google & play khat on youtube".
    Single-command requests or ambiguous splits intentionally return [] so
    existing routing wins.
    """
    actions = []
    for part in split_compound_commands(query):
        intent, data = _router_classify_single(part)
        if not intent:
            return []
        if intent == "GOOGLE_SEARCH":
            intent = "OPEN_URL"
            data = f"https://www.google.com/search?q={urllib.parse.quote_plus(str(data))}"
        actions.append((intent, data, part))

    if len(actions) < 2:
        return []
    return actions
