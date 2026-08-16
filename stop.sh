#!/usr/bin/env bash
# ==========================================================================
#  stop.sh — Stop all Local AI Stack services via systemd
# ==========================================================================
set -euo pipefail

echo "Stopping Local AI Stack..."

UNITS=(
    "comfyui-server" "olympus-kernel" "opencode-mcp"
    "voice-studio" "llama-server" "open-webui"
)

for unit in "${UNITS[@]}"; do
    if systemctl --user is-active --quiet "$unit.service" 2>/dev/null; then
        systemctl --user stop "$unit.service" && echo "  [ok] $unit stopped"
    else
        echo "  [  ] $unit not running"
    fi
done

# Ensure podman container is stopped
if podman ps --format '{{.Names}}' 2>/dev/null | grep -q open-webui; then
    podman stop open-webui 2>/dev/null && echo "  [ok] open-webui container stopped"
fi

echo "Done."
