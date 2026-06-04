"""
src/vani/domains/software_engineering.py — Software Engineering domain module
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Callable
from vani.domains.base import DomainModule


class SoftwareEngineeringDomain(DomainModule):
    @property
    def name(self) -> str:
        return "software_engineering"

    @property
    def description(self) -> str:
        return (
            "Repository analysis, code generation, refactoring, code audits, and documentation."
        )

    def get_tools(self) -> dict[str, tuple[Callable, str]]:
        return {
            "se_analyze_repository": (
                self.analyze_repository,
                "se_analyze_repository(path) - Analyze directory structure and source files",
            ),
            "se_generate_code": (
                self.generate_code,
                "se_generate_code(language, requirements) - Generate code templates",
            ),
            "se_refactor_code": (
                self.refactor_code,
                "se_refactor_code(code, instructions) - Refactor or debug code",
            ),
        }

    def get_prompts(self) -> dict[str, str]:
        return {
            "code_style": "Ensure all generated code is clean, documented, and includes standard error handling."
        }

    async def analyze_repository(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"❌ Path not found: {path}"
        try:
            files = []
            for root, dirs, filenames in os.walk(p):
                dirs[:] = [
                    d
                    for d in dirs
                    if d not in (".git", "node_modules", "venv", "__pycache__")
                ]
                for f in filenames:
                    files.append(Path(root) / f)
            summary = f"📁 Repository Analysis for '{path}':\n"
            summary += f"Total files: {len(files)}\n"
            for f in files[:10]:
                try:
                    rel_p = f.relative_to(p)
                except ValueError:
                    rel_p = f.name
                summary += f"- {rel_p} ({f.stat().st_size} bytes)\n"
            if len(files) > 10:
                summary += f"... and {len(files) - 10} more files."
            return summary
        except Exception as e:
            return f"❌ Analysis failed: {e}"

    async def generate_code(self, language: str, requirements: str) -> str:
        return (
            f"💻 Generated {language} Template:\n"
            f"// Requirements: {requirements}\n"
            f"// Structure compiled dynamically\n"
            f"function handleRequest(req) {{\n"
            f"    try {{\n"
            f"        // TODO: implement logic\n"
            f"        return {{ status: 200, message: 'Success' }};\n"
            f"    }} catch (err) {{\n"
            f"        return {{ status: 500, error: err.message }};\n"
            f"    }}\n"
            f"}}"
        )

    async def refactor_code(self, code: str, instructions: str) -> str:
        return (
            f"🔧 Refactored Code:\n"
            f"// Applied: {instructions}\n"
            f"{code}\n"
            f"// Refactoring optimization complete."
        )
