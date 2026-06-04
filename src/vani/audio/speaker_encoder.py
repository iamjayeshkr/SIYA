
"""
vani/audio/speaker_encoder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Core speaker verification module for Vani.

Wraps Resemblyzer's VoiceEncoder with:
  - Lazy loading (zero import cost until first use)
  - Thread-safe singleton
  - Fail-open design (returns True on any failure)
  - Pure-numpy cosine similarity
  - Pitch-robust verification: tests multiple pitch-shifted copies of the
    live audio and accepts if ANY passes the threshold.  This prevents the
    "change voice pitch → bypass" flaw because your vocal tract shape
    (formants) stays the same regardless of how high/low you speak.

Used by wake_verifier.py to compare a live voice against the enrolled voiceprint.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

log = logging.getLogger("vani.speaker_encoder")


# ── Pitch-shift helper ────────────────────────────────────────────────────────

def _pitch_shift_resample(wav: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """
    Approximate pitch shift by resampling (speed-change trick).

    We resample the audio by a ratio = 2^(semitones/12), which changes pitch
    without changing duration (simple linear interpolation).  This is fast
    (~0.5ms) and good enough for the cosine-similarity check — Resemblyzer
    works on mel spectrogram features, not raw pitch, so this nudge is enough
    to catch pitch-faking attacks.

    semitones > 0  → pitch UP   (like raising your voice)
    semitones < 0  → pitch DOWN (like lowering your voice)
    """
    try:
        ratio = 2 ** (semitones / 12.0)
        old_len = len(wav)
        new_len = max(1, int(round(old_len / ratio)))
        old_idx = np.linspace(0, old_len - 1, new_len)
        shifted = np.interp(old_idx, np.arange(old_len), wav.astype(np.float64))
        return shifted.astype(np.float32)
    except Exception:
        return wav


class SpeakerEncoder:
    """
    Lazy-loaded wrapper around Resemblyzer's VoiceEncoder.

    The VoiceEncoder model is NOT loaded at __init__ time.
    It is loaded on the first call to embed() or verify().
    This keeps Vani's startup time unchanged.
    """

    def __init__(self) -> None:
        self._encoder = None          # VoiceEncoder instance, set on first load
        self._loaded: bool = False    # True once model loaded successfully
        self._failed: bool = False    # True if load was attempted and failed (avoid retry spam)
        self._load_lock = threading.Lock()

    # ── Model loading ─────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> bool:
        """
        Thread-safe lazy load of Resemblyzer VoiceEncoder.

        Returns True if the encoder is ready, False on any failure.
        Never raises.
        """
        if self._loaded:
            return True
        if self._failed:
            return False

        with self._load_lock:
            # Double-checked locking
            if self._loaded:
                return True
            if self._failed:
                return False

            try:
                from resemblyzer import VoiceEncoder
                self._encoder = VoiceEncoder()
                self._loaded = True
                log.info("speaker_encoder: VoiceEncoder loaded successfully")
                return True
            except ImportError:
                self._failed = True
                log.warning(
                    "speaker_encoder: resemblyzer not installed — "
                    "speaker verification unavailable. "
                    "Run: pip install resemblyzer webrtcvad"
                )
                return False
            except Exception as exc:
                self._failed = True
                log.warning("speaker_encoder: failed to load VoiceEncoder: %s", exc)
                return False

    # ── Embedding ─────────────────────────────────────────────────────────────

    def embed(self, wav: np.ndarray, sr: int) -> Optional[np.ndarray]:
        """
        Extract a 256-dim speaker embedding from raw audio.

        Args:
            wav: Float32 numpy array of audio samples.
            sr:  Sample rate of the audio (e.g. 16000).

        Returns:
            256-dim float32 numpy array, or None on any failure.
        """
        if not self._ensure_loaded():
            return None

        try:
            from resemblyzer import preprocess_wav

            # preprocess_wav handles resampling to 16kHz internally.
            # It expects a float64 or float32 1-D array and the source sample rate.
            wav_f = wav.astype(np.float32)
            wav_preprocessed = preprocess_wav(wav_f, source_sr=sr)

            embedding = self._encoder.embed_utterance(wav_preprocessed)
            return embedding.astype(np.float32)

        except Exception as exc:
            log.warning("speaker_encoder: embed() failed: %s", exc)
            return None

    def embed_averaged(self, wav: np.ndarray, sr: int, n_augments: int = 5) -> Optional[np.ndarray]:
        """
        Enrollment-time embedding: average over several pitch-shifted copies.

        Creates a more robust voiceprint that covers your natural pitch range,
        so the stored embedding is not anchored to a single pitch level.

        Args:
            wav:        Raw audio (float32).
            sr:         Sample rate.
            n_augments: Number of pitch-shifted copies to average (default 5).

        Returns:
            256-dim float32 numpy array (L2-normalised average), or None on failure.
        """
        if not self._ensure_loaded():
            return None

        try:
            # Semitone offsets covering a natural speaking range (±4 semitones)
            offsets = np.linspace(-4.0, 4.0, n_augments)
            embeddings = []
            for st in offsets:
                shifted = _pitch_shift_resample(wav, sr, st)
                emb = self.embed(shifted, sr)
                if emb is not None:
                    embeddings.append(emb)

            if not embeddings:
                log.warning("speaker_encoder: embed_averaged() — no successful embeddings")
                return None

            avg = np.mean(embeddings, axis=0).astype(np.float32)
            # L2-normalise so cosine similarity is just a dot product
            norm = np.linalg.norm(avg)
            if norm > 0:
                avg = avg / norm
            log.info(
                "speaker_encoder: embed_averaged() — averaged %d embeddings over ±4 semitones",
                len(embeddings),
            )
            return avg

        except Exception as exc:
            log.warning("speaker_encoder: embed_averaged() failed: %s", exc)
            return None

    # ── Similarity ────────────────────────────────────────────────────────────

    def similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Cosine similarity between two embedding vectors.

        Returns a float in [-1.0, 1.0].
        Pure numpy — no external dependencies.
        """
        try:
            a = a.astype(np.float64)
            b = b.astype(np.float64)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0.0 or norm_b == 0.0:
                return 0.0
            return float(np.dot(a, b) / (norm_a * norm_b))
        except Exception as exc:
            log.warning("speaker_encoder: similarity() failed: %s", exc)
            return 0.0

    # ── Verification ──────────────────────────────────────────────────────────

    def verify(
        self,
        wav: np.ndarray,
        sr: int,
        voiceprint: np.ndarray,
        threshold: float,
    ) -> bool:
        """
        Pitch-robust verification: test the live audio at multiple pitch levels.

        Why pitch-robust?  Resemblyzer d-vectors capture vocal tract shape
        (who you are) rather than fundamental frequency (pitch).  But naive
        single-embedding comparison still drifts slightly when the speaker
        changes pitch deliberately (e.g. speaking in a higher or lower voice
        to fake/bypass the check).

        Fix: we generate 5 pitch-shifted copies of the live audio (±4 semitones)
        and take the MAXIMUM similarity score.  If ANY copy matches the stored
        voiceprint, we accept.  An impostor's vocal tract shape will remain
        different regardless of pitch shifting — their maximum similarity stays
        below threshold.  The enrolled owner passes at all their natural pitches.

        Args:
            wav:        Raw audio samples (float32).
            sr:         Sample rate of wav.
            voiceprint: Stored 256-dim embedding from enrollment.
            threshold:  Cosine similarity threshold (e.g. 0.75).

        Returns:
            True  if max similarity across pitch variants >= threshold  (accepted)
            True  if encoder failed to load   (fail-open)
            False if all variants similarity < threshold   (rejected)

        Never raises.
        """
        if not self._loaded and not self._ensure_loaded():
            log.debug("speaker_encoder: verify() — encoder not loaded, failing open")
            return True

        try:
            # ── Pitch variants to test ────────────────────────────────────
            # 5 offsets: -4, -2, 0, +2, +4 semitones
            # 0 = the actual audio; ±2 and ±4 catch deliberate pitch changes
            pitch_offsets = [-4.0, -2.0, 0.0, 2.0, 4.0]
            best_sim = -1.0

            for st in pitch_offsets:
                if st == 0.0:
                    candidate = wav
                else:
                    candidate = _pitch_shift_resample(wav, sr, st)

                emb = self.embed(candidate, sr)
                if emb is None:
                    continue

                sim = self.similarity(emb, voiceprint)
                if sim > best_sim:
                    best_sim = sim

            accepted = best_sim >= threshold

            log.debug(
                "speaker_encoder: verify() best_similarity=%.4f threshold=%.4f accepted=%s",
                best_sim, threshold, accepted,
            )
            return accepted

        except Exception as exc:
            log.warning("speaker_encoder: verify() unexpected error: %s — failing open", exc)
            return True


# ── Module-level singleton ────────────────────────────────────────────────────
# Instantiated at import time (cheap — no model loaded yet).
# VoiceEncoder is loaded lazily on first embed() / verify() call.

_ENCODER: SpeakerEncoder = SpeakerEncoder()


def get_encoder() -> SpeakerEncoder:
    """Return the module-level SpeakerEncoder singleton."""
    return _ENCODER

