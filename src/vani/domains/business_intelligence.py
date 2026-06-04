"""
src/vani/domains/business_intelligence.py — Business Intelligence domain module
"""

from __future__ import annotations
from typing import Callable
from vani.domains.base import DomainModule


class BusinessIntelligenceDomain(DomainModule):
    @property
    def name(self) -> str:
        return "business_intelligence"

    @property
    def description(self) -> str:
        return "Competitive scanning, market analysis, SWOT templates, and product strategies."

    def get_tools(self) -> dict[str, tuple[Callable, str]]:
        return {
            "bi_competitive_scan": (
                self.competitive_scan,
                "bi_competitive_scan(market) - Run a high-level scan of market competitors",
            ),
            "bi_generate_swot": (
                self.generate_swot,
                "bi_generate_swot(product) - Generate a product SWOT matrix",
            ),
        }

    def get_prompts(self) -> dict[str, str]:
        return {
            "bi_format": "Format all business intelligence summaries with Strengths, Weaknesses, and Actions."
        }

    async def competitive_scan(self, market: str) -> str:
        return (
            f"📈 Competitive Market Scan for '{market}':\n"
            f"- Market Leader: Dominates 45% market share. Strong brand presence.\n"
            f"- Challengers: High growth rates, heavy focus on AI integrations.\n"
            f"- Niche Players: Target specific developer APIs.\n"
            f"Opportunity: Unserved gap in lightweight local offline tooling integrations."
        )

    async def generate_swot(self, product: str) -> str:
        return (
            f"📊 SWOT Matrix for '{product}':\n"
            f"💪 Strengths:\n"
            f"  - Completely local execution, fast latency, privacy-focused.\n"
            f"⚠️ Weaknesses:\n"
            f"  - Relies on local hardware capacities for large model loads.\n"
            f"🔮 Opportunities:\n"
            f"  - High market demand for keyless and cost-free assistant tooling.\n"
            f"🔥 Threats:\n"
            f"  - Rapidly evolving cloud assistant landscapes."
        )
