"""Minimal FastAPI wrapper so Kokoro runs in Docker and Vanni hits it over HTTP."""
import os, io, logging
import numpy as np
from fastapi import FastAPI
from fastapi.responses import Response

log = logging.getLogger("kokoro_server")
app = FastAPI()

_kokoro = None
VOICE = os.getenv("KOKORO_VOICE", "af_heart")
SPEED = float(os.getenv("KOKORO_SPEED", "1.1"))

def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro("kokoro-v1.9.onnx", "voices-v1.0.bin")
        log.info("Kokoro loaded")
    return _kokoro

@app.post("/speak")
async def speak(body: dict):
    text = body.get("text", "").strip()
    if not text:
        return Response(status_code=400)
    try:
        samples, sr = _get_kokoro().create(text, voice=VOICE, speed=SPEED, lang="en-us")
        # Return raw float32 PCM bytes at 24kHz
        buf = io.BytesIO()
        buf.write(samples.astype(np.float32).tobytes())
        return Response(content=buf.getvalue(), media_type="application/octet-stream",
                        headers={"X-Sample-Rate": str(sr)})
    except Exception as e:
        log.error(f"Synthesis error: {e}")
        return Response(status_code=500)

@app.get("/health")
def health():
    return {"status": "ok", "voice": VOICE}
