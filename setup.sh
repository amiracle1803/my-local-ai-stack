#!/usr/bin/env bash
# ==========================================================================
#  setup.sh — One-time setup for the Local AI Stack
#
#  1. Creates Python virtual environment (.venv)
#  2. Installs all Python dependencies
#  3. Pulls required Ollama models
#  4. Optionally creates config from example
#
#  Run once, then use ./start.sh to launch everything.
# ==========================================================================
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"

echo
echo "  Local AI Stack Setup"
echo "  $(date)"
echo

# ── 1. Python ──────────────────────────────────────────────────────────────
echo "[1/5] Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "  [X] python3 not found. Install Python 3.12+ first."
    exit 1
fi
echo "  [ok] $(python3 --version)"

# ── 2. Virtual environment ─────────────────────────────────────────────────
echo "[2/5] Creating virtual environment..."
if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
    echo "  [ok] .venv created"
else
    echo "  [ok] .venv already exists"
fi

# ── 3. Dependencies ────────────────────────────────────────────────────────
echo "[3/5] Installing Python packages..."
.venv/bin/python -m ensurepip --upgrade 2>/dev/null || true
.venv/bin/python -m pip install --upgrade pip -q 2>/dev/null || true

# Base dependencies
.venv/bin/python -m pip install -q -r requirements.txt 2>&1 | tail -1
echo "  [ok] base requirements"

# Voice Studio dependencies
if [ -f "olympus/engines/voice/requirements.txt" ]; then
    .venv/bin/python -m pip install -q -r olympus/engines/voice/requirements.txt 2>&1 | tail -1
    echo "  [ok] voice dependencies"
fi

# ── 4. Ollama models ───────────────────────────────────────────────────────
echo "[4/5] Pulling Ollama models..."
MODELS=(
    "qwen3:8b" "qwen2.5vl:7b" "llama3.1:8b"
    "llama3.2:3b" "nomic-embed-text"
)
for model in "${MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "$model"; then
        echo "  [ok] $model"
    else
        echo "  [..] pulling $model..."
        ollama pull "$model" >/dev/null 2>&1 && echo "  [ok] $model" || echo "  [!] $model failed"
    fi
done

# ── 5. Config ──────────────────────────────────────────────────────────────
echo "[5/5] Config..."
if [ ! -f "stack.toml" ]; then
    echo "  [!] stack.toml missing — something is wrong"
else
    echo "  [ok] stack.toml present"
fi

# Enable systemd services
echo
echo "Enabling systemd user services..."
systemctl --user daemon-reload 2>/dev/null || true

# Generate podman open-webui service if needed
if ! systemctl --user is-enabled open-webui.service >/dev/null 2>&1; then
    if command -v podman >/dev/null 2>&1; then
        podman run -d --name open-webui --restart always --network host \
            -v open-webui-data:/app/backend/data \
            -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
            ghcr.io/open-webui/open-webui:main 2>/dev/null && \
        podman generate systemd --new --name open-webui > ~/.config/systemd/user/open-webui.service 2>/dev/null
        echo "  [ok] Open WebUI container created"
    fi
fi

for unit in olympus-kernel comfyui-server voice-studio opencode-mcp llama-server; do
    systemctl --user enable "$unit.service" 2>/dev/null && echo "  [ok] $unit enabled" || echo "  [-] $unit skipped"
done

echo
echo "  Setup complete."
echo
echo "  Next: ./start.sh     (launch all services)"
echo "        ./stop.sh      (stop all services)"
echo "        http://localhost:4600     (Olympus dashboard)"
echo "        http://localhost:8080     (Open WebUI chat)"
echo
