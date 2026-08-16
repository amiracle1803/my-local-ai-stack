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

echo "--- Core HTTP Services ---"
check_http_any "Olympus Kernel (4600)" "http://localhost:4600/"
check_http "Ollama (11434)" "http://localhost:11434/"
check_http "Memory Hub Panel (8125)" "http://localhost:8125/health"
check_http "Open WebUI (8080)" "http://localhost:8080"
check_http_any "ComfyUI (8188)" "http://localhost:8188/"
check_http "Voice Studio (5050)" "http://localhost:5050/api/health"

echo ""
echo "--- Systemd User Services ---"
check_systemd_user "Olympus Kernel" "olympus-kernel.service"
check_systemd_user "Open WebUI" "open-webui.service"
check_systemd_user "ComfyUI" "comfyui-server.service"
check_systemd_user "Voice Studio" "voice-studio.service"

echo ""
echo "--- Systemd System Services ---"
check_systemd_system "Ollama" "ollama.service"

echo ""
echo "--- Docker Containers (Memory Hub) ---"
check_docker "Memory Core" "tdai-memory-core"
check_docker "Memory Hub" "tdai-memory-hub"
check_docker "Memory Proxy" "tdai-proxy"

echo ""
echo "=== GPU Status ==="
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi not available"

echo ""
echo "=== Disk Space ==="
df -h /home/amire/Downloads/my-local-ai-stack | tail -1
