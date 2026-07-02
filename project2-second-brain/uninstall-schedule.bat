@echo off
setlocal
schtasks /Delete /TN "AIStack-SecondBrain-Nightly" /F
echo Done.
pause
