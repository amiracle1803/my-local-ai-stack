@echo off
:: watcher.bat — Auto-ingest new files dropped into raw/
::
:: Usage:
::   watcher.bat                      poll every 10 seconds
::   watcher.bat --interval 30        poll every 30 seconds
::   watcher.bat --dry-run            detect only, no ingest
::   watcher.bat --once               single scan, then exit
::
:: Requires ANTHROPIC_API_KEY in your environment.
::
python "%~dp0tools\watcher.py" %*
