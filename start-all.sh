#!/usr/bin/env bash
# Start all core services for my-local-ai-stack
# Usage: ./start-all.sh

set -euo pipefail

log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
ok() { echo -e "\033[1;32m[OK]\033[0m $*"; }
err() { echo -e "\033[1;31m[ERR]\033[0m $*" >&2; }

log "Starting all services..."

# Studio API (olympus kernel, port 4600) - used by W.A.T. studio_* tools
if systemctl --user is-active --quiet olympus-kernel.service; then
    ok "Olympus Kernel already running"
else
    log "Starting Olympus Kernel..."
    systemctl --user start olympus-kernel.service
    sleep 2
    ok "Olympus Kernel started"
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
  (curl -s http://localhost:4600/api/studio/status >/dev/null && echo '✅ Studio API (4600)') || echo '❌ Studio API (4600)';
  (curl -s http://localhost:11434/ >/dev/null && echo '✅ Ollama (11434)') || echo '❌ Ollama (11434)';
  (curl -s http://localhost:8188/ >/dev/null && echo '✅ ComfyUI (8188)') || echo '❌ ComfyUI (8188)';
  (curl -s http://localhost:5050/api/health >/dev/null && echo '✅ Voice Studio (5050)') || echo '❌ Voice Studio (5050)';
"
