@echo off
setlocal
schtasks /Delete /TN "AIStack-Research" /F
schtasks /Delete /TN "AIStack-RepoDigest" /F
echo Done.
pause
