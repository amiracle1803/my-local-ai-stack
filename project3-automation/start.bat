@echo off
REM Project 3 - Always-On Automation. Simple menu to run a job right now.
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [X] Run setup.bat in the main folder first.
    pause & exit /b 1
)

:menu
echo.
echo ============================================
echo   Project 3 - Automation
echo ============================================
echo   1. Run research digest now (reads feeds.txt)
echo   2. Run repo digest now (reads "repos" in config.json)
echo   3. Email triage (setup instructions)
echo   4. Exit
echo.
set /p choice="Pick 1-4: "

if "%choice%"=="1" (
    "%ROOT%\.venv\Scripts\python.exe" "%~dp0research.py"
    pause & goto menu
)
if "%choice%"=="2" (
    "%ROOT%\.venv\Scripts\python.exe" "%~dp0repo_digest.py"
    pause & goto menu
)
if "%choice%"=="3" (
    start "" "%~dp0n8n\README-email.md"
    goto menu
)
if "%choice%"=="4" exit /b 0
goto menu
