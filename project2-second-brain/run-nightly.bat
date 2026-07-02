@echo off
REM Quiet runner for the scheduler. Appends output to nightly.log.
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\.venv\Scripts\python.exe" ( exit /b 1 )
"%ROOT%\.venv\Scripts\python.exe" "%~dp0run_nightly.py" >> "%~dp0nightly.log" 2>&1
