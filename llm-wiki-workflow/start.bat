@echo off
cd /d "%~dp0"
title AI System Launcher
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

rem =========================================================
rem  Paths
rem =========================================================
set "WIKI_ROOT=%~dp0"
set "WIKI_FRONTEND=%WIKI_ROOT%frontend"
set "WIKI_API=http://localhost:7337"
set "WIKI_UI=http://localhost:7338"

set "ATLAS_ROOT=C:\Users\amire\Desktop\new ai agent work flow project\agent-atlas"
set "ATLAS_BACKEND=%ATLAS_ROOT%\backend"
set "ATLAS_FRONTEND=%ATLAS_ROOT%\frontend"
set "ATLAS_PYTHON=%ATLAS_BACKEND%\.venv\Scripts\python.exe"
set "ATLAS_URL=http://localhost:8000"
set "ATLAS_UI=http://localhost:5173"

echo.
echo  =====================================================
echo   AI System Launcher
echo   Agent Atlas  +  LLM Wiki  +  Obsidian
echo  =====================================================
echo.

rem =========================================================
rem  Pre-flight checks
rem =========================================================
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.8+ and add to PATH.
    pause & exit /b 1
)

if not exist "%ATLAS_ROOT%" (
    echo [WARN] Agent Atlas not found at:
    echo        %ATLAS_ROOT%
    echo        Agent Atlas services will be skipped.
    set "SKIP_ATLAS=1"
)

if "%ANTHROPIC_API_KEY%"=="" (
    echo [WARN] ANTHROPIC_API_KEY not set.
    echo        Wiki watcher and agent-cli will not call Claude.
    echo        Set it with:  set ANTHROPIC_API_KEY=sk-ant-...
    echo.
)

rem =========================================================
rem  [1/7] Agent Atlas Backend
rem =========================================================
if defined SKIP_ATLAS goto skip_atlas_backend

echo [1/7] Starting Agent Atlas backend (port 8000)...
if exist "%ATLAS_PYTHON%" (
    start "Agent Atlas - Backend" /d "%ATLAS_BACKEND%" cmd /k "%ATLAS_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
) else (
    echo        No venv found, using system Python...
    start "Agent Atlas - Backend" /d "%ATLAS_BACKEND%" cmd /k python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
)
timeout /t 6 /nobreak >nul

:skip_atlas_backend

rem =========================================================
rem  [2/7] Agent Atlas Frontend
rem =========================================================
if defined SKIP_ATLAS goto skip_atlas_frontend

echo [2/7] Starting Agent Atlas frontend (port 5173)...
start "Agent Atlas - Frontend" /d "%ATLAS_FRONTEND%" cmd /k npm run dev
timeout /t 4 /nobreak >nul

:skip_atlas_frontend

rem =========================================================
rem  [3/7] LLM Wiki index + lint
rem =========================================================
echo [3/7] Rebuilding wiki index...
python tools\wiki.py index
if %errorlevel% neq 0 (
    echo [ERROR] wiki index failed.
    pause & exit /b 1
)
python tools\wiki.py lint
if %errorlevel% neq 0 (
    echo [WARN] Lint issues found (see above).
)

rem =========================================================
rem  [4/7] LLM Wiki API server (port 7337)
rem =========================================================
echo [4/7] Starting LLM Wiki API server (port 7337)...
start "LLM Wiki - API" /d "%WIKI_ROOT%" cmd /k python tools\server.py
timeout /t 3 /nobreak >nul

rem =========================================================
rem  [5/7] LLM Wiki React frontend (port 7338)
rem =========================================================
echo [5/7] Starting LLM Wiki React UI (port 7338)...
if exist "%WIKI_FRONTEND%\package.json" (
    if not exist "%WIKI_FRONTEND%\node_modules" (
        echo        node_modules not found, running npm install...
        pushd "%WIKI_FRONTEND%"
        npm install --silent
        popd
    )
    start "LLM Wiki - Frontend" /d "%WIKI_FRONTEND%" cmd /k npm run dev
    timeout /t 4 /nobreak >nul
) else (
    echo [WARN] frontend\package.json not found, skipping React UI.
    set "WIKI_UI=%WIKI_API%"
)

rem =========================================================
rem  [6/7] Background services (watcher + Obsidian sync)
rem =========================================================
echo [6/7] Starting background services...

if not "%ANTHROPIC_API_KEY%"=="" (
    start "LLM Wiki - Watcher" /d "%WIKI_ROOT%" cmd /k python tools\watcher.py --interval 15
)

if exist "%USERPROFILE%\Documents\Obsidian Vault" (
    start "LLM Wiki - Obsidian Sync" /d "%WIKI_ROOT%" cmd /k python tools\obsidian_sync.py --watch --interval 10 -q
)

rem =========================================================
rem  [7/7] Open browsers
rem =========================================================
echo [7/7] Opening web UIs...
timeout /t 2 /nobreak >nul

if not defined SKIP_ATLAS (
    start "" "%ATLAS_UI%"
    timeout /t 1 /nobreak >nul
)
start "" "%WIKI_UI%"

rem =========================================================
rem  Summary
rem =========================================================
echo.
echo  =====================================================
echo   Everything is running
echo  =====================================================
echo.
if not defined SKIP_ATLAS (
    echo   Agent Atlas UI   %ATLAS_UI%
    echo   Agent Atlas API  %ATLAS_URL%
    echo   API Docs         %ATLAS_URL%/docs
    echo.
)
echo   LLM Wiki UI      %WIKI_UI%  (React)
echo   LLM Wiki API     %WIKI_API%
echo   Obsidian sync    Atlas\Knowledge\ (live)
if not "%ANTHROPIC_API_KEY%"=="" (
    echo   Watcher          monitoring raw\ every 15s
)
echo.
echo  -------------------------------------------------------
echo   Quick commands (run in a new terminal):
echo.
echo   atlas-bridge status           Check Agent Atlas
echo   atlas-bridge run "task"       Submit a task to Atlas
echo   atlas-bridge jobs             View running jobs
echo.
echo   agent-cli ingest raw\articles\file.md
echo   agent-cli query "question"
echo   wiki-cli search "term"
echo  =====================================================
echo.
echo  Starting Claude Code...
echo.
claude
