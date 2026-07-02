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
REM    4. Starts Agent Atlas (its FastAPI backend also serves its own UI,
REM       embedded at /agents in the dashboard). Lightweight -- doesn't load
REM       GPU models itself, just calls out to Ollama/LM Studio, so it's
REM       safe to always auto-start.
REM    5. Starts Obsidian (not GPU-heavy, but AnythingLLM's MCP vault access
REM       depends on its Local REST API plugin, which only runs while the
REM       app itself is open).
REM    6. Checks (but does NOT auto-start) the GPU-heavy apps: Voice Studio,
REM       ComfyUI, LM Studio, AnythingLLM. These load multi-GB models onto
REM       an 8GB laptop GPU -- auto-launching all of them at once alongside
REM       Ollama has actually driven this machine down to ~400MB free VRAM
REM       before. Start them yourself, only when you need them.
REM    7. Starts the unified dashboard and opens it in your browser.
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
REM Check n8n itself FIRST -- `where docker` can fail to find docker.exe on
REM PATH even when Docker Desktop (and n8n inside it) is already running.
curl -s -m 2 http://localhost:5678/healthz >nul 2>nul
if not errorlevel 1 (
    echo [ok] n8n is running.
) else (
    where docker >nul 2>nul
    if errorlevel 1 (
        echo [..] Docker not found -- skipping n8n ^(optional, see foundation\README.md^).
    ) else (
        if exist "foundation\.env" (
            echo [..] Starting n8n...
            pushd foundation
            docker compose up -d >nul 2>nul
            popd
        ) else (
            echo [..] n8n not configured yet -- run foundation\start-n8n.bat once to set it up.
        )
    )
)

REM --- 4. Agent Atlas (lightweight -- always auto-start) --------------------
curl -s -m 2 http://127.0.0.1:8000/api/health >nul 2>nul
if errorlevel 1 (
    if exist "apps\agent-atlas\backend\.venv\Scripts\python.exe" (
        echo [..] Starting Agent Atlas...
        start "Agent Atlas" cmd /c "cd /d "%~dp0apps\agent-atlas\backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
        timeout /t 3 /nobreak >nul
    ) else (
        echo [!] Agent Atlas isn't set up yet -- see apps\agent-atlas\README.md.
        echo     The dashboard's Agents tab and MCP-routed tasks won't work until it is.
    )
) else (
    echo [ok] Agent Atlas is running.
)

REM --- 5. Obsidian (lightweight -- always auto-start) ------------------------
REM Not GPU-heavy (no AI models loaded), but AnythingLLM's MCP connection to
REM the vault depends on Obsidian's Local REST API plugin, which only runs
REM while the app itself is open -- so this needs to come up every time.
curl -s -m 2 http://127.0.0.1:27123/ >nul 2>nul
if errorlevel 1 (
    echo [..] Starting Obsidian...
    start "" "shell:AppsFolder\md.obsidian"
    timeout /t 5 /nobreak >nul
) else (
    echo [ok] Obsidian is running.
)

REM --- 6. GPU-heavy apps: check status only, don't auto-start ---------------
echo.
echo [i] GPU-heavy apps ^(start manually when you need them -- see comment above^):
curl -s -m 2 http://127.0.0.1:5050/api/health >nul 2>nul
if errorlevel 1 (
    echo     [ ] Voice Studio    -- cd voice-studio ^&^& start.bat
) else (
    echo     [ok] Voice Studio   -- http://127.0.0.1:5050
)
curl -s -m 2 http://127.0.0.1:8188/system_stats >nul 2>nul
if errorlevel 1 (
    echo     [ ] ComfyUI         -- see CLAUDE.md for the launch command ^(needs --novram flags^)
) else (
    echo     [ok] ComfyUI        -- http://127.0.0.1:8188
)
curl -s -m 2 http://127.0.0.1:1234/v1/models >nul 2>nul
if errorlevel 1 (
    echo     [ ] LM Studio       -- open the LM Studio desktop app
) else (
    echo     [ok] LM Studio      -- http://127.0.0.1:1234
)
curl -s -m 2 http://127.0.0.1:3001/api/ping >nul 2>nul
if errorlevel 1 (
    echo     [ ] AnythingLLM     -- open the AnythingLLM desktop app
) else (
    echo     [ok] AnythingLLM    -- http://127.0.0.1:3001
)
curl -s -m 2 http://127.0.0.1:8811/sse >nul 2>nul
if errorlevel 1 (
    echo     [ ] MCP Gateway     -- optional, only for Agent Atlas's brave/github/n8n
    echo                            tools -- foundation\start-mcp-gateway.bat
) else (
    echo     [ok] MCP Gateway    -- http://127.0.0.1:8811
)

REM --- 7. Dashboard ----------------------------------------------------------
echo.
echo [ok] Starting the dashboard...
echo      Open your browser at:  http://localhost:8750
echo      (Press Ctrl+C in this window to stop the dashboard.)
echo.
start "" http://localhost:8750
".venv\Scripts\python.exe" "apps\project1-ops-hub\app.py"
pause
