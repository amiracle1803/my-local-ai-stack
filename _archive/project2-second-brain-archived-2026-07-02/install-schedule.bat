@echo off
REM Schedule the nightly brain review for 2:00 AM every day.
REM
REM By default this runs while you are logged in. To make it run even when
REM logged out, open Task Scheduler, find "AIStack-SecondBrain-Nightly",
REM and tick "Run whether user is logged on or not" (it will ask for your
REM Windows password). Also tick "Wake the computer to run this task" if you
REM want it to run overnight while the PC sleeps.
setlocal
set TASKNAME=AIStack-SecondBrain-Nightly
schtasks /Create /TN "%TASKNAME%" /TR "\"%~dp0run-nightly.bat\"" /SC DAILY /ST 02:00 /F
if errorlevel 1 (
  echo [X] Could not create the task. Try running this file as Administrator.
) else (
  echo [ok] Scheduled "%TASKNAME%" daily at 02:00.
  echo      Test it now with: start.bat   Remove it with: uninstall-schedule.bat
)
pause
