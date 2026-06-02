"""
vani/stt_whisper.py
───────────────────
Local offline Speech-to-Text using whisper.cpp via the `faster-whisper`
Python bindings (CTranslate2-based — fast CPU/GPU inference).

Serves as fallback when LiveKit + Gemini Realtime is unavailable:
  - Gemini rate limited
  - No internet connection
  - LiveKit cloud down

Model sizes (choose based on your Mac's RAM):
  tiny    →  75MB,  ~5x realtime,  good for Hinglish
  base    → 142MB,  ~7x realtime,  better accuracy
  small   → 244MB,  ~6x realtime,  recommended
  medium  → 769MB,  ~2x realtime,  best local quality
  large   →  1.5GB, ~1x realtime,  Gemini-level quality

Usage:
    from vani.stt_whisper import WhisperSTT

    stt = WhisperSTT(model_size="small")
    await stt.load()   # loads model into memory (~2s)

    # Transcribe a wav/mp3/m4a file
    text = await stt.transcribe_file("recording.wav")

    # Or transcribe raw PCM bytes (from mic capture)
    text = await stt.transcribe_bytes(pcm_bytes, sample_rate=16000)
"""

import asyncio
import io
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from vani.logging_config import get_logger

log = get_logger("stt.whisper")

# Model to use — override with VANI_WHISPER_MODEL env var
DEFAULT_MODEL = os.getenv("VANI_WHISPER_MODEL", "small")

# Language hint — speeds up transcription and improves Hinglish accuracy
# "hi" for Hindi, "en" for English, None for auto-detect
DEFAULT_LANGUAGE = os.getenv("VANI_WHISPER_LANGUAGE", None)  # None = auto

# Where to cache downloaded models
MODEL_CACHE_DIR = Path.home() / ".cache" / "vani" / "whisper"


class WhisperSTT:
    """
    Local speech-to-text using faster-whisper (CTranslate2 backend).

    Designed to be:
    - Loaded once at startup (keep in memory)
    - Used as fallback when Gemini STT is unavailable
    - Always available offline
    """

    def __init__(
        self,
        model_size: str = DEFAULT_MODEL,
        language: Optional[str] = DEFAULT_LANGUAGE,
        device: str = "auto",            # "cpu", "cuda", or "auto"
        compute_type: str = "auto",      # "int8", "float16", "auto"
    ):
        self.model_size = model_size
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._loaded = False
        self._load_lock = asyncio.Lock()

    async def load(self) -> None:
        """
        Load the Whisper model into memory.
        Safe to call multiple times — only loads once.
        Call at startup so first transcription isn't delayed.
        """
        async with self._load_lock:
            if self._loaded:
                return

            log.info("whisper_loading", model=self.model_size,
                     cache=str(MODEL_CACHE_DIR))
            t0 = time.monotonic()

            try:
                from faster_whisper import WhisperModel  # type: ignore
            except ImportError:
                raise RuntimeError(
                    "faster-whisper not installed. "
                    "Run: pip install faster-whisper"
                )

            MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

            # Load in a thread pool so we don't block the event loop
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(MODEL_CACHE_DIR),
                ),
            )

            self._loaded = True
            duration_ms = int((time.monotonic() - t0) * 1000)
            log.info("whisper_loaded", model=self.model_size, duration_ms=duration_ms)

    async def transcribe_file(
        self,
        path: str | Path,
        language: Optional[str] = None,
    ) -> str:
        """
        Transcribe an audio file (wav, mp3, m4a, ogg, flac).

        Args:
            path:     Path to audio file.
            language: Override language hint (None = use instance default).

        Returns:
            Transcribed text string.
        """
        if not self._loaded:
            await self.load()

        t0 = time.monotonic()
        lang = language or self.language

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            lambda: self._do_transcribe_file(str(path), lang),
        )

        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info("whisper_transcribed",
                 source="file",
                 text_len=len(text),
                 language=lang or "auto",
                 duration_ms=duration_ms)
        return text

    async def transcribe_bytes(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
        audio_format: str = "wav",
    ) -> str:
        """
        Transcribe raw audio bytes (from microphone capture or LiveKit).

        Args:
            audio_bytes:  Raw audio data.
            sample_rate:  Sample rate in Hz (Whisper needs 16kHz — will resample if needed).
            language:     Override language hint.
            audio_format: "wav", "pcm", or "mp3".

        Returns:
            Transcribed text string.
        """
        if not self._loaded:
            await self.load()

        t0 = time.monotonic()
        lang = language or self.language

        # Write to temp file — faster-whisper expects a file path
        suffix = f".{audio_format}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            tmp_path = f.name
            if audio_format == "pcm":
                # Raw PCM → wrap in WAV header
                f.write(self._pcm_to_wav(audio_bytes, sample_rate))
            else:
                f.write(audio_bytes)

        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(
                None,
                lambda: self._do_transcribe_file(tmp_path, lang),
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info("whisper_transcribed",
                 source="bytes",
                 bytes_size=len(audio_bytes),
                 text_len=len(text),
                 language=lang or "auto",
                 duration_ms=duration_ms)
        return text

    def _do_transcribe_file(self, path: str, language: Optional[str]) -> str:
        """Blocking transcription — run in executor."""
        segments, info = self._model.transcribe(
            path,
            language=language,
            beam_size=5,
            vad_filter=True,           # skip silence automatically
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
            },
            condition_on_previous_text=True,
            temperature=0.0,           # greedy decoding — more deterministic
        )
        # Collect all segments
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text

    @staticmethod
    def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
        """Wrap raw PCM (16-bit mono) in a minimal WAV header."""
        import struct
        num_samples = len(pcm_bytes) // 2
        num_channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = len(pcm_bytes)
        chunk_size = 36 + data_size

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", chunk_size, b"WAVE",
            b"fmt ", 16, 1, num_channels,
            sample_rate, byte_rate, block_align,
            bits_per_sample, b"data", data_size,
        )
        return header + pcm_bytes

    @property
    def is_loaded(self) -> bool:
        return self._loaded
