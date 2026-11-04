#!/usr/bin/env bash
# One-command standalone pipeline runner — no agent, no browser required.
# Uses the permanent config in stack.toml (including NVIDIA NIM DeepSeek model).
# See: python scripts/run_pipeline_standalone.py --help

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then VENV_PY="python3"; fi

# Colors
GREEN='\033[1;32m'; CYAN='\033[1;34m'; DIM='\033[2m'; NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  Anime Pipeline — Standalone Runner (no agent)    ║${NC}"
echo -e "${CYAN}║  Config: stack.toml → [nim] + [ollama] + [comfyui]║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
echo -e "${DIM}Tip: Use the Studio page at http://localhost:4600/#studio for a browser UI with the same power.${NC}"
echo ""

if [ $# -eq 0 ]; then
  echo "Usage:"
  echo "  ./run_pipeline.sh --slug my_episode --brief brief.md          # full run from brief"
  echo "  ./run_pipeline.sh --slug my_episode --stage stage3b           # single stage"
  echo "  ./run_pipeline.sh --list-models                                # show configured models"
  echo "  ./run_pipeline.sh --help                                       # full help"
  echo ""
  echo "Examples:"
  echo "  ./run_pipeline.sh --slug demo --brief /tmp/brief.md"
  echo "  ./run_pipeline.sh --slug demo --nim-model deepseek-ai/deepseek-v4-flash-0731"
  echo ""
  exec "$VENV_PY" "$REPO_ROOT/scripts/run_pipeline_standalone.py" --help
fi

exec "$VENV_PY" "$REPO_ROOT/scripts/run_pipeline_standalone.py" "$@"
