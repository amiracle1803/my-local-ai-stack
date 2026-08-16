@echo off
REM Start the n8n automation service (optional; only needed for email triage).
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
    echo [X] Docker is not installed / not on PATH.
    echo     Install Docker Desktop (free), then re-run this:
    echo        https://www.docker.com/products/docker-desktop/
    pause & exit /b 1
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo [!] Created .env from the example. Open it and set a real N8N_PASSWORD,
    echo     then run this again.
    notepad .env
    pause & exit /b 0
)

echo Starting n8n ...
docker compose up -d
if errorlevel 1 (
    echo [X] Failed to start. Is Docker Desktop running? See docs\TROUBLESHOOTING.md
    pause & exit /b 1
)
echo.
echo [ok] n8n is starting at  http://localhost:5678
echo      First load can take ~30 seconds.
start "" http://localhost:5678
pause
