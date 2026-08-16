@echo off
rem server.bat — Start the LLM Wiki (API + React UI)
rem
rem  API server:   http://localhost:7337  (FastAPI JSON)
rem  React UI:     http://localhost:7338  (Vite dev server)
rem
rem Usage:
rem   server.bat          Start everything and open the browser
rem   server.bat --build  Build the React app for production first
rem
cd /d "%~dp0"
set "WIKI_ROOT=%~dp0"
set "FRONTEND=%WIKI_ROOT%frontend"
set "API_PORT=7337"
set "UI_PORT=7338"
set "UI_URL=http://localhost:%UI_PORT%"
set "API_URL=http://localhost:%API_PORT%"

rem ── Handle --build flag ──────────────────────────────────────────────────────
if "%1"=="--build" (
    echo Building React frontend...
    pushd "%FRONTEND%"
    if not exist node_modules (
        echo Installing dependencies...
        npm install --silent
    )
    npm run build
    popd
    echo Build complete. Open %API_URL% to use the production app.
    echo.
)

rem ── Check if API is already running ─────────────────────────────────────────
netstat -an | findstr ":%API_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [INFO] API already running at %API_URL%
    goto start_frontend
)

echo Starting LLM Wiki API server at %API_URL%...
start "LLM Wiki - API" /d "%WIKI_ROOT%" cmd /k python tools\server.py
timeout /t 2 /nobreak >nul

:start_frontend
rem ── Check if React dev server is already running ─────────────────────────────
netstat -an | findstr ":%UI_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [INFO] React UI already running at %UI_URL%
    goto open_browser
)

if not exist "%FRONTEND%\package.json" (
    echo [WARN] frontend\package.json not found.
    echo        Using production build at %API_URL% instead.
    set "UI_URL=%API_URL%"
    goto open_browser
)

if not exist "%FRONTEND%\node_modules" (
    echo Installing npm dependencies...
    pushd "%FRONTEND%"
    npm install --silent
    popd
)

echo Starting LLM Wiki React UI at %UI_URL%...
start "LLM Wiki - Frontend" /d "%FRONTEND%" cmd /k npm run dev
timeout /t 3 /nobreak >nul

:open_browser
echo Opening %UI_URL%...
start "" "%UI_URL%"
