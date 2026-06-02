"""
vani/core/self_improvement.py — Phase 8

Self-Improvement Layer: analyzes tool failures, learns patterns, and builds
a strategy library that the executor can consult before retrying a failed task.

Data flow:
    executor.py         → writes agent_failures.jsonl   (Phase 2/5)
    task_history.py     → writes task_history.jsonl     (Phase 5/6)
                                    ↓
    analyze_failures()  → reads both files, finds patterns
    run_improvement_cycle() → runs hourly via WorkerManager (Phase 7)
                                    ↓
    learned_strategies.json ← updated with failure counts + fix hints
                                    ↓
    get_retry_strategy()    ← consulted by executor before retrying a task

Design principles:
  - Runs entirely in the background — never blocks VANI's response pipeline.
  - Zero risk to existing behavior: strategies are hints, not hard overrides.
  - Two tiers of knowledge:
      Tier 1 — hardcoded rules for known failure patterns (instant, no LLM)
      Tier 2 — pattern-learned counts from the failure log (grows over time)
  - All file I/O is wrapped in try/except — a crash here never affects VANI.

Output files (in conversations/):
    agent_failures.jsonl      — written by executor (input to this module)
    learned_strategies.json   — written by this module (read by executor)
    improvement_report.json   — human-readable summary of last analysis cycle
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from vani.config import PROJECT_ROOT

logger = logging.getLogger("vani.self_improvement")

# ── File paths ────────────────────────────────────────────────────────────────
FAILURES_LOG       = PROJECT_ROOT / "conversations" / "agent_failures.jsonl"
TASK_HISTORY_LOG   = PROJECT_ROOT / "conversations" / "task_history.jsonl"
STRATEGIES_FILE    = PROJECT_ROOT / "conversations" / "learned_strategies.json"
REPORT_FILE        = PROJECT_ROOT / "conversations" / "improvement_report.json"

# How many recent failures to analyze per cycle
_MAX_FAILURE_ENTRIES = 200
# Minimum times a pattern must appear to be recorded as a known issue
_MIN_PATTERN_COUNT = 2
# Success rate below this triggers an "intent needs attention" flag
_LOW_SUCCESS_THRESHOLD = 0.60


# ── Tier 1: Hardcoded fix rules ───────────────────────────────────────────────
# Format: "INTENT::error_substring" → "fix hint"
# These are instant lookups — no log parsing needed.
# Add new patterns here as you discover them in production.

_HARDCODED_FIXES: dict[str, str] = {
    # Browser / search
    "GOOGLE_SEARCH::browser not found":        "Open browser first via APP_OPEN before searching",
    "GOOGLE_SEARCH::timeout":                  "Retry after 1s delay; browser may still be loading",
    "OPEN_URL::no such file":                  "Check URL format — must include https://",
    "OPEN_URL::permission denied":             "URL may require auth; try opening in incognito",

    # YouTube
    "YOUTUBE_PLAY::not found":                 "Try a shorter search query without special characters",
    "YOUTUBE_PLAY::timeout":                   "YouTube tab may be slow; retry after 2s",

    # WhatsApp
    "WHATSAPP_SEND::timeout":                  "WhatsApp Web may be disconnected; open it first",
    "WHATSAPP_SEND::element not found":        "Contact name may differ; check spelling or use phone number",
    "WHATSAPP_CALL::timeout":                  "WhatsApp call requires active WhatsApp Web session",

    # Telegram
    "TELEGRAM_SEND::timeout":                  "Telegram may not be open; open it via APP_OPEN first",

    # Screen / vision
    "SCREEN_READ::empty result":               "Wait 1s for screen to update, then retry screenshot",
    "SCREEN_READ::permission denied":          "Screen recording permission needed in System Preferences",

    # Code
    "CODE_ASSIST::model unavailable":          "Qwen/Ollama may not be running; check ollama ps",

    # Apps
    "APP_OPEN::not found":                     "Application name may differ; try full app name or path",
    "APP_CLOSE::permission denied":            "Cannot close system apps; try via Task Manager",

    # Media
    "MEDIA_CONTROL::no media":                 "No active media player detected; open music app first",
}


# ── Public API ────────────────────────────────────────────────────────────────

def get_retry_strategy(intent: str, error: str) -> Optional[str]:
    """
    Returns a fix hint for a known failure pattern.

    Checks Tier 1 (hardcoded rules) first — instant lookup.
    Falls back to Tier 2 (learned patterns from STRATEGIES_FILE) if no hardcoded rule.

    Args:
        intent: Router intent string (e.g. "WHATSAPP_SEND")
        error:  Error string from the failed task

    Returns:
        A human-readable fix hint string, or None if no hint available.

    Called by executor.py before deciding whether to retry a task:
        hint = get_retry_strategy(task.intent, task.error or "")
        if hint:
            logger.info(f"[EXECUTOR] Strategy hint: {hint}")
    """
    if not intent:
        return None

    intent_upper = intent.strip().upper()
    error_lower = (error or "").lower()

    # ── Tier 1: Exact hardcoded lookup ────────────────────────────────────────
    for pattern, fix in _HARDCODED_FIXES.items():
        parts = pattern.split("::", 1)
        if len(parts) != 2:
            continue
        rule_intent, rule_error = parts
        if intent_upper == rule_intent.upper() and rule_error.lower() in error_lower:
            logger.debug(f"[SELF_IMPROVE] Tier-1 hint for {intent_upper}: {fix}")
            return fix

    # ── Tier 2: Learned strategy from STRATEGIES_FILE ────────────────────────
    try:
        if STRATEGIES_FILE.exists():
            with open(STRATEGIES_FILE, encoding="utf-8") as f:
                data = json.load(f)
            hints = data.get("learned_hints", {})
            key = f"{intent_upper}::{error_lower[:40]}"
            hint = hints.get(key)
            if hint:
                logger.debug(f"[SELF_IMPROVE] Tier-2 hint for {key}: {hint}")
                return hint
    except Exception as e:
        logger.debug(f"[SELF_IMPROVE] Tier-2 lookup failed: {e}")

    return None


def analyze_failures(max_entries: int = _MAX_FAILURE_ENTRIES) -> dict:
    """
    Read agent_failures.jsonl and extract failure patterns.

    Returns a dict with:
        pattern_counts:  {intent::error_prefix: count}
        intent_counts:   {intent: total_failures}
        most_common:     top-5 patterns as list of (pattern, count)
        total_failures:  int
    """
    if not FAILURES_LOG.exists():
        return {
            "pattern_counts": {},
            "intent_counts": {},
            "most_common": [],
            "total_failures": 0,
        }

    pattern_counts: Counter = Counter()
    intent_counts: Counter = Counter()
    total = 0

    try:
        with open(FAILURES_LOG, encoding="utf-8") as f:
            lines = f.readlines()

        # Analyze most recent entries first (tail of file)
        for line in lines[-max_entries:]:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                intent = (entry.get("intent") or "unknown").upper()
                error  = (entry.get("error") or "")[:40].lower()
                key    = f"{intent}::{error}"
                pattern_counts[key] += 1
                intent_counts[intent] += 1
                total += 1
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"[SELF_IMPROVE] Could not read failures log: {e}")
        return {"pattern_counts": {}, "intent_counts": {}, "most_common": [], "total_failures": 0}

    most_common = [
        {"pattern": pat, "count": cnt}
        for pat, cnt in pattern_counts.most_common(5)
        if cnt >= _MIN_PATTERN_COUNT
    ]

    return {
        "pattern_counts": dict(pattern_counts),
        "intent_counts":  dict(intent_counts),
        "most_common":    most_common,
        "total_failures": total,
    }


def analyze_success_rates() -> dict:
    """
    Read task_history.jsonl and compute per-intent success rates.

    Returns a dict: {intent: {"success": N, "total": N, "rate": 0.0-1.0}}
    Intents with success rate below _LOW_SUCCESS_THRESHOLD are flagged.
    """
    if not TASK_HISTORY_LOG.exists():
        return {}

    counts: dict[str, dict] = defaultdict(lambda: {"success": 0, "total": 0})

    try:
        with open(TASK_HISTORY_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    intent = (entry.get("intent") or "unknown").upper()
                    counts[intent]["total"] += 1
                    if entry.get("success", False):
                        counts[intent]["success"] += 1
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"[SELF_IMPROVE] Could not read task history: {e}")
        return {}

    result = {}
    for intent, c in counts.items():
        rate = c["success"] / c["total"] if c["total"] > 0 else 0.0
        result[intent] = {
            "success": c["success"],
            "total": c["total"],
            "rate": round(rate, 3),
            "flagged": rate < _LOW_SUCCESS_THRESHOLD and c["total"] >= 3,
        }

    return result


def _build_learned_hints(failure_analysis: dict) -> dict[str, str]:
    """
    Generate Tier-2 learned hints from failure patterns.

    For patterns not covered by Tier-1 hardcoded rules, we generate a
    generic hint based on the failure type. These grow more specific
    over time as the failure log accumulates more data.
    """
    hints = {}
    for pattern, count in failure_analysis.get("pattern_counts", {}).items():
        if count < _MIN_PATTERN_COUNT:
            continue
        # Skip if already covered by a Tier-1 rule
        if pattern in _HARDCODED_FIXES:
            continue

        parts = pattern.split("::", 1)
        if len(parts) != 2:
            continue
        intent, error = parts

        # Generate a generic hint based on error type
        if "timeout" in error:
            hint = f"{intent}: timed out {count}x — add delay before retry or check if prerequisite app is open"
        elif "not found" in error or "nahi mila" in error:
            hint = f"{intent}: target not found {count}x — verify name/path, check if app is running"
        elif "permission" in error:
            hint = f"{intent}: permission denied {count}x — check system permissions or run as admin"
        elif "empty" in error:
            hint = f"{intent}: empty result {count}x — add wait before this action"
        elif "connection" in error or "network" in error:
            hint = f"{intent}: network error {count}x — check internet/VPN before retrying"
        else:
            hint = f"{intent}: failed {count}x with '{error[:30]}' — monitor and investigate"

        hints[pattern] = hint

    return hints


def run_improvement_cycle() -> None:
    """
    Main self-improvement cycle. Called by WorkerManager every 60 minutes.

    Steps:
        1. Analyze failure patterns from agent_failures.jsonl
        2. Compute success rates from task_history.jsonl
        3. Build/update learned_hints for Tier-2 strategy lookup
        4. Write updated learned_strategies.json
        5. Write human-readable improvement_report.json
        6. Log a one-line summary
    """
    logger.debug("[SELF_IMPROVE] Starting improvement cycle...")

    try:
        failure_analysis = analyze_failures()
        success_rates    = analyze_success_rates()

        if failure_analysis["total_failures"] == 0 and not success_rates:
            logger.debug("[SELF_IMPROVE] No data yet — skipping cycle.")
            return

        # Build Tier-2 learned hints from failure patterns
        learned_hints = _build_learned_hints(failure_analysis)

        # Identify flagged (low-success) intents
        flagged_intents = [
            {"intent": intent, "rate": data["rate"], "total": data["total"]}
            for intent, data in success_rates.items()
            if data.get("flagged", False)
        ]

        # ── Write learned_strategies.json ─────────────────────────────────────
        STRATEGIES_FILE.parent.mkdir(parents=True, exist_ok=True)

        existing_strategies = {}
        if STRATEGIES_FILE.exists():
            try:
                with open(STRATEGIES_FILE, encoding="utf-8") as f:
                    existing_strategies = json.load(f)
            except Exception:
                pass

        # Merge: new learned hints extend (don't replace) existing ones
        existing_hints = existing_strategies.get("learned_hints", {})
        existing_hints.update(learned_hints)

        strategies = {
            "updated_at":      time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_failures_analyzed": failure_analysis["total_failures"],
            "failure_counts":  failure_analysis["pattern_counts"],
            "intent_failures": failure_analysis["intent_counts"],
            "learned_hints":   existing_hints,
            "flagged_intents": flagged_intents,
        }

        with open(STRATEGIES_FILE, "w", encoding="utf-8") as f:
            json.dump(strategies, f, indent=2, ensure_ascii=False)

        # ── Write improvement_report.json (human-readable) ────────────────────
        report = {
            "generated_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
            "summary":       _build_summary(failure_analysis, success_rates, flagged_intents),
            "top_failures":  failure_analysis["most_common"],
            "flagged_intents": flagged_intents,
            "new_hints_count": len(learned_hints),
            "total_hints":   len(existing_hints),
        }

        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # ── Log one-line summary ───────────────────────────────────────────────
        top = failure_analysis["most_common"]
        top_str = top[0]["pattern"] if top else "none"
        logger.info(
            f"[SELF_IMPROVE] Cycle complete — "
            f"{failure_analysis['total_failures']} failures analyzed, "
            f"{len(learned_hints)} new hints, "
            f"{len(flagged_intents)} flagged intents. "
            f"Top failure: {top_str}"
        )

    except Exception as e:
        logger.warning(f"[SELF_IMPROVE] Improvement cycle failed (non-fatal): {e}")


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _build_summary(
    failure_analysis: dict,
    success_rates: dict,
    flagged_intents: list,
) -> str:
    """Build a concise human-readable summary for the report."""
    parts = []

    total_f = failure_analysis.get("total_failures", 0)
    if total_f:
        parts.append(f"{total_f} failures analyzed")

    top = failure_analysis.get("most_common", [])
    if top:
        top_pattern = top[0]["pattern"]
        top_count   = top[0]["count"]
        parts.append(f"most common failure: {top_pattern!r} ({top_count}x)")

    if flagged_intents:
        names = ", ".join(f["intent"] for f in flagged_intents[:3])
        parts.append(f"low-success intents needing attention: {names}")

    total_intents = len(success_rates)
    if total_intents:
        overall_rates = [d["rate"] for d in success_rates.values() if d["total"] >= 3]
        if overall_rates:
            avg = sum(overall_rates) / len(overall_rates)
            parts.append(f"avg success rate across {len(overall_rates)} intents: {avg*100:.1f}%")

    return "; ".join(parts) if parts else "No significant patterns detected yet."


def get_report() -> dict:
    """
    Returns the most recent improvement report as a dict.
    Returns empty dict if no report has been generated yet.
    Used for health checks and debug logging.
    """
    if not REPORT_FILE.exists():
        return {}
    try:
        with open(REPORT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_flagged_intents() -> list[dict]:
    """
    Returns intents currently flagged as low-success.
    Convenience function for the planner to deprioritize known-bad paths.
    """
    try:
        if STRATEGIES_FILE.exists():
            with open(STRATEGIES_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("flagged_intents", [])
    except Exception:
        pass
    return []


def print_report() -> None:
    """
    Prints a human-readable summary of the latest improvement report to stdout.
    Useful for debugging from CLI or tests.
    """
    report = get_report()
    if not report:
        print("[SELF_IMPROVE] No report generated yet. Run run_improvement_cycle() first.")
        return

    print(f"\n{'='*60}")
    print(f"  VANI Self-Improvement Report — {report.get('generated_at','?')}")
    print(f"{'='*60}")
    print(f"  Summary: {report.get('summary','N/A')}")
    print(f"  New hints this cycle: {report.get('new_hints_count', 0)}")
    print(f"  Total hints in library: {report.get('total_hints', 0)}")

    top = report.get("top_failures", [])
    if top:
        print(f"\n  Top failure patterns:")
        for item in top:
            print(f"    • {item['pattern']} — {item['count']}x")

    flagged = report.get("flagged_intents", [])
    if flagged:
        print(f"\n  Intents needing attention (low success rate):")
        for item in flagged:
            print(f"    • {item['intent']}: {item['rate']*100:.1f}% success over {item['total']} calls")

    print(f"{'='*60}\n")
