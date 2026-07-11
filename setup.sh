#!/usr/bin/env bash
# ==========================================================================
#  setup.sh  --  Linux equivalent of setup.bat. Run me ONCE.
#
#  What it does (mirrors setup.bat):
#    1. Checks that Ollama and Python are installed.
#    2. Creates a Python virtual environment in .venv
#    3. Installs the lean base requirements.
#    4. Pulls the chat + embedding models.
#    5. Creates config.json from the example if you don't have one.
# ==========================================================================
set -u
cd "$(dirname "$0")"

echo
echo "============================================================"
echo "  Local AI Stack - one-time setup (Linux)"
echo "============================================================"
echo

# --- 1. Ollama -----------------------------------------------------------
if ! command -v ollama >/dev/null 2>&1; then
    echo "[X] Ollama is not installed or not on your PATH."
    echo "    Download and install it, then re-run setup.sh:"
    echo "       https://ollama.com/download"
    exit 1
fi
echo "[ok] Ollama found."

# --- 2. Python -----------------------------------------------------------
# Prefer uv (pinned Python 3.12 -- survives Fedora's system-Python upgrades);
# fall back to system python3.
if command -v uv >/dev/null 2>&1; then
    PYTHON_SETUP="uv"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_SETUP="python3"
else
    echo "[X] Python is not installed. Install python3 (or uv) and re-run."
    exit 1
fi
echo "[ok] Python found ($PYTHON_SETUP)."

# --- 3. Virtual environment ---------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
    echo "[..] Creating virtual environment in .venv ..."
    if [ "$PYTHON_SETUP" = "uv" ]; then
        uv venv --python 3.12 .venv || exit 1
    else
        python3 -m venv .venv || exit 1
    fi
fi
echo "[ok] Virtual environment ready."

echo "[..] Installing base requirements (this can take a few minutes)..."
if [ "$PYTHON_SETUP" = "uv" ]; then
    VIRTUAL_ENV="$PWD/.venv" uv pip install -r requirements.txt || {
        echo "[X] Installing requirements failed. See docs/TROUBLESHOOTING.md."; exit 1; }
else
    .venv/bin/python -m pip install --upgrade pip >/dev/null
    .venv/bin/python -m pip install -r requirements.txt || {
        echo "[X] Installing requirements failed. See docs/TROUBLESHOOTING.md."; exit 1; }
fi
echo "[ok] Python packages installed."

# --- 4. Models -----------------------------------------------------------
echo
echo "[..] Pulling models. First time downloads a few GB."
echo "     (Skips instantly if you already have them.)"
for MODEL in $(.venv/bin/python -c "from olympus.shared.lib.config import load_config as c;x=c();print(x['chat_model']);print(x['embed_model'])"); do
    echo "    pulling $MODEL ..."
    ollama pull "$MODEL"
done

# --- 5. config.json ------------------------------------------------------
if [ ! -f "config.json" ]; then
    cp config.example.json config.json
    echo "[ok] Created config.json  (edit \"vault_path\" to point at your Obsidian vault)"
else
    echo "[ok] config.json already exists - leaving it alone."
fi

echo
echo "============================================================"
echo "  Setup complete."
echo "============================================================"
echo "  Next:"
echo "    - Edit config.json and set \"vault_path\" to your Obsidian vault"
echo "    - Or just run ./start.sh -- it brings up the whole stack."
echo "    - Read docs/GUIDE.md for the full walkthrough."
echo
