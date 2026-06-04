"""
src/vani/core/observability.py — Performance Tracing, Token tracking, and operational reports
"""

from __future__ import annotations
import json
import logging
import time
from typing import List, Dict, Any, Optional
from vani.config import PROJECT_ROOT

logger = logging.getLogger("vani.core.observability")
OBSERVABILITY_LOG = PROJECT_ROOT / "conversations" / "observability.jsonl"


class Trace:
    def __init__(self, agent_name: str, action: str) -> None:
        self.agent_name = agent_name
        self.action = action
        self.start_time = time.time()
        self.end_time = 0.0
        self.duration = 0.0
        self.tokens_estimate = 0
        self.cost = 0.0
        self.success = True
        self.error: Optional[str] = None


class ObservabilityTracker:
    """Tracks latency, token footprints, and virtual API costs across task execution runs."""

    @staticmethod
    def start_trace(agent_name: str, action: str) -> Trace:
        return Trace(agent_name, action)

    @staticmethod
    def end_trace(trace: Trace, success: bool, tokens_count: int, error: Optional[str] = None) -> None:
        trace.end_time = time.time()
        trace.duration = round(trace.end_time - trace.start_time, 3)
        trace.success = success
        trace.tokens_estimate = tokens_count
        trace.error = error
        
        # Virtual API cost estimate: $0.075 per million tokens (standard local equivalent)
        trace.cost = round((tokens_count / 1000000.0) * 0.075, 6)

        try:
            OBSERVABILITY_LOG.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": trace.start_time,
                "agent": trace.agent_name,
                "action": trace.action,
                "duration_s": trace.duration,
                "tokens": trace.tokens_estimate,
                "cost_usd": trace.cost,
                "success": trace.success,
                "error": trace.error,
            }
            with open(OBSERVABILITY_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write observability log: {e}")

    @staticmethod
    def generate_health_report() -> Dict[str, Any]:
        """Compile execution statistics and latencies."""
        if not OBSERVABILITY_LOG.exists():
            return {"total_runs": 0, "success_rate": 100.0, "mean_duration_s": 0.0}

        runs = 0
        successes = 0
        total_duration = 0.0

        try:
            with open(OBSERVABILITY_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        runs += 1
                        if entry.get("success", True):
                            successes += 1
                        total_duration += float(entry.get("duration_s", 0.0))
        except Exception as e:
            logger.error(f"Failed to compile health report: {e}")

        success_rate = round((successes / runs) * 100.0, 1) if runs > 0 else 100.0
        mean_duration = round(total_duration / runs, 2) if runs > 0 else 0.0

        return {
            "timestamp": time.time(),
            "total_runs": runs,
            "successes": successes,
            "success_rate_percent": success_rate,
            "mean_duration_s": mean_duration,
        }

    @staticmethod
    def generate_usage_report() -> Dict[str, Any]:
        """Compile cumulative token usage and virtual API costs."""
        if not OBSERVABILITY_LOG.exists():
            return {"total_tokens": 0, "total_cost_usd": 0.0}

        total_tokens = 0
        total_cost = 0.0
        agent_footprints: Dict[str, int] = {}

        try:
            with open(OBSERVABILITY_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        tk = int(entry.get("tokens", 0))
                        total_tokens += tk
                        total_cost += float(entry.get("cost_usd", 0.0))
                        
                        agent = entry.get("agent", "unknown")
                        agent_footprints[agent] = agent_footprints.get(agent, 0) + tk
        except Exception as e:
            logger.error(f"Failed to compile usage report: {e}")

        return {
            "timestamp": time.time(),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "agent_tokens_breakdown": agent_footprints,
        }

    @staticmethod
    def generate_failure_analysis() -> Dict[str, Any]:
        """Scan logs to extract failure alerts and trace common errors."""
        failures_count = 0
        error_types: Dict[str, int] = {}
        recent_errors = []

        if OBSERVABILITY_LOG.exists():
            try:
                with open(OBSERVABILITY_LOG, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entry = json.loads(line)
                            if not entry.get("success", True):
                                failures_count += 1
                                err = entry.get("error") or "UnknownError"
                                # Group errors by first few words
                                err_key = " ".join(err.split()[:3])
                                error_types[err_key] = error_types.get(err_key, 0) + 1
                                recent_errors.append(
                                    {
                                        "timestamp": entry.get("timestamp"),
                                        "agent": entry.get("agent"),
                                        "action": entry.get("action"),
                                        "error": err,
                                    }
                                )
            except Exception as e:
                logger.error(f"Failed to compile failure report: {e}")

        return {
            "timestamp": time.time(),
            "total_failures": failures_count,
            "common_errors_breakdown": error_types,
            "recent_failures_trace": recent_errors[-5:],
        }
