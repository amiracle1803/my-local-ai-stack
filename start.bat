@echo off
REM ==========================================================================
REM  start.bat  --  The ONE button. Run this every time you want to use the
REM  stack. (setup.bat is the one-time installer; this is for daily use.)
REM
REM  What it does:
REM    1. Checks setup has been run (.venv exists) -- tells you to run
REM       setup.bat if not.
REM    2. Checks Ollama is reachable; starts it if it's installed but not
REM       running.
REM    3. Starts n8n (Docker) if Docker is available and not already running.
REM       Skipped silently if Docker isn't installed -- it's optional.
REM    4. Starts the unified dashboard and opens it in your browser.
REM ==========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   Local AI Stack
echo ============================================================
echo.

REM --- 1. Setup check ---------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [X] Setup hasn't been run yet.
    echo     Run setup.bat first, then come back and run start.bat.
    echo.
    pause
    exit /b 1
)

REM --- 2. Ollama -----------------------------------------------------------
curl -s -m 2 http://localhost:11434/api/version >nul 2>nul
if errorlevel 1 (
    where ollama >nul 2>nul
    if errorlevel 1 (
        echo [!] Ollama isn't installed. Get it from https://ollama.com/download
        echo     The dashboard will still open, but tasks won't work until it's running.
    ) else (
        echo [..] Ollama isn't running -- starting it...
        start "" "ollama" serve
        timeout /t 3 /nobreak >nul
    )
) else (
    echo [ok] Ollama is running.
)

REM --- 3. n8n (optional, Docker) --------------------------------------------
where docker >nul 2>nul
if errorlevel 1 (
    echo [..] Docker not found -- skipping n8n ^(optional, see foundation\README.md^).
) else (
    curl -s -m 2 http://localhost:5678/healthz >nul 2>nul
    if errorlevel 1 (
        if exist "foundation\.env" (
            echo [..] Starting n8n...
            pushd foundation
            docker compose up -d >nul 2>nul
            popd
        ) else (
            echo [..] n8n not configured yet -- run foundation\start-n8n.bat once to set it up.
        )
    ) else (
        echo [ok] n8n is running.
    )
)

REM --- 4. Dashboard ----------------------------------------------------------
echo.
echo [ok] Starting the dashboard...
echo      Open your browser at:  http://localhost:8750
echo      (Press Ctrl+C in this window to stop the dashboard.)
echo.
start "" http://localhost:8750
".venv\Scripts\python.exe" "project1-ops-hub\app.py"
pause
