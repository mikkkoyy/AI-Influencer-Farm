@echo off
chcp 65001 >nul
title AI Influencer Farm - Health Check
echo ============================================================
echo AI Influencer Farm - Health Check
echo ============================================================
echo.

REM Check if backend is running
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Backend is not running or not accessible.
    echo.
    echo Troubleshooting:
    echo 1. Make sure the backend is started (run start.bat)
    echo 2. Check if port 8000 is available
    echo 3. Check logs in logs/ directory
    pause
    exit /b 1
)

echo [OK] Backend is running.
echo.

REM Get health details
curl -s http://localhost:8000/health
echo.
echo.

REM Check Python dependencies
echo Checking Python dependencies...
.venv\Scripts\python.exe -c "import fastapi, sqlalchemy, httpx, edge_tts, faster_whisper; print('[OK] All core dependencies available')" 2>nul
if errorlevel 1 (
    echo [FAIL] Some dependencies are missing. Run install.bat to reinstall.
)

REM Check Ollama
echo.
echo Checking Ollama...
ollama list >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Ollama is not installed or not in PATH.
) else (
    echo [OK] Ollama is available.
    ollama list
)

REM Check FFmpeg
echo.
echo Checking FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] FFmpeg is not installed or not in PATH.
) else (
    echo [OK] FFmpeg is available.
)

echo.
echo ============================================================
echo Health Check Complete
echo ============================================================
pause
