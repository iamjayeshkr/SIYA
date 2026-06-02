"""
vani/memory/relationship_memory.py — Phase 6

Relationship Memory: stores people Vani knows about — their names, nicknames,
which platforms they're on, when Vani last interacted with them, and a running
sentiment score.

This data feeds into the planner for smarter contact resolution.
For example:
    "Send a message to bhai" → resolve_contact("bhai") → finds real name + platform.
    "How is Neha doing?" → can pull sentiment + last_seen for context.

Schema:
    contacts(id, name, nickname, aliases, platform, last_seen, sentiment, interaction_count, notes)
    interactions(id, contact_id, ts, intent, summary, sentiment_delta)

Thread safety: SQLite WAL mode + context manager per call.
Backward compat: new standalone file — nothing existing is modified.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from vani.config import PROJECT_ROOT

logger = logging.getLogger("vani.memory.relationship")

DB_PATH = PROJECT_ROOT / "conversations" / "vani_relationship.sqlite3"

# Sentiment is a float in [-1.0, 1.0].
# positive = warm/friendly interactions. negative = tension/conflict mentions.
_SENTIMENT_MIN = -1.0
_SENTIMENT_MAX = 1.0
_SENTIMENT_DECAY = 0.05   # each new interaction slightly decays old sentiment toward neutral


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    nickname          TEXT DEFAULT '',
    aliases           TEXT DEFAULT '[]',
    platform          TEXT DEFAULT '',
    last_seen         TEXT DEFAULT '',
    sentiment         REAL DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    notes             TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_contacts_name     ON contacts (lower(name));
CREATE INDEX IF NOT EXISTS idx_contacts_nickname ON contacts (lower(nickname));

CREATE TABLE IF NOT EXISTS interactions (
    id              TEXT PRIMARY KEY,
    contact_id      TEXT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    ts              REAL NOT NULL,
    intent          TEXT DEFAULT '',
    summary         TEXT DEFAULT '',
    sentiment_delta REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_interactions_contact ON interactions (contact_id);
CREATE INDEX IF NOT EXISTS idx_interactions_ts      ON interactions (ts);
"""


# ── Internal helpers ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _clamp_sentiment(val: float) -> float:
    return max(_SENTIMENT_MIN, min(_SENTIMENT_MAX, val))


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    # Deserialise JSON fields
    for field in ("aliases", "notes"):
        try:
            d[field] = json.loads(d[field] or "[]" if field == "aliases" else d[field] or "{}")
        except Exception:
            d[field] = [] if field == "aliases" else {}
    return d


# ── Public API ──────────────────────────────────────────────────────────────────

def remember_contact(
    name: str,
    nickname: str = "",
    aliases: list[str] | None = None,
    platform: str = "",
    notes: dict | None = None,
) -> dict:
    """
    Create or update a contact record.

    Uses the lowercase name as the stable primary key.
    Calling this again for an existing contact will update their nickname,
    platform, and notes — without resetting sentiment or interaction_count.

    Args:
        name:     Full name (e.g. "Neha Sharma")
        nickname: Common short name (e.g. "Neha", "didi")
        aliases:  Extra names / spellings (e.g. ["neha di", "neh"])
        platform: Primary messaging platform ("whatsapp", "telegram", etc.)
        notes:    Freeform key/value dict (e.g. {"relation": "sister", "phone": "+91..."})

    Returns:
        The full contact record as a dict.
    """
    contact_id = name.strip().lower()
    if not contact_id:
        raise ValueError("contact name cannot be empty")

    aliases_json = json.dumps(aliases or [], ensure_ascii=False)
    notes_json = json.dumps(notes or {}, ensure_ascii=False)
    now = _now_iso()

    with _connect() as conn:
        # Try insert first; on conflict update mutable fields only.
        conn.execute(
            """
            INSERT INTO contacts (id, name, nickname, aliases, platform, last_seen, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                nickname  = excluded.nickname,
                aliases   = excluded.aliases,
                platform  = excluded.platform,
                last_seen = excluded.last_seen,
                notes     = excluded.notes
            """,
            (contact_id, name.strip(), nickname.strip(), aliases_json, platform, now, notes_json),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        result = _row_to_dict(row)

    logger.info(f"[RELATIONSHIP] remembered contact: {name!r} (platform={platform!r})")
    return result


def resolve_contact(name: str) -> dict | None:
    """
    Look up a contact by name, nickname, or alias.

    Tries exact lowercase match first, then substring match.

    Args:
        name: Any name the user might use (real name, nickname, alias)

    Returns:
        Contact dict, or None if not found.
    """
    key = name.strip().lower()
    if not key:
        return None

    with _connect() as conn:
        # 1. Exact match on id (lower name) or nickname
        row = conn.execute(
            "SELECT * FROM contacts WHERE id=? OR lower(nickname)=?",
            (key, key),
        ).fetchone()
        if row:
            return _row_to_dict(row)

        # 2. Check aliases (stored as JSON array)
        all_rows = conn.execute("SELECT * FROM contacts").fetchall()
        for r in all_rows:
            try:
                aliases = json.loads(r["aliases"] or "[]")
                if key in [a.lower() for a in aliases]:
                    return _row_to_dict(r)
            except Exception:
                continue

        # 3. Substring match on name or nickname
        row = conn.execute(
            "SELECT * FROM contacts WHERE lower(name) LIKE ? OR lower(nickname) LIKE ?",
            (f"%{key}%", f"%{key}%"),
        ).fetchone()
        if row:
            return _row_to_dict(row)

    return None


def log_interaction(
    contact_name: str,
    intent: str = "",
    summary: str = "",
    sentiment_delta: float = 0.0,
) -> bool:
    """
    Record an interaction with a contact and update their sentiment score.

    Called automatically by CommunicationAgent after WhatsApp/Telegram actions.
    Can also be called manually when Rudra mentions someone in conversation.

    Args:
        contact_name:    Name/nickname to identify the contact
        intent:          Router intent that triggered the interaction (e.g. "WHATSAPP_SEND")
        summary:         Short description of what happened
        sentiment_delta: How this interaction shifts sentiment (-0.3 to +0.3 recommended)

    Returns:
        True if contact found and updated, False otherwise.
    """
    contact = resolve_contact(contact_name)
    if not contact:
        logger.debug(f"[RELATIONSHIP] log_interaction: contact {contact_name!r} not found, skipping")
        return False

    contact_id = contact["id"]
    now = time.time()

    with _connect() as conn:
        # Decay existing sentiment slightly toward neutral, then apply delta
        current_sentiment = contact.get("sentiment", 0.0)
        decayed = current_sentiment * (1.0 - _SENTIMENT_DECAY)
        new_sentiment = _clamp_sentiment(decayed + sentiment_delta)

        conn.execute(
            """
            UPDATE contacts
            SET sentiment         = ?,
                interaction_count = interaction_count + 1,
                last_seen         = ?
            WHERE id = ?
            """,
            (new_sentiment, _now_iso(), contact_id),
        )

        conn.execute(
            """
            INSERT INTO interactions (id, contact_id, ts, intent, summary, sentiment_delta)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), contact_id, now, intent, summary[:500], sentiment_delta),
        )
        conn.commit()

    logger.debug(
        f"[RELATIONSHIP] interaction logged for {contact_id!r}: "
        f"intent={intent!r}, sentiment_delta={sentiment_delta:+.2f}"
    )
    return True


def get_contact(name: str) -> dict | None:
    """
    Alias for resolve_contact — more readable in agent code.
    Returns full contact dict or None.
    """
    return resolve_contact(name)


def get_all_contacts() -> list[dict]:
    """Return all known contacts, sorted by interaction_count descending."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM contacts ORDER BY interaction_count DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_recent_interactions(contact_name: str, limit: int = 10) -> list[dict]:
    """
    Returns the most recent interactions with a contact.

    Args:
        contact_name: Name / nickname of the contact
        limit:        Max number of interactions to return

    Returns:
        List of interaction dicts, newest first. Empty list if contact unknown.
    """
    contact = resolve_contact(contact_name)
    if not contact:
        return []

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM interactions
            WHERE contact_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (contact["id"], limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_relationship_summary(contact_name: str) -> str:
    """
    Returns a human-readable summary of a relationship for prompt injection.

    Example output:
        "Neha (platform: whatsapp) — 12 interactions, last seen 2025-05-20T14:30:00,
         sentiment: warm (+0.42)"

    Args:
        contact_name: Name or nickname of the contact

    Returns:
        Single-line summary string, or empty string if not found.
    """
    contact = resolve_contact(contact_name)
    if not contact:
        return ""

    sentiment = contact.get("sentiment", 0.0)
    if sentiment > 0.3:
        mood = f"warm (+{sentiment:.2f})"
    elif sentiment < -0.3:
        mood = f"strained ({sentiment:.2f})"
    else:
        mood = f"neutral ({sentiment:+.2f})"

    parts = [
        f"{contact['name']}",
        f"(platform: {contact['platform']})" if contact.get("platform") else "",
        f"— {contact.get('interaction_count', 0)} interactions",
        f"last seen {contact.get('last_seen', 'unknown')}",
        f"sentiment: {mood}",
    ]
    return " ".join(p for p in parts if p)


def build_contacts_block(limit: int = 10) -> str:
    """
    Returns a compact block of top contacts for prompt injection.
    Called by memory/__init__.py's get_full_context().

    Args:
        limit: Max contacts to include

    Returns:
        Multi-line string, or empty string if no contacts.
    """
    contacts = get_all_contacts()[:limit]
    if not contacts:
        return ""

    lines = ["[Contacts Vani knows about]"]
    for c in contacts:
        name = c["name"]
        nick = f" / {c['nickname']}" if c.get("nickname") else ""
        platform = f" [{c['platform']}]" if c.get("platform") else ""
        lines.append(f"  • {name}{nick}{platform}")

    return "\n".join(lines)
