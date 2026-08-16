@echo off
setlocal
cd /d "%~dp0"
echo Stopping n8n ^(your workflows and data are kept^)...
docker compose down
echo Done.
pause
