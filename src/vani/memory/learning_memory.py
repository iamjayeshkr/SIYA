"""
learning_memory.py — Vani Persistent Learning System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stores user-taught facts, preferences, and quiz items.
Survives app close, restarts, and new sessions.

Storage: conversations/vani_learned.json  (same dir as existing memory)
Does NOT touch: Rudra_Vani_memory.json    (conversation history — untouched)

Item schema:
  {
    "id":         "uuid4-short",
    "type":       "fact" | "preference" | "quiz" | "rule",
    "category":   "preference" | "knowledge" | "habit" | "quiz_pending",
    "content":    "favorite color is black",
    "raw":        "mera favorite color black hai",
    "created":    "2026-05-20T10:30:00",
    "confidence": 1.0,
    "quiz_due":   "2026-05-21T10:30:00" | null
  }
"""

import json
import os
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from vani.config import PROJECT_ROOT
from vani.memory.human_memory import get_permanent_memory_block, remember_permanent, search_permanent_memory

logger = logging.getLogger(__name__)

# ── Storage ───────────────────────────────────────────────────────────────────

_LEARN_FILE = PROJECT_ROOT / "conversations" / "vani_learned.json"

_items: list = []
_loaded: bool = False


def _ensure_dir():
    _LEARN_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load():
    global _items, _loaded
    if _loaded:
        return
    _ensure_dir()
    if _LEARN_FILE.exists():
        try:
            with open(_LEARN_FILE, "r", encoding="utf-8") as f:
                _items = json.load(f)
            logger.info(f"[LEARN] Loaded {len(_items)} learned items")
        except Exception as e:
            logger.warning(f"[LEARN] Load failed: {e}")
            _items = []
    else:
        _items = []
    _loaded = True


def _save():
    _ensure_dir()
    tmp = str(_LEARN_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_items, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _LEARN_FILE)
        logger.info(f"[LEARN] Saved {len(_items)} items")
    except Exception as e:
        logger.error(f"[LEARN] Save failed: {e}")
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ── Intent Classification ─────────────────────────────────────────────────────

# Token-level triggers — partial match, not exact
_LEARN_TOKENS = {
    # Hindi
    "yaad", "seekho", "seekh", "bhoolna", "bhool", "puchhna", "puchna",
    "dilana", "note",
    # English
    "remember", "learn", "forget", "quiz", "remind",
    # Hinglish — covered by above + context
    "save",
}

_LEARN_PHRASES = [
    "yaad rakhna", "yaad kar lo", "yaad rakh lo", "yaad rakh lena",
    "yaad rakh le", "seekho ki", "seekh lo", "bhoolna mat", "mat bhoolna",
    "save kar lo", "save kar lena", "note kar lo", "note kar lena",
    "baad mein puchna", "baad mein puchhna", "baad mein yaad dilana",
    "isko yaad rakh", "yeh yaad rakh", "isko mat bhoolna",
    "remember this", "remember that", "learn this", "learn that",
    "save this", "don't forget", "do not forget", "note this",
    "ask me later", "quiz me later", "remind me later",
]

_QUIZ_PHRASES = [
    "baad mein puchna", "baad mein puchhna", "quiz me", "ask me later",
    "test me", "baad mein test", "quiz karna", "baad mein quiz",
]


def is_learn_intent(query: str) -> bool:
    """True if user wants Vani to learn/remember something."""
    q = query.lower().strip()
    
    # Exclude note creation, diagram generation, spreadsheet design, or file actions
    exclusions = {
        "create a note", "create note", "make a note", "make note",
        "take a note", "take note", "save a note", "save note",
        "write a note", "write note", "obsidian", "excel", "spreadsheet",
        "flowchart", "diagram", "draw", "banao", "open", "kholo", "likh"
    }
    for exc in exclusions:
        if exc in q:
            return False

    for phrase in _LEARN_PHRASES:
        if phrase in q:
            return True
    # Token overlap: needs a learn-token + some content (>4 words total)
    tokens = set(q.split())
    if tokens & _LEARN_TOKENS and len(q.split()) >= 3:
        # Avoid false positives on pure action commands
        action_only = {"open", "close", "play", "search", "call", "send"}
        if not (tokens & _LEARN_TOKENS <= action_only):
            return True
    return False


def _is_quiz_intent(query: str) -> bool:
    q = query.lower()
    return any(p in q for p in _QUIZ_PHRASES)


# ── Type classification ───────────────────────────────────────────────────────

def _classify(content: str, raw: str) -> tuple[str, str]:
    """Returns (type, category)."""
    c = content.lower()
    r = raw.lower()

    if _is_quiz_intent(raw):
        return "quiz", "quiz_pending"

    if any(w in c for w in ["favorite", "pasand", "like", "prefer", "colour", "color",
                              "food", "music", "game", "movie", "genre", "style"]):
        return "preference", "preference"

    if any(w in r for w in ["coding", "code", "style", "habit", "karta hai",
                              "karta hun", "always", "hamesha", "usually"]):
        return "rule", "habit"

    return "fact", "knowledge"


# ── Deduplication ─────────────────────────────────────────────────────────────

def _find_similar(content: str) -> Optional[dict]:
    """Find existing item with similar content (simple keyword overlap)."""
    _load()
    words = set(content.lower().split()) - {"is", "the", "a", "an", "ki", "ka", "ke", "hai", "hain", "mera", "meri"}
    for item in _items:
        existing_words = set(item["content"].lower().split()) - {"is", "the", "a", "an", "ki", "ka", "ke", "hai", "hain", "mera", "meri"}
        if len(words) > 0 and len(existing_words) > 0:
            overlap = len(words & existing_words) / max(len(words), len(existing_words))
            if overlap > 0.6:
                return item
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def save_learning(content: str, raw: str = "", force_type: str = "") -> dict:
    """
    Save a learned item. Deduplicates automatically.
    Returns the saved item.
    """
    _load()
    content = content.strip()
    raw = raw.strip() or content

    item_type, category = _classify(content, raw)
    if force_type:
        item_type = force_type

    quiz_due = None
    if item_type == "quiz":
        # Schedule quiz for next session (12 hours from now)
        quiz_due = (datetime.now() + timedelta(hours=12)).isoformat()

    # Update existing similar item instead of duplicating
    existing = _find_similar(content)
    if existing:
        existing["content"]    = content
        existing["raw"]        = raw
        existing["confidence"] = min(1.0, existing.get("confidence", 0.8) + 0.1)
        existing["updated"]    = datetime.now().isoformat()
        _save()
        remember_permanent(
            content,
            raw=raw,
            kind=item_type,
            category=category,
            importance=8 if item_type in {"preference", "rule"} else 6,
        )
        logger.info(f"[LEARN] Updated existing: {content[:60]}")
        return existing

    item = {
        "id":         uuid.uuid4().hex[:8],
        "type":       item_type,
        "category":   category,
        "content":    content,
        "raw":        raw,
        "created":    datetime.now().isoformat(),
        "confidence": 1.0,
        "quiz_due":   quiz_due,
    }
    _items.append(item)
    _save()
    remember_permanent(
        content,
        raw=raw,
        kind=item_type,
        category=category,
        importance=8 if item_type in {"preference", "rule"} else 6,
    )
    logger.info(f"[LEARN] Saved [{item_type}]: {content[:60]}")
    return item


def get_all_facts() -> list:
    """Return all non-quiz learned items."""
    _load()
    return [i for i in _items if i.get("type") != "quiz"]


def get_quiz_items(due_only: bool = True) -> list:
    """Return quiz items. If due_only, only return overdue items."""
    _load()
    now = datetime.now().isoformat()
    result = []
    for item in _items:
        if item.get("type") == "quiz":
            due = item.get("quiz_due", "")
            if not due_only or (due and due <= now):
                result.append(item)
    return result


def mark_quiz_done(item_id: str, reschedule_hours: int = 24):
    """Mark a quiz item as answered — reschedule or remove."""
    _load()
    for item in _items:
        if item.get("id") == item_id:
            item["quiz_due"] = (datetime.now() + timedelta(hours=reschedule_hours)).isoformat()
            item["confidence"] = min(1.0, item.get("confidence", 0.8) + 0.1)
            _save()
            return


def search_learned(query: str) -> list:
    """Search learned items by keyword."""
    _load()
    q_words = set(query.lower().split())
    results = []
    for item in _items:
        content_words = set(item["content"].lower().split())
        if q_words & content_words:
            results.append(item)
    for item in search_permanent_memory(query):
        results.append(
            {
                "id": item.get("id"),
                "type": item.get("kind", "fact"),
                "category": item.get("category", "knowledge"),
                "content": item.get("content", ""),
                "raw": item.get("raw", ""),
                "created": item.get("created_at", ""),
                "confidence": 1.0,
            }
        )
    return results


def get_learned_block() -> str:
    """
    Returns prompt block to inject into instructions_prompt.
    Only non-quiz facts. Keeps token count low (max 20 items, 80 chars each).
    """
    _load()
    facts = [i for i in _items if i.get("type") != "quiz"]
    if not facts:
        return ""

    # Most recent first, cap at 20
    recent = sorted(facts, key=lambda x: x.get("created", ""), reverse=True)[:20]
    lines = [f"  • [{i['category']}] {i['content']}" for i in recent]

    quiz_pending = get_quiz_items(due_only=True)
    quiz_note = ""
    if quiz_pending:
        quiz_note = (
            f"\nQUIZ PENDING ({len(quiz_pending)} items) — "
            "naturally ask user about one of these in conversation if opportunity arises: "
            + "; ".join(q["content"][:60] for q in quiz_pending[:3])
            + "\n"
        )

    block = (
        "\n\nUSER-TAUGHT FACTS (use these to answer questions, personalise responses):\n"
        + "\n".join(lines)
        + "\n"
        + quiz_note
    )
    permanent_block = get_permanent_memory_block()
    return block + permanent_block
