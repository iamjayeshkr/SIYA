"""
vani_audio_priority.py — Mac Audio Priority for Vanni
======================================================
Jab Vanni sun rahi ho → system microphone input mute + browser tab mute
Jab Vanni bol le      → sab unmute

Mac par:
  - Browser tab mute: AppleScript (Chrome/Safari/Firefox)
  - Microphone input mute: osascript input volume
"""

import sys
import subprocess
import logging
import os
import re

logger = logging.getLogger("vani.audio_priority")

IS_MAC     = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

BROWSERS_MAC = ["Google Chrome", "Chromium", "Brave Browser", "Safari", "Firefox"]
MEDIA_URL_HINTS = (
    "youtube.com", "music.youtube.com", "netflix.com", "primevideo.com",
    "hotstar.com", "jiocinema.com", "spotify.com", "soundcloud.com",
)
LOCAL_UI_HINTS = ("127.0.0.1", "localhost")
_PREVIOUS_OUTPUT_VOLUME: int | None = None
_DUCKED = False


def _run_applescript(script: str):
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=3
        )
        if result.returncode != 0:
            logger.debug(f"[applescript] stderr: {result.stderr.decode()}")
    except Exception as e:
        logger.debug(f"[applescript] {e}")


def _run_applescript_text(script: str) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode != 0:
            logger.debug(f"[applescript] stderr: {result.stderr.strip()}")
            return ""
        return result.stdout.strip()
    except Exception as e:
        logger.debug(f"[applescript] {e}")
        return ""


def _set_browser_mute_mac(mute: bool):
    """Media browser tabs mute/unmute karo; Vani localhost UI ko kabhi mute mat karo."""
    mute_val = "true" if mute else "false"
    for browser in BROWSERS_MAC:
        if browser in {"Google Chrome", "Chromium", "Brave Browser"}:
            script = f"""
try
    tell application "{browser}"
        repeat with w in every window
            repeat with t in every tab of w
                set tabUrl to URL of t
                if tabUrl does not contain "127.0.0.1" and tabUrl does not contain "localhost" then
                    if {str(not mute).lower()} or tabUrl contains "youtube.com" or tabUrl contains "music.youtube.com" or tabUrl contains "netflix.com" or tabUrl contains "primevideo.com" or tabUrl contains "hotstar.com" or tabUrl contains "jiocinema.com" or tabUrl contains "spotify.com" or tabUrl contains "soundcloud.com" then
                        set muted of t to {mute_val}
                    end if
                end if
            end repeat
        end repeat
    end tell
end try
"""
        elif browser == "Safari":
            script = f"""
try
    tell application "Safari"
        repeat with w in every window
            repeat with t in every tab of w
                set tabUrl to URL of t
                if tabUrl does not contain "127.0.0.1" and tabUrl does not contain "localhost" then
                    if {str(not mute).lower()} or tabUrl contains "youtube.com" or tabUrl contains "music.youtube.com" or tabUrl contains "netflix.com" or tabUrl contains "primevideo.com" or tabUrl contains "hotstar.com" or tabUrl contains "jiocinema.com" or tabUrl contains "spotify.com" or tabUrl contains "soundcloud.com" then
                        set muted of t to {mute_val}
                    end if
                end if
            end repeat
        end repeat
    end tell
end try
"""
        else:
            script = f"""
try
    tell application "{browser}"
        set muted of every tab of every window to {mute_val}
    end tell
end try
"""
        _run_applescript(script)
    logger.info(f"[audio_priority] Browsers {'muted' if mute else 'unmuted'}")


def _set_input_volume_mac(mute: bool):
    """System microphone input volume set karo — 0 = mute, 50 = normal."""
    vol = 0 if mute else 50
    _run_applescript(f"set volume input volume {vol}")
    logger.info(f"[audio_priority] Mic input volume → {vol}")


def _current_output_volume_mac() -> int | None:
    raw = _run_applescript_text("output volume of (get volume settings)")
    match = re.search(r"\d+", raw)
    if not match:
        return None
    return max(0, min(100, int(match.group(0))))


def _set_output_volume_mac(volume: int):
    volume = max(0, min(100, int(volume)))
    _run_applescript(f"set volume output volume {volume}")
    logger.info(f"[audio_priority] Output volume → {volume}")


def _duck_output_mac():
    global _PREVIOUS_OUTPUT_VOLUME, _DUCKED
    if os.getenv("VANI_DUCK_MEDIA_WHILE_LISTENING", "1") != "1":
        return
    duck_volume = int(os.getenv("VANI_LISTEN_OUTPUT_VOLUME", "12"))
    current = _current_output_volume_mac()
    if current is None:
        return
    if not _DUCKED:
        _PREVIOUS_OUTPUT_VOLUME = current
    if current > duck_volume:
        _set_output_volume_mac(duck_volume)
    _DUCKED = True


def _restore_output_mac():
    global _PREVIOUS_OUTPUT_VOLUME, _DUCKED
    if not _DUCKED:
        return
    restore = _PREVIOUS_OUTPUT_VOLUME
    _PREVIOUS_OUTPUT_VOLUME = None
    _DUCKED = False
    if restore is not None:
        _set_output_volume_mac(restore)


def vani_activated():
    """Vanni sun rahi hai — browser mute karo taaki clearly sune."""
    logger.info("[audio_priority] Vanni activated — muting")
    if IS_MAC:
        _set_browser_mute_mac(mute=True)
        _duck_output_mac()
        _set_input_volume_mac(mute=False)  # mic ON rakho — Vanni ko sunna hai


def vani_deactivated():
    """Vanni bol chuki — sab unmute karo."""
    logger.info("[audio_priority] Vanni deactivated — unmuting")
    if IS_MAC:
        _restore_output_mac()
        _set_browser_mute_mac(mute=False)
