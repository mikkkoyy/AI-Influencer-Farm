@echo off
chcp 65001 >nul
title AI Influencer Farm - Installer
echo ============================================================
echo AI Influencer Farm - Windows Installation
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required but not found.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python found.

REM Check Git
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git is required but not found.
    echo Download from: https://git-scm.com/download/win
    pause
    exit /b 1
)
echo [OK] Git found.

REM Check FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARN] FFmpeg not found in PATH.
    echo Download from: https://ffmpeg.org/download.html
    echo Extract to a folder and add to PATH, or place ffmpeg.exe in this directory.
    choice /C YN /M "Continue anyway"
) else (
    echo [OK] FFmpeg found.
)

REM Check Ollama
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Ollama not found in PATH.
    echo Download from: https://ollama.com/download
    choice /C YN /M "Continue anyway"
) else (
    echo [OK] Ollama found.
)

REM Create virtual environment
echo.
echo Creating Python virtual environment...
if exist .venv (
    echo [INFO] .venv already exists, skipping.
) else (
    python -m venv .venv
    echo [OK] Virtual environment created.
)

REM Activate and install dependencies
echo.
echo Installing Python dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

REM Create .env if not exists
if not exist .env (
    echo.
    echo Creating .env from .env.example...
    copy .env.example .env
    echo [OK] .env created. Please edit it before running the application.
) else (
    echo [OK] .env already exists.
)

REM Create required directories
echo.
echo Creating required directories...
if not exist storage\cookies mkdir storage\cookies
if not exist storage\backups mkdir storage\backups
if not exist storage\output mkdir storage\output
if not exist storage\image_cache mkdir storage\image_cache
if not exist config\prompts mkdir config\prompts
if not exist logs mkdir logs
echo [OK] Directories created.

REM Pull default Ollama model
echo.
echo Checking Ollama models...
ollama list | findstr "qwen2.5" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Pulling default Ollama model qwen2.5:0.5b (this may take a while)...
    ollama pull qwen2.5:0.5b
) else (
    echo [OK] Default Ollama model already installed.
)

echo.
echo ============================================================
echo Installation Complete!
echo ============================================================
echo.
echo Next steps:
echo 1. Edit .env to configure your settings
echo 2. Run start.bat to launch the application
echo 3. Open http://localhost:8000 in your browser
echo.
pause
