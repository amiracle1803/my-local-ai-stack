@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\activate.bat" (
    echo  [ERROR] No venv found. Run setup.bat first.
    pause & exit /b 1
)
call venv\Scripts\activate.bat
python app.py
pause
