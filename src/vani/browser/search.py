"""
vani/browser/search.py
━━━━━━━━━━━━━━━━━━━━━━
Browser search helpers.

This module intentionally has no app-specific UI code. The reasoning layer
imports the LangChain `google_search` tool from here at runtime.

Bug fixes (v2):
  ─────────────────────────────────────────────────────────────
  FIX 1 — "find me X" was including the word "me" in the query
    Old pattern: r"^(?:google|search|find|look up|lookup)\s+(.+)$"
    "find me best restaurants" → extracted "me best restaurants"
    Fix: strip filler words (me, mujhe, humko, please, zara) after
    the leading action verb before extracting the search term.

  FIX 2 — "kya hai X", "kaise karte hain X", "batao X" queries
    These pure Hinglish question forms have NO leading "google/search"
    trigger, so the router's _SEARCH_PATTERNS never matched them and
    they fell through to Ollama.  Added _HINGLISH_QUESTION_RE that
    catches these patterns in the router (router.py _router_classify
    now checks _classify_hinglish_question_as_search before returning
    None, None).

  FIX 3 — Intent enrichment was over-aggressively rewriting queries
    "learn python" was becoming:
      "best learn python tutorial site:udemy.com OR site:coursera.org OR site:youtube.com"
    That's fine for pure learning queries, but not when user says
    "kya hai python programming" (a definition query, not a course search).
    Fix: only enrich when classify_intent() confidence is high (score > 0.5).
  ─────────────────────────────────────────────────────────────
"""

import logging
import math
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

from vani.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

_I = re.IGNORECASE

# ---------------------------------------------------------------------------
# Hinglish → intent vocabulary
# ---------------------------------------------------------------------------

_HINGLISH_VOCAB: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:search\s+karo|search\s+kar|dhundo|dhoondo|khojo|khojna)\b", _I), "search"),
    (re.compile(r"\b(?:google\s+karo|google\s+kar|google\s+pe|google\s+par)\b", _I), "search on google"),
    (re.compile(r"\b(?:dekho|dekhna|dikhaao|dikhao)\b", _I), "show"),
    (re.compile(r"\b(?:batao|bata|bataana)\b", _I), "tell me"),
    (re.compile(r"\b(?:chahiye|chahie|chahta\s+hoon|chahti\s+hoon)\b", _I), "i want"),
    (re.compile(r"\b(?:kya\s+hai|kya\s+hain|kya\s+hota\s+hai)\b", _I), "what is"),
    (re.compile(r"\b(?:kaise\s+karte\s+hain|kaise\s+karte\s+ho|kaise|kaisa)\b", _I), "how to"),
    (re.compile(r"\b(?:kab\s+hai|kab\s+tha|kab)\b", _I), "when"),
    (re.compile(r"\b(?:kahan\s+hai|kahan\s+hain|kahan)\b", _I), "where"),
    (re.compile(r"\b(?:kitna|kitni|kitne)\b", _I), "how much"),
    (re.compile(r"\b(?:sabse\s+accha|best\s+wala|best\s+wali|top\s+wala)\b", _I), "best"),
    (re.compile(r"\b(?:sasta|saste|kam\s+daam|kam\s+paisa)\b", _I), "cheap affordable"),
    (re.compile(r"\b(?:naya|nayi|latest\s+wala|abhi\s+ka)\b", _I), "latest new"),
    (re.compile(r"\b(?:ke\s+liye|mein|par|pe|ka|ki|ke)\b", _I), ""),
    (re.compile(r"\b(?:aur\s+bhi|aur|bhi|ya)\b", _I), "or"),
    (re.compile(r"\b(?:par\s+bhi|lekin|magar)\b", _I), "but"),
    (re.compile(r"\b(?:zara|please|plz|pls|bhai|yaar|boss)\b", _I), ""),
    (re.compile(r"\b(?:mujhko|mujhe|humko|hume)\b", _I), ""),
    (re.compile(r"\b(?:thoda|bahut|zyada|kam)\b", _I), ""),
]

_GOOGLE_SUFFIX_RE = re.compile(
    r"\s+(?:on|par|pe|mein|me)\s+google(?:\.com)?\s*$", _I
)

# FIX 1: strip filler words ("me", "mujhe" etc.) after leading action verb
_LEADING_ACTION_RE = re.compile(
    r"^(?:google|search|find|look\s+up|lookup|khojo|dhundo|dhoondo)"
    r"(?:\s+(?:karo|kar|for|me\b|mujhe|humko|please|zara))?\s*",
    _I,
)

_TRAILING_CMD_RE = re.compile(
    r"\s+(?:google\s+karo|search\s+karo|dhundo|dhoondo|google\s+kar|search\s+kar)$",
    _I,
)

_WS_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# FIX 4 — "site:bceg.com on google" was misrouted to _extract_site_search()
#
# Root cause: Pattern 2 in _SITE_PATTERNS uses re.search(), so it finds
# "bceg.com" as a substring inside "site:bceg.com", treating the Google
# search operator as a site-search domain.  This produced nonsense like
# domain="bceg.com", query="on google".
#
# Fix: detect the site: operator early and route directly to the search API,
# stripping surrounding noise words ("on google", "google karo" etc.).
# ---------------------------------------------------------------------------
_SITE_OPERATOR_RE = re.compile(r"\bsite:\S+", re.I)

_SITE_OP_NOISE_RE = re.compile(
    r"\s+(?:on|par|pe|mein)\s+google(?:\.com)?\s*$"
    r"|\s+google\s+(?:karo|kar|search\s+karo)\s*$",
    re.I,
)

_SITE_OP_LEADING_RE = re.compile(
    r"^(?:search|google|find|look\s+up)\s+(?:karo\s+|kar\s+|for\s+)?",
    re.I,
)


def _clean_site_operator_query(q: str) -> str:
    """Strip noise around a site:-operator query, return clean Google query string."""
    q = _SITE_OP_NOISE_RE.sub("", q).strip()
    q = _SITE_OP_LEADING_RE.sub("", q).strip()
    return q

# ---------------------------------------------------------------------------
# FIX 2 — Hinglish question forms that have no leading search verb
# These should route to google_search but were going to Ollama before.
#
# Patterns captured:
#   "kya hai python programming"      → "what is python programming"
#   "kaise karte hain web scraping"   → "how to web scraping"
#   "kab hai IPL final"               → "when is IPL final"
#   "batao machine learning"          → "tell me machine learning"
#   "weather kya hai Delhi mein"      → weather query
# ---------------------------------------------------------------------------
_HINGLISH_QUESTION_RE = re.compile(
    r"^(?:"
    r"(?:kya\s+hai|kya\s+hain|kya\s+hota\s+hai)\s+(.+)"           # kya hai X
    r"|(?:kaise\s+karte?\s+(?:hain|ho|hoon)?|kaise)\s+(.+)"        # kaise karte hain X
    r"|(?:batao|bata)\s+(.+)"                                       # batao X
    r"|(.+?)\s+(?:kya\s+hai|kya\s+hain)\s*$"                      # X kya hai
    r"|(?:kab|kahan|kitna|kitni|kitne)\s+(?:hai\s+|hain\s+)?(.+)"  # kab/kahan/kitna X
    r")",
    _I,
)


def _extract_hinglish_question(query: str) -> Optional[str]:
    """
    If query is a Hinglish question, return the core search term.
    Otherwise return None.
    """
    m = _HINGLISH_QUESTION_RE.match(query.strip())
    if m:
        term = next((g.strip() for g in m.groups() if g), None)
        return term if term and len(term) > 1 else None
    return None


# ---------------------------------------------------------------------------
# Lightweight TF-IDF cosine similarity
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    n = len(tokens) or 1
    return {t: (c / n) * idf.get(t, 1.0) for t, c in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in b)
    norm_a = math.sqrt(sum(v * v for v in a.values())) or 1e-9
    norm_b = math.sqrt(sum(v * v for v in b.values())) or 1e-9
    return dot / (norm_a * norm_b)


_INTENT_CORPUS: dict[str, list[str]] = {
    "web_search":  ["search google web find information article news"],
    "buy_product": ["buy purchase price cost shop order online"],
    "learn":       ["course tutorial learn how to guide step by step"],
    "code":        ["code github repository programming algorithm implementation"],
    "weather":     ["weather forecast temperature rain today tomorrow"],
    "definition":  ["what is meaning define definition explain concept"],
    "news":        ["news latest update current events breaking"],
    "video":       ["youtube video watch clip"],
}


def _build_idf(corpus: dict[str, list[str]]) -> dict[str, float]:
    all_docs = [_tokenize(" ".join(phrases)) for phrases in corpus.values()]
    n_docs = len(all_docs)
    df: dict[str, int] = {}
    for doc in all_docs:
        for t in set(doc):
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n_docs + 1) / (d + 1)) + 1 for t, d in df.items()}


_IDF = _build_idf(_INTENT_CORPUS)
_INTENT_VECTORS: dict[str, dict[str, float]] = {
    label: _tfidf_vector(_tokenize(" ".join(phrases)), _IDF)
    for label, phrases in _INTENT_CORPUS.items()
}


def classify_intent(query: str) -> tuple[str, float]:
    """
    Return (closest_intent_label, score) for the cleaned query.
    Score is cosine similarity in [0, 1].
    """
    tokens = _tokenize(query)
    if not tokens:
        return "web_search", 0.0
    qvec = _tfidf_vector(tokens, _IDF)
    scores = {label: _cosine(qvec, ivec) for label, ivec in _INTENT_VECTORS.items()}
    best = max(scores, key=scores.get)
    return best, scores[best]


# ---------------------------------------------------------------------------
# Site-specific search extraction
# ---------------------------------------------------------------------------

_DOMAIN_TLDS = r"(?:com|org|net|io|co\.in|edu|gov)"

_SITE_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?:search\s+(?:karo\s+)?)?(.+?)\s+(?:search\s+(?:karo\s+)?)?(?:on|par|pe)\s+"
        r"([\w.-]+\." + _DOMAIN_TLDS + r")",
        _I,
    ),
    re.compile(
        r"([\w.-]+\." + _DOMAIN_TLDS + r")\s+(?:par|pe|on)\s+(.+?)\s+(?:search|dhundo|khojo)",
        _I,
    ),
    re.compile(
        r"([\w.-]+\." + _DOMAIN_TLDS + r")\s+(.+?)\s*(?:search\s*(?:karo|kar)?|dhundo|dhoondo|khojo)?$",
        _I,
    ),
]

_DOMAIN_RE = re.compile(r"^[\w.-]+\." + _DOMAIN_TLDS + r"$", _I)

_SITE_SEARCH_URLS: dict[str, str] = {
    "udemy.com":         "https://www.udemy.com/courses/search/?q={query}",
    "github.com":        "https://github.com/search?q={query}&type=repositories",
    "stackoverflow.com": "https://stackoverflow.com/search?q={query}",
    "youtube.com":       "https://www.youtube.com/results?search_query={query}",
    "amazon.in":         "https://www.amazon.in/s?k={query}",
    "amazon.com":        "https://www.amazon.com/s?k={query}",
    "flipkart.com":      "https://www.flipkart.com/search?q={query}",
    "reddit.com":        "https://www.reddit.com/search/?q={query}",
    "medium.com":        "https://medium.com/search?q={query}",
    "arxiv.org":         "https://arxiv.org/search/?searchtype=all&query={query}",
    "npmjs.com":         "https://www.npmjs.com/search?q={query}",
    "pypi.org":          "https://pypi.org/search/?q={query}",
    "leetcode.com":      "https://leetcode.com/search/?q={query}",
    "coursera.org":      "https://www.coursera.org/search?query={query}",
}


def _extract_site_search(raw_query: str) -> Optional[tuple[str, str]]:
    for pat in _SITE_PATTERNS:
        m = pat.search(raw_query)
        if m:
            g1, g2 = m.group(1).strip(), m.group(2).strip()
            if _DOMAIN_RE.match(g2):
                return g2.lower(), g1
            elif _DOMAIN_RE.match(g1):
                return g1.lower(), g2
    return None


def _site_search_url(domain: str, query: str) -> str:
    encoded = urllib.parse.quote_plus(query)
    if domain in {"google.com", "www.google.com"}:
        return f"https://www.google.com/search?q={encoded}"
    if domain in _SITE_SEARCH_URLS:
        return _SITE_SEARCH_URLS[domain].format(query=encoded)
    return f"https://www.google.com/search?q=site:{domain}+{encoded}"


# ---------------------------------------------------------------------------
# Core query cleaner
# ---------------------------------------------------------------------------

def _apply_hinglish_vocab(text: str) -> str:
    for pattern, replacement in _HINGLISH_VOCAB:
        text = pattern.sub(f" {replacement} ", text)
    return text


def _clean_query(query: str) -> str:
    q = (query or "").strip()
    q = _GOOGLE_SUFFIX_RE.sub("", q).strip()
    q = _LEADING_ACTION_RE.sub("", q)
    q = _TRAILING_CMD_RE.sub("", q)
    q = _apply_hinglish_vocab(q)
    return _WS_RE.sub(" ", q).strip()


# ---------------------------------------------------------------------------
# Result formatter
# ---------------------------------------------------------------------------

def _format_results(items: list[dict]) -> str:
    if not items:
        return "Koi results nahi mile."
    out = "Search results ye hain:\n"
    for i, item in enumerate(items, 1):
        title   = item.get("title", "No title")
        snippet = item.get("snippet", "").strip()
        out += f"{i}. {title}. {snippet}\n\n"
    return out.strip()


def _open_google_fallback(query: str) -> str:
    url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
    _open_default(url)
    return url


# ---------------------------------------------------------------------------
# Public LangChain tool
# ---------------------------------------------------------------------------

@tool
async def google_search(query: str) -> str:
    """
    Google par search karta hai aur top 3 results return karta hai.
    Speech ke liye friendly format mein — no raw links.

    Supported query styles (English + Hinglish):
    - "Google karo latest iPhone price"
    - "Search karo weather in Delhi"
    - "Find best Python tutorials"         ← FIX 1: no longer includes "me"
    - "udemy.com par machine learning course search karo"
    - "search two sum on leetcode.com"
    - "Python tutorial dhundo"
    - "Kya hai machine learning"           ← FIX 2: now routed here correctly
    - "Kaise karte hain web scraping"      ← FIX 2: now routed here correctly
    - "batao latest IPL results"           ← FIX 2: now routed here correctly
    """
    raw_query = query.strip()

    # ── Check search_cache first ──
    try:
        from vani.core.cache import search_cache
        cached_result = search_cache.get(raw_query)
        if cached_result:
            logger.info("Search cache hit for query: %s", raw_query)
            return cached_result
    except Exception as exc:
        logger.warning("Could not access search cache: %s", exc)

    # ── Step 0: Google site: operator  (e.g. "site:bceg.com on google") ────────
    # Must be checked BEFORE _extract_site_search() which would otherwise
    # misparse "site:domain.com" as a site-search domain (FIX 4).
    if _SITE_OPERATOR_RE.search(raw_query):
        clean_q = _clean_site_operator_query(raw_query)
        logger.info("site: operator query detected → %s", clean_q)
        api_key          = os.getenv("GOOGLE_SEARCH_API_KEY")
        search_engine_id = os.getenv("SEARCH_ENGINE_ID")
        if not api_key or not search_engine_id:
            _open_google_fallback(clean_q)
            res = f"✅ Google search browser mein khul gaya: {clean_q}"
            try:
                search_cache.set(raw_query, res, ttl_seconds=3600)
            except Exception:
                pass
            return res
        try:
            response = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": search_engine_id, "q": clean_q, "num": 3},
                timeout=10,
            )
            if response.status_code == 200:
                res = _format_results(response.json().get("items", []))
                try:
                    search_cache.set(raw_query, res, ttl_seconds=3600)
                except Exception:
                    pass
                return res
        except Exception as exc:
            logger.warning("site: operator search API failed: %s", exc)
        _open_google_fallback(clean_q)
        res = f"✅ Google search browser mein khul gaya: {clean_q}"
        try:
            search_cache.set(raw_query, res, ttl_seconds=3600)
        except Exception:
            pass
        return res

    # ── Step 1: site-specific routing ──────────────────────────────────────
    site_result = _extract_site_search(raw_query)
    if site_result:
        domain, q = site_result
        q = _clean_query(q)
        logger.info("Site-specific search → domain=%s  query=%s", domain, q)
        url = _site_search_url(domain, q)
        _open_default(url)
        res = f"✅ '{q}' ko {domain} par search kar diya. Browser mein result khul gaya."
        try:
            search_cache.set(raw_query, res, ttl_seconds=3600)
        except Exception:
            pass
        return res

    # ── Step 2: clean & classify ────────────────────────────────────────────
    cleaned = _clean_query(raw_query)
    intent, score  = classify_intent(cleaned)
    logger.info("Search query: %s  |  intent: %s (score=%.2f)", cleaned, intent, score)

    if not cleaned:
        return "Search query empty hai."

    # FIX 3: only enrich when intent confidence is high enough
    # Low-confidence classification should not rewrite the query
    _ENRICH_THRESHOLD = 0.50

    enriched = cleaned
    if score >= _ENRICH_THRESHOLD:
        if intent == "learn":
            enriched = f"best {cleaned} tutorial site:udemy.com OR site:coursera.org OR site:youtube.com"
        elif intent == "code":
            enriched = f"{cleaned} site:github.com OR site:stackoverflow.com"
        elif intent == "buy_product":
            enriched = f"{cleaned} buy price India"

    # ── Step 3: call Google Custom Search API ───────────────────────────────
    api_key          = os.getenv("GOOGLE_SEARCH_API_KEY")
    search_engine_id = os.getenv("SEARCH_ENGINE_ID")

    if not api_key or not search_engine_id:
        _open_google_fallback(enriched)
        res = f"✅ Google search default browser mein khul gaya: {cleaned}"
        try:
            search_cache.set(raw_query, res, ttl_seconds=3600)
        except Exception:
            pass
        return res

    try:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": search_engine_id, "q": enriched, "num": 3},
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("Google Search API failed; opening browser fallback: %s", exc)
        _open_google_fallback(enriched)
        res = f"✅ Google search browser mein khul gaya: {cleaned}"
        try:
            search_cache.set(raw_query, res, ttl_seconds=3600)
        except Exception:
            pass
        return res

    if response.status_code != 200:
        logger.warning("Google Search API returned %s; opening browser fallback", response.status_code)
        _open_google_fallback(enriched)
        res = f"✅ Google search browser mein khul gaya: {cleaned}"
        try:
            search_cache.set(raw_query, res, ttl_seconds=3600)
        except Exception:
            pass
        return res

    res = _format_results(response.json().get("items", []))
    try:
        search_cache.set(raw_query, res, ttl_seconds=3600)
    except Exception:
        pass
    return res


# ---------------------------------------------------------------------------
# Utility — open URL in default OS browser
# ---------------------------------------------------------------------------

def _open_default(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
    elif sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "", url])
    else:
        subprocess.Popen(["xdg-open", url])


# ---------------------------------------------------------------------------
# Startup helper
# ---------------------------------------------------------------------------

async def get_current_datetime() -> str:
    timezone = os.getenv("VANI_TIMEZONE", "Asia/Kolkata")
    try:
        now      = datetime.now(ZoneInfo(timezone))
        tz_label = "IST" if timezone == "Asia/Kolkata" else timezone
        return now.strftime(f"%d %B %Y, %I:%M %p {tz_label}")
    except Exception:
        return datetime.now().strftime("%d %B %Y, %I:%M %p")


# ---------------------------------------------------------------------------
# Public helper for router.py — classify Hinglish question as search query
# ---------------------------------------------------------------------------

def classify_hinglish_question_as_search(query: str) -> Optional[str]:
    """
    Called by router._router_classify() to catch Hinglish questions that
    have no leading 'google/search' trigger word.

    Returns the extracted search term, or None if not a Hinglish question.

    Examples:
      "kya hai machine learning"    → "machine learning"
      "kaise karte hain scraping"   → "scraping"
      "batao latest IPL results"    → "latest IPL results"
      "weather kya hai Delhi mein"  → "weather Delhi"   (after clean)
    """
    term = _extract_hinglish_question(query)
    if not term:
        return None
    return _clean_query(term) or term