@echo off
chcp 65001 >nul
title AI Influencer Farm - Starting
echo ============================================================
echo AI Influencer Farm - Starting Backend
echo ============================================================
echo.

REM Check if virtual environment exists
if not exist .venv\Scripts\python.exe (
    echo [ERROR] Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)

REM Check if already running
tasklist /FI "WINDOWTITLE eq AI Influencer Farm*" 2>nul | find /I /N "AI Influencer Farm">nul
if "%ERRORLEVEL%"=="0" (
    echo [WARN] Application may already be running.
    choice /C YN /M "Force start anyway"
)

REM Start backend in background
echo Starting backend...
start "AI Influencer Farm" /B .venv\Scripts\python.exe main.py

REM Wait for backend to start
echo Waiting for backend to start...
timeout /t 5 /nobreak >nul

REM Check health
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Backend did not start properly. Check logs for details.
    pause
    exit /b 1
)

REM Open dashboard
echo.
echo [OK] Backend started successfully!
echo Dashboard: http://localhost:8000
echo.
echo Press any key to open dashboard in browser...
pause >nul

start http://localhost:8000

echo.
echo Backend is running. Close this window to stop the application.
echo Or run stop.bat to stop it gracefully.
pause
