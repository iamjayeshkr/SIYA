@echo off
REM start_desktop.bat — Launch local LiveKit server and Vani Desktop App
setlocal enabledelayedexpansion

echo ===================================================
echo Vani Desktop — Starting local LiveKit Server...
echo ===================================================

if exist "livekit-server.exe" (
    echo [INFO] Starting LiveKit server in background...
    start "LiveKit Server" /min .\livekit-server.exe --dev
) else (
    echo [INFO] livekit-server.exe not found. Skipping local server.
)

echo ===================================================
echo Vani Desktop — Starting Electron UI...
echo ===================================================

cd /d "%~dp0\desktop"

if not exist "node_modules" (
    echo [INFO] node_modules not found. Installing Electron dependencies...
    call npm install
)

echo [INFO] Launching Electron app...
call npm start

pause
