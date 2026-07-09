@echo off
REM Voice Studio — local Kokoro TTS on http://127.0.0.1:5050
REM First run creates a private venv and installs CPU torch + kokoro.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [..] First run: creating venv and installing dependencies...
    python -m venv .venv || exit /b 1
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)

echo [ok] Starting Voice Studio at http://127.0.0.1:5050
.venv\Scripts\python.exe app.py
