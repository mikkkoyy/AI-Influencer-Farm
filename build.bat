@echo off
chcp 65001 >nul
title AI Influencer Farm - Build
echo ============================================================
echo AI Influencer Farm - Build Script
echo ============================================================
echo.

REM Check if virtual environment exists
if not exist .venv\Scripts\python.exe (
    echo [ERROR] Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Run tests
echo Running tests...
python -m pytest tests/ -v
if errorlevel 1 (
    echo [WARN] Some tests failed. Continuing with build...
) else (
    echo [OK] All tests passed.
)

REM Initialize database
echo.
echo Initializing database...
python -c "from core.db import init_db; init_db()"
if errorlevel 1 (
    echo [FAIL] Database initialization failed.
    pause
    exit /b 1
)
echo [OK] Database initialized.

REM Create distribution package
echo.
echo Creating distribution package...
if exist dist rmdir /S /Q dist
mkdir dist

REM Copy essential files
xcopy /E /I /Y *.py dist\
xcopy /E /I /Y config\* dist\config\
xcopy /E /I /Y core\* dist\core\
xcopy /E /I /Y dashboard\* dist\dashboard\
xcopy /E /I /Y pipeline\* dist\pipeline\
xcopy /E /I /Y bot\* dist\bot\
xcopy /E /I /Y scripts\* dist\scripts\
xcopy /E /I /Y storage\* dist\storage\
xcopy /E /I /Y music\* dist\music\
xcopy /E /I /Y tests\* dist\tests\

REM Copy batch files
copy install.bat dist\
copy start.bat dist\
copy stop.bat dist\
copy health-check.bat dist\
copy build.bat dist\

REM Copy requirements and docs
copy requirements.txt dist\
copy README.md dist\
copy .env.example dist\

echo.
echo [OK] Build complete. Distribution is in dist/ directory.
echo.
pause
