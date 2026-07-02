@echo off
REM Project 2 - Second Brain. Runs one review pass right now (extract + summarise).
REM Great for testing. For automatic nightly runs, use install-schedule.bat.
setlocal
set ROOT=%~dp0..
if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [X] Run setup.bat in the main folder first.
    pause & exit /b 1
)
echo Running the second-brain nightly pass now...
echo (Reads notes changed since last run, files tasks/decisions/insights,
echo  and writes a Daily Review into your vault's _generated folder.)
echo.
"%ROOT%\.venv\Scripts\python.exe" "%~dp0run_nightly.py"
echo.
echo Look in your vault under _generated\ for the results.
pause
