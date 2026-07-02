@echo off
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\.venv\Scripts\python.exe" ( exit /b 1 )
"%ROOT%\.venv\Scripts\python.exe" "%~dp0research.py" >> "%~dp0research.log" 2>&1
