"""
tests/test_speaker_verification.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Speaker verification test suite.

All tests that require Resemblyzer use pytest.importorskip so they are
gracefully skipped in CI environments where resemblyzer is not installed.
Tests that do NOT need Resemblyzer (feature-flag path, numpy-only ops,
enrollment file I/O) run unconditionally.
"""

import importlib
import os
import sys

import numpy as np
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. Feature flag disabled — must return True without loading Resemblyzer
# ─────────────────────────────────────────────────────────────────────────────

def test_verify_disabled_returns_true_without_loading_resemblyzer(monkeypatch):
    """When VANI_SPEAKER_VERIFY=0, verify returns True and Resemblyzer is never imported."""
    monkeypatch.setenv("VANI_SPEAKER_VERIFY", "0")

    # Force module re-import so VERIFY_ENABLED is re-read with our patched env var.
    # Remove cached module if already loaded so the flag is re-evaluated.
    for mod_name in list(sys.modules.keys()):
        if "wake_verifier" in mod_name:
            del sys.modules[mod_name]

    from vani.audio.wake_verifier import VERIFY_ENABLED, verify_wake_audio_sync

    assert VERIFY_ENABLED is False, "VERIFY_ENABLED should be False when env=0"

    dummy = np.zeros(16000, dtype=np.float32)
    result = verify_wake_audio_sync(dummy, 16000)
    assert result is True, "verify_wake_audio_sync must return True when disabled"

    assert "resemblyzer" not in sys.modules, (
        "Resemblyzer must NOT be imported when VANI_SPEAKER_VERIFY=0"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Pure numpy cosine similarity — no Resemblyzer needed
# ─────────────────────────────────────────────────────────────────────────────

def test_similarity_pure_numpy():
    """SpeakerEncoder.similarity() is pure numpy — works without Resemblyzer."""
    from vani.audio.speaker_encoder import SpeakerEncoder

    enc = SpeakerEncoder()  # does NOT load model

    a = np.ones(256, dtype=np.float64)
    a = a / np.linalg.norm(a)

    # Identical vectors → similarity ≈ 1.0
    assert abs(enc.similarity(a, a) - 1.0) < 1e-5, "similarity(a, a) should be ~1.0"

    # Opposite vectors → similarity ≈ -1.0
    assert abs(enc.similarity(a, -a) - (-1.0)) < 1e-5, "similarity(a, -a) should be ~-1.0"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Enrollment status — not enrolled (empty tmp dir)
# ─────────────────────────────────────────────────────────────────────────────

def test_enrollment_status_not_enrolled(tmp_path, monkeypatch):
    """get_enrollment_status() returns enrolled=False when voiceprint file is absent."""
    import vani.services.voice_enrollment as ve

    monkeypatch.setattr(ve, "VOICEPRINT_PATH", tmp_path / "voiceprint.npy")

    status = ve.get_enrollment_status()
    assert status["enrolled"] is False
    assert status["path"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Save / load / delete voiceprint cycle
# ─────────────────────────────────────────────────────────────────────────────

def test_save_and_load_voiceprint(tmp_path, monkeypatch):
    """Full save→load→delete cycle with a fake 256-dim embedding."""
    import vani.services.voice_enrollment as ve

    monkeypatch.setattr(ve, "VOICEPRINT_PATH", tmp_path / "voiceprint.npy")

    embedding = np.random.randn(256).astype(np.float32)

    assert ve.save_voiceprint(embedding) is True
    assert ve.is_enrolled() is True

    loaded = ve.load_voiceprint()
    assert loaded is not None
    assert np.allclose(loaded, embedding), "Loaded embedding must match saved embedding"

    assert ve.delete_voiceprint() is True
    assert ve.is_enrolled() is False


# ─────────────────────────────────────────────────────────────────────────────
# 5. enroll_from_audio — audio too short
# ─────────────────────────────────────────────────────────────────────────────

def test_enroll_from_audio_too_short(tmp_path, monkeypatch):
    """enroll_from_audio() returns too_short when audio < 4 seconds."""
    import vani.services.voice_enrollment as ve

    monkeypatch.setattr(ve, "VOICEPRINT_PATH", tmp_path / "voiceprint.npy")

    # 0.5 seconds at 16kHz = 8000 samples
    wav = np.zeros(8000, dtype=np.float32)
    result = ve.enroll_from_audio([wav], sr=16000)

    assert result["ok"] is False
    assert result["reason"] == "too_short"
    assert result["seconds"] < ve.ENROLLMENT_MIN_SECONDS


# ─────────────────────────────────────────────────────────────────────────────
# 6. enroll_from_audio with Resemblyzer (skipped if not installed)
# ─────────────────────────────────────────────────────────────────────────────

def test_enroll_from_audio_requires_resemblyzer(tmp_path, monkeypatch):
    """Full enrollment succeeds when Resemblyzer is available."""
    pytest.importorskip("resemblyzer")

    import vani.services.voice_enrollment as ve

    monkeypatch.setattr(ve, "VOICEPRINT_PATH", tmp_path / "voiceprint.npy")

    # 5 seconds of random audio at 16kHz
    wav = np.random.randn(80000).astype(np.float32) * 0.1
    result = ve.enroll_from_audio([wav], sr=16000)

    assert result["ok"] is True, f"Enrollment should succeed, got: {result}"
    assert (tmp_path / "voiceprint.npy").exists(), "voiceprint.npy must be written to disk"


# ─────────────────────────────────────────────────────────────────────────────
# 7. verify_wake_audio_sync — fail open when not enrolled
# ─────────────────────────────────────────────────────────────────────────────

def test_verify_fail_open_when_not_enrolled(tmp_path, monkeypatch):
    """When VANI_SPEAKER_VERIFY=1 but no voiceprint exists, verify returns True (fail-open)."""
    monkeypatch.setenv("VANI_SPEAKER_VERIFY", "1")

    # Reload wake_verifier so VERIFY_ENABLED re-reads the env var
    for mod_name in list(sys.modules.keys()):
        if "wake_verifier" in mod_name:
            del sys.modules[mod_name]

    import vani.services.voice_enrollment as ve
    monkeypatch.setattr(ve, "VOICEPRINT_PATH", tmp_path / "voiceprint.npy")

    # Also patch the cache in wake_verifier after reimport
    from vani.audio import wake_verifier as wv
    # Force cache reset so it reads from our patched path
    wv._voiceprint_cache = None
    wv._voiceprint_loaded = False

    dummy = np.zeros(16000, dtype=np.float32)
    result = wv.verify_wake_audio_sync(dummy, 16000)

    assert result is True, "Must return True (fail-open) when not enrolled"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Wake command service still works after changes
# ─────────────────────────────────────────────────────────────────────────────

def test_wake_command_still_works_after_changes():
    """All original wake phrases still recognized — no regression from our changes."""
    from vani.services.wake import is_wake_command

    wake_phrases = [
        "hey vani",
        "hey vaani",
        "ok vani",
        "okay vani",
        "wake up vani",
        "utho vani",
        "vani sun",
        "activate vani",
        "hello vani",
    ]

    for phrase in wake_phrases:
        assert is_wake_command(phrase), f"Wake phrase not recognized: '{phrase}'"
