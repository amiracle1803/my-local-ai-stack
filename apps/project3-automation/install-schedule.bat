@echo off
REM Schedule the automations:
REM   - research digest every 3 hours
REM   - repo digest once a day at 6 PM
REM Both run while you're logged in. See notes in Project 2's install-schedule.bat
REM for how to make them run when logged out.
setlocal
schtasks /Create /TN "AIStack-Research" /TR "\"%~dp0run-research.bat\"" /SC HOURLY /MO 3 /F
schtasks /Create /TN "AIStack-RepoDigest" /TR "\"%~dp0run-digest.bat\"" /SC DAILY /ST 18:00 /F
echo.
echo [ok] Scheduled: AIStack-Research (every 3h), AIStack-RepoDigest (daily 18:00).
echo      Remove them with uninstall-schedule.bat
pause
