@echo off
REM ==========================================================================
REM  setup.bat  --  Run me ONCE. Sets up everything the three projects share.
REM
REM  What it does:
REM    1. Checks that Ollama and Python are installed (tells you where to get
REM       them if not).
REM    2. Creates a Python virtual environment in .venv
REM    3. Installs the lean base requirements.
REM    4. Pulls the chat + embedding models.
REM    5. Creates config.json from the example if you don't have one.
REM ==========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Local AI Stack - one-time setup
echo ============================================================
echo.

REM --- 1. Ollama -----------------------------------------------------------
where ollama >nul 2>nul
if errorlevel 1 (
    echo [X] Ollama is not installed or not on your PATH.
    echo     Download and install it, then re-run setup.bat:
    echo        https://ollama.com/download
    echo.
    pause
    exit /b 1
)
echo [ok] Ollama found.

REM --- 2. Python -----------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [X] Python is not installed or not on your PATH.
    echo     Install Python 3.11 or newer (tick "Add python.exe to PATH"):
    echo        https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo [ok] Python found.

REM --- 3. Virtual environment ---------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [..] Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [X] Could not create the virtual environment.
        pause
        exit /b 1
    )
)
echo [ok] Virtual environment ready.

echo [..] Upgrading pip and installing base requirements ^(this can take a few minutes^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [X] Installing requirements failed. Check your internet connection and
    echo     re-run setup.bat. See docs\TROUBLESHOOTING.md if it keeps failing.
    pause
    exit /b 1
)
echo [ok] Python packages installed.

REM --- 4. Models -----------------------------------------------------------
echo.
echo [..] Pulling models. First time downloads a few GB - grab a coffee.
echo      (Skips instantly if you already have them.)
for /f "usebackq tokens=* delims=" %%M in (`".venv\Scripts\python.exe" -c "from shared.lib.config import load_config as c;x=c();print(x['chat_model']);print(x['embed_model'])"`) do (
    echo     pulling %%M ...
    ollama pull %%M
)

REM --- 5. config.json ------------------------------------------------------
if not exist "config.json" (
    copy /y "config.example.json" "config.json" >nul
    echo [ok] Created config.json  ^(edit "vault_path" to point at your Obsidian vault^)
) else (
    echo [ok] config.json already exists - leaving it alone.
)

echo.
echo ============================================================
echo   Setup complete.
echo ============================================================
echo   Next:
echo     - Edit config.json and set "vault_path" to your Obsidian vault
echo       (or leave it to use the sample vault in .\vault).
echo     - Or just run start.bat -- it brings up the whole stack, including
echo       the unified dashboard, in one go.
echo     - Individual projects also still have their own start.bat if you
echo       want to run just one:
echo         apps\project1-ops-hub\start.bat        (task dropbox)
echo         apps\project2-second-brain\start.bat   (nightly brain review)
echo         apps\project3-automation\start.bat     (research + automation)
echo     - Read docs\GUIDE.md for the full walkthrough.
echo.
pause
