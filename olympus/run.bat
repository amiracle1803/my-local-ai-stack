@echo off
REM Start the Olympus kernel directly (start.bat at repo root does this too).
cd /d "%~dp0"
..\.venv\Scripts\python.exe -m uvicorn kernel.app:app --host 0.0.0.0 --port 4600
