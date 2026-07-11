#!/usr/bin/env bash
# ==========================================================================
#  start.sh  --  Linux equivalent of start.bat. The ONE button for daily use.
#
#  Mirrors start.bat:
#    1. Setup check (.venv exists)
#    2. Ollama up (systemd user unit or direct spawn)
#    3. n8n via podman (optional)
#    4. Olympus kernel      :4600
#    5. OpenCode MCP        :4720
#    6. Obsidian (flatpak)
#    7. GPU-heavy apps: status check only, never auto-start
#       (ComfyUI, Voice Studio, LM Studio, AnythingLLM -- 8GB VRAM budget)
#    8. Print the hub URL
# ==========================================================================
set -u
cd "$(dirname "$0")"

up() { curl -s -m 2 -o /dev/null "$1"; }   # 0 = reachable

echo
echo "============================================================"
echo "  Local AI Stack"
echo "============================================================"
echo

# --- 1. Setup check --------------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "[X] Setup hasn't been run yet. Run ./setup.sh first."
    exit 1
fi

# --- 2. Ollama --------------------------------------------------------------
if up http://localhost:11434/api/version; then
    echo "[ok] Ollama is running."
elif systemctl --user start ollama.service 2>/dev/null; then
    echo "[..] Started Ollama (systemd user service)."
elif command -v ollama >/dev/null 2>&1; then
    echo "[..] Starting Ollama..."
    nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
    sleep 3
else
    echo "[!] Ollama isn't installed. Get it from https://ollama.com/download"
fi

# --- 3. n8n (optional, podman/docker) ---------------------------------------
if up http://localhost:5678/healthz; then
    echo "[ok] n8n is running."
elif command -v podman >/dev/null 2>&1 && podman container exists aistack-n8n 2>/dev/null; then
    echo "[..] Starting n8n (podman)..."
    podman start aistack-n8n >/dev/null
elif command -v podman-compose >/dev/null 2>&1 && [ -f foundation/.env ]; then
    echo "[..] Starting n8n (podman-compose)..."
    (cd foundation && podman-compose -f docker-compose.yml up -d >/dev/null 2>&1)
else
    echo "[..] podman/n8n not set up -- skipping (optional, see foundation/README.md)."
fi

# --- 4. Olympus (lightweight, always auto-start) ----------------------------
if up http://127.0.0.1:4600/api/health; then
    echo "[ok] Olympus is running."
else
    echo "[..] Starting Olympus..."
    (cd olympus && nohup ../.venv/bin/python -m uvicorn kernel.app:app \
        --host 0.0.0.0 --port 4600 > ../olympus.log 2>&1 &)
    sleep 3
fi

# --- 5. OpenCode MCP (lightweight, always auto-start) ------------------------
if up http://127.0.0.1:4720/health; then
    echo "[ok] OpenCode MCP is running."
else
    echo "[..] Starting OpenCode MCP..."
    nohup .venv/bin/python -m uvicorn olympus.skills.opencode.mcp_server:app \
        --host 127.0.0.1 --port 4720 > opencode.log 2>&1 &
    sleep 3
fi

# --- 6. Obsidian (Local REST API plugin needs the app open) ------------------
if up http://127.0.0.1:27123/; then
    echo "[ok] Obsidian is running."
elif command -v flatpak >/dev/null 2>&1 && flatpak info md.obsidian.Obsidian >/dev/null 2>&1; then
    echo "[..] Starting Obsidian..."
    nohup flatpak run md.obsidian.Obsidian >/dev/null 2>&1 &
    sleep 5
else
    echo "[..] Obsidian not installed as flatpak -- skipping."
fi

# --- 7. GPU-heavy apps: status only ------------------------------------------
echo
echo "[i] GPU-heavy apps (start manually when you need them):"
if up http://127.0.0.1:5050/api/health; then
    echo "    [ok] Voice Studio   -- http://127.0.0.1:5050"
else
    echo "    [ ] Voice Studio    -- cd olympus/engines/voice && .venv/bin/python app.py"
fi
if up http://127.0.0.1:8188/system_stats; then
    echo "    [ok] ComfyUI        -- http://127.0.0.1:8188"
else
    echo "    [ ] ComfyUI         -- cd ComfyUI && nohup .venv/bin/python main.py --listen 127.0.0.1 --port 8188 &"
fi
if up http://127.0.0.1:1234/v1/models; then
    echo "    [ok] LM Studio      -- http://127.0.0.1:1234"
else
    echo "    [ ] LM Studio       -- lms daemon up   (~/.lmstudio/bin on PATH)"
fi
if up http://127.0.0.1:3001/api/ping; then
    echo "    [ok] AnythingLLM    -- http://127.0.0.1:3001"
else
    echo "    [ ] AnythingLLM     -- ~/Applications/AnythingLLMDesktop.AppImage"
fi
if up http://127.0.0.1:3030/api/public/health; then
    echo "    [ok] Langfuse       -- http://127.0.0.1:3030"
else
    echo "    [ ] Langfuse        -- cd foundation && podman-compose -f docker-compose-langfuse.yml up -d"
fi
if command -v ffmpeg >/dev/null 2>&1; then
    echo "    [ok] FFmpeg         -- available"
else
    echo "    [ ] FFmpeg          -- sudo dnf install ffmpeg"
fi

# --- 8. Open the hub ----------------------------------------------------------
echo
echo "[ok] Everything's up."
echo "     OLYMPUS: http://127.0.0.1:4600   |   OpenCode MCP: http://127.0.0.1:4720"
echo
command -v xdg-open >/dev/null 2>&1 && xdg-open http://127.0.0.1:4600 >/dev/null 2>&1 &
true
