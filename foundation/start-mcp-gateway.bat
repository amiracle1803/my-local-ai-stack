@echo off
REM Start Docker MCP Toolkit's gateway (optional; only needed for the
REM brave/github/n8n/etc. catalog servers Agent Atlas's mcp_client.py
REM calls out to). Not required for the rest of the stack.
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
    echo [X] Docker is not installed / not on PATH.
    echo     Install Docker Desktop (free): https://www.docker.com/products/docker-desktop/
    pause & exit /b 1
)

curl -s -m 2 -o nul http://127.0.0.1:8811/sse
if not errorlevel 1 (
    echo [ok] MCP gateway is already running at http://127.0.0.1:8811
    goto :eof
)

REM This token only guards localhost:8811 against other processes/sites on
REM this machine making requests to the gateway (DNS-rebinding protection)
REM -- it is NOT a credential for brave/github/n8n themselves. Those need
REM their own secrets, set once via:
REM   docker mcp secret set brave.api_key=<your Brave Search API key>
REM   docker mcp secret set github.personal_access_token=<your PAT>
REM   docker mcp secret set n8n.api_key=<your n8n API key>
set MCP_GATEWAY_AUTH_TOKEN=agent-atlas-dev-fixed-token-12345

echo Starting MCP gateway (profile: amir_ai_agents) on port 8811...
start "MCP Gateway" /min docker mcp gateway run --profile amir_ai_agents --transport sse --port 8811
timeout /t 4 /nobreak >nul
echo [ok] MCP gateway starting at http://127.0.0.1:8811/sse
echo      Servers without a configured secret will return a clear error when
echo      called, not silently fail -- see the docker mcp secret set commands above.
