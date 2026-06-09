"""
vani/audio/wake_verifier.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━
Async bridge between the wake listener and speaker verification.

Design goals:
  - Zero overhead when VANI_SPEAKER_VERIFY=0 (default)
  - Async path hides ~70ms verification behind ASR warmup (no latency regression)
  - Sync path available for NSSpeechRecognizer delegate (non-async context)
  - Fail-open on every error — Vani never goes silent due to a verify error
  - Voiceprint loaded once and cached in memory (no repeated disk reads)

Environment variables (read once at import time):
  VANI_SPEAKER_VERIFY    "1" to enable, "0" to disable (default: "0")
  VANI_SPEAKER_THRESHOLD cosine similarity threshold (default: "0.78")
  VANI_SPEAKER_GATE      "false"/"0"/"no"/"off" to bypass gate in dev (default: "true")
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

log = logging.getLogger("vani.wake_verifier")

# ── Feature flags — read ONCE at import time ──────────────────────────────────
# All flags are read at import.  Restart Vani to pick up .env changes.

import os as _os

# Master switch: VANI_SPEAKER_VERIFY=1 enables speaker verification.
# Master switch: VANI_SPEAKER_VERIFY=1 enables speaker verification.
VERIFY_ENABLED: bool = _os.getenv("VANI_SPEAKER_VERIFY", "0") == "1"

# Dev bypass: VANI_SPEAKER_GATE=false skips verification even when VERIFY=1.
# Useful during development so you don't need to flip VERIFY off and on.
# Accepted falsy values: "false", "0", "no", "off"  (case-insensitive)
_gate_raw = _os.getenv("VANI_SPEAKER_GATE", "true").strip().lower()
GATE_ENABLED: bool = _gate_raw not in ("false", "0", "no", "off")

# Cosine similarity threshold.  Raised to 0.82 for strict speaker verification.
# Lower to 0.70 in noisy conditions or if too many false rejections.
THRESHOLD: float = float(_os.getenv("VANI_SPEAKER_THRESHOLD", "0.82"))


_last_env_mtime = 0.0
_last_verify_enabled = _os.getenv("VANI_SPEAKER_VERIFY", "0") == "1"

def is_verify_enabled() -> bool:
    """Check if speaker verification is active, reloading .env to pick up live updates if it changed."""
    global _last_env_mtime, _last_verify_enabled
    try:
        from vani.config import PROJECT_ROOT
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            mtime = env_path.stat().st_mtime
            if mtime != _last_env_mtime:
                import dotenv
                dotenv.load_dotenv(str(env_path), override=True)
                _last_env_mtime = mtime
                _last_verify_enabled = _os.getenv("VANI_SPEAKER_VERIFY", "0") == "1"
    except Exception:
        pass
    return _last_verify_enabled


def is_gate_enabled() -> bool:
    """Check if speaker verification gate is active."""
    gate_raw = _os.getenv("VANI_SPEAKER_GATE", "true").strip().lower()
    return gate_raw not in ("false", "0", "no", "off")


def get_threshold() -> float:
    """Get the current cosine similarity threshold."""
    try:
        return float(_os.getenv("VANI_SPEAKER_THRESHOLD", "0.82"))
    except Exception:
        return 0.82


# ── Startup log ───────────────────────────────────────────────────────────────
if VERIFY_ENABLED and GATE_ENABLED:
    log.info(
        "wake_verifier: speaker gate ACTIVE (threshold=%.2f)",
        THRESHOLD,
    )
elif VERIFY_ENABLED and not GATE_ENABLED:
    log.warning(
        "wake_verifier: VANI_SPEAKER_GATE=false — verification BYPASSED (dev mode)",
    )
else:
    log.debug("wake_verifier: speaker verification disabled (VANI_SPEAKER_VERIFY=0)")


# ── Voiceprint cache ──────────────────────────────────────────────────────────
# Loaded from disk on first verify call, then held in memory for the session.
# Automatically reloads if the voiceprint file modification time changes.
# A lock is used because the wake listener callback and async paths may race
# on the first call.

_voiceprint_cache: Optional[np.ndarray] = None
_voiceprint_loaded: bool = False        # True after first load attempt (even if None)
_voiceprint_lock = threading.Lock()
_last_mtime: float = 0.0


def _get_voiceprint() -> Optional[np.ndarray]:
    """
    Return the cached voiceprint, loading from disk on first call or when mtime changes.

    Returns None if:
      - Not enrolled (file doesn't exist)
      - File is corrupt / wrong shape
      - Any disk read error

    Thread-safe. Never raises.
    """
    global _voiceprint_cache, _voiceprint_loaded, _last_mtime

    from vani.services.voice_enrollment import VOICEPRINT_PATH
    if not VOICEPRINT_PATH.exists():
        with _voiceprint_lock:
            _voiceprint_cache = None
            _voiceprint_loaded = True
            _last_mtime = 0.0
        return None

    try:
        mtime = VOICEPRINT_PATH.stat().st_mtime
    except Exception:
        mtime = 0.0

    if not _voiceprint_loaded or mtime != _last_mtime:
        with _voiceprint_lock:
            # Double-checked locking
            try:
                mtime = VOICEPRINT_PATH.stat().st_mtime
            except Exception:
                mtime = 0.0

            if not _voiceprint_loaded or mtime != _last_mtime:
                try:
                    from vani.services.voice_enrollment import load_voiceprint
                    _voiceprint_cache = load_voiceprint()
                    _last_mtime = mtime
                    if _voiceprint_cache is not None:
                        log.info(
                            "wake_verifier: voiceprint loaded from disk (shape=%s, mtime=%.1f)",
                            _voiceprint_cache.shape,
                            _last_mtime,
                        )
                    else:
                        log.info("wake_verifier: no enrolled voiceprint found — verify will fail open")
                except Exception as exc:
                    log.warning("wake_verifier: could not load voiceprint: %s — failing open", exc)
                    _voiceprint_cache = None
                    _last_mtime = 0.0
                finally:
                    _voiceprint_loaded = True

    return _voiceprint_cache


def reload_voiceprint() -> None:
    """
    Force reload of voiceprint from disk on next verify call.

    Call this after enrollment or deletion so the new state is picked up
    immediately without restarting the wake listener.

    Called by router._handle_voice_enroll() and router._handle_voice_delete().
    """
    global _voiceprint_cache, _voiceprint_loaded, _last_mtime
    with _voiceprint_lock:
        _voiceprint_cache = None
        _voiceprint_loaded = False
        _last_mtime = 0.0
    log.info("wake_verifier: voiceprint cache cleared — will reload on next verify")


# ── Sync verification (for NSSpeechRecognizer delegate) ──────────────────────

def verify_wake_audio_sync(wav: np.ndarray, sr: int) -> bool:
    """
    Synchronously verify whether `wav` matches the enrolled voiceprint.

    Runs on the calling thread (~70ms on CPU).
    Safe to call from NSSpeechRecognizer delegate or any non-async context.

    Returns:
        True  — verified as owner, OR feature/gate disabled, OR not enrolled yet,
                OR any unexpected failure (fail-open design)
        False — verified as NOT the owner (similarity below threshold)

    Never raises.
    """
    # Fast path 1 — feature disabled entirely (dynamic env check)
    if not is_verify_enabled():
        return True

    # Fast path 2 — dev bypass (VANI_SPEAKER_GATE=false) (dynamic env check)
    if not is_gate_enabled():
        log.debug("wake_verifier: gate disabled via VANI_SPEAKER_GATE, bypassing verification")
        return True

    try:
        voiceprint = _get_voiceprint()

        # Not enrolled → fail open so first-time setup is never blocked
        if voiceprint is None:
            log.debug("wake_verifier: sync — not enrolled, failing open")
            return True

        from vani.audio.speaker_encoder import get_encoder
        threshold = get_threshold()
        result = get_encoder().verify(wav, sr, voiceprint, threshold)

        if result:
            log.debug("wake_verifier: accepted (similarity >= %.2f)", threshold)
        else:
            log.info(
                "wake_verifier: rejected — speaker not recognised (similarity < %.2f)",
                threshold,
            )
        return result

    except Exception as exc:
        log.warning("wake_verifier: sync verify() unexpected error: %s — failing open", exc)
        return True


# ── Async verification (for asyncio contexts) ─────────────────────────────────

async def verify_wake_audio_async(wav: np.ndarray, sr: int) -> bool:
    """
    Asynchronously verify whether `wav` matches the enrolled voiceprint.

    Runs verification in a thread pool executor so it doesn't block the
    event loop. The ~70ms CPU work happens in a worker thread while
    the ASR pipeline can warm up concurrently — zero perceived latency.

    Returns:
        True  — verified as owner, OR feature/gate disabled, OR not enrolled yet,
                OR any unexpected failure (fail-open design)
        False — verified as NOT the owner (similarity below threshold)

    Never raises.
    """
    # Fast path 1 — feature disabled (before any await)
    if not is_verify_enabled():
        return True

    # Fast path 2 — dev bypass (before any await)
    if not is_gate_enabled():
        log.debug("wake_verifier: gate disabled via VANI_SPEAKER_GATE, bypassing verification")
        return True

    try:
        import asyncio
        loop = asyncio.get_running_loop()

        # Run the blocking ~70ms CPU work off the event loop.
        # verify_wake_audio_sync handles all remaining logic (cache, threshold, fail-open).
        result = await loop.run_in_executor(
            None,                                # default ThreadPoolExecutor
            verify_wake_audio_sync, wav, sr,
        )
        return result

    except Exception as exc:
        log.warning("wake_verifier: async verify() unexpected error: %s — failing open", exc)
        return True