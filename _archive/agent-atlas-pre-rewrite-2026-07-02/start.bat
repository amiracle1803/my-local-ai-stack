@echo off
title Agent Atlas
color 0B

set "ROOT=%~dp0"
set "BACK=%ROOT%backend"
set "FRONT=%ROOT%frontend"
set "PY=%ROOT%backend\.venv\Scripts\python.exe"

echo.
echo  ============================================
echo   Agent Atlas  ^|  Local Multi-Agent System
echo  ============================================
echo.

:: Verify Python venv
if not exist "%PY%" (
    echo  [ERROR] Python venv not found at:
    echo          %PY%
    echo.
    echo  Run this first:
    echo    cd backend
    echo    python -m venv .venv
    echo    .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:: Verify node_modules
if not exist "%FRONT%\node_modules" (
    echo  [ERROR] Frontend dependencies missing.
    echo          Run:  cd frontend ^&^& npm install
    echo.
    pause
    exit /b 1
)

echo  Starting Backend  (FastAPI  ^|  http://localhost:8000)
start "Atlas Backend" cmd /k "cd /d "%BACK%" && "%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo  Waiting for backend...
timeout /t 6 /nobreak >nul

echo  Starting Frontend (Vite     ^|  http://localhost:5173)
start "Atlas Frontend" cmd /k "cd /d "%FRONT%" && npm run dev"

echo  Waiting for frontend to compile...
timeout /t 8 /nobreak >nul

echo.
echo  ============================================
echo   Ready!
echo.
echo   UI       :  http://localhost:5173
echo   API      :  http://localhost:8000
echo   API Docs :  http://localhost:8000/docs
echo  ============================================
echo.

start "" "http://localhost:5173"
exit
