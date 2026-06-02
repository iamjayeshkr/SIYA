"""
vani/reasoning/browser_regex.py  ·  v3.0 (Advanced + Hardened)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Advanced browser + YouTube + search intent classifier.

DESIGN GOALS:
  • Zero Ollama calls for ANY browser/YouTube/search command
  • Every permutation of English + Hinglish voice command covered
  • Sub-millisecond matching via compiled regex + priority chain
  • Single entry point: classify_browser_intent(query) → (intent, data) | None

v3 CHANGES vs v2:
  ─────────────────────────────────────────────────────────────────────
  FIX 1 — BROWSER_URL false-positive swallowing song-play commands
    Root cause: _BROWSER_URL_RE was matching before YT_PLAY_SONG in certain
    orderings ("open youtube and play X" matched "youtube" as a domain).
    Fix: URL regex now requires a dot (.) in the matched domain segment OR an
    explicit http(s) scheme, so bare site-names without TLD don't match.
    YT intents are still evaluated before BROWSER_URL in the chain.

  FIX 2 — Ambiguous "aage jao" (go forward in browser vs. YT seek)
    Old: any "aage jao" triggered BROWSER_FORWARD even with a time value.
    Fix: _BROWSER_FORWARD_RE negative lookahead excludes trailing digits/time
    words so "aage jao 10 second" stays as YT_SEEK_FWD.

  FIX 3 — YT_PLAY swallowing pure search queries without "youtube" keyword
    Old: "chalo dhoondo India vs Pakistan score" → YT_PLAY (wrong).
    Fix: YT_PLAY / YT_PAUSE now require either "youtube" in query OR a
    music-context keyword (bajao/chalao/gana/song) to fire.

  FIX 4 — _SEARCH_WEATHER_RE over-matching short city names
    Old: "karo" at end of queries accidentally matched as city.
    Fix: negative lookahead on city group excludes pure Hindi command words.

  FIX 5 — Tab number word-boundary collision
    Old: "char" inside "search" or "character" triggered BROWSER_TAB_N.
    Fix: tab-number words are now bounded with \\b anchors.

  FIX 6 — SEARCH_CALCULATOR false positives on phone numbers / years
    Old: bare "2025 kitna hoga" → SEARCH_CALCULATOR.
    Fix: require at least one operator or math keyword in the expression.

  FIX 7 — Duplicate named group "quality" across alternation branches
    Old: Python 3.7+ raises error on duplicate named groups in one pattern.
    Fix: _QUALITY_VALS uses numbered capture; quality value extracted via
    a fallback scan instead of .group("quality").

  NEW — BROWSER_SPLIT_SCREEN  split/tile current tab
  NEW — BROWSER_READING_MODE  toggle reader/distraction-free mode
  NEW — BROWSER_CLEAR_CACHE   clear browsing data / cache
  NEW — BROWSER_PRINT         print current page
  NEW — BROWSER_SAVE_PAGE     save page as HTML/PDF
  NEW — BROWSER_EXTENSIONS    open extension manager
  NEW — YT_DISLIKE            dislike video
  NEW — YT_SUBSCRIBE          subscribe/unsubscribe channel
  NEW — YT_PLAYLIST           add to playlist
  NEW — SEARCH_FLIGHT         flight search
  NEW — SEARCH_STOCK          stock / crypto price query

INTENT MAP (complete):
  BROWSER_OPEN          open/launch a browser app
  BROWSER_URL           navigate to a URL or domain
  BROWSER_SEARCH        search on Google/Bing/DuckDuckGo
  BROWSER_NEW_TAB       open a new tab
  BROWSER_CLOSE_TAB     close current tab
  BROWSER_REOPEN_TAB    reopen last closed tab
  BROWSER_NEXT_TAB      switch to next tab
  BROWSER_PREV_TAB      switch to previous tab
  BROWSER_TAB_N         jump to tab number N  (data = int)
  BROWSER_BACK          go back in history
  BROWSER_FORWARD       go forward in history
  BROWSER_REFRESH       reload current page
  BROWSER_HARD_REFRESH  hard reload (bypass cache)
  BROWSER_ZOOM_IN       zoom in
  BROWSER_ZOOM_OUT      zoom out
  BROWSER_ZOOM_RESET    reset zoom
  BROWSER_FULLSCREEN    toggle fullscreen
  BROWSER_FIND          Ctrl/Cmd+F in-page find  (data = term or "")
  BROWSER_SCROLL_DOWN   scroll down
  BROWSER_SCROLL_UP     scroll up
  BROWSER_SCROLL_TOP    scroll to top
  BROWSER_SCROLL_BOTTOM scroll to bottom
  BROWSER_BOOKMARK      bookmark current page
  BROWSER_HISTORY       open history
  BROWSER_DOWNLOADS     open downloads
  BROWSER_DEVTOOLS      open dev tools
  BROWSER_INCOGNITO     open incognito / private window
  BROWSER_MUTE_TAB      mute / unmute tab audio
  BROWSER_PIN_TAB       pin / unpin current tab
  BROWSER_SCREENSHOT    take page screenshot
  BROWSER_COPY_URL      copy current URL
  BROWSER_FOCUS_BAR     focus address bar
  BROWSER_SPLIT_SCREEN  split / tile browser
  BROWSER_READING_MODE  reader / focus mode
  BROWSER_CLEAR_CACHE   clear cache / browsing data
  BROWSER_PRINT         print page
  BROWSER_SAVE_PAGE     save page
  BROWSER_EXTENSIONS    open extensions

  YT_PLAY               play / resume
  YT_PAUSE              pause / stop
  YT_SEEK_FWD           seek forward  (data = seconds)
  YT_SEEK_BWD           seek backward (data = seconds)
  YT_NEXT               next video/song
  YT_PREV               previous video/song
  YT_PLAY_SONG          search & play song  (data = song name)
  YT_CLOSE_TAB          close YouTube tab
  YT_FULLSCREEN         toggle fullscreen
  YT_MUTE               mute / unmute
  YT_SPEED_UP           speed up playback
  YT_SPEED_DOWN         slow down playback
  YT_SPEED_RESET        reset speed to 1x
  YT_LOOP               toggle loop
  YT_CAPTIONS           toggle captions / subtitles
  YT_QUALITY            change video quality  (data = "1080p" / "720p" etc.)
  YT_LIKE               like video
  YT_DISLIKE            dislike video
  YT_SUBSCRIBE          subscribe / unsubscribe channel
  YT_PLAYLIST           add to playlist
  YT_THEATER            toggle theater mode
  YT_MINIPLAYER         toggle miniplayer

  SEARCH_GOOGLE         explicit Google search
  SEARCH_YOUTUBE        search on YouTube
  SEARCH_MAPS           Google Maps search
  SEARCH_IMAGES         Google Images search
  SEARCH_NEWS           news search
  SEARCH_SHOPPING       shopping search
  SEARCH_TRANSLATE      translation request  (data = {text, lang})
  SEARCH_WEATHER        weather query  (data = city/location)
  SEARCH_CALCULATOR     math / calculation query  (data = expression)
  SEARCH_DEFINE         word definition query  (data = word)
  SEARCH_TIMER          set a timer  (data = seconds)
  SEARCH_FLIGHT         flight search  (data = query string)
  SEARCH_STOCK          stock / crypto price  (data = symbol/name)
"""

from __future__ import annotations

import re
from typing import Optional

# ── Compile flag shorthand ────────────────────────────────────────────────────
_I = re.IGNORECASE


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — SHARED PRIMITIVES
# ══════════════════════════════════════════════════════════════════════════════

_V_OPEN    = r"(?:open|launch|start|kholo|kholna|chalu|chalao|shuru|open\s+karo|khol\s+do)"
_V_CLOSE   = r"(?:close|band|bandh|hatao|hata\s+do|quit|exit|band\s+karo|close\s+karo|close\s+kar)"
_V_GO      = r"(?:go(?:\s+to)?|jao|jao\s+pe|navigate(?:\s+to)?|visit|pe\s+jao|par\s+jao|chalo)"
_V_SEARCH  = r"(?:search(?:\s+karo|\s+kar)?|google(?:\s+karo|\s+kar)?|find|dhundo|dhoondo|khojo|dekho|dikhao|batao)"
_V_PLAY    = r"(?:play(?:\s+karo|\s+kar)?|chalu(?:\s+karo|\s+kar)?|resume(?:\s+karo|\s+kar)?|chalao|bajao|laga(?:o|do)?|start(?:\s+karo)?)"
_V_PAUSE   = r"(?:pause(?:\s+karo|\s+kar)?|rok(?:\s+do)?|stop(?:\s+karo|\s+kar)?|ruko|thehro|band\s+karo)"
_V_REFRESH = r"(?:refresh(?:\s+karo|\s+kar)?|reload(?:\s+karo|\s+kar)?|dobara\s+load(?:\s+karo)?|page\s+reload)"

_FILLER    = r"(?:please|zara|pls|plz|bhai|yaar|boss|mujhe|mujhko|thodaa?|ek\s+baar|jaldi|abhi|haan)?"

_DIR_FWD   = r"(?:forward|aage|skip\s+aage|fast\s+forward|aagey)"
_DIR_BWD   = r"(?:back(?:ward)?|peeche|rewind|wapas|piche)"
_DIR_DOWN  = r"(?:down(?:ward)?|neeche|neechey|niche)"
_DIR_UP    = r"(?:up(?:ward)?|upar|uppar)"

# Time value — only non-capturing groups
_TIME_VAL  = (
    r"(?:"
    r"(?:\d+)\s*(?:hour|hr|ghanta|ghante)s?\s*(?:(?:\d+)\s*(?:min(?:ute)?s?))?"
    r"|(?:\d+)\s*(?:min(?:ute)?s?)"
    r"|(?:\d+)\s*(?:sec(?:ond)?s?|s\b)"
    r"|(?:\d+)"
    r")"
)

_TAB_NUMS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5,
    "chhe": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Quality values — uses a plain capture group (no named group to avoid
# duplicate-name errors when embedded in multi-branch alternations).
_QUALITY_PAT = r"(?:2160p?|4k|1440p?|1080p?|720p?|480p?|360p?|240p?|144p?|auto(?:matic)?)"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — BROWSER NAVIGATION & TABS
# ══════════════════════════════════════════════════════════════════════════════

# 2a. Open browser app
_BROWSER_OPEN_RE = re.compile(
    rf"(?:{_V_OPEN}\s+)?"
    r"(?P<browser>google\s+chrome|chrome|firefox|safari|brave(?:\s+browser)?"
    r"|microsoft\s+edge|edge|opera|vivaldi|arc(?:\s+browser)?)"
    rf"(?:\s+{_V_OPEN})?",
    _I,
)

# 2b. Navigate to URL / domain
# FIX 1: require a real TLD dot in domain to avoid bare "youtube" matching
_BROWSER_URL_RE = re.compile(
    rf"(?:{_V_OPEN}|{_V_GO})\s+"
    r"(?P<url>"
    r"(?:https?://)[^\s]+"                                       # explicit scheme
    r"|[a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)+(?::\d+)?(?:/\S*)?" # has a dot-TLD
    r"|[a-z0-9][a-z0-9\-]*\s+dot\s+[a-z]{2,6}"                  # "youtube dot com"
    r")",
    _I,
)

# 2c. Address bar focus
_BROWSER_FOCUS_BAR_RE = re.compile(
    r"(?:"
    r"(?:address|url|location)\s+bar(?:\s+(?:focus|mein\s+jao|pe\s+click|kholna))?"
    r"|(?:focus|open)\s+(?:address|url|location)\s+bar"
    r"|omnibar(?:\s+focus)?"
    r"|search\s+bar(?:\s+(?:focus|pe\s+click))?"
    r")",
    _I,
)

# 2d. New tab
_BROWSER_NEW_TAB_RE = re.compile(
    r"(?:"
    r"(?:new|naya|nayi|fresh|blank)\s+tab(?:\s+(?:kholo|kholna|open\s+karo|open\s+kar))?"
    r"|tab\s+(?:new|naya|nayi|naya\s+wala|kholo|kholna|open\s+karo)"
    r"|(?:kholo|kholna|open\s+karo)\s+(?:new|naya)\s+tab"
    r")",
    _I,
)

# 2e. Close tab
_BROWSER_CLOSE_TAB_RE = re.compile(
    r"(?:"
    r"(?:close|band|bandh|hatao|hata\s+do)\s+(?:(?:current|active|yeh|is)\s+)?tab"
    r"|tab\s+(?:close|band|bandh|hatao|hata\s+do|close\s+karo|band\s+karo)"
    r"|current\s+tab\s+(?:close|band|hatao)"
    r"|(?:yeh|is|this)\s+tab\s+(?:close|band|hatao)"
    r"|tab\s+close\s+karo"
    r")",
    _I,
)

# 2e-ii. Close ALL tabs matching a site/name
# "close all youtube tabs", "saari youtube tabs band karo", "sab youtube tabs hatao"
_BROWSER_CLOSE_ALL_BY_NAME_RE = re.compile(
    r"(?:"
    r"(?:close|band|bandh|hatao|hata\s+do)\s+"
    r"(?:all|saari|saare|sab(?:hi)?|every(?:one)?|tamam)\s+"
    r"(?P<site_all>[a-z0-9][\w.\-\s]{0,40}?)\s*tabs?"
    r"|(?:all|saari|saare|sab(?:hi)?|tamam)\s+"
    r"(?P<site_all2>[a-z0-9][\w.\-\s]{0,40}?)\s*tabs?\s+"
    r"(?:close|band|bandh|hatao|hata\s+do|close\s+karo|band\s+karo)"
    r")",
    _I,
)

# 2e-iii. Close a SPECIFIC named tab (single)
# "close the claude tab", "gmail tab band karo", "close netflix tab"
_BROWSER_CLOSE_BY_NAME_RE = re.compile(
    r"(?:"
    r"(?:close|band|bandh|hatao|hata\s+do)\s+"
    r"(?:the\s+|wo\s+|woh\s+|yeh\s+|is\s+)?"
    r"(?P<site_one>[a-z0-9][\w.\-\s]{0,40}?)\s+tab(?:\s+(?:close|band|hatao|karo))?"
    r"|(?P<site_two>[a-z0-9][\w.\-\s]{0,40}?)\s+tab\s+"
    r"(?:close|band|bandh|hatao|hata\s+do|close\s+karo|band\s+karo)"
    r")",
    _I,
)

# 2j-ii. Switch to a named tab
# "switch to claude tab", "go to gmail tab", "youtube par switch karo",
# "claude par jao", "netflix pe jao", "return to github"
_BROWSER_SWITCH_BY_NAME_RE = re.compile(
    r"(?:"
    # verb-first: "switch to X", "go to X", "return to X", "focus X"
    r"(?:switch\s+to|go\s+to|return\s+to|wapas\s+(?:jao|chalo)|focus)\s+"
    r"(?:the\s+|wo\s+|woh\s+)?"
    r"(?P<sw_site>[a-z0-9][a-z0-9\-]{1,38})(?:\s+tab)?"
    r"|"
    # "open X tab" — requires "tab" word to avoid stealing URLs
    r"open\s+(?P<sw_site_open>[a-z0-9][a-z0-9\-]{1,38})\s+tab"
    r"|"
    # site-first + nav verb: "X par/pe switch karo", "X par/pe jao", "X tab pe jao"
    r"(?P<sw_site2>[a-z0-9][a-z0-9\-]{1,38})\s+(?:tab\s+)?"
    r"(?:par|pe)\s+(?:switch(?:\s+karo)?|jao|chalo|switch\s+ho\s+jao)"
    r"|"
    # site-first + tab + nav verb: "X tab pe switch", "X tab pe jao"
    r"(?P<sw_site3>[a-z0-9][a-z0-9\-]{1,38})\s+tab\s+"
    r"(?:pe\s+jao|par\s+jao|switch|kholo|dikhao|focus|pe\s+switch)"
    r")",
    _I,
)

# 2f. Reopen closed tab
_BROWSER_REOPEN_TAB_RE = re.compile(
    r"(?:"
    r"reopen(?:\s+(?:last\s+)?(?:closed\s+)?tab)?"
    r"|(?:last\s+)?closed\s+tab\s+(?:wapas|phir\s+se|open\s+karo|restore)"
    r"|tab\s+(?:undo|restore|wapas\s+lao)"
    r"|undo\s+(?:tab\s+)?close"
    r"|(?:wapas|phir\s+se)\s+(?:wo|last|pichla)\s+tab"
    r")",
    _I,
)

# 2g. Next tab
_BROWSER_NEXT_TAB_RE = re.compile(
    r"(?:"
    r"next\s+tab"
    r"|agla\s+tab"
    r"|tab\s+(?:aage|next|forward)"
    r"|(?:aage\s+wala|next\s+wala)\s+tab"
    r"|switch\s+(?:to\s+)?next\s+tab"
    r"|tab\s+switch\s+(?:aage|right|next)"
    r")",
    _I,
)

# 2h. Previous tab
_BROWSER_PREV_TAB_RE = re.compile(
    r"(?:"
    r"prev(?:ious)?\s+tab"
    r"|pichla\s+tab"
    r"|tab\s+(?:peeche|prev(?:ious)?|back(?:ward)?)"
    r"|(?:peeche\s+wala|previous\s+wala|pichla\s+wala)\s+tab"
    r"|switch\s+(?:to\s+)?prev(?:ious)?\s+tab"
    r"|tab\s+switch\s+(?:peeche|left|back)"
    r")",
    _I,
)

# 2i. Jump to tab N  (FIX 5: word boundaries on tab number words)
_BROWSER_TAB_N_RE = re.compile(
    r"(?:"
    r"tab\s+(?:number\s+)?(?P<n1>\d+)"
    r"|(?P<n2>\d+)(?:st|nd|rd|th)?\s+tab(?:\s+pe\s+jao)?"
    r"|(?P<nw>\bek\b|\bdo\b|\bteen\b|\bchar\b|\bpaanch\b|\bchhe\b|\bsaat\b|\baath\b|\bnau\b|\bdas\b"
    r"|\bone\b|\btwo\b|\bthree\b|\bfour\b|\bfive\b|\bsix\b|\bseven\b|\beight\b|\bnine\b|\bten\b)"
    r"\s+(?:number\s+)?tab"
    r")",
    _I,
)

# 2j. Back / Forward navigation
# FIX 2: Forward regex has negative lookahead to exclude time-bearing "aage jao"
_BROWSER_BACK_RE = re.compile(
    r"(?:"
    r"(?:browser\s+)?(?:go\s+)?back(?:\s+(?:karo|kar|jao))?"
    r"|peeche\s+(?:jao|karo|wapas)"
    r"|wapas\s+(?:jao|karo|peeche)"
    r"|previous\s+page(?:\s+(?:karo|jao))?"
    r"|history\s+(?:mein\s+)?back"
    r"|(?:alt\s+)?left\s+arrow\s+press"
    r"|page\s+back(?:\s+karo)?"
    r")",
    _I,
)

_BROWSER_FORWARD_RE = re.compile(
    r"(?:"
    r"(?:browser\s+)?(?:go\s+)?forward(?:\s+(?:karo|kar|jao))?"
    # "aage jao" only if NOT followed by a digit/time — let YT_SEEK_FWD handle those
    r"|aage\s+jao(?!\s*\d)(?!\s*(?:second|sec|minute|min|hour|hr|ghanta))"
    r"|next\s+page(?:\s+(?:karo|jao))?"
    r"|history\s+(?:mein\s+)?forward"
    r"|page\s+forward(?:\s+karo)?"
    r")",
    _I,
)

# 2k. Refresh / Hard Refresh
_BROWSER_REFRESH_RE = re.compile(
    r"(?:"
    r"(?:page\s+)?refresh(?:\s+(?:karo|kar))?"
    r"|(?:page\s+)?reload(?:\s+(?:karo|kar))?"
    r"|dobara\s+(?:load|kholo)(?:\s+(?:karo|kar))?"
    r"|f5\s+(?:press\s+)?(?:karo|kar)?"
    r")",
    _I,
)

_BROWSER_HARD_REFRESH_RE = re.compile(
    r"(?:"
    r"hard\s+refresh(?:\s+(?:karo|kar))?"
    r"|force\s+reload(?:\s+(?:karo|kar))?"
    r"|cache\s+(?:clear\s+karke\s+)?reload"
    r"|ctrl\s*\+?\s*shift\s*\+?\s*r"
    r"|shift\s+refresh"
    r")",
    _I,
)

# 2l. Zoom
_BROWSER_ZOOM_IN_RE = re.compile(
    r"(?:"
    r"zoom\s+in(?:\s+(?:karo|kar))?"
    r"|(?:page\s+)?bada\s+karo"
    r"|(?:text|font)\s+(?:bada|large|increase)(?:\s+karo)?"
    r"|(?:increase|badao)\s+(?:zoom|size)"
    r"|(?:ctrl|cmd)\s*\+?\s*plus"
    r")",
    _I,
)

_BROWSER_ZOOM_OUT_RE = re.compile(
    r"(?:"
    r"zoom\s+out(?:\s+(?:karo|kar))?"
    r"|(?:page\s+)?chota\s+karo"
    r"|(?:text|font)\s+(?:chota|small|decrease)(?:\s+karo)?"
    r"|(?:decrease|ghatao)\s+(?:zoom|size)"
    r"|(?:ctrl|cmd)\s*\+?\s*minus"
    r")",
    _I,
)

_BROWSER_ZOOM_RESET_RE = re.compile(
    r"(?:"
    r"zoom\s+reset(?:\s+(?:karo|kar))?"
    r"|(?:zoom|size)\s+(?:normal|default|reset|wapas\s+normal)(?:\s+karo)?"
    r"|100\s*%\s+(?:zoom\s+)?(?:karo|set\s+karo)?"
    r")",
    _I,
)

# 2m. Fullscreen
_BROWSER_FULLSCREEN_RE = re.compile(
    r"(?:"
    r"(?:browser\s+)?fullscreen(?:\s+(?:karo|kar|toggle))?"
    r"|full\s+screen(?:\s+(?:karo|kar|mode))?"
    r"|f11(?:\s+(?:press\s+)?(?:karo|kar))?"
    r"|browser\s+(?:maximize|full\s+kar)"
    r"|(?:window\s+)?full\s+kar(?:\s+do)?"
    r")",
    _I,
)

# 2n. In-page find
_BROWSER_FIND_RE = re.compile(
    r"(?:"
    r"(?:find|search)\s+(?:in|on|mein|page\s+mein|this\s+page)"
    r"|(?:ctrl|cmd)\s*\+?\s*f\b"
    r"|page\s+(?:mein\s+)?(?:find|dhundo|search)(?:\s+(?P<term>.+))?"
    r"|(?:find|dhundo)\s+(?:(?:in|on|mein)\s+)?(?:this\s+)?page"
    r")",
    _I,
)

# 2o. Scroll
_BROWSER_SCROLL_DOWN_RE = re.compile(
    r"(?:"
    r"scroll\s+down(?:\s+(?:karo|kar))?"
    r"|(?:page\s+)?neeche(?:\s+(?:jao|karo|scroll))?"
    r"|neechey\s+(?:jao|karo)"
    r"|down\s+scroll(?:\s+(?:karo|kar))?"
    r"|neeche\s+scroll\s+(?:karo|kar)"
    r")",
    _I,
)

_BROWSER_SCROLL_UP_RE = re.compile(
    r"(?:"
    r"scroll\s+up(?:\s+(?:karo|kar))?"
    r"|(?:page\s+)?upar(?:\s+(?:jao|karo|scroll))?"
    r"|uppar\s+(?:jao|karo)"
    r"|up\s+scroll(?:\s+(?:karo|kar))?"
    r"|upar\s+scroll\s+(?:karo|kar)"
    r")",
    _I,
)

_BROWSER_SCROLL_TOP_RE = re.compile(
    r"(?:"
    r"scroll\s+to\s+(?:the\s+)?top(?:\s+(?:karo|kar))?"
    r"|(?:page\s+ke\s+)?(?:bilkul\s+)?upar(?:\s+(?:jao|jate\s+hain))?"
    r"|top\s+(?:pe|par)\s+(?:jao|scroll\s+karo)"
    r"|(?:home\s+key|ctrl\s*\+?\s*home)"
    r"|sabse\s+upar(?:\s+jao)?"
    r")",
    _I,
)

_BROWSER_SCROLL_BOTTOM_RE = re.compile(
    r"(?:"
    r"scroll\s+to\s+(?:the\s+)?(?:bottom|end)(?:\s+(?:karo|kar))?"
    r"|(?:page\s+ke\s+)?(?:bilkul\s+)?neeche(?:\s+(?:jao|jate\s+hain))?"
    r"|bottom\s+(?:pe|par)\s+(?:jao|scroll\s+karo)"
    r"|(?:end\s+key|ctrl\s*\+?\s*end)"
    r"|sabse\s+neeche(?:\s+jao)?"
    r")",
    _I,
)

# 2p. Bookmark
_BROWSER_BOOKMARK_RE = re.compile(
    r"(?:"
    r"bookmark(?:\s+(?:karo|kar|add\s+karo|this\s+page))?"
    r"|(?:this\s+)?page\s+(?:bookmark|save|favourite)\s*(?:karo|kar|mein\s+add)?"
    r"|(?:add\s+to\s+)?(?:favourites?|bookmarks?)(?:\s+(?:mein\s+add|add\s+karo))?"
    r"|(?:ctrl|cmd)\s*\+?\s*d\b"
    r"|pasand\s+(?:mein\s+)?(?:add|save)\s+karo"
    r")",
    _I,
)

# 2q. History / Downloads / DevTools
_BROWSER_HISTORY_RE = re.compile(
    r"(?:"
    r"(?:open|show|dikha(?:o)?)\s+(?:browser\s+)?history"
    r"|browser\s+history(?:\s+(?:kholo|dikha(?:o)?|open))?"
    r"|(?:ctrl|cmd)\s*\+?\s*h\b"
    r"|history\s+(?:mein\s+)?(?:jao|dekho|kholo)"
    r")",
    _I,
)

_BROWSER_DOWNLOADS_RE = re.compile(
    r"(?:"
    r"(?:open|show|dikha(?:o)?)\s+downloads?"
    r"|downloads?\s+(?:folder\s+)?(?:kholo|dikha(?:o)?|open|show)?"
    r"|(?:ctrl|cmd)\s*\+?\s*j\b"
    r"|download\s+(?:folder|page)\s+(?:kholo|dekho)"
    r")",
    _I,
)

_BROWSER_DEVTOOLS_RE = re.compile(
    r"(?:"
    r"(?:open|show)\s+(?:dev(?:eloper)?\s+)?(?:tools?|console|inspector)"
    r"|dev(?:eloper)?\s+tools?(?:\s+(?:kholo|open))?"
    r"|(?:f12|f\s*12)(?:\s+(?:press\s+)?(?:karo|kar))?"
    r"|inspect(?:\s+element)?(?:\s+(?:karo|kar))?"
    r"|console\s+(?:kholo|open)"
    r")",
    _I,
)

# 2r. Incognito / Private
_BROWSER_INCOGNITO_RE = re.compile(
    r"(?:"
    r"(?:open|new)\s+(?:incognito|private|secret)\s+(?:window|tab|mode)?"
    r"|incognito(?:\s+(?:window|mode|mein|tab))?(?:\s+(?:kholo|open\s+karo))?"
    r"|private\s+(?:window|mode|tab|browsing)?(?:\s+(?:kholo|open\s+karo))?"
    r"|(?:ctrl|cmd)\s*\+?\s*shift\s*\+?\s*n\b"
    r"|chhupa\s+ke\s+browse(?:\s+karna)?"
    r")",
    _I,
)

# 2s. Mute tab
_BROWSER_MUTE_TAB_RE = re.compile(
    r"(?:"
    r"(?:mute|unmute)\s+(?:this\s+)?tab"
    r"|tab\s+(?:mute|unmute|silent|awaaz\s+band)"
    r"|(?:is\s+)?tab\s+ki\s+awaaz\s+(?:band|mute)\s+(?:karo|kar)"
    r"|tab\s+(?:audio|sound)\s+(?:mute|off|band)"
    r")",
    _I,
)

# 2t. Pin tab
_BROWSER_PIN_TAB_RE = re.compile(
    r"(?:"
    r"(?:pin|unpin)\s+(?:this\s+)?tab(?:\s+(?:karo|kar))?"
    r"|tab\s+(?:pin|unpin)(?:\s+(?:karo|kar))?"
    r"|tab\s+ko\s+(?:pin|unpin)\s+(?:karo|kar)"
    r")",
    _I,
)

# 2u. Screenshot
_BROWSER_SCREENSHOT_RE = re.compile(
    r"(?:"
    r"(?:take|le|lena)\s+(?:page\s+)?screenshot(?:\s+(?:karo|kar))?"
    r"|page\s+(?:ka\s+)?screenshot(?:\s+(?:lo|le\s+lo|lena|karo))?"
    r"|screenshot(?:\s+(?:lo|lena|karo|le\s+lo|nikaalo))?"
    r")",
    _I,
)

# 2v. Copy URL
_BROWSER_COPY_URL_RE = re.compile(
    r"(?:"
    r"copy\s+(?:current\s+)?(?:url|link|address)(?:\s+(?:karo|kar))?"
    r"|(?:url|link|address)\s+copy(?:\s+(?:karo|kar))?"
    r"|is\s+(?:page\s+ka|tab\s+ka)\s+(?:url|link)\s+copy(?:\s+(?:karo|kar))?"
    r")",
    _I,
)

# ── NEW v3 browser intents ─────────────────────────────────────────────────────

_BROWSER_SPLIT_SCREEN_RE = re.compile(
    r"(?:"
    r"split\s+(?:screen|view|tab)(?:\s+(?:karo|kar|mode))?"
    r"|tile\s+(?:windows?|tabs?)(?:\s+(?:karo|kar))?"
    r"|side\s+by\s+side(?:\s+(?:dekho|karo))?"
    r"|do\s+tabs?\s+ek\s+saath\s+(?:dikha(?:o)?|karo)"
    r")",
    _I,
)

_BROWSER_READING_MODE_RE = re.compile(
    r"(?:"
    r"reader\s+(?:mode|view)(?:\s+(?:on|off|toggle|karo|kar))?"
    r"|reading\s+mode(?:\s+(?:on|off|toggle|karo|kar))?"
    r"|distraction\s*[\-\s]?free(?:\s+mode)?(?:\s+(?:karo|kar))?"
    r"|focus\s+mode(?:\s+(?:karo|kar))?"
    r"|reader\s+(?:view\s+)?(?:kholo|chalu\s+karo|toggle)"
    r")",
    _I,
)

_BROWSER_CLEAR_CACHE_RE = re.compile(
    r"(?:"
    r"clear\s+(?:browser\s+)?(?:cache|cookies?|history|data|browsing\s+data)"
    r"|cache\s+(?:clear|delete|hatao)(?:\s+(?:karo|kar))?"
    r"|cookies?\s+(?:delete|clear|hatao)(?:\s+(?:karo|kar))?"
    r"|browsing\s+data\s+(?:clear|delete)(?:\s+(?:karo|kar))?"
    r")",
    _I,
)

_BROWSER_PRINT_RE = re.compile(
    r"(?:"
    r"(?:print|print\s+karo)(?:\s+(?:this\s+)?(?:page|tab))?"
    r"|page\s+print(?:\s+(?:karo|kar))?"
    r"|(?:ctrl|cmd)\s*\+?\s*p\b"
    r")",
    _I,
)

_BROWSER_SAVE_PAGE_RE = re.compile(
    r"(?:"
    r"save\s+(?:this\s+)?page(?:\s+(?:karo|kar|as))?"
    r"|page\s+(?:save|download)(?:\s+(?:karo|kar))?"
    r"|(?:ctrl|cmd)\s*\+?\s*s\b"
    r"|page\s+ko\s+(?:save|download)\s+(?:karo|kar)"
    r")",
    _I,
)

_BROWSER_EXTENSIONS_RE = re.compile(
    r"(?:"
    r"(?:open|show|manage)\s+(?:browser\s+)?extensions?"
    r"|extensions?\s+(?:manager|page)?(?:\s+(?:kholo|open))?"
    r"|addon\s+(?:manager|page)?(?:\s+(?:kholo|open))?"
    r"|chrome://extensions"
    r")",
    _I,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — YOUTUBE CONTROLS
# ══════════════════════════════════════════════════════════════════════════════

_NON_YT_GUARD_RE = re.compile(
    r"\b(?:whatsapp|telegram|spotify|apple\s+music|hotstar|netflix|prime\s+video"
    r"|gaana|wynk|jiosaavn|jio\s+saavn|instagram|facebook)\b",
    _I,
)

# FIX 3: YT_PLAY requires either "youtube" OR a music keyword
_YT_CONTEXT_RE = re.compile(
    r"\b(?:youtube|bajao|chalao|gana|gaana|song|music|video\s+play)\b",
    _I,
)

_YT_PLAY_RE = re.compile(
    r"(?:"
    r"(?:youtube\s+)?(?:video|gana|song)?\s*"
    r"(?:play|chalu|resume|chalao|bajao|laga(?:o|do)?|start)(?:\s+(?:karo|kar))?"
    r"|(?:play|chalu|resume|chalao|bajao|laga(?:o|do)?|start)\s+(?:youtube|video|gana)"
    r"|space\s+(?:press\s+)?(?:karo|kar)?"
    r")",
    _I,
)

_YT_PAUSE_RE = re.compile(
    r"(?:"
    r"(?:youtube\s+)?(?:video|gana|song)?\s*"
    r"(?:pause|rok|ruko|stop|thehro|band\s+karo)(?:\s+(?:karo|kar|do))?"
    r"|(?:pause|rok|ruko|stop|thehro)\s+(?:youtube|video|gana)"
    r")",
    _I,
)

_YT_SEEK_FWD_RE = re.compile(
    rf"(?:"
    rf"(?P<fwd_time1>{_TIME_VAL})\s+{_DIR_FWD}"
    rf"|{_DIR_FWD}\s+(?P<fwd_time2>{_TIME_VAL})"
    rf"|skip\s+(?:forward\s+)?(?P<fwd_time3>{_TIME_VAL})"
    rf"|fast\s+forward\s+(?P<fwd_time4>{_TIME_VAL})?"
    r")",
    _I,
)

_YT_SEEK_BWD_RE = re.compile(
    rf"(?:"
    rf"(?P<bwd_time1>{_TIME_VAL})\s+{_DIR_BWD}"
    rf"|{_DIR_BWD}\s+(?P<bwd_time2>{_TIME_VAL})"
    rf"|rewind\s+(?P<bwd_time3>{_TIME_VAL})?"
    rf"|wapas\s+(?P<bwd_time4>{_TIME_VAL})\s+second"
    r")",
    _I,
)

_YT_NEXT_RE = re.compile(
    r"(?:"
    r"next\s+(?:song|video|gana|track|wala)"
    r"|agla\s+(?:song|video|gana|track|wala)"
    r"|pudcha\s+(?:song|gana|track)"
    r"|(?:song|video|gana)\s+next(?:\s+(?:karo|kar|chalao))?"
    r"|next\s+(?:chalao|bajao|play\s+karo)"
    r"|shift\s*\+?\s*n"
    r")",
    _I,
)

_YT_PREV_RE = re.compile(
    r"(?:"
    r"prev(?:ious)?\s+(?:song|video|gana|track|wala)"
    r"|pichla\s+(?:song|video|gana|track|wala)"
    r"|pehle\s+wala\s+(?:song|gana|video)"
    r"|(?:song|video|gana)\s+prev(?:ious)?(?:\s+(?:karo|kar|chalao))?"
    r"|prev(?:ious)?\s+(?:chalao|bajao|play\s+karo)"
    r"|shift\s*\+?\s*p"
    r")",
    _I,
)

_YT_PLAY_SONG_RE = re.compile(
    r"(?:"
    r"youtube\s+(?:par\s+|pe\s+)?(?:search\s+(?:karo\s+)?|" + _V_PLAY + r"\s+)?(?P<s1>.+)"
    r"|(?P<s2>.+?)\s+(?:youtube\s+(?:par|pe)\s+)?(?:bajao|chalao|play\s+(?:karo|kar)?|laga(?:o|do)?)"
    r"|(?:song|gana|music|track)\s+(?:bajao|chalao|laga(?:o|do)?)\s+(?P<s3>.+)"
    r"|(?P<s4>.+?)\s+(?:ka\s+)?(?:song|gana)\s+(?:bajao|laga(?:o|do)?|chalao)"
    r"|open\s+youtube\s+and\s+play\s+(?P<s5>.+)"
    r")",
    _I,
)

_YT_CLOSE_TAB_RE = re.compile(
    r"(?:"
    # bare "tab close/band" only fires when "youtube" context present (enforced at dispatch)
    r"(?:youtube\s+)?tab\s+(?:close|band|bandh|hatao)(?:\s+(?:karo|kar))?"
    r"|(?:close|band)\s+youtube(?:\s+tab)?"
    r"|youtube\s+(?:band|close|hatao)(?:\s+(?:karo|kar))?"
    r"|youtube\s+window\s+(?:band|close)(?:\s+(?:karo|kar))?"
    r")",
    _I,
)

# Negative-lookahead version used at dispatch time:
# Do NOT fire YT_CLOSE_TAB when a non-youtube named site precedes "tab"
_YT_CLOSE_TAB_NAMED_GUARD_RE = re.compile(
    r"\b(?!youtube\b)[a-z][a-z0-9\-]{2,}\s+tab\s+(?:close|band|bandh|hatao)",
    _I,
)

# "tab close karo" / "tab band karo" without youtube context → BROWSER_CLOSE_TAB
_BARE_TAB_CLOSE_RE = re.compile(
    r"^tab\s+(?:close|band|bandh|hatao)(?:\s+(?:karo|kar))?$",
    _I,
)

_YT_FULLSCREEN_RE = re.compile(
    r"(?:"
    r"(?:youtube\s+)?(?:full\s*screen|fullscreen)(?:\s+(?:karo|kar|toggle|mode))?"
    r"|video\s+(?:bada\s+karo|fullscreen)"
    r"|(?:f\s+key|f\s+press)\s+(?:karo|kar)"
    r"|press\s+f\s+(?:for\s+fullscreen)?"
    r")",
    _I,
)

_YT_MUTE_RE = re.compile(
    r"(?:"
    r"(?:youtube\s+)?(?:mute|unmute)(?:\s+(?:karo|kar|youtube))?"
    r"|(?:youtube\s+)?awaaz\s+(?:band|off|mute|chalu|on)(?:\s+(?:karo|kar))?"
    r"|video\s+(?:mute|unmute|silent)(?:\s+(?:karo|kar))?"
    r"|(?:m\s+key|m\s+press)\s+(?:karo|kar)"
    r")",
    _I,
)

_YT_SPEED_UP_RE = re.compile(
    r"(?:"
    r"(?:speed|playback)\s+(?:up|increase|badao|tez|fast(?:er)?)(?:\s+(?:karo|kar))?"
    r"|(?:1\.25|1\.5|1\.75|2)x\s+(?:speed|pe\s+chalao|set\s+karo)"
    r"|tez(?:i\s+se)?\s+(?:chalao|play\s+karo)"
    r"|(?:shift\s*\+?\s*>|>)\s*(?:press\s+)?(?:karo|kar)?"
    r")",
    _I,
)

_YT_SPEED_DOWN_RE = re.compile(
    r"(?:"
    r"(?:speed|playback)\s+(?:down|decrease|slow(?:er)?|dhheema|ghatao)(?:\s+(?:karo|kar))?"
    r"|(?:0\.25|0\.5|0\.75)x\s+(?:speed|pe\s+chalao|set\s+karo)"
    r"|dhheema\s+(?:chalao|play\s+karo|karo)"
    r"|(?:shift\s*\+?\s*<|<)\s*(?:press\s+)?(?:karo|kar)?"
    r")",
    _I,
)

_YT_SPEED_RESET_RE = re.compile(
    r"(?:"
    r"(?:speed|playback)\s+(?:reset|normal|default|1x|wapas\s+normal)(?:\s+(?:karo|kar))?"
    r"|1x\s+(?:speed\s+)?(?:pe|par)\s+(?:set|wapas)"
    r"|normal\s+speed(?:\s+(?:karo|kar|pe\s+chalao))?"
    r")",
    _I,
)

_YT_LOOP_RE = re.compile(
    r"(?:"
    r"(?:toggle\s+)?loop(?:\s+(?:karo|kar|on|off))?"
    r"|video\s+(?:loop|repeat)(?:\s+(?:karo|kar|on|off))?"
    r"|(?:repeat|dobara\s+chalao)\s+(?:this\s+)?(?:video|song|gana)(?:\s+(?:karo|kar))?"
    r"|baar\s+baar\s+(?:chalao|bajao)"
    r")",
    _I,
)

_YT_CAPTIONS_RE = re.compile(
    r"(?:"
    r"(?:toggle|on|off|enable|disable|chalu|band)\s+(?:captions?|subtitles?|cc)"
    r"|(?:captions?|subtitles?|cc)\s+(?:on|off|toggle|chalu|band|enable|disable)(?:\s+(?:karo|kar))?"
    r"|(?:subtitles?|captions?)\s+(?:dikha(?:o)?|hatao|chalu\s+karo|band\s+karo)"
    r"|(?:c\s+key|c\s+press)\s+(?:karo|kar)"
    r")",
    _I,
)

# FIX 7: Quality pattern without named group (avoids duplicate-name error)
_YT_QUALITY_RE = re.compile(
    rf"(?:"
    rf"(?:quality|resolution)\s+({_QUALITY_PAT})(?:\s+(?:set|karo|kar|pe\s+chalao))?"
    rf"|({_QUALITY_PAT})\s+(?:quality|resolution|mein\s+chalao|pe\s+set\s+karo)"
    rf"|(?:set|change)\s+(?:quality|resolution)\s+(?:to\s+)?({_QUALITY_PAT})"
    r")",
    _I,
)

_YT_LIKE_RE = re.compile(
    r"(?:"
    r"(?:like|thumbs?\s+up)(?:\s+(?:this\s+)?(?:video|gana|song))?(?:\s+(?:karo|kar|do))?"
    r"|video\s+(?:like|pasand)\s+(?:karo|kar)"
    r"|is\s+video\s+ko\s+like\s+(?:karo|kar|do)"
    r")",
    _I,
)

_YT_THEATER_RE = re.compile(
    r"(?:"
    r"(?:toggle\s+)?theater(?:\s+mode)?(?:\s+(?:karo|kar))?"
    r"|cinema(?:\s+mode)?(?:\s+(?:karo|kar))?"
    r"|(?:t\s+key|t\s+press)\s+(?:karo|kar)"
    r")",
    _I,
)

_YT_MINIPLAYER_RE = re.compile(
    r"(?:"
    r"(?:toggle\s+)?miniplayer(?:\s+(?:karo|kar))?"
    r"|mini(?:\s+player)?(?:\s+(?:mode|karo|kar))?"
    r"|(?:i\s+key|i\s+press)\s+(?:karo|kar)"
    r"|picture.in.picture(?:\s+(?:karo|kar|mode))?"
    r")",
    _I,
)

# NEW v3 YT intents
_YT_DISLIKE_RE = re.compile(
    r"(?:"
    r"(?:dislike|thumbs?\s+down)(?:\s+(?:this\s+)?(?:video|gana|song))?(?:\s+(?:karo|kar|do))?"
    r"|video\s+dislike(?:\s+(?:karo|kar))?"
    r"|is\s+video\s+ko\s+dislike\s+(?:karo|kar|do)"
    r")",
    _I,
)

_YT_SUBSCRIBE_RE = re.compile(
    r"(?:"
    r"(?:subscribe|unsubscribe)(?:\s+(?:to\s+)?(?:this\s+)?(?:channel|creator))?(?:\s+(?:karo|kar|do))?"
    r"|channel\s+(?:subscribe|unsubscribe)(?:\s+(?:karo|kar))?"
    r"|subscribe\s+karo\s+(?:is\s+)?channel(?:\s+ko)?"
    r")",
    _I,
)

_YT_PLAYLIST_RE = re.compile(
    r"(?:"
    r"add\s+to\s+(?:my\s+)?playlist(?:\s+(?:karo|kar))?"
    r"|playlist\s+mein\s+add(?:\s+(?:karo|kar))?"
    r"|save\s+(?:to\s+)?(?:watch\s+later|playlist)"
    r"|watch\s+later\s+mein\s+(?:add|save)(?:\s+(?:karo|kar))?"
    r")",
    _I,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — SEARCH ENGINE INTENTS
# ══════════════════════════════════════════════════════════════════════════════

_SEARCH_GOOGLE_RE = re.compile(
    r"(?:"
    r"(?:google|search|find|look\s*up|lookup)\s+"
    r"(?:(?:me|mujhe|humko|please|zara|karo|kar|for|kijiye)\s+)*"
    r"(?P<gq1>.+)"
    r"|"
    r"(?P<gq2>.+?)\s+"
    r"(?:google\s+(?:karo|kar)|search\s+(?:karo|kar)|dhundo|dhoondo|khojo|batao|dikhao|dekho)"
    r"|"
    r"(?:kya\s+(?:hai|hain|hota\s+hai)|kaisa?\s+(?:hai|hain)|kab\s+(?:hai|tha)|kahan\s+(?:hai|hain)"
    r"|kitna\s+(?:hai|hain)|kaise\s+(?:karte|kare)|kaun\s+(?:hai|hain)|kyun\s+(?:hai|hain))\s+"
    r"(?P<gq3>.+)"
    r"|"
    r"(?P<gq4>.+?)\s+ke\s+baare?\s+mein\s+(?:batao|bata|bolo|likho|search)"
    r")",
    _I,
)

_SEARCH_YOUTUBE_RE = re.compile(
    r"(?:"
    r"youtube\s+(?:par\s+|pe\s+)?(?:search\s+(?:karo\s+)?|dhundo\s+)(?P<yq1>.+)"
    r"|(?P<yq2>.+?)\s+youtube\s+(?:par|pe)\s+(?:search\s+(?:karo|kar)?|dhundo)"
    r"|youtube\s+(?:par|pe)\s+(?P<yq3>.+?)\s+(?:dhundo|search\s+(?:karo|kar)?)"
    r")",
    _I,
)

_SEARCH_MAPS_RE = re.compile(
    r"(?:"
    r"(?:google\s+)?maps\s+(?:par\s+|pe\s+|mein\s+)?(?:search\s+(?:karo\s+)?|(?:dikha(?:o)?|dikhao)\s+)?(?P<mq1>.+)"
    r"|(?:directions?\s+(?:to|for)|rasta\s+(?:batao|nikalo))\s+(?P<mq2>.+)"
    r"|(?P<mq3>.+?)\s+(?:ka|ki|ke)\s+(?:location|jagah|address|rasta)\s+(?:dikha(?:o)?|batao|dhundo)"
    r"|(?P<mq4>.+?)\s+(?:kahan\s+hai|kaha\s+hai|kidhar\s+hai)"
    r"|navigate\s+to\s+(?P<mq5>.+)"
    r")",
    _I,
)

_SEARCH_IMAGES_RE = re.compile(
    r"(?:"
    r"(?:google\s+)?images?\s+(?:of|for|mein)\s+(?P<iq1>.+)"
    r"|(?P<iq2>.+?)\s+(?:ki\s+|ka\s+|ke\s+)?(?:image|photo|picture|tasveer|taswiir)\s+"
    r"(?:dhundo|search\s+(?:karo|kar)?|dikha(?:o)?)"
    r"|(?:image|photo|picture)\s+search\s+(?:karo\s+)?(?P<iq3>.+)"
    r"|(?P<iq4>.+?)\s+(?:dikhao|dikha)\s+(?:image|photo|tasveer)"
    r")",
    _I,
)

_SEARCH_NEWS_RE = re.compile(
    r"(?:"
    r"(?:latest|aaj\s+ki|abhi\s+ki|recent|taaza)\s+(?P<nq1>.+?)\s+(?:news|khabar(?:en)?)"
    r"|(?:news|khabar(?:en)?)\s+(?:of|about|ke\s+baare\s+mein)?\s+(?P<nq2>.+)"
    r"|(?P<nq3>.+?)\s+(?:ki\s+)?(?:news|khabar(?:en)?)\s+(?:dikha(?:o)?|batao|search\s+(?:karo|kar)?)"
    r"|aaj\s+kya\s+hua\s+(?P<nq4>.+?)(?:\s+mein)?"
    r")",
    _I,
)

_SEARCH_SHOPPING_RE = re.compile(
    r"(?:"
    r"(?:buy|purchase|order|kharido|kharidna|kharid\s+do)\s+(?P<sq1>.+)"
    r"|(?P<sq2>.+?)\s+(?:kharido|kharidna|buy\s+karo|order\s+karo|price\s+check)"
    r"|(?P<sq3>.+?)\s+(?:ka|ki)\s+(?:price|daam|cost|rate)\s+(?:batao|kya\s+hai|check\s+karo)"
    r"|(?:amazon|flipkart|meesho|myntra)\s+(?:par\s+|pe\s+)?(?:search\s+(?:karo\s+)?)?(?P<sq4>.+)"
    r")",
    _I,
)

_SEARCH_TRANSLATE_RE = re.compile(
    r"(?:"
    r"(?:translate|anuvad\s+karo|translate\s+karo)\s+"
    r"(?P<text>.+?)\s+(?:to|in(?:to)?|mein)\s+(?P<lang>[a-z]+)"
    r"|(?P<text2>.+?)\s+(?:ko|ka)\s+(?P<lang2>[a-z]+)\s+mein\s+"
    r"(?:translate|anuvad)\s+(?:karo|kar)"
    r"|(?P<lang3>[a-z]+)\s+mein\s+(?:translate\s+(?:karo\s+)?)?(?P<text3>.+)"
    r")",
    _I,
)

# FIX 4: city group uses negative lookahead to exclude pure Hindi command verbs
_HINDI_CMD_WORDS = r"(?:karo|kar|batao|dhundo|dikha|dikhao|jao|do|de|lo|le)"
_SEARCH_WEATHER_RE = re.compile(
    r"(?:"
    rf"(?:weather|mausam|temp(?:erature)?)\s+(?:in|of|at|mein|ka|ki)?\s*(?P<city1>[a-z](?:[a-z\s]{{0,30}}?)?)(?!\s*{_HINDI_CMD_WORDS})$"
    r"|(?P<city2>[a-z\s]+?)\s+(?:ka|ki|mein)\s+(?:weather|mausam|temp(?:erature)?)(?:\s+(?:kya\s+hai|batao))?"
    r"|(?:aaj|kal|parso)\s+(?:ka|ki)\s+(?:weather|mausam)(?:\s+(?P<city3>[a-z\s]+?))?"
    r"|(?:barish|baarish|rain|snow|dhoop)\s+(?:hoga\s+kya|hai\s+kya|aayegi\s+kya)"
    r")",
    _I,
)

# FIX 6: Calculator requires at least one math operator or keyword
_SEARCH_CALCULATOR_RE = re.compile(
    r"(?:"
    r"(?:calculate|compute|solve|hisaab\s+karo|calculate\s+karo)\s+(?P<expr1>.+)"
    r"|(?P<expr2>[\d\s]+(?:[\+\-\*\/\^]|plus|minus|times|divided\s+by|raised\s+to)[\d\s\+\-\*\/\^\(\)\.]+)"
    r"\s*(?:=|equals?|kitna\s+hoga|kya\s+hoga|answer)"
    r"|(?P<expr3>\d+)\s+(?:plus|\+|aur|jodo)\s+(?P<expr3b>\d+)"
    r"|(?P<expr4>\d+)\s+(?:minus|-|ghataao|ghata)\s+(?P<expr4b>\d+)"
    r"|(?P<expr5>\d+)\s+(?:times|x|\*|guna|multiply)\s+(?P<expr5b>\d+)"
    r"|(?P<expr6>\d+)\s+(?:divided\s+by|/|bhaago|divide)\s+(?P<expr6b>\d+)"
    r")",
    _I,
)

_SEARCH_DEFINE_RE = re.compile(
    r"(?:"
    r"(?:define|meaning\s+of|matlab\s+(?:kya\s+hai|batao)|arth\s+(?:kya\s+hai|batao))\s+(?P<word1>.+)"
    r"|(?P<word2>.+?)\s+(?:ka\s+)?(?:meaning|matlab|arth|definition)\s*(?:kya\s+hai|batao)?"
    r")",
    _I,
)

_SEARCH_TIMER_RE = re.compile(
    rf"(?:"
    rf"(?:set|laga(?:o)?|start)\s+(?:a\s+)?(?:timer|alarm)\s+(?:for\s+|of\s+)?{_TIME_VAL}"
    rf"|{_TIME_VAL}\s+(?:ka\s+)?(?:timer|alarm)\s+(?:set|laga(?:o)?|start)(?:\s+(?:karo|kar))?"
    rf"|timer\s+{_TIME_VAL}(?:\s+(?:set|laga(?:o)?|karo|kar))?"
    r")",
    _I,
)

# NEW v3 search intents
_SEARCH_FLIGHT_RE = re.compile(
    r"(?:"
    r"(?:search|find|book|check)\s+(?:a\s+)?flight(?:s?)\s+(?:from|to|between)?\s+(?P<fq1>.+)"
    r"|flight(?:s?)\s+(?:from|to)\s+(?P<fq2>.+)"
    r"|(?P<fq3>.+?)\s+(?:se|se\s+lekar)\s+(?P<fq4>.+?)\s+(?:ka|ki)\s+flight"
    r"|(?P<fq5>.+?)\s+to\s+(?P<fq6>.+?)\s+flight(?:\s+(?:search|dhundo|check))?"
    r")",
    _I,
)

_SEARCH_STOCK_RE = re.compile(
    r"(?:"
    r"(?:stock|share|crypto|bitcoin|price|rate)\s+(?:of|for)?\s+(?P<stk1>[A-Z]{1,5}|[a-z\s]+)"
    r"|(?P<stk2>[A-Z]{1,5})\s+(?:stock|share|crypto|price|rate)"
    r"|(?P<stk3>.+?)\s+(?:ka|ki|ke)\s+(?:stock|share|crypto)\s+(?:price|rate|kya\s+hai)"
    r"|(?:sensex|nifty|dow|nasdaq|s&p)\s+(?:aaj|today|abhi|current)"
    r")",
    _I,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — TIME PARSER
# ══════════════════════════════════════════════════════════════════════════════

_BARE_DIGIT_RE = re.compile(r"\b(\d+)\b")


def parse_seconds(query: str) -> int:
    """
    Extract duration in seconds from a query string.
    Handles: "10 min", "30 sec", "2 hours 15 min", "1:30", bare number (→ seconds).
    Returns 10 as default if nothing found.
    """
    total = 0
    found = False

    # HH:MM:SS or MM:SS
    ts = re.search(r"(\d+):(\d{2})(?::(\d{2}))?", query)
    if ts:
        parts = [int(x) for x in ts.groups(default="0")]
        if ts.group(3):
            total = parts[0] * 3600 + parts[1] * 60 + parts[2]
        else:
            total = parts[0] * 60 + parts[1]
        return total

    for h_m in re.finditer(r"(\d+)\s*(?:hour|hr|ghanta|ghante)s?", query, _I):
        total += int(h_m.group(1)) * 3600; found = True
    for m_m in re.finditer(r"(\d+)\s*(?:min(?:ute)?s?)", query, _I):
        total += int(m_m.group(1)) * 60; found = True
    for s_m in re.finditer(r"(\d+)\s*(?:sec(?:ond)?s?)\b", query, _I):
        total += int(s_m.group(1)); found = True

    if not found:
        bare = _BARE_DIGIT_RE.search(query)
        return int(bare.group(1)) if bare else 10

    return total if total > 0 else 10


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SONG NAME EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

_SONG_NOISE_RE = re.compile(
    r"\b(?:play|karo|kar|chalao|bajao|laga(?:o|do)?|do|de|youtube|par|pe|pe\s+chalao"
    r"|song|gana|gaana|music|video|wala|yeh|ye|isko|usko|please|pls"
    r"|search|dhundo|dhoondo|khojo|open|and|aur|sunao|suno|bajana|hai|haan)\\b",
    _I,
)
_SONG_NOISE_RE = re.compile(
    r"\b(?:play|karo|kar|chalao|bajao|laga(?:o|do)?|do|de|youtube|par|pe"
    r"|song|gana|gaana|music|video|wala|yeh|ye|isko|usko|please|pls"
    r"|search|dhundo|dhoondo|khojo|open|and|aur|sunao|suno|bajana|hai|haan)\b",
    _I,
)
_WS_RE = re.compile(r"\s{2,}")


def extract_song_name(query: str) -> str:
    """Strip command noise and return the probable song/artist name."""
    cleaned = _SONG_NOISE_RE.sub(" ", query)
    cleaned = _WS_RE.sub(" ", cleaned).strip(" .,!?")
    return cleaned if len(cleaned) > 1 else query.strip()


def _first_group(*groups) -> str:
    """Return the first non-None, non-empty group from a regex match."""
    for g in groups:
        if g and g.strip():
            return g.strip()
    return ""


def _quality_from_match(m: re.Match) -> str:
    """Extract quality value from a _YT_QUALITY_RE match (any capture group)."""
    for g in m.groups():
        if g:
            return g.lower().replace("automatic", "auto")
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — NEGATIVE GUARDS
# ══════════════════════════════════════════════════════════════════════════════

_MESSAGING_GUARD_RE = re.compile(
    r"\b(?:whatsapp|telegram|instagram|facebook\s+messenger|signal|sms|text\s+message"
    r"|message\s+(?:bhejo|send|padho)|chat\s+(?:padho|kholo))\b",
    _I,
)

_MEDIA_APP_GUARD_RE = re.compile(
    r"\b(?:spotify|apple\s+music|hotstar|netflix|prime\s+video|disney|hulu"
    r"|gaana|wynk|jiosaavn)\b",
    _I,
)

_SCREEN_GUARD_RE = re.compile(
    r"\b(?:screen\s+(?:padho|read|text)|screen\s+se|jo\s+screen\s+pe\s+(?:hai|likha))\b",
    _I,
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — PRIORITY CHAIN CLASSIFIER
# ══════════════════════════════════════════════════════════════════════════════

def classify_browser_intent(query: str) -> Optional[tuple[str, object]]:
    """
    Classify a query into a browser/YouTube/search intent.

    Returns (intent_str, data) where data is:
      - str  for search queries, URLs, song names, browser names
      - int  for seconds (seek, timer) or tab number
      - dict for translate: {"text": ..., "lang": ...}
      - None for on/off toggle intents

    Returns None if no browser/YouTube/search intent detected.
    """
    if not query:
        return None

    q  = query.strip()
    ql = q.lower()

    # ── Negative guards ───────────────────────────────────────────────────────
    if _MESSAGING_GUARD_RE.search(ql):
        return None
    if _SCREEN_GUARD_RE.search(ql):
        return None

    has_yt   = bool(re.search(r"\byoutube\b", ql))
    has_mapp = bool(_MEDIA_APP_GUARD_RE.search(ql))

    # ── BROWSER APP OPEN ──────────────────────────────────────────────────────
    m = _BROWSER_OPEN_RE.fullmatch(q.strip())
    if not m:
        if re.search(r"\b(?:open|launch|kholo|chalu\s+karo)\b", ql):
            m = _BROWSER_OPEN_RE.search(q)
    if m:
        browser = m.group("browser").lower().replace(" ", "_")
        return ("BROWSER_OPEN", browser)

    # ── NAMED-TAB PRE-CHECKS (must run before YT block to avoid YT false-positives) ──
    # "close all youtube tabs" must NOT become YT_PLAY_SONG
    # "gmail tab band karo" must NOT become YT_CLOSE_TAB

    _pre_close_all = _BROWSER_CLOSE_ALL_BY_NAME_RE.search(ql)
    if _pre_close_all:
        _site = (_pre_close_all.group("site_all") or _pre_close_all.group("site_all2") or "").strip()
        if _site:
            return ("BROWSER_CLOSE_ALL_BY_NAME", _site)

    _pre_switch = _BROWSER_SWITCH_BY_NAME_RE.search(ql)
    if _pre_switch:
        _site = (
            _pre_switch.group("sw_site") or
            _pre_switch.group("sw_site_open") or
            _pre_switch.group("sw_site2") or
            _pre_switch.group("sw_site3") or ""
        ).strip()
        if _site and _site.lower() not in {
            "next", "previous", "prev", "agla", "pichla", "new", "naya",
            "tab", "the", "a", "an",
        }:
            return ("BROWSER_SWITCH_BY_NAME", _site)

    _pre_close_one = _BROWSER_CLOSE_BY_NAME_RE.search(ql)
    if _pre_close_one:
        _site = (_pre_close_one.group("site_one") or _pre_close_one.group("site_two") or "").strip()
        if _site and _site.lower() not in {
            "current", "active", "yeh", "is", "this", "tab", "wo", "woh",
        }:
            return ("BROWSER_CLOSE_BY_NAME", _site)

    # "tab close karo" / "tab band karo" (no site, no youtube) → BROWSER_CLOSE_TAB
    if _BARE_TAB_CLOSE_RE.search(ql):
        return ("BROWSER_CLOSE_TAB", None)

    # ── YOUTUBE CONTROLS ──────────────────────────────────────────────────────
    if not has_mapp or has_yt:

        if _YT_CLOSE_TAB_RE.search(ql) and not _YT_CLOSE_TAB_NAMED_GUARD_RE.search(ql):
            return ("YT_CLOSE_TAB", None)

        if _YT_SEEK_FWD_RE.search(ql):
            return ("YT_SEEK_FWD", parse_seconds(q))

        if _YT_SEEK_BWD_RE.search(ql):
            return ("YT_SEEK_BWD", parse_seconds(q))

        if _YT_NEXT_RE.search(ql):
            return ("YT_NEXT", None)
        if _YT_PREV_RE.search(ql):
            return ("YT_PREV", None)

        if _YT_FULLSCREEN_RE.search(ql):
            return ("YT_FULLSCREEN", None)

        if _YT_MUTE_RE.search(ql):
            return ("YT_MUTE", None)

        if _YT_SPEED_RESET_RE.search(ql):
            return ("YT_SPEED_RESET", None)
        if _YT_SPEED_UP_RE.search(ql):
            return ("YT_SPEED_UP", None)
        if _YT_SPEED_DOWN_RE.search(ql):
            return ("YT_SPEED_DOWN", None)

        if _YT_LOOP_RE.search(ql):
            return ("YT_LOOP", None)

        if _YT_CAPTIONS_RE.search(ql):
            return ("YT_CAPTIONS", None)

        mq = _YT_QUALITY_RE.search(ql)
        if mq:
            return ("YT_QUALITY", _quality_from_match(mq))

        # New v3 YT
        if _YT_DISLIKE_RE.search(ql):
            return ("YT_DISLIKE", None)
        if _YT_SUBSCRIBE_RE.search(ql):
            return ("YT_SUBSCRIBE", None)
        if _YT_PLAYLIST_RE.search(ql):
            return ("YT_PLAYLIST", None)

        if _YT_LIKE_RE.search(ql):
            return ("YT_LIKE", None)

        if _YT_THEATER_RE.search(ql):
            return ("YT_THEATER", None)

        if _YT_MINIPLAYER_RE.search(ql):
            return ("YT_MINIPLAYER", None)

        # FIX 3: Pause / Play require YT context
        if _YT_PAUSE_RE.search(ql) and (has_yt or _YT_CONTEXT_RE.search(ql)) and not has_mapp:
            return ("YT_PAUSE", None)

        if _YT_PLAY_RE.search(ql) and (has_yt or _YT_CONTEXT_RE.search(ql)) and not has_mapp:
            return ("YT_PLAY", None)

        # Play song — last YT check
        ms = _YT_PLAY_SONG_RE.search(q)
        if ms and (has_yt or re.search(r"\b(?:bajao|chalao|gana|song|music)\b", ql)):
            song = _first_group(
                ms.group("s1"), ms.group("s2"),
                ms.group("s3"), ms.group("s4"),
                ms.group("s5") if "s5" in ms.groupdict() else None,
            )
            song = extract_song_name(song or q)
            if song:
                return ("YT_PLAY_SONG", song)

    # ── SEARCH — YouTube ──────────────────────────────────────────────────────
    mys = _SEARCH_YOUTUBE_RE.search(q)
    if mys:
        sq = _first_group(mys.group("yq1"), mys.group("yq2"), mys.group("yq3"))
        if sq:
            return ("SEARCH_YOUTUBE", sq)

    # ── SEARCH — Maps ─────────────────────────────────────────────────────────
    mm = _SEARCH_MAPS_RE.search(q)
    if mm:
        loc = _first_group(
            mm.group("mq1"), mm.group("mq2"), mm.group("mq3"),
            mm.group("mq4"), mm.group("mq5"),
        )
        if loc:
            return ("SEARCH_MAPS", loc)

    # ── SEARCH — Images ───────────────────────────────────────────────────────
    mi = _SEARCH_IMAGES_RE.search(q)
    if mi:
        img = _first_group(mi.group("iq1"), mi.group("iq2"), mi.group("iq3"), mi.group("iq4"))
        if img:
            return ("SEARCH_IMAGES", img)

    # ── SEARCH — News ─────────────────────────────────────────────────────────
    mn = _SEARCH_NEWS_RE.search(q)
    if mn:
        nq = _first_group(mn.group("nq1"), mn.group("nq2"), mn.group("nq3"), mn.group("nq4"))
        if nq:
            return ("SEARCH_NEWS", nq)

    # ── SEARCH — Shopping ─────────────────────────────────────────────────────
    msho = _SEARCH_SHOPPING_RE.search(q)
    if msho:
        sq = _first_group(
            msho.group("sq1"), msho.group("sq2"),
            msho.group("sq3"), msho.group("sq4"),
        )
        if sq:
            return ("SEARCH_SHOPPING", sq)

    # ── SEARCH — Translate ────────────────────────────────────────────────────
    mtr = _SEARCH_TRANSLATE_RE.search(q)
    if mtr:
        text = _first_group(
            mtr.group("text")  if "text"  in mtr.groupdict() else None,
            mtr.group("text2") if "text2" in mtr.groupdict() else None,
            mtr.group("text3") if "text3" in mtr.groupdict() else None,
        )
        lang = _first_group(
            mtr.group("lang")  if "lang"  in mtr.groupdict() else None,
            mtr.group("lang2") if "lang2" in mtr.groupdict() else None,
            mtr.group("lang3") if "lang3" in mtr.groupdict() else None,
        )
        if text:
            return ("SEARCH_TRANSLATE", {"text": text, "lang": lang or "english"})

    # ── SEARCH — Weather ─────────────────────────────────────────────────────
    mw = _SEARCH_WEATHER_RE.search(ql)
    if mw:
        city = _first_group(
            mw.group("city1") if "city1" in mw.groupdict() else None,
            mw.group("city2") if "city2" in mw.groupdict() else None,
            mw.group("city3") if "city3" in mw.groupdict() else None,
        )
        return ("SEARCH_WEATHER", city.strip() if city else "")

    # ── SEARCH — Calculator ───────────────────────────────────────────────────
    mc = _SEARCH_CALCULATOR_RE.search(q)
    if mc:
        expr = _first_group(
            mc.group("expr1") if "expr1" in mc.groupdict() else None,
            mc.group("expr2") if "expr2" in mc.groupdict() else None,
        ) or q
        return ("SEARCH_CALCULATOR", expr.strip())

    # ── SEARCH — Define ───────────────────────────────────────────────────────
    md = _SEARCH_DEFINE_RE.search(q)
    if md:
        word = _first_group(
            md.group("word1") if "word1" in md.groupdict() else None,
            md.group("word2") if "word2" in md.groupdict() else None,
        )
        if word:
            return ("SEARCH_DEFINE", word.strip())

    # ── SEARCH — Timer ────────────────────────────────────────────────────────
    mt = _SEARCH_TIMER_RE.search(q)
    if mt:
        return ("SEARCH_TIMER", parse_seconds(q))

    # ── SEARCH — Flights ──────────────────────────────────────────────────────
    mfl = _SEARCH_FLIGHT_RE.search(q)
    if mfl:
        fq = _first_group(
            mfl.group("fq1") if "fq1" in mfl.groupdict() else None,
            mfl.group("fq2") if "fq2" in mfl.groupdict() else None,
            mfl.group("fq5") if "fq5" in mfl.groupdict() else None,
        ) or q
        return ("SEARCH_FLIGHT", fq.strip())

    # ── SEARCH — Stock / Crypto ───────────────────────────────────────────────
    mst = _SEARCH_STOCK_RE.search(q)
    if mst:
        sym = _first_group(
            mst.group("stk1") if "stk1" in mst.groupdict() else None,
            mst.group("stk2") if "stk2" in mst.groupdict() else None,
            mst.group("stk3") if "stk3" in mst.groupdict() else None,
        ) or q
        return ("SEARCH_STOCK", sym.strip())

    # ── BROWSER — URL navigation ──────────────────────────────────────────────
    mu = _BROWSER_URL_RE.search(q)
    if mu:
        raw = mu.group("url")
        url = re.sub(r"\s+dot\s+", ".", raw, flags=_I).replace(" ", "")
        if "." in url and not url.startswith("http"):
            url = "https://" + url
        return ("BROWSER_URL", url)

    # ── BROWSER — TAB OPERATIONS ──────────────────────────────────────────────
    if _BROWSER_REOPEN_TAB_RE.search(ql):
        return ("BROWSER_REOPEN_TAB", None)

    # Named-tab: CLOSE ALL  (must come before single-close to avoid partial match)
    m_close_all = _BROWSER_CLOSE_ALL_BY_NAME_RE.search(ql)
    if m_close_all:
        site = (
            m_close_all.group("site_all") or m_close_all.group("site_all2") or ""
        ).strip()
        if site:
            return ("BROWSER_CLOSE_ALL_BY_NAME", site)

    # Named-tab: CLOSE ONE
    m_close_one = _BROWSER_CLOSE_BY_NAME_RE.search(ql)
    if m_close_one:
        site = (
            m_close_one.group("site_one") or m_close_one.group("site_two") or ""
        ).strip()
        # Guard: reject if site is a bare command word (false positive)
        if site and site.lower() not in {
            "current", "active", "yeh", "is", "this", "tab", "wo", "woh",
        }:
            return ("BROWSER_CLOSE_BY_NAME", site)

    # Named-tab: SWITCH
    m_switch = _BROWSER_SWITCH_BY_NAME_RE.search(ql)
    if m_switch:
        site = (
            m_switch.group("sw_site") or
            m_switch.group("sw_site_open") or
            m_switch.group("sw_site2") or
            m_switch.group("sw_site3") or ""
        ).strip()
        if site and site.lower() not in {
            "next", "previous", "prev", "agla", "pichla", "new", "naya",
            "tab", "the", "a", "an",
        }:
            return ("BROWSER_SWITCH_BY_NAME", site)

    if _BROWSER_CLOSE_TAB_RE.search(ql):
        return ("BROWSER_CLOSE_TAB", None)
    if _BROWSER_NEW_TAB_RE.search(ql):
        return ("BROWSER_NEW_TAB", None)

    mtn = _BROWSER_TAB_N_RE.search(ql)
    if mtn:
        n_raw  = (mtn.group("n1") or mtn.group("n2") or "").strip()
        n_word = (mtn.group("nw") or "").strip().lower()
        if n_raw:
            return ("BROWSER_TAB_N", int(n_raw))
        elif n_word in _TAB_NUMS:
            return ("BROWSER_TAB_N", _TAB_NUMS[n_word])

    if _BROWSER_NEXT_TAB_RE.search(ql):
        return ("BROWSER_NEXT_TAB", None)
    if _BROWSER_PREV_TAB_RE.search(ql):
        return ("BROWSER_PREV_TAB", None)

    # ── BROWSER — NAVIGATION ──────────────────────────────────────────────────
    if _BROWSER_HARD_REFRESH_RE.search(ql):
        return ("BROWSER_HARD_REFRESH", None)
    if _BROWSER_REFRESH_RE.search(ql):
        return ("BROWSER_REFRESH", None)
    if _BROWSER_BACK_RE.search(ql):
        return ("BROWSER_BACK", None)
    if _BROWSER_FORWARD_RE.search(ql):
        return ("BROWSER_FORWARD", None)

    # ── BROWSER — SCROLL ──────────────────────────────────────────────────────
    if _BROWSER_SCROLL_BOTTOM_RE.search(ql):
        return ("BROWSER_SCROLL_BOTTOM", None)
    if _BROWSER_SCROLL_TOP_RE.search(ql):
        return ("BROWSER_SCROLL_TOP", None)
    if _BROWSER_SCROLL_DOWN_RE.search(ql):
        return ("BROWSER_SCROLL_DOWN", None)
    if _BROWSER_SCROLL_UP_RE.search(ql):
        return ("BROWSER_SCROLL_UP", None)

    # ── BROWSER — ZOOM ────────────────────────────────────────────────────────
    if _BROWSER_ZOOM_RESET_RE.search(ql):
        return ("BROWSER_ZOOM_RESET", None)
    if _BROWSER_ZOOM_IN_RE.search(ql):
        return ("BROWSER_ZOOM_IN", None)
    if _BROWSER_ZOOM_OUT_RE.search(ql):
        return ("BROWSER_ZOOM_OUT", None)

    # ── BROWSER — MISC ────────────────────────────────────────────────────────
    if _BROWSER_FULLSCREEN_RE.search(ql):
        return ("BROWSER_FULLSCREEN", None)
    if _BROWSER_INCOGNITO_RE.search(ql):
        return ("BROWSER_INCOGNITO", None)
    if _BROWSER_MUTE_TAB_RE.search(ql):
        return ("BROWSER_MUTE_TAB", None)
    if _BROWSER_PIN_TAB_RE.search(ql):
        return ("BROWSER_PIN_TAB", None)
    if _BROWSER_SCREENSHOT_RE.search(ql):
        return ("BROWSER_SCREENSHOT", None)
    if _BROWSER_COPY_URL_RE.search(ql):
        return ("BROWSER_COPY_URL", None)
    if _BROWSER_BOOKMARK_RE.search(ql):
        return ("BROWSER_BOOKMARK", None)
    if _BROWSER_HISTORY_RE.search(ql):
        return ("BROWSER_HISTORY", None)
    if _BROWSER_DOWNLOADS_RE.search(ql):
        return ("BROWSER_DOWNLOADS", None)
    if _BROWSER_DEVTOOLS_RE.search(ql):
        return ("BROWSER_DEVTOOLS", None)
    if _BROWSER_FOCUS_BAR_RE.search(ql):
        return ("BROWSER_FOCUS_BAR", None)

    # New v3 browser misc
    if _BROWSER_CLEAR_CACHE_RE.search(ql):
        return ("BROWSER_CLEAR_CACHE", None)
    if _BROWSER_PRINT_RE.search(ql):
        return ("BROWSER_PRINT", None)
    if _BROWSER_SAVE_PAGE_RE.search(ql):
        return ("BROWSER_SAVE_PAGE", None)
    if _BROWSER_READING_MODE_RE.search(ql):
        return ("BROWSER_READING_MODE", None)
    if _BROWSER_SPLIT_SCREEN_RE.search(ql):
        return ("BROWSER_SPLIT_SCREEN", None)
    if _BROWSER_EXTENSIONS_RE.search(ql):
        return ("BROWSER_EXTENSIONS", None)

    if _BROWSER_FIND_RE.search(ql):
        mf = _BROWSER_FIND_RE.search(q)
        term = mf.group("term") if mf and "term" in mf.groupdict() else ""
        return ("BROWSER_FIND", term or "")

    # ── SEARCH — Google (broadest, always last) ────────────────────────────────
    mg = _SEARCH_GOOGLE_RE.search(q)
    if mg:
        gq = _first_group(
            mg.group("gq1") if "gq1" in mg.groupdict() else None,
            mg.group("gq2") if "gq2" in mg.groupdict() else None,
            mg.group("gq3") if "gq3" in mg.groupdict() else None,
            mg.group("gq4") if "gq4" in mg.groupdict() else None,
        )
        if gq:
            return ("SEARCH_GOOGLE", gq.strip())

    return None


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — ROUTER INTEGRATION SHIM  (backward compatible)
# ══════════════════════════════════════════════════════════════════════════════

_ROUTER_INTENT_MAP: dict[str, str] = {
    "YT_PLAY":           "YOUTUBE_PLAY",
    "YT_PAUSE":          "YOUTUBE_PAUSE",
    "YT_SEEK_FWD":       "YOUTUBE_SEEK_FORWARD",
    "YT_SEEK_BWD":       "YOUTUBE_SEEK_BACKWARD",
    "YT_NEXT":           "YOUTUBE_NEXT",
    "YT_PREV":           "YOUTUBE_PREVIOUS",
    "YT_PLAY_SONG":      "YOUTUBE_PLAY_SONG",
    "YT_CLOSE_TAB":      "YOUTUBE_CLOSE_TAB",
    "YT_FULLSCREEN":     "YOUTUBE_FULLSCREEN",
    "YT_MUTE":           "YOUTUBE_MUTE",
    "YT_SPEED_UP":       "YOUTUBE_SPEED_UP",
    "YT_SPEED_DOWN":     "YOUTUBE_SPEED_DOWN",
    "YT_SPEED_RESET":    "YOUTUBE_SPEED_RESET",
    "YT_LOOP":           "YOUTUBE_LOOP",
    "YT_CAPTIONS":       "YOUTUBE_CAPTIONS",
    "YT_QUALITY":        "YOUTUBE_QUALITY",
    "YT_LIKE":           "YOUTUBE_LIKE",
    "YT_DISLIKE":        "YOUTUBE_DISLIKE",
    "YT_SUBSCRIBE":      "YOUTUBE_SUBSCRIBE",
    "YT_PLAYLIST":       "YOUTUBE_PLAYLIST",
    "YT_THEATER":        "YOUTUBE_THEATER",
    "YT_MINIPLAYER":     "YOUTUBE_MINIPLAYER",
    "SEARCH_GOOGLE":     "GOOGLE_SEARCH",
    "SEARCH_YOUTUBE":    "YOUTUBE_PLAY_SONG",
    "BROWSER_CLOSE_TAB":        "TAB_CLOSE",
    "BROWSER_CLOSE_BY_NAME":    "TAB_CLOSE_BY_NAME",
    "BROWSER_CLOSE_ALL_BY_NAME":"TAB_CLOSE_ALL_BY_NAME",
    "BROWSER_SWITCH_BY_NAME":   "TAB_SWITCH_BY_NAME",
    "BROWSER_NEXT_TAB":         "TAB_NEXT",
    "BROWSER_PREV_TAB":   "TAB_PREVIOUS",
    "BROWSER_URL":        "OPEN_URL",
    "BROWSER_OPEN":       "APP_OPEN",
}


def classify_youtube_query(query: str) -> Optional[tuple[str, str]]:
    """router.py drop-in — replaces classify_youtube_query() from youtube.py."""
    result = classify_browser_intent(query)
    if result is None:
        return None
    intent, data = result
    router_intent = _ROUTER_INTENT_MAP.get(intent)
    if router_intent is None:
        return None
    return (router_intent, query if isinstance(data, type(None)) else str(data))


def classify_search_intent(query: str) -> Optional[str]:
    """router.py drop-in — replaces _classify_search_intent() from router.py."""
    result = classify_browser_intent(query)
    if result is None:
        return None
    intent, data = result
    if intent == "SEARCH_GOOGLE":
        return str(data)
    return None