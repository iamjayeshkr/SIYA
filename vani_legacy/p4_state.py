"""
vani/p4_state.py  — P4 Persistent Tray State
─────────────────────────────────────────────
Saves and restores Vani's tray + session state across restarts.
So when you open Vani after closing it, she remembers:
  - Last active mode (voice / text / away)
  - Window position (restored by Rust on next launch)
  - Notification preferences
  - Last session summary

State file: ~/vani_tray_state.json
Auto-saved every 60 seconds and on clean exit.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from vani.logging_config import get_logger

log = get_logger("p4.state")

STATE_PATH = Path.home() / "vani_tray_state.json"
AUTOSAVE_INTERVAL = 60   # seconds


@dataclass
class TrayState:
    # Window
    window_x: int = -1          # -1 = let OS decide
    window_y: int = -1
    window_visible: bool = True

    # Mode
    last_mode: str = "voice"    # "voice" | "text" | "away"
    notifications_enabled: bool = True
    wake_word_enabled: bool = True

    # Session context
    last_active_ts: float = field(default_factory=time.time)
    session_count: int = 0
    last_session_summary: str = ""

    # P4 feature flags
    streaming_enabled: bool = True
    parallel_tools_enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TrayState":
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


class TrayStateManager:
    """Loads, saves, and auto-saves TrayState."""

    def __init__(self, path: Path = STATE_PATH):
        self._path = path
        self._state = TrayState()
        self._dirty = False
        self._task: Optional[asyncio.Task] = None

    def load(self) -> TrayState:
        """Load state from disk. If missing or corrupt, returns defaults."""
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                self._state = TrayState.from_dict(raw)
                log.info("tray_state_loaded", path=str(self._path),
                         session=self._state.session_count)
            except Exception as e:
                log.warning("tray_state_load_failed", error=str(e))
                self._state = TrayState()
        self._state.session_count += 1
        self._state.last_active_ts = time.time()
        self.save()   # immediately persist incremented session count
        return self._state

    def save(self) -> None:
        """Synchronously write state to disk."""
        try:
            self._path.write_text(json.dumps(self._state.to_dict(), indent=2))
            self._dirty = False
        except Exception as e:
            log.warning("tray_state_save_failed", error=str(e))

    def update(self, **kwargs) -> None:
        """Update one or more fields and mark dirty."""
        for k, v in kwargs.items():
            if hasattr(self._state, k):
                setattr(self._state, k, v)
            else:
                log.warning("tray_state_unknown_key", key=k)
        self._dirty = True

    @property
    def state(self) -> TrayState:
        return self._state

    async def start_autosave(self) -> None:
        """Start background autosave loop."""
        async def _loop():
            while True:
                await asyncio.sleep(AUTOSAVE_INTERVAL)
                if self._dirty:
                    self.save()
                    log.debug("tray_state_autosaved")
        self._task = asyncio.create_task(_loop())
        log.info("tray_state_autosave_started", interval_s=AUTOSAVE_INTERVAL)

    def stop(self) -> None:
        """Stop autosave and flush to disk."""
        if self._task:
            self._task.cancel()
        self.save()
        log.info("tray_state_saved_on_exit")


# ── Module-level singleton ────────────────────────────────────────────────────
tray_state_manager = TrayStateManager()
