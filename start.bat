@echo off
REM start.bat — Launch Vani on Windows
setlocal enabledelayedexpansion

echo =========================================
echo Siya OS — Starting up on Windows
echo =========================================

if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment .venv not found.
    echo Please create it first by running:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements\windows.txt -r requirements\livekit.txt
    exit /b 1
)

call bin\run_vani.bat

pause
