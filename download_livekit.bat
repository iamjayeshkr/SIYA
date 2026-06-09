@echo off
echo Downloading LiveKit Server (Windows Native)...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/livekit/livekit/releases/download/v1.7.2/livekit_1.7.2_windows_amd64.zip' -OutFile 'livekit-server.zip'"
echo Extracting files...
powershell -Command "Expand-Archive -Path 'livekit-server.zip' -DestinationPath '.'"
echo Cleaning up...
del livekit-server.zip
echo.
echo ==========================================================
echo LiveKit Server downloaded successfully!
echo.
echo To run the server, use:
echo .\livekit-server.exe --dev
echo ==========================================================
echo.
pause
