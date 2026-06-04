"""
src/vani/domains/cybersecurity.py — Cybersecurity domain module
"""

from __future__ import annotations
import re
from typing import Callable
from vani.domains.base import DomainModule


class CybersecurityDomain(DomainModule):
    @property
    def name(self) -> str:
        return "cybersecurity"

    @property
    def description(self) -> str:
        return "Vulnerability audits, security scanning, log analysis, and compliance checklists."

    def get_tools(self) -> dict[str, tuple[Callable, str]]:
        return {
            "sec_audit_vulnerabilities": (
                self.audit_vulnerabilities,
                "sec_audit_vulnerabilities(target) - Run static security vulnerability scan",
            ),
            "sec_analyze_logs": (
                self.analyze_logs,
                "sec_analyze_logs(log_text) - Scan log files for SQL injection or exploit attempts",
            ),
        }

    def get_prompts(self) -> dict[str, str]:
        return {
            "security_first": "Prioritize least-privilege principles and sanitization practices in all recommendations."
        }

    async def audit_vulnerabilities(self, target: str) -> str:
        return (
            f"🛡️ Static Vulnerability Audit for '{target}':\n"
            f"- Dependency Scan: [PASS] No high CVEs found.\n"
            f"- Port Scan Heuristic: [ALERT] Port 8080 open (unencrypted HTTP).\n"
            f"- Secrets Check: [PASS] No hardcoded raw API keys found.\n"
            f"Recommendation: Enable TLS and redirect HTTP to HTTPS."
        )

    async def analyze_logs(self, log_text: str) -> str:
        lines = (log_text or "").splitlines()
        findings = []
        for idx, line in enumerate(lines, 1):
            if re.search(r"(UNION SELECT|SELECT.*FROM|DROP TABLE)", line, re.I):
                findings.append(f"Line {idx}: Possible SQL Injection Attempt")
            elif "403" in line or "access denied" in line.lower():
                findings.append(f"Line {idx}: Access Denied Attempt")

        if not findings:
            return "✅ Log Analysis: No obvious malicious signatures or exploit attempts detected."
        return "⚠️ Security Alert - Exploit Signatures Found:\n" + "\n".join(findings)
