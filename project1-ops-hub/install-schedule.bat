@echo off
REM OPTIONAL: check the task-inbox folder every 5 minutes automatically.
REM Runs while you're logged in. To run when logged out, open Task Scheduler
REM and tick "Run whether user is logged on or not" (needs your password).
setlocal
set TASKNAME=AIStack-TaskInbox
schtasks /Create /TN "%TASKNAME%" /TR "\"%~dp0run-inbox.bat\"" /SC MINUTE /MO 5 /F
if errorlevel 1 (
  echo [X] Could not create the scheduled task. Try running this file as Administrator.
) else (
  echo [ok] Scheduled "%TASKNAME%" to run every 5 minutes.
  echo      Remove it any time with uninstall-schedule.bat
)
pause
