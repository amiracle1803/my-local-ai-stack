@echo off
REM Start Langfuse (optional; LLM call tracing/observability for Agent
REM Atlas). Not required for the rest of the stack.
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
    echo [X] Docker is not installed / not on PATH.
    echo     Install Docker Desktop: https://www.docker.com/products/docker-desktop/
    pause & exit /b 1
)

curl -s -m 2 -o nul http://127.0.0.1:3030
if not errorlevel 1 (
    echo [ok] Langfuse is already running at http://127.0.0.1:3030
    goto :eof
)

echo Starting Langfuse (this pulls ~2 images on first run, may take a minute)...
docker compose -f docker-compose-langfuse.yml up -d
if errorlevel 1 (
    echo [X] Failed to start. Is Docker Desktop running?
    pause & exit /b 1
)
echo.
echo [ok] Langfuse starting at  http://localhost:3030
echo      Login: local@agent-atlas.local / agent-atlas-local-dev-password
echo      First boot runs DB migrations -- give it ~30 seconds.
start "" http://localhost:3030
pause
