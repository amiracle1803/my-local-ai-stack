@echo off
REM Process every task file dropped in task-inbox\ then move them to done\.
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [X] Run setup.bat first.
    pause & exit /b 1
)
"%ROOT%\.venv\Scripts\python.exe" "%~dp0run_inbox.py" >> "%~dp0inbox.log" 2>&1
type "%~dp0inbox.log"
