"""
vani/voice_stack.py
───────────────────
Manages the hybrid voice pipeline described in the architecture doc.

PRIMARY path:  LiveKit → Gemini Realtime  (online, low-latency)
FALLBACK path: Mic capture → Whisper STT → LLM → Piper TTS  (offline)

The VoiceStack automatically switches between paths based on:
  - Network connectivity check
  - Gemini Realtime connection health
  - Manual override (VANI_FORCE_OFFLINE=true)

The Twin-Brain dispatcher runs on top of both paths — the STT output
always feeds the same planner regardless of which path captured it.

Usage:
    from vani.voice_stack import VoiceStack

    stack = VoiceStack(model_router=model_router)
    await stack.start()

    # In your main loop:
    text = await stack.listen()           # returns transcribed speech
    await stack.speak("Got it, Rudra")    # speaks the response
"""

import asyncio
import os
import time
from enum import Enum
from typing import Callable, Optional

from vani.logging_config import get_logger
from vani.stt_whisper import WhisperSTT

log = get_logger("voice_stack")

FORCE_OFFLINE = os.getenv("VANI_FORCE_OFFLINE", "false").lower() == "true"
CONNECTIVITY_CHECK_URL = "https://dns.google"
CONNECTIVITY_TIMEOUT = 3.0


class VoiceMode(str, Enum):
    PRIMARY  = "primary"   # LiveKit + Gemini Realtime
    FALLBACK = "fallback"  # Whisper STT + Piper TTS


class VoiceStack:
    """
    Hybrid voice pipeline with automatic primary/fallback switching.

    Pass your existing LiveKit session manager as `livekit_session`.
    If None, always uses fallback mode.
    """

    def __init__(
        self,
        model_router=None,
        livekit_session=None,             # your existing LiveKit session object
        whisper_model: str = "small",
        piper_voice: str = "en_US-lessac-medium",
        on_mode_change: Optional[Callable[[VoiceMode], None]] = None,
    ):
        self.model_router = model_router
        self.livekit = livekit_session
        self.on_mode_change = on_mode_change

        self._whisper = WhisperSTT(model_size=whisper_model)
        self._piper_voice = piper_voice
        self._mode = VoiceMode.PRIMARY if (livekit_session and not FORCE_OFFLINE) else VoiceMode.FALLBACK
        self._connectivity_task: Optional[asyncio.Task] = None
        self._piper_available = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise the voice stack. Call at app startup."""
        # Pre-load Whisper so first offline transcription is instant
        asyncio.create_task(self._preload_whisper())

        # Check Piper availability
        self._piper_available = await self._check_piper()

        # Start background connectivity monitor
        self._connectivity_task = asyncio.create_task(self._connectivity_loop())

        log.info("voice_stack_started",
                 initial_mode=self._mode,
                 whisper_model=self._whisper.model_size,
                 piper_available=self._piper_available,
                 force_offline=FORCE_OFFLINE)

    async def stop(self) -> None:
        if self._connectivity_task:
            self._connectivity_task.cancel()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def mode(self) -> VoiceMode:
        return self._mode

    @property
    def is_online(self) -> bool:
        return self._mode == VoiceMode.PRIMARY

    async def listen(self, timeout: float = 30.0) -> str:
        """
        Capture speech and return transcribed text.

        In PRIMARY mode: delegates to LiveKit/Gemini Realtime.
        In FALLBACK mode: captures from mic and runs Whisper locally.
        """
        if self._mode == VoiceMode.PRIMARY and self.livekit:
            return await self._listen_primary(timeout)
        else:
            return await self._listen_fallback(timeout)

    async def speak(self, text: str) -> None:
        """
        Speak text aloud.

        In PRIMARY mode: Gemini Realtime handles TTS natively.
        In FALLBACK mode: Piper TTS → system audio.
        """
        if self._mode == VoiceMode.PRIMARY and self.livekit:
            await self._speak_primary(text)
        else:
            await self._speak_fallback(text)

    # ── Primary path (LiveKit + Gemini Realtime) ──────────────────────────────

    async def _listen_primary(self, timeout: float) -> str:
        """Delegate to existing LiveKit session for STT."""
        try:
            # Adapt to your existing LiveKit session API
            if hasattr(self.livekit, "listen"):
                return await asyncio.wait_for(self.livekit.listen(), timeout=timeout)
            elif hasattr(self.livekit, "get_transcript"):
                return await asyncio.wait_for(self.livekit.get_transcript(), timeout=timeout)
            else:
                raise RuntimeError("LiveKit session has no listen() method")
        except (asyncio.TimeoutError, Exception) as e:
            log.warning("primary_listen_failed", error=str(e), switching_to_fallback=True)
            await self._switch_to_fallback()
            return await self._listen_fallback(timeout)

    async def _speak_primary(self, text: str) -> None:
        """Gemini Realtime handles TTS — just send text to the session."""
        try:
            if hasattr(self.livekit, "speak"):
                await self.livekit.speak(text)
            elif hasattr(self.livekit, "send_text"):
                await self.livekit.send_text(text)
        except Exception as e:
            log.warning("primary_speak_failed", error=str(e))
            await self._speak_fallback(text)

    # ── Fallback path (Whisper STT + Piper TTS) ───────────────────────────────

    async def _listen_fallback(self, timeout: float) -> str:
        """
        Capture audio from the system microphone and transcribe with Whisper.
        Uses sounddevice for mic capture (cross-platform).
        """
        log.info("fallback_listen_start", timeout=timeout)
        t0 = time.monotonic()

        try:
            audio_bytes = await self._capture_mic(duration=min(timeout, 10.0))
            text = await self._whisper.transcribe_bytes(audio_bytes, sample_rate=16000)
            duration_ms = int((time.monotonic() - t0) * 1000)
            log.info("fallback_listen_done", text_len=len(text), duration_ms=duration_ms)
            return text
        except Exception as e:
            log.error("fallback_listen_failed", error=str(e))
            return ""

    async def _speak_fallback(self, text: str) -> None:
        """Synthesise speech with Piper TTS and play through system audio."""
        if not self._piper_available:
            log.warning("piper_unavailable", message="Piper not installed — cannot speak in offline mode")
            # Last resort: print to console
            print(f"[Vani]: {text}")
            return

        try:
            import subprocess
            proc = await asyncio.create_subprocess_exec(
                "piper",
                "--model", self._piper_voice,
                "--output-raw",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            raw_audio, _ = await proc.communicate(input=text.encode())

            # Play via aplay (Linux) or afplay (macOS)
            player = "afplay" if os.uname().sysname == "Darwin" else "aplay"
            play_proc = await asyncio.create_subprocess_exec(
                player, "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await play_proc.communicate(input=raw_audio)

        except Exception as e:
            log.error("piper_speak_failed", error=str(e))

    async def _capture_mic(self, duration: float = 5.0) -> bytes:
        """Capture audio from the system microphone as raw 16kHz mono PCM."""
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            raise RuntimeError("sounddevice not installed. Run: pip install sounddevice numpy")

        SAMPLE_RATE = 16000
        loop = asyncio.get_event_loop()

        def _record():
            audio = sd.rec(
                int(duration * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocking=True,
            )
            return audio.tobytes()

        return await loop.run_in_executor(None, _record)

    # ── Mode switching ────────────────────────────────────────────────────────

    async def _switch_to_fallback(self) -> None:
        if self._mode != VoiceMode.FALLBACK:
            self._mode = VoiceMode.FALLBACK
            log.warning("voice_mode_switched", mode="fallback")
            if self.on_mode_change:
                self.on_mode_change(VoiceMode.FALLBACK)

    async def _switch_to_primary(self) -> None:
        if self._mode != VoiceMode.PRIMARY and self.livekit:
            self._mode = VoiceMode.PRIMARY
            log.info("voice_mode_switched", mode="primary")
            if self.on_mode_change:
                self.on_mode_change(VoiceMode.PRIMARY)

    # ── Connectivity monitor ──────────────────────────────────────────────────

    async def _connectivity_loop(self) -> None:
        """Check network every 30s and switch voice mode accordingly."""
        while True:
            await asyncio.sleep(30)
            online = await self._check_connectivity()
            if online and self._mode == VoiceMode.FALLBACK and not FORCE_OFFLINE:
                log.info("connectivity_restored")
                await self._switch_to_primary()
            elif not online and self._mode == VoiceMode.PRIMARY:
                log.warning("connectivity_lost")
                await self._switch_to_fallback()

    async def _check_connectivity(self) -> bool:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    CONNECTIVITY_CHECK_URL,
                    timeout=aiohttp.ClientTimeout(total=CONNECTIVITY_TIMEOUT),
                ) as resp:
                    return resp.status < 500
        except Exception:
            return False

    async def _preload_whisper(self) -> None:
        """Load Whisper model in background so it's ready when needed."""
        try:
            await self._whisper.load()
        except Exception as e:
            log.warning("whisper_preload_failed", error=str(e))

    async def _check_piper(self) -> bool:
        """Check if Piper TTS binary is installed."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "piper", "--version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except FileNotFoundError:
            log.warning("piper_not_found",
                        hint="Install Piper: https://github.com/rhasspy/piper")
            return False
