@echo off
REM mac_siya.bat — Launch Vani with English-only responses and local ultra-fast TTS (50-150ms)
setlocal enabledelayedexpansion

echo ==================================================
echo Starting Siya in STRICT English Only Mode
echo Voice Backend: Local Native TTS (Siri/SAPI) - 50-150ms
echo ==================================================

set "VANI_ENGLISH_ONLY=1"
set "VANI_LOCAL_TTS=1"

call start_local.bat
