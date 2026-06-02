"""
vani/services/voice_enrollment.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Voice enrollment service for Vani.

Manages the owner's voiceprint:
  - Saving / loading / deleting the stored .npy voiceprint file
  - Running the enrollment flow from captured audio chunks
  - Providing enrollment status for the HTTP API

The voiceprint is stored at:
  <PROJECT_ROOT>/conversations/voiceprint.npy

This directory is already created by human_memory.py so no extra setup needed.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from vani.config import PROJECT_ROOT

log = logging.getLogger("vani.voice_enrollment")

# ── Constants ─────────────────────────────────────────────────────────────────

VOICEPRINT_PATH: Path = PROJECT_ROOT / "conversations" / "voiceprint.npy"

# Minimum audio duration required for a reliable voiceprint.
# Resemblyzer needs ~3–4s of clean speech; 4.0s gives a small safety margin.
ENROLLMENT_MIN_SECONDS: float = 4.0

ENROLLMENT_SAMPLE_RATE: int = 16000

# Expected embedding dimension from Resemblyzer VoiceEncoder
_EXPECTED_DIM: int = 256

# Lock for atomic voiceprint file operations
_file_lock = threading.Lock()


# ── Status helpers ────────────────────────────────────────────────────────────

def is_enrolled() -> bool:
    """
    Return True if a valid voiceprint exists on disk.

    Checks:
      - File exists
      - File is a valid numpy array
      - Shape is (256,) — Resemblyzer embedding dimension

    Never raises.
    """
    try:
        if not VOICEPRINT_PATH.exists():
            return False
        vp = np.load(str(VOICEPRINT_PATH))
        return vp.shape == (_EXPECTED_DIM,)
    except Exception:
        return False


def load_voiceprint() -> Optional[np.ndarray]:
    """
    Load the stored voiceprint from disk.

    Returns:
        256-dim float32 numpy array, or None if not enrolled or file is corrupt.

    Never raises.
    """
    try:
        if not VOICEPRINT_PATH.exists():
            return None
        vp = np.load(str(VOICEPRINT_PATH)).astype(np.float32)
        if vp.shape != (_EXPECTED_DIM,):
            log.warning(
                "voice_enrollment: voiceprint has unexpected shape %s (expected (%d,)) — treating as not enrolled",
                vp.shape, _EXPECTED_DIM,
            )
            return None
        return vp
    except Exception as exc:
        log.warning("voice_enrollment: load_voiceprint() failed: %s", exc)
        return None


def get_enrollment_status() -> dict:
    """
    Return current enrollment state as a dict for the HTTP API.

    Returns:
        {
            "enrolled": bool,
            "path": str or None,
            "size_bytes": int or None,
        }
    """
    try:
        enrolled = is_enrolled()
        if enrolled:
            size = VOICEPRINT_PATH.stat().st_size
            return {
                "enrolled": True,
                "path": str(VOICEPRINT_PATH),
                "size_bytes": size,
            }
        return {
            "enrolled": False,
            "path": None,
            "size_bytes": None,
        }
    except Exception as exc:
        log.warning("voice_enrollment: get_enrollment_status() failed: %s", exc)
        return {"enrolled": False, "path": None, "size_bytes": None}


# ── Voiceprint file operations ────────────────────────────────────────────────

def save_voiceprint(embedding: np.ndarray) -> bool:
    """
    Atomically save an embedding to disk as the enrolled voiceprint.

    Uses write-to-BytesIO + write_bytes + os.replace() for atomic writes.
    (np.save auto-appends .npy to filenames, so we serialise to bytes first.)

    Returns True on success, False on failure. Never raises.
    """
    import io
    try:
        with _file_lock:
            VOICEPRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Serialise to bytes first so np.save cannot mangle the tmp filename
            buf = io.BytesIO()
            np.save(buf, embedding.astype(np.float32))
            tmp_path = VOICEPRINT_PATH.with_name("voiceprint.npy.tmp")
            tmp_path.write_bytes(buf.getvalue())
            os.replace(str(tmp_path), str(VOICEPRINT_PATH))
        log.info("voice_enrollment: voiceprint saved → %s", VOICEPRINT_PATH)
        return True
    except Exception as exc:
        log.warning("voice_enrollment: save_voiceprint() failed: %s", exc)
        return False


def delete_voiceprint() -> bool:
    """
    Delete the stored voiceprint from disk.

    Returns True if deleted, False if not found or error. Never raises.
    """
    try:
        with _file_lock:
            if not VOICEPRINT_PATH.exists():
                log.debug("voice_enrollment: delete_voiceprint() — file not found, nothing to delete")
                return False
            VOICEPRINT_PATH.unlink()
        log.info("voice_enrollment: voiceprint deleted")
        return True
    except Exception as exc:
        log.warning("voice_enrollment: delete_voiceprint() failed: %s", exc)
        return False


# ── Enrollment flow ───────────────────────────────────────────────────────────

def enroll_from_audio(wav_chunks: list, sr: int) -> dict:
    """
    Run the enrollment flow from a list of captured audio chunks.

    Args:
        wav_chunks: List of float32 numpy arrays (mic capture chunks).
        sr:         Sample rate of the audio (should be 16000).

    Returns one of:
        {"ok": False, "reason": "too_short", "seconds": float}
            — not enough audio captured
        {"ok": False, "reason": "embed_failed"}
            — Resemblyzer failed to extract embedding
        {"ok": False, "reason": "save_failed"}
            — file write failed
        {"ok": True, "seconds": float, "path": str}
            — enrollment succeeded

    Never raises.
    """
    try:
        # ── 1. Concatenate chunks ─────────────────────────────────────────────
        if not wav_chunks:
            return {"ok": False, "reason": "too_short", "seconds": 0.0}

        wav = np.concatenate([np.asarray(c, dtype=np.float32) for c in wav_chunks])
        actual_seconds = len(wav) / float(sr)

        log.debug(
            "voice_enrollment: enroll_from_audio() received %.2fs of audio (%d samples at %dHz)",
            actual_seconds, len(wav), sr,
        )

        # ── 2. Duration check ─────────────────────────────────────────────────
        if actual_seconds < ENROLLMENT_MIN_SECONDS:
            log.warning(
                "voice_enrollment: audio too short (%.2fs < %.1fs required)",
                actual_seconds, ENROLLMENT_MIN_SECONDS,
            )
            return {
                "ok": False,
                "reason": "too_short",
                "seconds": round(actual_seconds, 2),
            }

        # ── 3. Extract embedding (pitch-robust average) ───────────────────
        from vani.audio.speaker_encoder import get_encoder
        encoder = get_encoder()
        # embed_averaged() creates embeddings at 5 pitch levels (±4 semitones)
        # and averages them.  This makes the stored voiceprint robust to your
        # natural pitch variation — Vani won't reject you when you speak
        # higher/lower than you did during enrollment.
        embedding = encoder.embed_averaged(wav, sr, n_augments=5)

        if embedding is None:
            log.warning("voice_enrollment: embed() returned None — enrollment failed")
            return {"ok": False, "reason": "embed_failed"}

        # ── 4. Save voiceprint ────────────────────────────────────────────────
        if not save_voiceprint(embedding):
            return {"ok": False, "reason": "save_failed"}

        log.info(
            "voice_enrollment: enrollment complete — %.2fs audio, voiceprint saved",
            actual_seconds,
        )
        return {
            "ok": True,
            "seconds": round(actual_seconds, 2),
            "path": str(VOICEPRINT_PATH),
        }

    except Exception as exc:
        log.warning("voice_enrollment: enroll_from_audio() unexpected error: %s", exc)
        return {"ok": False, "reason": str(exc)}
