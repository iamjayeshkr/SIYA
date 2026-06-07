"""
src/vani/audio/indic_tts_adapter.py
Refined AI4Bharat Indic-TTS Pipeline Adapter.
Exposes the exact same public API as kokoro_tts.py.
"""

import os
import sys
import time
import re
import queue
import urllib.request
import shutil
import tempfile
import subprocess
import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from scipy.io.wavfile import write as wav_write
import numpy as np

# Load configurations
from vani.config import (
    PROJECT_ROOT,
    INDIC_TTS_ENABLED,
    VANI_TTS_SPEAKER,
    VANI_TTS_LANG,
    VANI_TTS_FILLER,
    VANI_INDIC_TTS_CHECKPOINTS,
    VANI_CACHE_DIR,
    INDIC_TTS_MAX_CHARS,
)

log = logging.getLogger("vani.indic_tts")

INDIC_TTS_DIR = PROJECT_ROOT / "Indic-TTS-master"
INFERENCE_DIR = INDIC_TTS_DIR / "inference"

# Append Indic-TTS paths to sys.path so modules like `src` can be imported
if str(INFERENCE_DIR) not in sys.path:
    sys.path.append(str(INFERENCE_DIR))

# Global states
_playback_proc = None
_stop_requested = False
_cache: dict[str, str] = {}          # phrase → wav file path
_engine = None                          # TextToSpeechEngine singleton
_engine_lock = threading.Lock()
_engine_ready = threading.Event()
SAMPLE_RATE = 22050

# ── RVC Integration Setup ──
_rvc_instance = None
_rvc_ready = threading.Event()

def _load_rvc_model():
    global _rvc_instance
    pth_path = PROJECT_ROOT / "shreya.pth"
    if not pth_path.exists():
        log.info("[RVC] shreya.pth not found in project root. RVC voice conversion disabled.")
        return

    try:
        log.info("[RVC] Initializing RVC model in daemon thread...")
        edgervc_dir = PROJECT_ROOT / "EdgeRVC"
        if str(edgervc_dir) not in sys.path:
            sys.path.insert(0, str(edgervc_dir))

        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        os.environ["TORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        os.environ["weight_root"] = str(PROJECT_ROOT)
        os.environ["index_root"] = str(PROJECT_ROOT)
        os.environ["outside_index_root"] = str(PROJECT_ROOT)
        os.environ["rmvpe_root"] = str(edgervc_dir / "assets/rmvpe")

        orig_cwd = os.getcwd()
        os.chdir(str(edgervc_dir))
        try:
            from configs.config import Config as RVCConfig
            from infer.modules.vc.modules import VC as RVC_VC
            
            cfg = RVCConfig()
            cfg.device = "cpu"
            cfg.is_half = False
            
            _rvc_instance = RVC_VC(cfg)
            _rvc_instance.get_vc("shreya.pth")
            _rvc_ready.set()
            log.info("[RVC] RVC model loaded successfully.")
        finally:
            os.chdir(orig_cwd)
    except Exception as e:
        log.error(f"[RVC] Failed to load RVC: {e}", exc_info=True)

def _convert_voice_rvc(input_wav_path: str) -> str:
    """Run RVC voice conversion on the input wav file."""
    if not _rvc_ready.is_set() or _rvc_instance is None:
        return input_wav_path
    
    try:
        start_time = time.time()
        output_dir = Path(VANI_CACHE_DIR) / "rvc_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        orig_cwd = os.getcwd()
        edgervc_dir = PROJECT_ROOT / "EdgeRVC"
        os.chdir(str(edgervc_dir))
        
        try:
            info, converted_path = _rvc_instance.vc_single(
                sid=0,
                input_audio_path=input_wav_path,
                f0_up_key=0,
                f0_file=None,
                f0_method=os.getenv("VANI_RVC_METHOD", "pm"),
                file_index="",
                file_index2=str(PROJECT_ROOT / "shreya.index"),
                index_rate=0.75,
                filter_radius=3,
                resample_sr=0,
                rms_mix_rate=0.25,
                protect=0.33,
                save_dir=str(output_dir),
                format1="wav",
            )
            elapsed = int((time.time() - start_time) * 1000)
            log.info(f"[RVC] Voice conversion latency: {elapsed}ms | {info}")
            if converted_path and os.path.exists(converted_path):
                return converted_path
        finally:
            os.chdir(orig_cwd)
    except Exception as e:
        log.error(f"[RVC] RVC voice conversion failed: {e}")
        
    return input_wav_path

WARM_PHRASES = [
    "Haan yaar", "Ho gaya", "Ek second", "Samajh gaya", "Bilkul",
    "Theek hai", "Nahi yaar", "Kya hua", "Bata", "Suno",
    "Achha", "Hmm", "Dekho", "Haan bolo", "Kar deta hun",
    "Thoda wait kar", "Pata nahi yaar", "Interesting hai yeh",
    "Sahi kaha", "Bilkul sahi", "Main dekh raha hun",
    "Ek kaam kar", "Yeh lo", "Done", "Ready hai",
    "Koi baat nahi", "Chal theek hai", "Acha sun",
    "Main samjha", "Haan haan", "Sahi hai",
    "Ab sun", "Yaar sun", "Bol",
    "Okay", "Sure", "Got it",
    "Ruk", "Bas ek second", "Haan kar raha hun",
]


def _download_checkpoints(checkpoints_path: Path):
    hi_dir = checkpoints_path / "hi"
    required_files = [
        hi_dir / "fastpitch" / "best_model.pth",
        hi_dir / "fastpitch" / "config.json",
        hi_dir / "fastpitch" / "speakers.pth",
        hi_dir / "hifigan" / "best_model.pth",
        hi_dir / "hifigan" / "config.json",
    ]
    if all(f.exists() for f in required_files):
        return
        
    log.info("[IndicTTS] Checkpoints missing. Downloading hi.zip...")
    checkpoints_path.mkdir(parents=True, exist_ok=True)
    zip_path = checkpoints_path / "hi.zip"
    url = "https://github.com/AI4Bharat/Indic-TTS/releases/download/v1-checkpoints-release/hi.zip"
    try:
        def _reporthook(blocknum, blocksize, totalsize):
            readsofar = blocknum * blocksize
            if totalsize > 0:
                percent = readsofar * 1e2 / totalsize
                if blocknum % 500 == 0:
                    log.info(f"[IndicTTS] Downloading checkpoints: {percent:.1f}%")
        
        urllib.request.urlretrieve(url, zip_path, _reporthook)
        log.info("[IndicTTS] Download complete. Extracting hi.zip...")
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(checkpoints_path)
        zip_path.unlink()
        log.info("[IndicTTS] Extraction complete.")
    except Exception as e:
        log.error(f"[IndicTTS] Failed to download/extract checkpoints: {e}")
        if zip_path.exists():
            zip_path.unlink()


def _generate_breath_filler(cache_dir: Path):
    breath_path = cache_dir / "__filler_breath__.wav"
    if breath_path.exists():
        _cache["__filler_breath__"] = str(breath_path)
        return
        
    duration = 0.08  # 80ms
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # White noise
    noise = np.random.normal(0, 0.1, len(t))
    # Exponential decay envelope
    envelope = np.exp(-50 * t)  # decay factor
    breath_audio = noise * envelope
    # Normalize
    max_val = np.max(np.abs(breath_audio))
    if max_val > 0:
        breath_audio = breath_audio / max_val
    # Convert to 16-bit PCM wav
    wav_write(str(breath_path), SAMPLE_RATE, (breath_audio * 32767).astype(np.int16))
    _cache["__filler_breath__"] = str(breath_path)
    log.info("[IndicTTS] Generated breath filler sound.")


def _generate_hmm_filler(cache_dir: Path):
    hmm_path = cache_dir / "__filler_hmm__.wav"
    if hmm_path.exists():
        _cache["__filler_hmm__"] = str(hmm_path)
        return
        
    if _engine is not None:
        try:
            log.info("[IndicTTS] Synthesizing hmm filler...")
            audio = _engine.infer_from_text("Hmm", lang=VANI_TTS_LANG, speaker_name=VANI_TTS_SPEAKER)
            # Trim to 300ms
            max_samples = int(0.3 * SAMPLE_RATE)
            trimmed_audio = audio[:max_samples]
            # Normalize
            max_val = np.max(np.abs(trimmed_audio))
            if max_val > 0:
                trimmed_audio = trimmed_audio / max_val
            wav_write(str(hmm_path), SAMPLE_RATE, (trimmed_audio * 32767).astype(np.int16))
            _cache["__filler_hmm__"] = str(hmm_path)
            log.info("[IndicTTS] Generated hmm filler sound via TTS.")
            return
        except Exception as e:
            log.error(f"[IndicTTS] Failed to generate hmm filler via TTS: {e}")
            
    # Fallback: Generate a high-quality human-like hum mathematically
    try:
        log.info("[IndicTTS] Generating mathematical hmm filler...")
        duration = 1.0  # 1 second of hum
        t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
        
        # Fundamental frequency at 120Hz (warm pitch) + harmonics
        f0 = 120.0
        wave = (
            1.0 * np.sin(2 * np.pi * f0 * t) +
            0.5 * np.sin(2 * np.pi * 2 * f0 * t) +
            0.2 * np.sin(2 * np.pi * 3 * f0 * t)
        )
        
        # Envelope: fade-in (0.2s), steady, fade-out (0.5s)
        fade_in_len = int(0.2 * SAMPLE_RATE)
        fade_out_len = int(0.5 * SAMPLE_RATE)
        
        envelope = np.ones(len(t))
        envelope[:fade_in_len] = np.linspace(0, 1, fade_in_len)
        envelope[-fade_out_len:] = np.linspace(1, 0, fade_out_len)
        
        # Add soft breathy noise for realism
        noise = np.random.normal(0, 0.05, len(t))
        hum_audio = (wave + noise) * envelope
        
        # Normalize
        max_val = np.max(np.abs(hum_audio))
        if max_val > 0:
            hum_audio = hum_audio / max_val
            
        wav_write(str(hmm_path), SAMPLE_RATE, (hum_audio * 32767).astype(np.int16))
        _cache["__filler_hmm__"] = str(hmm_path)
        log.info("[IndicTTS] Generated mathematical hmm filler sound successfully.")
    except Exception as e:
        log.error(f"[IndicTTS] Failed to generate mathematical hmm filler: {e}")


def _warm_cache_thread():
    cache_dir = Path(VANI_CACHE_DIR) / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate breath filler first (doesn't need TTS engine)
    _generate_breath_filler(cache_dir)
    
    # Wait for the engine to be ready
    _engine_ready.wait()
    
    # Wait for RVC engine to be ready if pth exists, so cache warming generates converted files
    pth_path = PROJECT_ROOT / "shreya.pth"
    if pth_path.exists():
        log.info("[IndicTTS] Waiting for RVC engine to load before warming cache...")
        _rvc_ready.wait(timeout=30)
    
    # Generate hmm filler
    _generate_hmm_filler(cache_dir)
    
    # Post-process hmm filler with RVC if enabled
    hmm_path = cache_dir / "__filler_hmm__.wav"
    if hmm_path.exists() and _rvc_ready.is_set():
        try:
            converted = _convert_voice_rvc(str(hmm_path))
            if converted != str(hmm_path):
                shutil.move(converted, str(hmm_path))
                log.info("[IndicTTS] Hmm filler RVC-converted.")
        except Exception as e:
            log.error(f"[IndicTTS] Failed to convert hmm filler: {e}")
            
    start_time = time.time()
    warmed_count = 0
    
    for phrase in WARM_PHRASES:
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', phrase.lower())
        suffix = "_rvc" if _rvc_ready.is_set() else ""
        wav_path = cache_dir / f"phrase_{safe_name}{suffix}.wav"
        
        if wav_path.exists():
            _cache[phrase] = str(wav_path)
            warmed_count += 1
            continue
            
        try:
            audio = _engine.infer_from_text(phrase, lang=VANI_TTS_LANG, speaker_name=VANI_TTS_SPEAKER)
            # Normalize
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val
            wav_write(str(wav_path), SAMPLE_RATE, (audio * 32767).astype(np.int16))
            
            # Post-process with RVC if enabled
            if _rvc_ready.is_set():
                converted = _convert_voice_rvc(str(wav_path))
                if converted != str(wav_path):
                    shutil.move(converted, str(wav_path))
                    
            _cache[phrase] = str(wav_path)
            warmed_count += 1
        except Exception as e:
            log.error(f"[IndicTTS] Failed to warm cache for phrase '{phrase}': {e}")
            
    elapsed = time.time() - start_time
    log.info(f"[IndicTTS] Cache warmed: {warmed_count}/{len(WARM_PHRASES)} phrases ({elapsed:.1f}s)")


def _load_engine():
    global _engine
    try:
        checkpoints_path = Path(VANI_INDIC_TTS_CHECKPOINTS)
        if not checkpoints_path.is_absolute():
            checkpoints_path = PROJECT_ROOT / checkpoints_path
            
        _download_checkpoints(checkpoints_path)
        
        # Patch config.json to use absolute path for speakers.pth
        config_path = checkpoints_path / "hi" / "fastpitch" / "config.json"
        speakers_path = checkpoints_path / "hi" / "fastpitch" / "speakers.pth"
        if config_path.exists() and speakers_path.exists():
            import json
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                
                modified = False
                if cfg.get("speakers_file") != str(speakers_path):
                    cfg["speakers_file"] = str(speakers_path)
                    modified = True
                
                if isinstance(cfg.get("model_args"), dict):
                    if cfg["model_args"].get("speakers_file") != str(speakers_path):
                        cfg["model_args"]["speakers_file"] = str(speakers_path)
                        modified = True
                        
                if modified:
                    log.info(f"[IndicTTS] Updating config.json speakers_file path to {speakers_path}")
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, indent=4)
            except Exception as ce:
                log.error(f"[IndicTTS] Failed to update config.json: {ce}")
        
        from TTS.utils.synthesizer import Synthesizer
        from src.inference import TextToSpeechEngine
        
        log.info("[IndicTTS] Initializing Synthesizer models...")
        hi_model = Synthesizer(
            tts_checkpoint=str(checkpoints_path / "hi" / "fastpitch" / "best_model.pth"),
            tts_config_path=str(checkpoints_path / "hi" / "fastpitch" / "config.json"),
            tts_speakers_file=str(checkpoints_path / "hi" / "fastpitch" / "speakers.pth"),
            tts_languages_file=None,
            vocoder_checkpoint=str(checkpoints_path / "hi" / "hifigan" / "best_model.pth"),
            vocoder_config=str(checkpoints_path / "hi" / "hifigan" / "config.json"),
            encoder_checkpoint="",
            encoder_config="",
            use_cuda=False,
        )
        
        _engine = TextToSpeechEngine({"hi": hi_model}, enable_denoiser=False)
        _engine_ready.set()
        log.info("[IndicTTS] Engine successfully loaded.")
    except Exception as e:
        log.error(f"[IndicTTS] Failed to load engine: {e}", exc_info=True)


# Start engine loader, RVC model loader, and warm cache threads
if INDIC_TTS_ENABLED:
    threading.Thread(target=_load_engine, daemon=True).start()
    threading.Thread(target=_load_rvc_model, daemon=True).start()
    threading.Thread(target=_warm_cache_thread, daemon=True).start()
else:
    try:
        # Generate offline/mathematical fillers at startup even if Indic-TTS is disabled
        cache_dir = Path(VANI_CACHE_DIR) / "tts_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        _generate_breath_filler(cache_dir)
        _generate_hmm_filler(cache_dir)
    except Exception as e:
        log.warning(f"[IndicTTS] Offline filler generation failed: {e}")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'([.!?।])', text)
    sentences = []
    current = ""
    for i in range(0, len(parts) - 1, 2):
        sentence = (parts[i] + parts[i+1]).strip()
        if not sentence:
            continue
        if len(sentence) < 8:
            current = (current + " " + sentence).strip()
        else:
            if current:
                sentences.append(current)
                current = ""
            sentences.append(sentence)
    if len(parts) % 2 == 1:
        last_part = parts[-1].strip()
        if last_part:
            current = (current + " " + last_part).strip()
    if current:
        sentences.append(current)
    return [s for s in sentences if s.strip()]


def _synthesize_to_wav(text: str) -> str | None:
    if _stop_requested:
        return None
        
    text_strip = text.strip()
    if text_strip in _cache:
        log.info(f"[IndicTTS] Cache hit (exact): \"{text_strip[:40]}...\"")
        return _cache[text_strip]
        
    for phrase, path in _cache.items():
        if text_strip.startswith(phrase) and (len(text_strip) == len(phrase) or text_strip[len(phrase)] in " ,.!?।"):
            log.info(f"[IndicTTS] Cache hit (partial start): \"{phrase}\" for \"{text_strip[:40]}...\"")
            return path
            
    acquired = _engine_lock.acquire(timeout=15)
    if not acquired:
        log.warning("[IndicTTS] Engine lock timeout. Synthesis skipped.")
        return None
        
    try:
        if _engine is None:
            log.warning("[IndicTTS] Engine not initialized.")
            return None
            
        start_time = time.time()
        audio = _engine.infer_from_text(text_strip, lang=VANI_TTS_LANG, speaker_name=VANI_TTS_SPEAKER)
        
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val
            
        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        wav_write(temp_path, SAMPLE_RATE, (audio * 32767).astype(np.int16))
        elapsed = int((time.time() - start_time) * 1000)
        log.info(f"[IndicTTS] Synthesis latency: {elapsed}ms | \"{text_strip[:40]}...\"")
        
        # Post-process with RVC if enabled
        try:
            converted = _convert_voice_rvc(temp_path)
            if converted != temp_path:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                temp_path = converted
        except Exception as re:
            log.error(f"[RVC] Voice conversion post-processing failed: {re}")
            
        return temp_path
    except Exception as e:
        log.error(f"[IndicTTS] Synthesis failed: {e}", exc_info=True)
        return None
    finally:
        _engine_lock.release()


def _play_filler():
    """Internal filler — called inside synthesize_and_play BEFORE engine wait."""
    filler = os.getenv("VANI_TTS_FILLER", "breath")
    if filler == "none":
        return
    filler_path = _cache.get(f"__filler_{filler}__")
    if filler_path:
        try:
            subprocess.Popen(["afplay", filler_path],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass


async def play_filler(filler_type: str = "auto", response_len: int = 0) -> bool:
    """
    Public async API — play a filler sound INSTANTLY before TTS synthesis.
    Called from say_to_user() in worker.py before synthesis begins.

    filler_type "breath"  → 80ms soft inhale (numpy generated, always fast)
    filler_type "hmm"     → ~1s warm hum sound (mathematical or synthesized)
    filler_type "auto"    → breath if response_len < 60, hmm otherwise
    Returns True if played, False if cache miss. Never raises.
    """
    try:
        if filler_type == "auto":
            filler_type = "hmm" if response_len >= 60 else "breath"

        key = f"__filler_{filler_type}__"
        wav_path = _cache.get(key) or _cache.get("__filler_breath__")
        if not wav_path:
            return False

        if sys.platform == "win32":
            import winsound
            # winsound.PlaySound plays completely asynchronously on Windows
            winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        else:
            subprocess.Popen(
                ["afplay", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    except Exception as e:
        log.debug(f"[IndicTTS] play_filler failed (non-fatal): {e}")
        return False


def _play_wav_blocking(wav_path: str) -> bool:
    global _playback_proc
    if _stop_requested:
        return False
    try:
        _playback_proc = subprocess.Popen(["afplay", wav_path])
        _playback_proc.wait()
    except Exception as e:
        log.error(f"[IndicTTS] Playback error: {e}")
        try:
            import soundfile as sf
            import sounddevice as sd
            data, fs = sf.read(wav_path)
            sd.play(data, fs)
            sd.wait()
        except Exception as se:
            log.error(f"[IndicTTS] Fallback playback error: {se}")
    return True


def _play_wav(wav_path: str) -> bool:
    return _play_wav_blocking(wav_path)


# ── Public APIs ───────────────────────────────────────────────────────────────

def stop_playback():
    global _stop_requested, _playback_proc
    _stop_requested = True
    if _playback_proc and _playback_proc.poll() is None:
        try:
            _playback_proc.terminate()
            _playback_proc.kill()
        except Exception:
            pass


def is_short_reply(text: str) -> bool:
    return INDIC_TTS_ENABLED and len(text.strip()) <= INDIC_TTS_MAX_CHARS


def is_kokoro_short(text: str) -> bool:
    return is_short_reply(text)


async def synthesize_and_play(text: str) -> bool:
    global _stop_requested
    _stop_requested = False
    
    if not INDIC_TTS_ENABLED:
        return False
        
    text_strip = text.strip()
    if not text_strip:
        return False
        
    start_total = time.time()
    
    if text_strip in _cache:
        log.info(f"[IndicTTS] cache_hit=True | 0ms | \"{text_strip[:40]}...\"")
        return _play_wav(_cache[text_strip])
        
    sentences = _split_sentences(text_strip)
    if not sentences:
        return False
        
    first_sent = sentences[0]
    sorted_phrases = sorted(_cache.keys(), key=len, reverse=True)
    for phrase in sorted_phrases:
        if first_sent.startswith(phrase) and (len(first_sent) == len(phrase) or first_sent[len(phrase)] in " ,.!?।"):
            rest = first_sent[len(phrase):].strip(" ,.!?।")
            sentences[0] = phrase
            if rest:
                sentences.insert(1, rest)
            break
            
    # ── Filler BEFORE engine wait — user hears something instantly ───────────
    _play_filler()

    if not _engine_ready.is_set():
        log.info("[IndicTTS] Waiting for engine to initialize...")
        ready = _engine_ready.wait(timeout=15)
        if not ready or _engine is None:
            log.warning("[IndicTTS] Engine failed to initialize in time.")
            return False

    latencies = []
    # ── Double-buffer: synthesize sentence i+1 while playing sentence i ──────
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        # Prefetch first 2 sentences immediately
        for s in sentences[:2]:
            futures.append(executor.submit(_synthesize_to_wav, s))
        # Pad remaining slots with None — filled lazily below
        for _ in sentences[2:]:
            futures.append(None)

        for i, s in enumerate(sentences):
            if _stop_requested:
                break

            # While playing sentence i, kick off synthesis of sentence i+2
            if i + 2 < len(sentences) and futures[i + 2] is None:
                futures[i + 2] = executor.submit(_synthesize_to_wav, sentences[i + 2])

            start_wait = time.time()
            wav_path = futures[i].result()
            wait_time_ms = int((time.time() - start_wait) * 1000)

            if s in _cache:
                latencies.append(f"s{i+1}=0ms(cache)")
            else:
                latencies.append(f"s{i+1}={wait_time_ms}ms")

            if wav_path:
                _play_wav_blocking(wav_path)
                if wav_path not in _cache.values() and "tts_cache" not in wav_path:
                    try:
                        os.unlink(wav_path)
                    except Exception:
                        pass

    latencies_summary = " ".join(latencies)
    total_dur_ms = int((time.time() - start_total) * 1000)
    log.info(f"[IndicTTS] {latencies_summary} | total_time={total_dur_ms}ms | {len(sentences)} sentences")
    return True


async def synthesize_and_play_chunked(text: str) -> bool:
    global _stop_requested, _playback_proc
    if not _engine_ready.is_set():
        ready = _engine_ready.wait(timeout=15)
        if not ready or _engine is None:
            return False
    
    sentences = _split_sentences(text)
    if not sentences:
        return False
    
    _stop_requested = False
    loop = asyncio.get_event_loop()
    
    def _synth(sentence: str) -> str | None:
        """Synthesize one sentence → returns wav file path or None."""
        if _stop_requested:
            return None
        # Check cache first
        if sentence in _cache:
            return _cache[sentence]
        if _engine is None:
            return None
        try:
            with _engine_lock:
                audio = _engine.infer_from_text(
                    sentence, lang=VANI_TTS_LANG, 
                    speaker_name=VANI_TTS_SPEAKER
                )
            max_val = np.max(np.abs(audio))
            if max_val > 0:
                audio = audio / max_val
            tmp = tempfile.mktemp(suffix=".wav", dir=str(Path(VANI_CACHE_DIR) / "tts_cache"))
            wav_write(tmp, SAMPLE_RATE, (audio * 32767).astype(np.int16))
            
            # Post-process with RVC if enabled
            try:
                converted = _convert_voice_rvc(tmp)
                if converted != tmp:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
                    tmp = converted
            except Exception as re:
                log.error(f"[RVC] Voice conversion post-processing failed: {re}")
                
            return tmp
        except Exception as e:
            log.error(f"[IndicTTS] Synth error: {e}")
            return None
    
    # Double-buffer: synthesize next while playing current
    executor = ThreadPoolExecutor(max_workers=2)
    
    # Kick off sentence 0 synthesis immediately
    futures = []
    for i, sentence in enumerate(sentences[:2]):  # prefetch first 2
        futures.append(loop.run_in_executor(executor, _synth, sentence))
    
    played_any = False
    for i, sentence in enumerate(sentences):
        # Prefetch next+1 if exists
        if i + 2 < len(sentences):
            futures.append(
                loop.run_in_executor(executor, _synth, sentences[i + 2])
            )
        
        # Wait for current sentence
        wav_path = await futures[i]
        
        if _stop_requested:
            break
        if not wav_path:
            continue
        
        # Play current sentence (blocking in executor so asyncio isn't blocked)
        def _play(path):
            global _playback_proc
            try:
                _playback_proc = subprocess.Popen(
                    ["afplay", path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                _playback_proc.wait()
            except Exception as e:
                log.error(f"[IndicTTS] Playback error: {e}")
        
        await loop.run_in_executor(None, _play, wav_path)
        played_any = True
        
        # Delete temporary WAV chunk if not cached
        if wav_path not in _cache.values():
            try:
                os.unlink(wav_path)
            except Exception:
                pass
    
    executor.shutdown(wait=False)
    return played_any
