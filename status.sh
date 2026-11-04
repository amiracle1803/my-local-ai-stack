#!/usr/bin/env bash
# Check status of all core services
# Usage: ./status.sh

echo "=== my-local-ai-stack Service Status ==="
echo ""

check_http() {
    local name=$1
    local url=$2
    local expect=${3:-200}
    if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "^$expect$"; then
        echo "✅ $name"
    else
        echo "❌ $name"
    fi
}

check_http_any() {
    local name=$1
    local url=$2
    if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "^[2-3][0-9][0-9]$"; then
        echo "✅ $name"
    else
        echo "❌ $name"
    fi
}

check_systemd_user() {
    local name=$1
    local service=$2
    if systemctl --user is-active --quiet "$service"; then
        echo "✅ $name (systemd: $service)"
    else
        echo "❌ $name (systemd: $service - inactive)"
    fi
}

check_systemd_system() {
    local name=$1
    local service=$2
    if systemctl is-active --quiet "$service"; then
        echo "✅ $name (systemd: $service)"
    else
        echo "❌ $name (systemd: $service - inactive)"
    fi
}

check_docker() {
    local name=$1
    local container=$2
    # Use docker with group access if available
    if groups | grep -q docker; then
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$container"; then
            echo "✅ $name (docker: $container)"
        else
            echo "❌ $name (docker: $container - not running)"
        fi
    else
        # Fallback: try without group
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$container"; then
            echo "✅ $name (docker: $container)"
        else
            echo "⚠️  $name (docker: $container - need docker group)"
        fi
    fi
}

echo "--- Studio (this machine's job in W.A.T.: GPU media) ---"
check_http "Studio API (4600)" "http://localhost:4600/api/studio/status"
check_http_any "ComfyUI (8188)" "http://localhost:8188/"
check_http "Voice Studio (5050)" "http://localhost:5050/api/health"
check_http "Ollama GPU (11434)" "http://localhost:11434/"

echo ""
echo "--- Systemd Services ---"
check_systemd_user "Studio API (olympus-kernel)" "olympus-kernel.service"
check_systemd_user "ComfyUI" "comfyui-server.service"
check_systemd_user "Voice Studio" "voice-studio.service"
check_systemd_user "llama.cpp Model Selector (8080)" "llama-selector.service"
check_systemd_user "OpenCode MCP Bridge (4720)" "opencode-mcp.service"
check_systemd_system "Ollama" "ollama.service"

echo ""
echo "--- Moved into W.A.T. (2026-11-03) ---"
echo "   n8n, memory, Open WebUI, dashboards and proxies now live on the ProDesk."
echo "   See everything: W.A.T. Catalog -> http://100.103.246.96:8770/catalog"

echo ""
echo "=== GPU Status ==="
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi not available"

echo ""
echo "=== Disk Space ==="
df -h /home/amire/Downloads/my-local-ai-stack | tail -1
