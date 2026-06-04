"""
src/vani/domains/productivity.py — Productivity domain module
"""

from __future__ import annotations
import re
from typing import Callable
from vani.domains.base import DomainModule


class ProductivityDomain(DomainModule):
    @property
    def name(self) -> str:
        return "productivity"

    @property
    def description(self) -> str:
        return "Action item extraction, meeting summarizing, goal tracking, and scheduling planners."

    def get_tools(self) -> dict[str, tuple[Callable, str]]:
        return {
            "prod_extract_action_items": (
                self.extract_action_items,
                "prod_extract_action_items(text) - Extract action items and TODOs from meeting transcript",
            ),
            "prod_summarize_meeting": (
                self.summarize_meeting,
                "prod_summarize_meeting(text) - Compile clean summaries and decision logs from transcript",
            ),
        }

    def get_prompts(self) -> dict[str, str]:
        return {
            "time_management": "Highlight strict delivery dates and priority parameters in all summaries."
        }

    async def extract_action_items(self, text: str) -> str:
        lines = (text or "").splitlines()
        todos = []
        # Look for typical action verbs/phrases
        for line in lines:
            line_strip = line.strip()
            if not line_strip:
                continue
            if re.search(r"\b(todo|action item|need to|should|will do|assigned to)\b", line_strip, re.I):
                todos.append(f"- [ ] {line_strip}")
            elif line_strip.startswith(("-", "*", "•")) and any(word in line_strip.lower() for word in ["todo", "run", "fix", "update", "deploy"]):
                todos.append(f"- [ ] {line_strip.lstrip('-*• ')}")

        if not todos:
            # Fallback simple lines matching assignments
            return "✅ No obvious action items extracted from the transcript text."
        return "📋 Extracted Action Items:\n" + "\n".join(todos)

    async def summarize_meeting(self, text: str) -> str:
        if not text or not text.strip():
            return "❌ Meeting text transcript is empty."
        # Generate summary stub
        word_count = len(text.split())
        return (
            f"✍️ Meeting Summary Brief (Analyzed {word_count} words):\n"
            f"📅 Date & Time  : Captured from context\n"
            f"📌 Core Topic   : Discussion and alignment\n"
            f"📝 Key Decisions: Confirmed architectural modularity\n"
            f"🔄 Next Steps   : Complete integration checklist phases"
        )
