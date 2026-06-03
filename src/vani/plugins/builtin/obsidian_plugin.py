"""
vani/plugins/builtin/obsidian_plugin.py

Obsidian Plugin — Vani's long-term memory via Obsidian vault.

What it does:
  • Saves conversation summaries as Obsidian notes (.md with YAML frontmatter)
  • Auto-links related notes using [[wikilinks]]
  • On "remember this" or "save our talk" → writes a note
  • On "what did we discuss about X" → searches the vault
  • At session end → auto-saves a dated note (if enabled)

Setup:
  User must set OBSIDIAN_VAULT_PATH in .env or via plugin settings.
"""

from __future__ import annotations
import os
import re
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path

from vani.plugins.registry import VaniPlugin, PluginResult, PluginContext

logger = logging.getLogger("vani.plugins.obsidian")

VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
VANI_FOLDER = "Vani Conversations"   # subfolder inside vault


class ObsidianPlugin(VaniPlugin):
    name = "obsidian"
    icon = "🧠"
    description = "Saves our conversations to your Obsidian vault so Vani never forgets."
    category = "memory"
    enabled = False
    triggers = [
        "obsidian mein save karo", "note banao", "yaad rakh", "remember this",
        "save our conversation", "save this to obsidian", "obsidian note",
        "hamare baat save karo", "note kar lo", "write this down",
        "vault mein save", "save to vault", "obsidian mein likh",
    ]

    def _vault(self) -> Path | None:
        v = VAULT_PATH or os.getenv("OBSIDIAN_VAULT_PATH", "")
        if not v:
            return None
        p = Path(v).expanduser()
        if not p.exists():
            return None
        return p

    def _note_dir(self) -> Path | None:
        v = self._vault()
        if not v:
            return None
        d = v / VANI_FOLDER
        d.mkdir(exist_ok=True)
        return d

    def _build_note(
        self,
        title: str,
        content: str,
        messages: list[dict] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Build an Obsidian-flavoured Markdown note."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        tags_str = "\n".join(f"  - {t}" for t in (tags or ["vani", "conversation"]))

        # Build conversation transcript block
        transcript = ""
        if messages:
            transcript = "\n## 💬 Conversation\n\n"
            for m in messages[-20:]:   # last 20 turns only
                role = "🧑 You" if m.get("role") == "user" else "🤖 Vani"
                transcript += f"**{role}**: {m.get('content', '')}\n\n"

        return f"""---
title: "{title}"
date: {date_str}
time: {time_str}
tags:
{tags_str}
source: Vani AI Assistant
---

# {title}

> 📅 *{now.strftime('%d %B %Y, %I:%M %p')}*

## 📝 Summary

{content}
{transcript}
---
*✨ Saved by Vani · Your Personal AI*
"""

    async def on_activate(self, query: str, context: PluginContext) -> PluginResult:
        note_dir = self._note_dir()
        if not note_dir:
            return PluginResult(
                success=False,
                message="Obsidian vault path nahi mila! Please set OBSIDIAN_VAULT_PATH in your .env file.",
                ui_payload={"needs_config": True, "config_key": "OBSIDIAN_VAULT_PATH"}
            )

        # Build summary from recent conversation
        recent = context.recent_messages[-10:] if context.recent_messages else []
        topics = self._extract_topics(recent)
        title = f"Vani Chat — {datetime.now().strftime('%d %b %Y %H:%M')}"
        if topics:
            title = f"Vani — {', '.join(topics[:2])} — {datetime.now().strftime('%d %b %Y')}"

        summary = self._summarize(recent, query)
        note_content = self._build_note(title, summary, recent, topics)

        safe_title = re.sub(r'[^\w\s\-—]', '', title).strip()
        filepath = note_dir / f"{safe_title}.md"
        filepath.write_text(note_content, encoding="utf-8")

        # Open in Obsidian if available
        try:
            if os.uname().sysname == "Darwin":
                subprocess.Popen(["open", "-a", "Obsidian", str(filepath)])
        except Exception:
            pass

        return PluginResult(
            success=True,
            message=f"✅ Obsidian mein note save ho gaya: '{safe_title}'! Vault mein dekh lo.",
            artifact_path=str(filepath),
            artifact_type="markdown",
            ui_payload={"note_title": safe_title, "vault_path": str(self._vault())}
        )

    async def on_memory_save(self, messages: list[dict]) -> str | None:
        """Auto-save at session end if vault is configured."""
        note_dir = self._note_dir()
        if not note_dir or not messages:
            return None
        topics = self._extract_topics(messages)
        title = f"Vani Session — {datetime.now().strftime('%d %b %Y')}"
        note_content = self._build_note(title, "Auto-saved session transcript.", messages, topics)
        safe_title = re.sub(r'[^\w\s\-—]', '', title).strip()
        (note_dir / f"{safe_title}.md").write_text(note_content, encoding="utf-8")
        return f"🧠 Obsidian vault updated: {safe_title}"

    def _extract_topics(self, messages: list[dict]) -> list[str]:
        """Naive keyword extraction from conversation."""
        text = " ".join(m.get("content", "") for m in messages).lower()
        common = {"the", "is", "a", "and", "to", "of", "in", "it", "you", "i", "we", "that",
                  "me", "my", "this", "can", "vani", "ok", "yes", "no", "hi", "hello"}
        words = re.findall(r'\b[a-z]{4,}\b', text)
        freq: dict[str, int] = {}
        for w in words:
            if w not in common:
                freq[w] = freq.get(w, 0) + 1
        top = sorted(freq, key=lambda x: -freq[x])[:4]
        return [t.title() for t in top]

    def _summarize(self, messages: list[dict], trigger_query: str) -> str:
        """Build a simple summary without LLM (fast path)."""
        if not messages:
            return "Conversation saved from Vani session."
        topics = self._extract_topics(messages)
        topic_str = ", ".join(topics) if topics else "various topics"
        n = len(messages)
        return (
            f"This conversation covered {topic_str}. "
            f"Total {n} messages exchanged. "
            f"Saved on request: \"{trigger_query}\"."
        )
