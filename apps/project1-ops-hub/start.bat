@echo off
REM Project 1 - Task Dropbox web app.
REM Opens a local web page you type tasks into.
setlocal
set ROOT=%~dp0..

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [X] Setup hasn't been run yet. From the main folder, run: setup.bat
    pause
    exit /b 1
)

echo Starting Task Dropbox...
echo Open your browser at:  http://localhost:8750
echo (Press Ctrl+C in this window to stop.)
echo.
start "" http://localhost:8750
"%ROOT%\.venv\Scripts\python.exe" "%~dp0app.py"
pause
