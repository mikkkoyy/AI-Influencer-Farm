@echo off
chcp 65001 >nul
title AI Influencer Farm - Stopping
echo ============================================================
echo AI Influencer Farm - Stopping Backend
echo ============================================================
echo.

echo Stopping backend processes...
setlocal enabledelayedexpansion
for /f "tokens=2 delims=," %%p in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV /NH 2^>nul') do (
    set "PID=%%~p"
    echo Stopping PID: !PID!
    taskkill /F /PID !PID! >nul 2>&1
)
endlocal

echo.
echo [OK] Backend stopped.
pause
