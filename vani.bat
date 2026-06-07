@echo off
REM bin/run_vani.bat
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

cd /d "%PROJECT_ROOT%"

REM Find .venv
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    set "VENV=%PROJECT_ROOT%\.venv"
) else if exist "%PROJECT_ROOT%\venv311\Scripts\activate.bat" (
    set "VENV=%PROJECT_ROOT%\venv311"
) else if exist "%PROJECT_ROOT%\venv311_new\Scripts\activate.bat" (
    set "VENV=%PROJECT_ROOT%\venv311_new"
) else (
    echo [ERROR] Python virtual environment not found. Expected .venv or venv311.
    echo Please run the following command to create the virtual environment first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements\windows.txt -r requirements\livekit.txt
    exit /b 1
)

call "%VENV%\Scripts\activate.bat"

echo [SIYA] Using virtual environment: %VENV%

REM Set default environment variables
if "%VANI_VOICE_BACKEND%"=="" set "VANI_VOICE_BACKEND=livekit"
if "%VANI_LOW_POWER_UI%"=="" set "VANI_LOW_POWER_UI=1"
if "%VANI_PREWARM_OLLAMA%"=="" set "VANI_PREWARM_OLLAMA=0"
if "%VANI_USE_SILERO%"=="" set "VANI_USE_SILERO=0"
if "%VANI_TEXT_TIMEOUT%"=="" set "VANI_TEXT_TIMEOUT=8"
if "%VANI_REALTIME_TEMPERATURE%"=="" set "VANI_REALTIME_TEMPERATURE=0.65"
if "%VANI_ENDPOINT_MIN_DELAY%"=="" set "VANI_ENDPOINT_MIN_DELAY=0.12"
if "%VANI_ENDPOINT_MAX_DELAY%"=="" set "VANI_ENDPOINT_MAX_DELAY=0.45"
if "%VANI_INTERRUPT_MIN_DURATION%"=="" set "VANI_INTERRUPT_MIN_DURATION=0.18"
if "%VANI_FALSE_INTERRUPT_TIMEOUT%"=="" set "VANI_FALSE_INTERRUPT_TIMEOUT=0.8"
if "%VANI_MAX_SPEECH_DURATION%"=="" set "VANI_MAX_SPEECH_DURATION=8.0"
if "%VANI_WAIT_FOR_SPEECH_PLAYOUT%"=="" set "VANI_WAIT_FOR_SPEECH_PLAYOUT=0"
if "%VANI_TIMEZONE%"=="" set "VANI_TIMEZONE=Asia/Kolkata"
if "%TZ%"=="" set "TZ=Asia/Kolkata"

set "PYTHONPATH=%PROJECT_ROOT%\src;%PYTHONPATH%"

REM Check dependencies
python -c "import importlib, importlib.util, sys; required = ['dotenv', 'livekit', 'livekit.agents', 'livekit.plugins.google', 'livekit.plugins.noise_cancellation', 'livekit.plugins.silero', 'google.genai', 'langchain', 'requests', 'fuzzywuzzy']; missing = [m for m in required if importlib.util.find_spec(m) is None]; sys.exit(1 if missing else 0)" >nul 2>&1

if errorlevel 1 (
    echo [ERROR] Missing required Python packages.
    echo Please run the following command to install dependencies:
    echo     .venv\Scripts\pip install -r requirements\windows.txt -r requirements\livekit.txt
    exit /b 1
)

echo [SIYA] Launching Siya...
python -m vani.launcher
