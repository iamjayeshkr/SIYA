"""
docker/kokoro/kokoro_server.py
Minimal FastAPI wrapper — Kokoro runs in Docker, Vanni calls over HTTP.

Enhancement: audio post-processed server-side before returning PCM bytes,
so all clients (including mobile) get clean, natural-sounding voice.
"""
import os
import io
import re
import logging
import numpy as np
from fastapi import FastAPI
from fastapi.responses import Response

log = logging.getLogger("kokoro_server")
app = FastAPI()

_kokoro = None
VOICE   = os.getenv("KOKORO_VOICE", "af_heart")
SPEED   = float(os.getenv("KOKORO_SPEED", "0.95"))   # slightly slower = warmer
SR      = 24000


def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
        log.info(f"Kokoro loaded — voice={VOICE} speed={SPEED}")
    return _kokoro


def _enhance(samples: np.ndarray) -> np.ndarray:
    """Server-side audio enhancement — same pipeline as kokoro_tts.py."""
    try:
        from scipy.signal import butter, sosfilt
    except ImportError:
        return samples

    audio = samples.astype(np.float32)

    # 1. High-pass 80 Hz
    sos_hp = butter(4, 80.0 / (SR / 2), btype="high", output="sos")
    audio  = sosfilt(sos_hp, audio).astype(np.float32)

    # 2. Presence boost 3–8 kHz (+2 dB)
    sos_p   = butter(2, [3000.0/(SR/2), 8000.0/(SR/2)], btype="band", output="sos")
    band_p  = sosfilt(sos_p, audio).astype(np.float32)
    boost   = 10 ** (2.0 / 20)
    audio   = audio + (boost - 1.0) * band_p

    # 3. De-essing 6–9 kHz (−3 dB)
    sos_e   = butter(2, [6000.0/(SR/2), min(9000.0/(SR/2), 0.99)], btype="band", output="sos")
    band_e  = sosfilt(sos_e, audio).astype(np.float32)
    cut     = 10 ** (-3.0 / 20)
    audio   = audio - (1.0 - cut) * band_e

    # 4. RMS normalise to −18 dBFS
    rms    = float(np.sqrt(np.mean(audio ** 2))) + 1e-9
    target = 10 ** (-18.0 / 20)
    gain   = float(np.clip(target / rms, 10**(-12/20), 10**(12/20)))
    audio  = audio * gain

    # 5. Peak limiter −1 dBFS
    ceiling = 10 ** (-1.0 / 20)
    audio   = np.clip(audio, -ceiling, ceiling)

    # 6. Fade-in/out 5ms
    fade_n = min(int(SR * 0.005), len(audio) // 10)
    if fade_n > 0:
        fade = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
        audio[:fade_n]  *= fade
        audio[-fade_n:] *= fade[::-1]

    return audio.astype(np.float32)


def _detect_lang(voice: str) -> str:
    v = voice.lower()
    if v.startswith(("hf_", "hm_", "hi_")): return "hi"
    if v.startswith(("bf_", "bm_")):         return "en-gb"
    if v.startswith(("zf_", "zm_")):         return "zh-cn"
    return "en-us"


@app.post("/speak")
async def speak(body: dict):
    text = body.get("text", "").strip()
    if not text:
        return Response(status_code=400)
    try:
        samples, sr = _get_kokoro().create(
            text, voice=VOICE, speed=SPEED, lang=_detect_lang(VOICE)
        )
        enhanced = _enhance(samples)
        return Response(
            content=enhanced.tobytes(),
            media_type="application/octet-stream",
            headers={"X-Sample-Rate": str(sr)},
        )
    except Exception as e:
        log.error(f"Synthesis error: {e}")
        return Response(status_code=500)


@app.get("/health")
def health():
    return {"status": "ok", "voice": VOICE, "speed": SPEED}
