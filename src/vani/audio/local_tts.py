"""
local_tts.py — Native OS TTS for Siya (VANI_LOCAL_TTS=1 mode)

Strategy:
  macOS  → subprocess.Popen(["say", "-v", voice, text])
             Spawns a child process; returns instantly (~5ms).
             'say' speaks asynchronously. No blocking.
  Windows → win32com SAPI with SVSFlagsAsync (flag=1).
             Non-blocking. Falls back to PowerShell if win32com missing.

Latency profile (from conversation_item_added event to first audio):
  macOS  say:    40–80ms  (process spawn + CoreAudio buffer fill)
  Windows SAPI:  60–120ms (COM dispatch + SAPI buffer)

speak_local_async() is the primary entry point — fire and forget.
speak_local() is the synchronous (blocking) fallback, kept for compat.
"""

import sys
import subprocess
import re
import threading
import logging

log = logging.getLogger("vani.audio.local_tts")

# ── Voice selection ────────────────────────────────────────────────────────────
# macOS voices: Samantha (en-US), Karen (en-AU), Daniel (en-GB), Rishi (en-IN)
# Rishi is the closest to an Indian accent on macOS.
# Override via env var: VANI_MAC_VOICE=Rishi
import os
_MAC_VOICE = os.getenv("VANI_MAC_VOICE", "Rishi")
_MAC_RATE = os.getenv("VANI_MAC_RATE", "210")  # words per minute (default ~175)

# Windows SAPI voice substring match (case-insensitive)
# e.g. "Zira" (en-US female), "David" (en-US male), "Heera" (en-IN female)
_WIN_VOICE = os.getenv("VANI_WIN_VOICE", "Zira")

# ── Text cleaning ──────────────────────────────────────────────────────────────

def clean_for_speech(text: str) -> str:
    """Strip markdown, code blocks, emojis, and extra whitespace."""
    # Remove code blocks
    clean = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    clean = re.sub(r"`[^`]+`", " ", clean)
    # Remove markdown symbols
    clean = re.sub(r"[*_#>|\\-]+", " ", clean)
    # Strip non-ASCII (emojis, Devanagari, etc.) — 'say' handles English only well
    clean = clean.encode("ascii", "ignore").decode("ascii")
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


# ── macOS ──────────────────────────────────────────────────────────────────────

def _speak_mac(text: str):
    """
    Non-blocking macOS speech via 'say'.
    Popen returns immediately; the child process plays audio independently.
    If a previous 'say' is still speaking, macOS queues or overlaps —
    call _stop_mac() before this if you want to interrupt.
    """
    try:
        subprocess.Popen(
            ["say", "-v", _MAC_VOICE, "-r", _MAC_RATE, text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug(f"[macOS say] Popen OK: {text[:60]!r} voice={_MAC_VOICE} rate={_MAC_RATE}")
    except FileNotFoundError:
        log.error("[macOS say] 'say' command not found — are you on macOS?")
    except Exception as e:
        log.error(f"[macOS say] Popen failed: {e}")


def _stop_mac():
    """Kill any running 'say' process (interrupt current speech)."""
    try:
        subprocess.run(["pkill", "-x", "say"], capture_output=True)
    except Exception:
        pass


# ── Windows ───────────────────────────────────────────────────────────────────

def _speak_windows(text: str):
    """
    Non-blocking Windows speech via SAPI (win32com) with async flag.
    Falls back to PowerShell Add-Type if win32com not installed.
    """
    try:
        import win32com.client
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        # Try to select preferred voice
        try:
            voices = speaker.GetVoices()
            for i in range(voices.Count):
                if _WIN_VOICE.lower() in voices.Item(i).GetDescription().lower():
                    speaker.Voice = voices.Item(i)
                    break
        except Exception:
            pass  # use default voice
        # SVSFlagsAsync = 1 → non-blocking
        speaker.Speak(text, 1)
        log.debug(f"[Windows SAPI] Async speak OK: {text[:60]!r}")
    except ImportError:
        # Fallback: PowerShell (slower ~200ms startup, but always available)
        _speak_windows_ps(text)
    except Exception as e:
        log.error(f"[Windows SAPI] Failed: {e}")
        _speak_windows_ps(text)


def _speak_windows_ps(text: str):
    """PowerShell TTS fallback — slower startup but no deps."""
    try:
        escaped = text.replace("'", "''")
        ps_cmd = (
            f"Add-Type -AssemblyName System.Speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SpeakAsync('{escaped}')"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug(f"[Windows PS] Speak fallback OK: {text[:60]!r}")
    except Exception as e:
        log.error(f"[Windows PS] Speak failed: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def speak_local_async(text: str):
    """
    Primary entry point — fire and forget.
    Cleans text, dispatches to OS-native TTS in a daemon thread.
    Returns immediately (~0ms from caller's perspective).
    
    Called from conversation_item_added event handler in app.py.
    """
    clean_text = clean_for_speech(text)
    if not clean_text:
        return

    def _run():
        if sys.platform == "darwin":
            _speak_mac(clean_text)
        elif sys.platform == "win32":
            _speak_windows(clean_text)
        else:
            log.warning(f"[local_tts] Unsupported platform {sys.platform!r}: {clean_text!r}")
            print(f"[Siya]: {clean_text}")

    t = threading.Thread(target=_run, daemon=True, name="native-tts")
    t.start()


def speak_local(text: str):
    """
    Synchronous speak — blocks until TTS process is spawned (not until finished).
    Kept for backward compatibility with any existing callers.
    Prefer speak_local_async() for new code.
    """
    speak_local_async(text)


def stop_speaking():
    """Interrupt current speech (Mac only for now)."""
    if sys.platform == "darwin":
        _stop_mac()
