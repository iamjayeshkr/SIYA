"""
src/vani/audio/kokoro_tts.py
Local Kokoro TTS — fast path for short Hinglish replies.

Install: pip install kokoro-onnx sounddevice numpy requests
Model:   downloads automatically on first run to ~/.cache/kokoro/

Voice:   af_heart (default) — warm Indian-English female
         Change KOKORO_VOICE env var to try: af_bella, af_sarah, am_adam

Routing: Used by worker.say_to_user() for replies ≤ KOKORO_MAX_CHARS chars.
         Gemini Realtime is the fallback for longer text.
"""

import os
import asyncio
import logging
import threading
import numpy as np

log = logging.getLogger("vani.kokoro")

KOKORO_ENABLED   = os.getenv("KOKORO_ENABLED", "1") == "1"
KOKORO_MAX_CHARS = int(os.getenv("KOKORO_MAX_CHARS", "120"))   # unused — Kokoro now handles all lengths
KOKORO_VOICE     = os.getenv("KOKORO_VOICE", "af_heart")
KOKORO_SPEED     = float(os.getenv("KOKORO_SPEED", "1.1"))   # slightly faster = more natural
KOKORO_SAMPLE_RATE = 24000   # Kokoro outputs at 24kHz
KOKORO_HTTP_URL  = os.getenv("KOKORO_HTTP_URL", "").strip()

_stop_requested = False

def stop_playback():
    global _stop_requested
    _stop_requested = True


_kokoro: object = None          # KokoroTTS instance (lazy init)
_kokoro_lock = threading.Lock()
_kokoro_available: bool | None = None   # None=not tried, True/False after first attempt


def _download_file(url: str, dest_path: str):
    """Download a file with logging."""
    import urllib.request
    from pathlib import Path
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            dest.unlink()
        except Exception:
            pass
    log.info(f"[Kokoro] Downloading {url} to {dest_path}...")
    try:
        # Use urllib to download chunked
        with urllib.request.urlopen(url) as response, open(dest_path, 'wb') as out_file:
            meta = response.info()
            file_size = int(meta.get("Content-Length", 0))
            log.info(f"[Kokoro] Downloading {dest.name} ({file_size / (1024*1024):.1f} MB)...")
            
            downloaded = 0
            block_size = 65536
            last_reported = 0
            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                downloaded += len(buffer)
                out_file.write(buffer)
                
                # Log progress every 10%
                if file_size > 0:
                    percent = int(downloaded * 100 / file_size)
                    if percent >= last_reported + 10:
                        log.info(f"[Kokoro] Download progress for {dest.name}: {percent}%")
                        last_reported = (percent // 10) * 10
        log.info(f"[Kokoro] Successfully downloaded {dest.name}")
    except Exception as e:
        log.error(f"[Kokoro] Failed to download {url}: {e}")
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        raise e


def _load_kokoro() -> bool:
    """Lazy-load Kokoro. Returns True if available. Downloads files if missing."""
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
            onnx_path = cache_dir / "kokoro-v1.0.onnx"
            voices_path = cache_dir / "voices-v1.0.bin"

            # Check and download ONNX model file (expected size = 325532387 bytes)
            if not onnx_path.exists() or onnx_path.stat().st_size != 325532387:
                url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
                _download_file(url, str(onnx_path))

            # Check and download voices file (expected size = 28214398 bytes)
            if not voices_path.exists() or voices_path.stat().st_size != 28214398:
                url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
                _download_file(url, str(voices_path))

            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(onnx_path), str(voices_path))
            _kokoro_available = True
            log.info(f"[Kokoro] ✅ Loaded — voice={KOKORO_VOICE} speed={KOKORO_SPEED}")
        except Exception as e:
            _kokoro_available = False
            log.warning(f"[Kokoro] Not available (failed to load/download): {e}")
    return bool(_kokoro_available)


def is_kokoro_short(text: str) -> bool:
    """Return True if text is short enough for Kokoro fast path."""
    return KOKORO_ENABLED and len(text.strip()) <= KOKORO_MAX_CHARS


def synthesize_sync(text: str) -> np.ndarray | None:
    """
    Synthesize text → numpy float32 audio array at 24kHz.
    Returns None if Kokoro is unavailable or synthesis fails.
    Runs synchronously — call from a thread or asyncio executor.
    """
    if KOKORO_HTTP_URL:
        try:
            import requests
            r = requests.post(f"{KOKORO_HTTP_URL}/speak", json={"text": text}, timeout=10)
            if r.status_code == 200:
                return np.frombuffer(r.content, dtype=np.float32)
            else:
                log.warning(f"[Kokoro] HTTP synthesis failed: {r.status_code}")
                return None
        except Exception as e:
            log.warning(f"[Kokoro] HTTP synthesis error: {e}")
            return None

    if not _load_kokoro():
        return None
    try:
        lang = "en-us"
        voice = KOKORO_VOICE.lower()
        if voice.startswith(("hf_", "hm_", "hi_")):
            lang = "hi"
        elif voice.startswith(("zf_", "zm_")):
            lang = "zh-cn"
        elif voice.startswith(("jf_", "jm_")):
            lang = "ja"
        elif voice.startswith(("ff_", "fm_")):
            lang = "fr-fr"
        elif voice.startswith(("ef_", "em_")):
            lang = "es-es"
        elif voice.startswith(("if_", "im_")):
            lang = "it-it"
        elif voice.startswith(("pf_", "pm_")):
            lang = "pt-br"
        elif voice.startswith(("bf_", "bm_")):
            lang = "en-gb"

        samples, sample_rate = _kokoro.create(
            text,
            voice=KOKORO_VOICE,
            speed=KOKORO_SPEED,
            lang=lang,
        )
        return samples
    except Exception as e:
        log.warning(f"[Kokoro] Synthesis error: {e}")
        return None


def play_sync(samples: np.ndarray) -> None:
    global _stop_requested
    _stop_requested = False          # reset at start of each new playback
    try:
        import sounddevice as sd
        sd.play(samples, samplerate=KOKORO_SAMPLE_RATE)
        chunk = 1024
        total = len(samples)
        played = 0
        while played < total:
            if _stop_requested:
                sd.stop()
                _stop_requested = False
                return
            played += chunk
            sd.sleep(20)             # check every 20ms
    except Exception as e:
        log.warning(f"[Kokoro] Playback error: {e}")


async def synthesize_and_play(text: str) -> bool:
    """
    Async wrapper: synthesize + play Kokoro audio.
    Runs synthesis in executor to avoid blocking the event loop.
    Returns True if spoken successfully, False if Kokoro unavailable/error.
    """
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


async def synthesize_and_play_chunked(text: str, chunk_chars: int = 120) -> bool:
    """
    For long text: split into sentence chunks, synthesize + play each chunk
    sequentially. First chunk starts playing ~30ms after call — no full wait.
    Falls back to synthesize_and_play for short text.
    """
    if not KOKORO_ENABLED:
        return False
    if not _load_kokoro():
        return False

    # Split on sentence boundaries
    import re
    sentences = re.split(r'(?<=[.!?।,])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return False

    # For very short text, use the simple path
    if len(sentences) == 1:
        return await synthesize_and_play(text)

    try:
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
    except Exception as e:
        log.warning(f"[Kokoro] Chunked synthesis error: {e}")
        return False
