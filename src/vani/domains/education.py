"""
src/vani/domains/education.py — Education domain module
"""

from __future__ import annotations
from typing import Callable
from vani.domains.base import DomainModule


class EducationDomain(DomainModule):
    @property
    def name(self) -> str:
        return "education"

    @property
    def description(self) -> str:
        return (
            "Learning syllabus planning, interactive quiz building, and curriculum tracking."
        )

    def get_tools(self) -> dict[str, tuple[Callable, str]]:
        return {
            "edu_create_syllabus": (
                self.create_syllabus,
                "edu_create_syllabus(subject) - Generate a structured learning curriculum",
            ),
            "edu_generate_quiz": (
                self.generate_quiz,
                "edu_generate_quiz(topic, questions_count) - Build a multiple-choice quiz",
            ),
        }

    def get_prompts(self) -> dict[str, str]:
        return {
            "learner_centric": "Adapt language to a supportive, structured, and pedagogical teaching style."
        }

    async def create_syllabus(self, subject: str) -> str:
        return (
            f"📚 Structured Syllabus: Introduction to {subject}\n"
            f"  - Week 1: Core Fundamentals & Setups\n"
            f"  - Week 2: Key Structures and Operations\n"
            f"  - Week 3: Multi-agent interaction schemas\n"
            f"  - Week 4: Deployment pipelines and scaling\n"
            f"Recommended reading: Main developer documentation and source tutorials."
        )

    async def generate_quiz(self, topic: str, questions_count: int = 3) -> str:
        count = int(questions_count)
        return (
            f"📝 Multiple Choice Quiz: {topic} (Total Questions: {count})\n"
            f"1. What is the main design feature of {topic}?\n"
            f"  [a] Resource efficiency  [b] Cloud-only lockouts  [c] Hardcoded sequences\n"
            f"2. How does the system handle state changes?\n"
            f"  [a] Session resetting  [b] Vector database indexing  [c] Re-compilation\n"
            f"Quiz generation complete. Call answers_check to evaluate."
        )
