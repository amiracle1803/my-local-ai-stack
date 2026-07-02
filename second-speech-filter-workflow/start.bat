@echo off
title Speech Filter
color 0A
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo  [ERROR] Virtual environment not found.
    echo         Run setup.bat first.
    pause & exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo  ==========================================
echo   Speech Filter  ^|  F5-TTS Audio Cleaner
echo   GPU Accelerated  ^|  RTX 4070
echo  ==========================================
echo.
echo  Starting at http://localhost:5001
echo.

python app.py
pause
