@echo off
REM mac_siya.bat — WINDOWS launcher for Native TTS mode
REM For macOS, use: bash siya_native.sh
REM
REM Latency: 250-400ms | Voice: Windows SAPI (Zira/Heera) | Language: English
setlocal enabledelayedexpansion

echo ==================================================
echo  Siya — Native TTS Mode (Windows)
echo  Voice: Windows SAPI (%VANI_WIN_VOICE%)
echo  Latency: 250-400ms  ^|  English only
echo ==================================================

set "VANI_LOCAL_TTS=1"
set "VANI_ENGLISH_ONLY=1"
set "VANI_ENDPOINT_MIN_DELAY=0.05"
set "VANI_ENDPOINT_MAX_DELAY=0.15"
set "VANI_INTERRUPT_MIN_DURATION=0.08"

REM Windows voice: Zira (en-US female), David (en-US male), Heera (en-IN female)
if not defined VANI_WIN_VOICE set "VANI_WIN_VOICE=Zira"

call start_local.bat
