"""
vani_talking_tom.py — Talking Tom mode for Vani
================================================
Jo bhi audio aaye — baat, gana, kuch bhi —
pitch upar uthao + speed slightly badhaao + turant wapas bajao.

Dependencies (free, open source):
    pip install sounddevice numpy librosa soundfile
"""

import threading
import numpy as np
import sounddevice as sd
import librosa

# ── Config ────────────────────────────────────────────────────────────────────
SAMPLE_RATE   = 44100   # Hz
CHANNELS      = 1       # mono
CHUNK_SIZE    = 4096    # samples per chunk (buffer size)
PITCH_STEPS   = 6       # semitones upar — 6 = Tom voice (4-8 ke beech try karo)
SPEED_FACTOR  = 1.25    # 1.0 = normal, 1.25 = thoda fast (Tom style)
PLAYBACK_GAIN = 1.3     # volume boost (1.0 = same, 1.5 = louder)

# ── State ─────────────────────────────────────────────────────────────────────
_active        = False
_stream_in     = None
_stream_out    = None
_lock          = threading.Lock()
_audio_buffer  = []     # collected chunks
_processing    = False


def _pitch_shift_chunk(audio: np.ndarray, sr: int, n_steps: float) -> np.ndarray:
    """
    Audio chunk ko pitch shift karo.
    librosa.effects.pitch_shift float32 chahta hai.
    """
    audio_f32 = audio.astype(np.float32)
    shifted   = librosa.effects.pitch_shift(audio_f32, sr=sr, n_steps=n_steps)
    return shifted


def _process_and_play(audio_data: np.ndarray):
    """
    Collected audio ko pitch shift + speed adjust karo, phir play karo.
    """
    global _processing
    _processing = True
    try:
        audio = audio_data.astype(np.float32)

        # Step 1: Pitch shift (Tom ki squeaky voice)
        shifted = librosa.effects.pitch_shift(audio, sr=SAMPLE_RATE, n_steps=PITCH_STEPS)

        # Step 2: Speed change — time stretch (speed > 1.0 = faster)
        if SPEED_FACTOR != 1.0:
            rate   = 1.0 / SPEED_FACTOR   # librosa stretch rate — inverse of speed
            shifted = librosa.effects.time_stretch(shifted, rate=rate)

        # Step 3: Volume gain
        shifted = shifted * PLAYBACK_GAIN

        # Step 4: Clip to avoid distortion
        shifted = np.clip(shifted, -1.0, 1.0)

        # Step 5: Play — blocking (waits until done)
        sd.play(shifted, samplerate=SAMPLE_RATE)
        sd.wait()

    except Exception as e:
        print(f"[TalkingTom] Process error: {e}")
    finally:
        _processing = False


# ── Silence detection ─────────────────────────────────────────────────────────
_SILENCE_THRESHOLD = 0.01   # RMS below this = silence
_SILENCE_CHUNKS    = 8      # kitne consecutive silent chunks ke baad "utterance end" maano
_silence_count     = 0
_collecting        = False
_collected         = []


def _audio_callback(indata, frames, time_info, status):
    """
    Sounddevice input callback — har chunk yahan aata hai.
    Silence detection se utterance boundary pakadta hai.
    """
    global _silence_count, _collecting, _collected, _processing

    if not _active:
        return

    # Agar abhi playback chal raha hai toh record mat karo (feedback avoid)
    if _processing:
        return

    chunk = indata[:, 0].copy()   # mono
    rms   = float(np.sqrt(np.mean(chunk ** 2)))

    if rms > _SILENCE_THRESHOLD:
        # Sound detect hua — collect karo
        _collecting    = True
        _silence_count = 0
        _collected.append(chunk)
    else:
        if _collecting:
            _silence_count += 1
            _collected.append(chunk)   # silence bhi include karo (natural ending)

            if _silence_count >= _SILENCE_CHUNKS:
                # Utterance khatam — process karo
                _collecting    = False
                _silence_count = 0

                if _collected:
                    full_audio = np.concatenate(_collected)
                    _collected = []

                    # Alag thread mein process (callback block nahi hoga)
                    t = threading.Thread(
                        target=_process_and_play,
                        args=(full_audio,),
                        daemon=True
                    )
                    t.start()


# ── Public API ────────────────────────────────────────────────────────────────

def start_talking_tom():
    """Talking Tom mode activate karo."""
    global _active, _stream_in, _silence_count, _collecting, _collected

    with _lock:
        if _active:
            print("[TalkingTom] Already active.")
            return

        _active        = True
        _silence_count = 0
        _collecting    = False
        _collected     = []

        try:
            _stream_in = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=CHUNK_SIZE,
                callback=_audio_callback,
            )
            _stream_in.start()
            print("[TalkingTom] 🎤 Mode ON — bol ya gaa, main repeat karungi!")

        except Exception as e:
            _active = False
            print(f"[TalkingTom] ❌ Start failed: {e}")
            print("  → Check karo mic permission aur sounddevice install hai ya nahi.")


def stop_talking_tom():
    """Talking Tom mode band karo."""
    global _active, _stream_in, _collecting, _collected

    with _lock:
        if not _active:
            return

        _active     = False
        _collecting = False
        _collected  = []

        if _stream_in:
            try:
                _stream_in.stop()
                _stream_in.close()
            except Exception:
                pass
            _stream_in = None

        sd.stop()
        print("[TalkingTom] 🔇 Mode OFF — wapas normal hoon.")


def is_active() -> bool:
    return _active


def set_pitch(semitones: float):
    """Runtime mein pitch change karo — 4=slight, 6=Tom, 10=very squeaky."""
    global PITCH_STEPS
    PITCH_STEPS = semitones
    print(f"[TalkingTom] Pitch set to {semitones} semitones")


def set_speed(factor: float):
    """Runtime mein speed change karo — 1.0=normal, 1.3=fast, 1.5=very fast."""
    global SPEED_FACTOR
    SPEED_FACTOR = factor
    print(f"[TalkingTom] Speed set to {factor}x")


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    print("Talking Tom Test Mode")
    print("─────────────────────")
    print("Mic mein kuch bolo ya gaao — Vani repeat karegi!")
    print("Ctrl+C se band karo.\n")

    start_talking_tom()

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        stop_talking_tom()
        print("Done.")