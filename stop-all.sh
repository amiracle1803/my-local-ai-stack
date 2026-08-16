#!/usr/bin/env bash
# Stop all core services for my-local-ai-stack
# Usage: ./stop-all.sh

set -euo pipefail

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok() { echo -e "\033[1;32m[OK]\033[0m $*"; }

log "Stopping all services..."

# ComfyUI
if systemctl --user is-active --quiet comfyui-server.service; then
    log "Stopping ComfyUI..."
    systemctl --user stop comfyui-server.service
    ok "ComfyUI stopped"
fi

# Voice Studio
if systemctl --user is-active --quiet voice-studio.service; then
    log "Stopping Voice Studio..."
    systemctl --user stop voice-studio.service
    ok "Voice Studio stopped"
fi

# Olympus Kernel
if systemctl --user is-active --quiet olympus-kernel.service; then
    log "Stopping Olympus Kernel..."
    systemctl --user stop olympus-kernel.service
    ok "Olympus Kernel stopped"
fi

# Open WebUI
if systemctl --user is-active --quiet open-webui.service; then
    log "Stopping Open WebUI..."
    systemctl --user stop open-webui.service
    ok "Open WebUI stopped"
fi

# Memory Hub (Docker)
if docker ps --format '{{.Names}}' | grep -qx tdai-memory-core; then
    log "Stopping Memory Hub..."
    cd /home/amire/Downloads/my-local-ai-stack/TencentDB-Agent-Memory/deploy/global-images
    ./stop-all.sh
    ok "Memory Hub stopped"
fi

# Ollama (optional - keep running for other uses)
# Uncomment to stop Ollama too:
# if systemctl is-active --quiet ollama.service; then
#     log "Stopping Ollama..."
#     sudo systemctl stop ollama.service
#     ok "Ollama stopped"
# fi

ok "All services stopped"
