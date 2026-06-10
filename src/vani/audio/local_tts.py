import sys
import subprocess
import re
import logging

log = logging.getLogger("vani.audio.local_tts")

def clean_for_speech(text: str) -> str:
    """Strip emojis, markdown, code blocks, and extra whitespaces for clean TTS."""
    clean = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    clean = re.sub(r"[*_`#>\-|]+", " ", clean)
    # Strip emojis
    clean = clean.encode('ascii', 'ignore').decode('ascii')
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

def speak_local(text: str):
    """Speak text locally using native OS TTS engines asynchronously."""
    clean_text = clean_for_speech(text)
    if not clean_text:
        return

    if sys.platform == "win32":
        try:
            import win32com.client
            # Initialize SAPI SpVoice
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            # 1 = SVSFlagsAsync (speaks asynchronously, non-blocking)
            speaker.Speak(clean_text, 1)
            log.info(f"[win32 SAPI] Spoke text asynchronously: {clean_text!r}")
        except Exception as e:
            log.error(f"[win32 SAPI] Speech failed: {e}")
            print(f"[Vani local]: {clean_text}")

    elif sys.platform == "darwin":
        try:
            # Run macOS 'say' command in a detached process
            subprocess.Popen(["say", clean_text])
            log.info(f"[macOS say] Spoke text: {clean_text!r}")
        except Exception as e:
            log.error(f"[macOS say] Speech failed: {e}")
            print(f"[Vani local]: {clean_text}")

    else:
        # Fallback for Linux or other platforms
        log.warning(f"[Local TTS fallback] Console fallback for: {clean_text!r}")
        print(f"[Vani local]: {clean_text}")
