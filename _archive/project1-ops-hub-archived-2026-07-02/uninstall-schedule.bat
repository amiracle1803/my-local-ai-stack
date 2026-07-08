@echo off
setlocal
schtasks /Delete /TN "AIStack-TaskInbox" /F
echo Done.
pause
