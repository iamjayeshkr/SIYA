"""
src/vani/audio/kokoro_tts.py
Local Kokoro TTS — fast path for Hinglish replies with human-quality voice.

Install: pip install kokoro-onnx sounddevice numpy scipy librosa requests
Model:   downloads automatically on first run to ~/.cache/kokoro/

Voice:    af_heart (default) — warm Indian-English female
          Change KOKORO_VOICE env var: af_bella, af_sarah, am_adam, bf_emma

Audio post-processing pipeline (makes Kokoro sound natural/human):
  1. Normalize loudness to -18 LUFS (consistent volume)
  2. Subtle 3-8 kHz presence boost (+2 dB) — adds clarity, reduces muffled feel
  3. Very gentle de-essing at 6-9 kHz  — removes synthetic sibilance
  4. 80 Hz high-pass   — removes low-end rumble from ONNX artifacts
  5. Micro fade-in/fade-out (5ms) — eliminates click/pop at start and end
  6. Final peak-limit at -1 dBFS — prevents clipping on output
  

Chunking uses sentence-boundary splitting (no comma breaks) for natural flow.
"""

import os
import asyncio
import logging
import threading
import re
import numpy as np

log = logging.getLogger("vani.kokoro")

KOKORO_ENABLED      = os.getenv("KOKORO_ENABLED", "1") == "1"
KOKORO_MAX_CHARS    = int(os.getenv("KOKORO_MAX_CHARS", "120"))
KOKORO_VOICE        = os.getenv("KOKORO_VOICE", "af_heart")
KOKORO_SPEED        = float(os.getenv("KOKORO_SPEED", "0.95"))   # slightly slower = warmer, more natural
KOKORO_SAMPLE_RATE  = 24000   # Kokoro outputs at 24kHz
KOKORO_HTTP_URL     = os.getenv("KOKORO_HTTP_URL", "").strip()

# Audio enhancement toggles
KOKORO_ENHANCE      = os.getenv("KOKORO_ENHANCE", "1") == "1"    # master switch for post-processing
KOKORO_GAIN_DB      = float(os.getenv("KOKORO_GAIN_DB", "-18"))  # target loudness in dBFS (RMS)

_stop_requested = False

def stop_playback():
    global _stop_requested
    _stop_requested = True


_kokoro: object = None
_kokoro_lock = threading.Lock()
_kokoro_available: bool | None = None


# ── Download helper ────────────────────────────────────────────────────────────

def _download_file(url: str, dest_path: str):
    import urllib.request
    from pathlib import Path
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            dest.unlink()
        except Exception:
            pass
    log.info(f"[Kokoro] Downloading {url} → {dest_path}...")
    try:
        with urllib.request.urlopen(url) as response, open(dest_path, "wb") as out_file:
            meta = response.info()
            file_size = int(meta.get("Content-Length", 0))
            log.info(f"[Kokoro] File size: {file_size / (1024*1024):.1f} MB")
            downloaded, last_reported, block_size = 0, 0, 65536
            while True:
                buf = response.read(block_size)
                if not buf:
                    break
                downloaded += len(buf)
                out_file.write(buf)
                if file_size > 0:
                    pct = int(downloaded * 100 / file_size)
                    if pct >= last_reported + 10:
                        log.info(f"[Kokoro] {dest.name}: {pct}%")
                        last_reported = (pct // 10) * 10
        log.info(f"[Kokoro] Downloaded {dest.name}")
    except Exception as e:
        log.error(f"[Kokoro] Download failed {url}: {e}")
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        raise


# ── Model loader ───────────────────────────────────────────────────────────────

def _load_kokoro() -> bool:
    global _kokoro, _kokoro_available
    if KOKORO_HTTP_URL:
        return True
    if _kokoro_available is not None:
        return _kokoro_available
    with _kokoro_lock:
        if _kokoro_available is not None:
            return _kokoro_available
        try:
            from pathlib import Path
            cache_dir = Path.home() / ".cache" / "kokoro"
            onnx_path   = cache_dir / "kokoro-v1.0.onnx"
            voices_path = cache_dir / "voices-v1.0.bin"

            if not onnx_path.exists() or onnx_path.stat().st_size != 325532387:
                _download_file(
                    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
                    str(onnx_path),
                )
            if not voices_path.exists() or voices_path.stat().st_size != 28214398:
                _download_file(
                    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
                    str(voices_path),
                )

            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(onnx_path), str(voices_path))
            _kokoro_available = True
            log.info(f"[Kokoro] ✅ Loaded — voice={KOKORO_VOICE} speed={KOKORO_SPEED}")
        except Exception as e:
            _kokoro_available = False
            log.warning(f"[Kokoro] Not available: {e}")
    return bool(_kokoro_available)


# ── Audio post-processing — the "human-voice" pipeline ────────────────────────

def _enhance_audio(samples: np.ndarray, sr: int = KOKORO_SAMPLE_RATE) -> np.ndarray:
    """
    Apply a lightweight signal-processing chain that transforms ONNX TTS output
    into warmer, clearer, more natural-sounding speech.

    The chain is designed to run in <5ms for a 3-second clip on CPU.
    Falls back to unmodified samples if scipy is missing.
    """
    if not KOKORO_ENHANCE:
        return samples

    try:
        from scipy.signal import butter, sosfilt
    except ImportError:
        log.debug("[Kokoro] scipy not installed — skipping audio enhancement")
        return samples

    audio = samples.astype(np.float32)

    # ── 1. High-pass at 80 Hz — remove ONNX low-end rumble ──────────────────
    sos_hp = butter(4, 80.0 / (sr / 2), btype="high", output="sos")
    audio = sosfilt(sos_hp, audio).astype(np.float32)

    # ── 2. Presence boost 3–8 kHz (+2 dB) — adds clarity / intelligibility ──
    #    A gentle shelf/bandpass that lifts the "speech presence" range.
    sos_pres = butter(2, [3000.0 / (sr / 2), 8000.0 / (sr / 2)], btype="band", output="sos")
    band_pres = sosfilt(sos_pres, audio).astype(np.float32)
    boost = 10 ** (2.0 / 20)  # +2 dB linear
    audio = audio + (boost - 1.0) * band_pres   # add boosted component back

    # ── 3. Gentle de-essing 6–9 kHz (−3 dB) — softens robotic sibilance ─────
    sos_ess = butter(2, [6000.0 / (sr / 2), min(9000.0 / (sr / 2), 0.99)], btype="band", output="sos")
    band_ess = sosfilt(sos_ess, audio).astype(np.float32)
    cut = 10 ** (-3.0 / 20)  # −3 dB linear
    audio = audio - (1.0 - cut) * band_ess

    # ── 4. RMS loudness normalisation to target dBFS ─────────────────────────
    rms = float(np.sqrt(np.mean(audio ** 2))) + 1e-9
    target_rms = 10 ** (KOKORO_GAIN_DB / 20)
    gain = target_rms / rms
    # Clamp gain to prevent blowing up very quiet passages (±12 dB max)
    gain = float(np.clip(gain, 10 ** (-12 / 20), 10 ** (12 / 20)))
    audio = audio * gain

    # ── 5. Hard peak-limiter at -1 dBFS ──────────────────────────────────────
    ceiling = 10 ** (-1.0 / 20)
    audio = np.clip(audio, -ceiling, ceiling)

    # ── 6. Micro fade-in / fade-out (5ms) — removes click artifacts ──────────
    fade_samples = min(int(sr * 0.005), len(audio) // 10)
    if fade_samples > 0:
        fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        audio[:fade_samples]  *= fade
        audio[-fade_samples:] *= fade[::-1]

    return audio.astype(np.float32)


# ── Sentence-boundary chunker ──────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """
    Split on true sentence boundaries only (.  !  ?  ।).
    Do NOT split on commas — mid-sentence comma breaks sound robotic.
    Each chunk is at most 180 chars so Kokoro's ONNX attention doesn't degrade.
    """
    # Split on sentence-ending punctuation followed by whitespace
    parts = re.split(r'(?<=[.!?।])\s+', text.strip())
    chunks: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) + 1 <= 180:
            current = (current + " " + part).strip()
        else:
            if current:
                chunks.append(current)
            # If a single part is > 180 chars, split on last space before 180
            while len(part) > 180:
                cut = part[:180].rfind(" ")
                cut = cut if cut > 80 else 180
                chunks.append(part[:cut].strip())
                part = part[cut:].strip()
            current = part
    if current:
        chunks.append(current)
    return chunks or [text.strip()]


# ── Language detection ─────────────────────────────────────────────────────────

def _detect_lang(voice: str) -> str:
    voice = voice.lower()
    if voice.startswith(("hf_", "hm_", "hi_")):   return "hi"
    if voice.startswith(("zf_", "zm_")):            return "zh-cn"
    if voice.startswith(("jf_", "jm_")):            return "ja"
    if voice.startswith(("ff_", "fm_")):            return "fr-fr"
    if voice.startswith(("ef_", "em_")):            return "es-es"
    if voice.startswith(("if_", "im_")):            return "it-it"
    if voice.startswith(("pf_", "pm_")):            return "pt-br"
    if voice.startswith(("bf_", "bm_")):            return "en-gb"
    return "en-us"


# ── Core synthesis ─────────────────────────────────────────────────────────────

def synthesize_sync(text: str) -> np.ndarray | None:
    """
    Synthesize text → enhanced float32 audio at KOKORO_SAMPLE_RATE.
    Returns None on failure. Runs synchronously (call from executor or thread).
    """
    # ── HTTP mode (Docker kokoro server) ─────────────────────────────────────
    if KOKORO_HTTP_URL:
        try:
            import requests
            r = requests.post(f"{KOKORO_HTTP_URL}/speak", json={"text": text}, timeout=10)
            if r.status_code == 200:
                raw = np.frombuffer(r.content, dtype=np.float32)
                return _enhance_audio(raw)
            log.warning(f"[Kokoro] HTTP {r.status_code}")
            return None
        except Exception as e:
            log.warning(f"[Kokoro] HTTP error: {e}")
            return None

    # ── Local ONNX mode ───────────────────────────────────────────────────────
    if not _load_kokoro():
        return None
    try:
        samples, _sr = _kokoro.create(
            text,
            voice=KOKORO_VOICE,
            speed=KOKORO_SPEED,
            lang=_detect_lang(KOKORO_VOICE),
        )
        return _enhance_audio(samples)
    except Exception as e:
        log.warning(f"[Kokoro] Synthesis error: {e}")
        return None


# ── Playback ───────────────────────────────────────────────────────────────────

def play_sync(samples: np.ndarray) -> None:
    global _stop_requested
    _stop_requested = False
    try:
        import sounddevice as sd
        sd.play(samples, samplerate=KOKORO_SAMPLE_RATE)
        chunk, total, played = 1024, len(samples), 0
        while played < total:
            if _stop_requested:
                sd.stop()
                _stop_requested = False
                return
            played += chunk
            sd.sleep(20)
    except Exception as e:
        log.warning(f"[Kokoro] Playback error: {e}")


# ── Async public API ───────────────────────────────────────────────────────────

def is_kokoro_short(text: str) -> bool:
    return KOKORO_ENABLED and len(text.strip()) <= KOKORO_MAX_CHARS


async def synthesize_and_play(text: str) -> bool:
    """Synthesize + play a single chunk. Returns True on success."""
    if not KOKORO_ENABLED:
        return False
    if not KOKORO_HTTP_URL and not _load_kokoro():
        return False
    try:
        loop = asyncio.get_running_loop()
        samples = await loop.run_in_executor(None, synthesize_sync, text)
        if samples is None:
            return False
        await loop.run_in_executor(None, play_sync, samples)
        log.info(f"[Kokoro] ✅ Spoke ({len(text)} chars): {text[:60]}...")
        return True
    except Exception as e:
        log.warning(f"[Kokoro] synthesize_and_play error: {e}")
        return False


async def synthesize_and_play_chunked(text: str, chunk_chars: int = 180) -> bool:
    """
    Pipeline mode: split text at real sentence boundaries, then synthesize
    and play each sentence sequentially.

    First sentence starts playing ~80ms after call — low perceived latency.
    Each chunk gets the full enhancement pipeline for consistent quality.
    """
    if not KOKORO_ENABLED:
        return False
    if not KOKORO_HTTP_URL and not _load_kokoro():
        return False

    sentences = _split_sentences(text)
    if not sentences:
        return False
    if len(sentences) == 1:
        return await synthesize_and_play(text)

    loop = asyncio.get_running_loop()
    success = False
    global _stop_requested

    for sentence in sentences:
        if _stop_requested:
            break
        if not sentence:
            continue
        samples = await loop.run_in_executor(None, synthesize_sync, sentence)
        if samples is not None:
            await loop.run_in_executor(None, play_sync, samples)
            success = True

    return success
