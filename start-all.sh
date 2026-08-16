#!/usr/bin/env bash
# Start all core services for my-local-ai-stack
# Usage: ./start-all.sh

set -euo pipefail

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok() { echo -e "\033[1;32m[OK]\033[0m $*"; }
err() { echo -e "\033[1;31m[ERR]\033[0m $*" >&2; }

log "Starting all services..."

# Olympus Kernel (port 4600)
if systemctl --user is-active --quiet olympus-kernel.service; then
    ok "Olympus Kernel already running"
else
    log "Starting Olympus Kernel..."
    systemctl --user start olympus-kernel.service
    sleep 2
    ok "Olympus Kernel started"
fi

# Open WebUI (port 8080)
if systemctl --user is-active --quiet open-webui.service; then
    ok "Open WebUI already running"
else
    log "Starting Open WebUI..."
    systemctl --user start open-webui.service
    sleep 5
    ok "Open WebUI started"
fi

# Memory Hub (ports 8125, 8424) - Docker containers
if docker ps --format '{{.Names}}' | grep -qx tdai-memory-core; then
    ok "Memory Hub already running"
else
    log "Starting Memory Hub (Docker)..."
    cd /home/amire/Downloads/my-local-ai-stack/TencentDB-Agent-Memory/deploy/global-images
    ./start-all.sh
    ok "Memory Hub started"
fi

# ComfyUI (port 8188) - systemd user service
if systemctl --user is-active --quiet comfyui-server.service; then
    ok "ComfyUI already running"
else
    log "Starting ComfyUI..."
    systemctl --user start comfyui-server.service
    sleep 3
    ok "ComfyUI started"
fi

# Ollama (port 11434) - system service
if systemctl is-active --quiet ollama.service; then
    ok "Ollama already running"
else
    log "Starting Ollama..."
    sudo systemctl start ollama.service
    sleep 3
    ok "Ollama started"
fi

# Voice Studio (port 5050) - systemd user service
if systemctl --user is-active --quiet voice-studio.service; then
    ok "Voice Studio already running"
else
    log "Starting Voice Studio..."
    systemctl --user start voice-studio.service
    sleep 2
    ok "Voice Studio started"
fi

echo ""
log "All services started. Checking status..."
sleep 2

bash -c "
  (curl -s http://localhost:4600/health >/dev/null && echo '✅ Olympus Kernel (4600)') || echo '❌ Olympus Kernel (4600)';
  (curl -s http://localhost:11434/ >/dev/null && echo '✅ Ollama (11434)') || echo '❌ Ollama (11434)';
  (curl -s http://localhost:8125/health >/dev/null && echo '✅ Memory Hub (8125)') || echo '❌ Memory Hub (8125)';
  (curl -s http://localhost:8080 >/dev/null && echo '✅ Open WebUI (8080)') || echo '❌ Open WebUI (8080)';
  (curl -s http://localhost:8188/ >/dev/null && echo '✅ ComfyUI (8188)') || echo '❌ ComfyUI (8188)';
  (curl -s http://localhost:5050/health >/dev/null && echo '✅ Voice Studio (5050)') || echo '❌ Voice Studio (5050)';
"
