"""
vani/p4_wake_word.py  —  P4 Wake Word (Python fallback)
─────────────────────────────────────────────────────────
Python-side wake word controller that the Rust process communicates with
via the existing FastAPI server on port 8765.

The Rust side (main.rs) polls GET /wake/status and fires
POST /wake/trigger when it detects audio energy above threshold.

This module:
  1. Manages the wake word state machine
  2. Integrates with Vani's existing voice activation flow
  3. Provides endpoints for Rust ↔ Python communication

Wake word detection flow:
  Rust mic listener → energy threshold → POST /wake/trigger
  → Python wakes Vani → plays confirmation sound → starts listening
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from vani.logging_config import get_logger

log = get_logger("p4.wake_word")


@dataclass
class WakeWordState:
    enabled: bool = True
    last_triggered: float = 0.0
    cooldown_s: float = 2.0      # min seconds between wake events
    total_triggers: int = 0
    false_positive_count: int = 0


class WakeWordController:
    """
    Manages wake word state and integrates with the existing voice stack.
    The Rust process sends triggers; this class decides whether to act on them.
    """

    def __init__(self):
        self._state = WakeWordState()
        self._on_wake_callbacks: list = []

    def on_wake(self, callback) -> None:
        """Register a callback to be called when wake word is detected."""
        self._on_wake_callbacks.append(callback)

    def trigger(self, confidence: float = 1.0) -> dict:
        """
        Called when Rust detects a potential wake word.
        Returns {"acted": bool, "reason": str}.
        """
        now = time.time()

        if not self._state.enabled:
            return {"acted": False, "reason": "disabled"}

        cooldown_remaining = self._state.cooldown_s - (now - self._state.last_triggered)
        if cooldown_remaining > 0:
            return {"acted": False, "reason": f"cooldown {cooldown_remaining:.1f}s"}

        if confidence < 0.6:
            self._state.false_positive_count += 1
            return {"acted": False, "reason": f"low confidence {confidence:.2f}"}

        # Act on the wake word
        self._state.last_triggered = now
        self._state.total_triggers += 1

        log.info("wake_word_triggered", confidence=confidence,
                 total=self._state.total_triggers)

        # Fire callbacks (non-blocking)
        for cb in self._on_wake_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb())
                else:
                    cb()
            except Exception as e:
                log.warning("wake_callback_error", error=str(e))

        return {"acted": True, "reason": "ok"}

    def status(self) -> dict:
        return {
            "enabled": self._state.enabled,
            "last_triggered": self._state.last_triggered,
            "cooldown_s": self._state.cooldown_s,
            "total_triggers": self._state.total_triggers,
            "false_positive_count": self._state.false_positive_count,
        }

    def set_enabled(self, enabled: bool) -> None:
        self._state.enabled = enabled
        log.info("wake_word_enabled_changed", enabled=enabled)


# Module-level singleton
wake_word_controller = WakeWordController()
