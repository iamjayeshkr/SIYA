"""
vani/wake_listener.py
Always-on background wake listener — Siri-style, works 24/7.

Two parallel detectors run simultaneously on the same mic stream:

  1. VOSK keyword spotter  — hears "vani" / "vanni" / "hey vani" etc.
     • Fully offline, ~50ms latency, tiny 40MB model.
     • Falls back to NSSpeechRecognizer on macOS if Vosk not installed.

  2. Double-clap detector  — two sharp energy spikes within 0.8s,
     separated by at least 0.15s of silence.
     • Zero extra dependencies (just numpy + sounddevice).
     • Works even when music is playing (uses relative energy delta).

Both detectors share one sounddevice InputStream so there's only one
mic handle open.  When either fires, Vani wakes.

Install Vosk model (optional but recommended):
    pip install vosk
    # Download small English model from https://alphacephei.com/vosk/models
    # e.g. vosk-model-small-en-us-0.15  →  place at ~/vani_wake_model/
    # OR set VANI_VOSK_MODEL_PATH=/path/to/model

Environment variables:
    VANI_VOSK_MODEL_PATH   — path to Vosk model dir (default: ~/vani_wake_model)
    VANI_WAKE_COOLDOWN     — seconds between wake triggers (default: 3)
    VANI_CLAP_ENABLED      — 1/0, enable double-clap (default: 1)
    VANI_CLAP_THRESHOLD    — energy multiplier for clap spike (default: 4.0)
    VANI_CLAP_GAP_MIN      — min seconds between claps (default: 0.15)
    VANI_CLAP_GAP_MAX      — max seconds between claps (default: 0.8)
    VANI_SPEAKER_VERIFY    — 1/0, enable speaker verification (default: 0)
    VANI_MAC_NOTIFICATIONS — 1/0, show macOS notifications (default: 1)
"""

import argparse
import collections
import json
import logging
import os
import subprocess
import sys
import time
import threading as _threading
from html import escape
from pathlib import Path

from vani.config import PROJECT_ROOT
from vani.launcher import wake_vani
from vani.services.wake import WAKE_ACK_REPLY, get_wake_reply

log = logging.getLogger("vani.wake_listener")

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# ── Speaker verification imports (lazy, guarded) ──────────────────────────────
try:
    from vani.audio.wake_verifier import verify_wake_audio_sync as _verify_wake
    from vani.audio.wake_verifier import VERIFY_ENABLED as _VERIFY_ENABLED
except ImportError:
    _verify_wake = None
    _VERIFY_ENABLED = False


# ─────────────────────────────────────────────────────────────────────────────
# Shared mic state
# ─────────────────────────────────────────────────────────────────────────────
_SAMPLE_RATE = 16000          # Hz — Vosk and clap detector both use 16kHz
_BLOCK_SIZE = 512             # frames per callback (~32ms at 16kHz)
_shared_stream = None
_stream_lock = _threading.Lock()

# Ring buffer for speaker verification (2.5s of audio)
_AUDIO_RING: collections.deque = collections.deque(maxlen=125)
_AUDIO_RING_LOCK = _threading.Lock()

# Cooldown state (shared between both detectors)
_last_wake_time: float = 0.0
_wake_lock = _threading.Lock()


def _cooldown_ok() -> bool:
    global _last_wake_time
    now = time.monotonic()
    cooldown = float(os.getenv("VANI_WAKE_COOLDOWN", "3"))
    with _wake_lock:
        if now - _last_wake_time < cooldown:
            return False
        _last_wake_time = now
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Wake action (shared)
# ─────────────────────────────────────────────────────────────────────────────

def _do_wake(source: str) -> None:
    """Trigger Vani wake sequence. source = 'voice' | 'clap'"""
    log.info("[wake] triggered by %s", source)

    # Speaker verification gate (only for voice wakes — clap always passes)
    if source == "voice" and _VERIFY_ENABLED and _verify_wake is not None:
        try:
            import numpy as np
            with _AUDIO_RING_LOCK:
                if _AUDIO_RING:
                    wav = np.concatenate(list(_AUDIO_RING))
                else:
                    wav = None
            if wav is not None:
                accepted = _verify_wake(wav, _SAMPLE_RATE)
                if accepted:
                    log.info("[wake] speaker verify: accepted")
                    try:
                        from vani.security_state import deactivate_lockdown, is_locked_down
                        if is_locked_down():
                            deactivate_lockdown()
                    except Exception:
                        pass
                else:
                    log.info("[wake] speaker verify: rejected")
                    try:
                        from vani.security_state import activate_lockdown, is_locked_down
                        if not is_locked_down():
                            activate_lockdown()
                    except Exception:
                        pass
                    return
        except Exception as exc:
            log.warning("[wake] speaker verify error: %s — proceeding", exc)

    try:
        wake_vani()
    except Exception as exc:
        log.exception("[wake] wake_vani() failed: %s", exc)

    _speak_ack(get_wake_reply())
    _notify_mac("Vani", f"Woke via {source}")


# ─────────────────────────────────────────────────────────────────────────────
# ① VOSK keyword spotter
# ─────────────────────────────────────────────────────────────────────────────

WAKE_KEYWORDS = [
    "vani", "vanni", "vaani",
    "hey vani", "hey vanni", "hey vaani",
    "ok vani", "okay vani",
    "hello vani",
    "vani sun", "vani uth ja",
    "wake up vani",
]

_vosk_recognizer = None
_vosk_queue: "collections.deque | None" = None


def _load_vosk():
    global _vosk_recognizer
    try:
        from vosk import Model, KaldiRecognizer
        model_path = os.getenv(
            "VANI_VOSK_MODEL_PATH",
            str(Path.home() / "vani_wake_model")
        )
        if not Path(model_path).exists():
            log.warning(
                "[vosk] Model not found at %s. "
                "Download from https://alphacephei.com/vosk/models and set "
                "VANI_VOSK_MODEL_PATH. Falling back to NSSpeechRecognizer.",
                model_path,
            )
            return False
        model = Model(model_path)
        _vosk_recognizer = KaldiRecognizer(model, _SAMPLE_RATE)
        _vosk_recognizer.SetWords(False)
        log.info("[vosk] Model loaded from %s ✅", model_path)
        return True
    except ImportError:
        log.info("[vosk] Not installed — pip install vosk to enable fast offline wake word.")
        return False
    except Exception as exc:
        log.warning("[vosk] Load failed: %s", exc)
        return False


def _vosk_audio_callback(pcm_bytes: bytes) -> None:
    """Feed PCM bytes to Vosk; fires wake if keyword detected."""
    global _vosk_recognizer
    if _vosk_recognizer is None:
        return
    try:
        if _vosk_recognizer.AcceptWaveform(pcm_bytes):
            result = json.loads(_vosk_recognizer.Result())
        else:
            result = json.loads(_vosk_recognizer.PartialResult())

        text = (result.get("text") or result.get("partial") or "").lower().strip()
        if not text:
            return

        matched = any(kw in text for kw in WAKE_KEYWORDS)
        if matched:
            log.info("[vosk] Heard: '%s'", text)
            if _cooldown_ok():
                _threading.Thread(target=_do_wake, args=("voice",), daemon=True).start()
    except Exception as exc:
        log.debug("[vosk] callback error: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# ② Double-clap detector
# ─────────────────────────────────────────────────────────────────────────────
#
# Algorithm:
#   • Maintain a short rolling RMS of the last N frames (ambient noise floor).
#   • A "clap" is detected when RMS of current block > floor * THRESHOLD.
#   • After first clap, wait for second clap within [GAP_MIN, GAP_MAX] seconds.
#   • If second clap arrives in that window → wake.
#
# This is relative-energy based so it works even in noisy environments.

_clap_state = {
    "first_clap_time": None,    # monotonic time of first clap
    "floor_rms": 0.01,          # rolling ambient noise estimate
    "floor_buf": collections.deque(maxlen=40),  # ~1.3s of blocks for floor
}
_CLAP_THRESHOLD = float(os.getenv("VANI_CLAP_THRESHOLD", "4.0"))
_CLAP_GAP_MIN = float(os.getenv("VANI_CLAP_GAP_MIN", "0.15"))
_CLAP_GAP_MAX = float(os.getenv("VANI_CLAP_GAP_MAX", "0.8"))
_CLAP_ENABLED = os.getenv("VANI_CLAP_ENABLED", "1") == "1"


def _clap_audio_callback(pcm_float32) -> None:
    """Receive one block of float32 audio; detect double-clap pattern."""
    if not _CLAP_ENABLED:
        return
    try:
        import numpy as np
        rms = float(np.sqrt(np.mean(pcm_float32 ** 2)))

        # Update rolling noise floor (use only quiet frames)
        st = _clap_state
        st["floor_buf"].append(rms)
        if len(st["floor_buf"]) >= 5:
            # floor = median of quietest 70% of recent blocks
            sorted_rms = sorted(st["floor_buf"])
            cutoff = int(len(sorted_rms) * 0.7)
            st["floor_rms"] = max(0.001, float(np.mean(sorted_rms[:cutoff])))

        # Spike detection
        is_clap = rms > st["floor_rms"] * _CLAP_THRESHOLD and rms > 0.02

        if not is_clap:
            return

        now = time.monotonic()
        first = st["first_clap_time"]

        if first is None:
            # Record first clap
            st["first_clap_time"] = now
            log.debug("[clap] First clap detected (rms=%.4f, floor=%.4f)", rms, st["floor_rms"])
        else:
            gap = now - first
            if gap < _CLAP_GAP_MIN:
                # Too fast — same clap's echo, ignore
                return
            elif gap <= _CLAP_GAP_MAX:
                # ✅ Double clap!
                st["first_clap_time"] = None
                log.info("[clap] Double-clap detected! gap=%.2fs", gap)
                if _cooldown_ok():
                    _threading.Thread(target=_do_wake, args=("clap",), daemon=True).start()
            else:
                # Too slow — treat this as a new first clap
                log.debug("[clap] Gap too long (%.2fs), resetting to new first clap", gap)
                st["first_clap_time"] = now
    except Exception as exc:
        log.debug("[clap] callback error: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Shared sounddevice InputStream
# ─────────────────────────────────────────────────────────────────────────────

def _start_shared_mic_stream() -> bool:
    """Open one sounddevice stream; feed audio to both Vosk and clap detector."""
    global _shared_stream
    try:
        import sounddevice as sd
        import numpy as np

        def _callback(indata, frames, time_info, status):
            pcm = indata[:, 0].astype(np.float32)

            # Ring buffer for speaker verification
            with _AUDIO_RING_LOCK:
                _AUDIO_RING.append(pcm.copy())

            # ① Feed Vosk (needs int16 PCM bytes)
            if _vosk_recognizer is not None:
                pcm_int16 = (pcm * 32767).astype(np.int16)
                _vosk_audio_callback(pcm_int16.tobytes())

            # ② Feed clap detector (float32 fine)
            _clap_audio_callback(pcm)

        _shared_stream = sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=_BLOCK_SIZE,
            callback=_callback,
        )
        _shared_stream.start()
        log.info("[mic] Shared mic stream started ✅  (sr=%d, block=%d)", _SAMPLE_RATE, _BLOCK_SIZE)
        return True
    except ImportError:
        log.warning("[mic] sounddevice not installed — clap detection unavailable. pip install sounddevice")
        return False
    except Exception as exc:
        log.warning("[mic] Could not open mic stream: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# macOS NSSpeechRecognizer fallback (when Vosk not available)
# ─────────────────────────────────────────────────────────────────────────────

WAKE_COMMANDS = [
    "vani", "vaani", "vanni",
    "wake up vani", "wake up vaani",
    "hey vani", "hey vaani",
    "ok vani", "okay vani",
    "vani sun", "vaani sun",
    "utho vani", "utho vaani",
    "vani uth ja", "vaani uth ja",
    "activate vani", "activate vaani",
    "hello vani", "hello vaani",
]


def _run_nsspeech_fallback():
    """macOS NSSpeechRecognizer — only used when Vosk is not available."""
    if not IS_MAC:
        log.warning("[nsspeech] Only supported on macOS")
        return

    from AppKit import NSSpeechRecognizer
    from Foundation import NSObject
    from PyObjCTools import AppHelper

    class WakeDelegate(NSObject):
        def speechRecognizer_didRecognizeCommand_(self, recognizer, command):
            log.info("[nsspeech] Heard: '%s'", command)
            if _cooldown_ok():
                _threading.Thread(target=_do_wake, args=("voice",), daemon=True).start()

    delegate = WakeDelegate.alloc().init()
    recognizer = NSSpeechRecognizer.alloc().init()
    recognizer.setCommands_(WAKE_COMMANDS)
    recognizer.setListensInForegroundOnly_(False)
    recognizer.setDelegate_(delegate)
    recognizer.startListening()
    log.info("[nsspeech] NSSpeechRecognizer fallback active (%d phrases)", len(WAKE_COMMANDS))
    AppHelper.runConsoleEventLoop()   # blocks — runs the macOS run loop


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _speak_ack(text: str = "") -> None:
    if not text:
        text = get_wake_reply()
    if IS_MAC:
        try:
            subprocess.Popen(["say", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            log.warning("[ack] say failed: %s", exc)
    elif IS_WINDOWS:
        try:
            script = (
                f"Add-Type -AssemblyName System.Speech; "
                f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f'$s.Speak("{text}")'
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            log.warning("[ack] powershell tts failed: %s", exc)


def _notify_mac(title: str, message: str) -> None:
    if not IS_MAC or os.getenv("VANI_MAC_NOTIFICATIONS", "1") != "1":
        return
    try:
        script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# LaunchAgent installer (macOS auto-start at login)
# ─────────────────────────────────────────────────────────────────────────────

WAKE_AGENT_LABEL = "com.rudra.vani.wake"
WAKE_AGENT_PATH = Path.home() / "Library/LaunchAgents" / f"{WAKE_AGENT_LABEL}.plist"


def install_macos_launchagent() -> None:
    if not IS_MAC:
        raise RuntimeError("Wake LaunchAgent install is only supported on macOS.")
    python_path = escape(sys.executable)
    project_root = escape(str(PROJECT_ROOT))
    src_root = escape(str(PROJECT_ROOT / "src"))
    home = escape(str(Path.home()))
    env_path = escape(os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>{WAKE_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>vani.wake_listener</string>
    </array>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <true/>
    <key>StandardOutPath</key>   <string>{home}/Library/Logs/vani_wake_listener.log</string>
    <key>StandardErrorPath</key> <string>{home}/Library/Logs/vani_wake_listener_err.log</string>
    <key>WorkingDirectory</key>  <string>{project_root}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{env_path}</string>
        <key>PYTHONPATH</key>
        <string>{src_root}</string>
    </dict>
</dict>
</plist>
"""
    WAKE_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    WAKE_AGENT_PATH.write_text(plist)
    subprocess.run(["launchctl", "unload", str(WAKE_AGENT_PATH)], capture_output=True)
    subprocess.run(["launchctl", "load", str(WAKE_AGENT_PATH)], capture_output=True)
    print(f"✅ Wake listener installed: {WAKE_AGENT_PATH}")
    print("Vani will now start automatically at login and listen 24/7.")


def uninstall_macos_launchagent() -> None:
    if not IS_MAC:
        raise RuntimeError("Wake LaunchAgent uninstall is only supported on macOS.")
    subprocess.run(["launchctl", "unload", str(WAKE_AGENT_PATH)], capture_output=True)
    WAKE_AGENT_PATH.unlink(missing_ok=True)
    print("Wake listener removed.")


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_listener() -> None:
    """
    Start all detectors.  Preference order:
      1. Vosk (offline keyword spotter, fastest) + shared mic stream
      2. Clap detector always runs alongside (shares same mic stream)
      3. NSSpeechRecognizer on macOS as fallback if Vosk model missing
    """
    log.info("[wake] Starting Vani always-on wake listener...")

    vosk_ok = _load_vosk()
    mic_ok = _start_shared_mic_stream()

    if vosk_ok and mic_ok:
        log.info("[wake] Vosk keyword spotter active ✅")
    elif IS_MAC:
        log.info("[wake] Vosk unavailable — starting NSSpeechRecognizer fallback")
        # NSSpeechRecognizer runs its own event loop; start it in a daemon thread
        # so the clap detector (if mic opened) also stays alive.
        t = _threading.Thread(target=_run_nsspeech_fallback, daemon=True)
        t.start()
    else:
        log.warning(
            "[wake] No keyword spotter available on this platform. "
            "Install Vosk: pip install vosk  and download a model."
        )

    if mic_ok and _CLAP_ENABLED:
        log.info("[wake] Double-clap detector active ✅  (threshold=%.1fx, gap=%.2f-%.2fs)",
                 _CLAP_THRESHOLD, _CLAP_GAP_MIN, _CLAP_GAP_MAX)
    elif not _CLAP_ENABLED:
        log.info("[wake] Clap detector disabled (VANI_CLAP_ENABLED=0)")
    else:
        log.info("[wake] Clap detector unavailable (mic stream not open)")

    _notify_mac("Vani", "Always-on wake listener active — say 'Vani' or double-clap!")
    log.info("[wake] Listener ready. Say 'Vani' or double-clap to wake.")

    # Keep the main thread alive (mic stream callbacks run on sounddevice's thread)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[wake] Shutting down.")
        if _shared_stream:
            _shared_stream.stop()
            _shared_stream.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Vani background wake listener")
    parser.add_argument("--commands", action="store_true", help="Print supported wake phrases and exit")
    parser.add_argument("--install", action="store_true", help="Install as a macOS login LaunchAgent (auto-start)")
    parser.add_argument("--uninstall", action="store_true", help="Remove the macOS login LaunchAgent")
    args = parser.parse_args()

    if args.commands:
        print("Voice wake phrases:")
        for cmd in WAKE_COMMANDS:
            print(f"  • {cmd}")
        print("\nClap: double-clap (two claps within 0.8s)")
        return
    if args.install:
        install_macos_launchagent()
        return
    if args.uninstall:
        uninstall_macos_launchagent()
        return

    logging.basicConfig(
        level=os.getenv("VANI_WAKE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT / "src"))
    run_listener()


if __name__ == "__main__":
    main()