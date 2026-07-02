@echo off
rem atlas-bridge.bat — Connect LLM Wiki to Agent Atlas
rem
rem Usage:
rem   atlas-bridge status                          Check if Atlas is running
rem   atlas-bridge run "your task here"            Submit task (sync)
rem   atlas-bridge run "your task" --background    Submit as background job
rem   atlas-bridge jobs                            Show recent jobs
rem   atlas-bridge agents                          List all 18 agents
rem   atlas-bridge search "query"                  Search Obsidian vault via Atlas
rem   atlas-bridge reindex                         Re-index vault in Atlas
rem
rem Set ATLAS_URL env var to change the Agent Atlas endpoint (default: http://localhost:8000)
rem
python "%~dp0tools\atlas_bridge.py" %*
