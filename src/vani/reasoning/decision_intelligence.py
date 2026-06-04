"""
src/vani/reasoning/decision_intelligence.py — Decision-Support and Tradeoff Analysis Engine
"""

from __future__ import annotations
import logging
from typing import List, Dict, Any

logger = logging.getLogger("vani.reasoning.decision_intelligence")


class DecisionIntelligence:
    """
    Assists in human decision-making by calculating weighted tradeoff grids,
    assessing risks, and organizing scenario planning metrics.
    """

    @staticmethod
    def evaluate_tradeoffs(
        options: List[Dict[str, Any]], factors: List[str], weights: Dict[str, float] = None
    ) -> Dict[str, Any]:
        """
        Evaluate options against weighted factors.
        Args:
            options: List of {"name": str, "scores": {"factor": score_1_to_10}}
            factors: List of factor names (e.g., ["cost", "speed", "safety"])
            weights: Dict mapping factor -> weight (defaults to 1.0 per factor)
        Returns:
            Dict containing sorted ranked options, weighted scores, and best option.
        """
        if not options:
            return {"rankings": [], "best_option": None}

        w = weights or {f: 1.0 for f in factors}
        # Normalize weights so they sum to 1.0
        total_w = sum(w.get(f, 1.0) for f in factors) or 1.0
        norm_w = {f: w.get(f, 1.0) / total_w for f in factors}

        rankings = []
        for opt in options:
            name = opt["name"]
            scores = opt.get("scores", {})
            
            weighted_sum = 0.0
            for f in factors:
                score = float(scores.get(f, 5.0))  # Default neutral score 5/10
                weighted_sum += score * norm_w.get(f, 1.0)

            rankings.append(
                {
                    "name": name,
                    "weighted_score": round(weighted_sum, 2),
                    "raw_scores": scores,
                }
            )

        # Sort descending by weighted score
        rankings.sort(key=lambda x: x["weighted_score"], reverse=True)
        return {
            "rankings": rankings,
            "best_option": rankings[0]["name"] if rankings else None,
            "normalized_weights": {k: round(v, 2) for k, v in norm_w.items()},
        }

    @staticmethod
    def generate_decision_brief(
        title: str,
        goal: str,
        options: List[Dict[str, Any]],
        factors: List[str],
        weights: Dict[str, float] = None,
        risks: Dict[str, str] = None,
    ) -> str:
        """
        Compiles a structured markdown decision brief report for human review.
        """
        eval_result = DecisionIntelligence.evaluate_tradeoffs(options, factors, weights)
        best = eval_result["best_option"]
        rankings = eval_result["rankings"]
        norm_w = eval_result["normalized_weights"]

        brief = f"# Decision Brief: {title}\n\n"
        brief += f"🎯 **Objective/Goal**:\n{goal}\n\n"
        brief += "📊 **Weighted Decision Grid**:\n"
        brief += "| Option | Weighted Score (1-10) | Factors breakdown |\n"
        brief += "| :--- | :---: | :--- |\n"
        
        for rank in rankings:
            name = rank["name"]
            score = rank["weighted_score"]
            breakdown = ", ".join(f"{f}: {rank['raw_scores'].get(f, 5)}" for f in factors)
            brief += f"| **{name}** | {score} | {breakdown} |\n"

        brief += f"\n💡 **Recommendation**:\nWe recommend executing **{best}** based on the weighted criteria scorecard.\n\n"
        
        if norm_w:
            brief += "**Criteria weights evaluation**:\n"
            brief += ", ".join(f"{k} ({int(v*100)}%)" for k, v in norm_w.items()) + "\n\n"

        if risks:
            brief += "⚠️ **Risk & Tradeoff Assessments**:\n"
            for opt_name, risk_desc in risks.items():
                brief += f"- **{opt_name}**: {risk_desc}\n"
            brief += "\n"

        brief += "📝 *Note: This brief is designed to assist human judgment and is non-binding.*"
        return brief
