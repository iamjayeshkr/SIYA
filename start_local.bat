@echo off
REM start_local.bat — Launch local LiveKit server and Siya on Windows
setlocal enabledelayedexpansion

echo =========================================
echo Siya OS — Starting local LiveKit Server...
echo =========================================

if not exist "livekit-server.exe" (
    echo [ERROR] livekit-server.exe not found in root.
    echo Please run download_livekit.bat first.
    pause
    exit /b 1
)

start "LiveKit Server" .\livekit-server.exe --dev

echo =========================================
echo Siya OS — Starting up on Windows...
echo =========================================

call start.bat
