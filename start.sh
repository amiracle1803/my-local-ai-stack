#!/usr/bin/env bash
# ------------------------------------------------------------
# start.sh – one-click launcher for the anime-pipeline demo.
#
# Double‑click (or run) this script to:
#   1. Create a minimal demo project under ./olympus/engines/pipeline/projects/demo_proj
#   2. Populate a short sample script (input/script.txt).
#   3. Ensure required services are running (Ollama LLM and Voice‑Studio).
#   4. Clear any stale GPU lock.
#   5. Run the full pipeline (world‑bible → storyboard → screenplay → panels → animation → TTS → lip‑sync → assembly).
#   6. Open the final MP4 with the system video player.
# ------------------------------------------------------------

set -euo pipefail

# Helper functions
log() { echo -e "\033[1;34m[INFO]\033[0m $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }

# Resolve repo root (directory containing this script)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$REPO_ROOT/olympus/engines/pipeline/projects/demo_proj"

# 1. Clean any prior demo project
if [ -d "$PROJECT_ROOT" ]; then
    log "Removing existing demo project directory"
    rm -rf "$PROJECT_ROOT"
fi

# 2. Write a temporary sample script for project creation (in /tmp)
TEMP_SCRIPT="/tmp/demo_script.txt"
cat > "$TEMP_SCRIPT" <<'SCRIPT_EOF'
Title: The Star-Runner

A young courier named Kira lives in the bustling sky‑city of Nimbus. She dreams of becoming a legendary messenger, delivering parcels across the floating islands.

One day, a mysterious client gives her a sealed envelope that glows with a faint blue aura. The client whispers, "This must reach the Summit Gate before sunrise."

Kira accepts, racing her sky‑bike through soaring arches, dodging wind‑spouts and rival couriers. As dawn approaches, she spots the Summit Gate, a towering crystal arch.

She lands, hands over the envelope, and the gate awakens, opening a portal to a hidden realm. The client turns out: a guardian of the skies, thanking Kira for her bravery.

Kira returns to Nimbus as a hero, her name now spoken in the taverns of the clouds.
SCRIPT_EOF
log "Temporary script written to $TEMP_SCRIPT"

# 2. Ensure Python path includes the repo root
export PYTHONPATH="${PYTHONPATH:-}:$REPO_ROOT"
log "PYTHONPATH set to $PYTHONPATH"
export AGI_SCORER_ENABLED=0
log "AGI scoring disabled via env"

# 3. Start required services
# 3a. Ollama (LLM)
if ! pgrep -x ollama >/dev/null 2>&1; then
    log "Starting Ollama server..."
    ollama serve > "$PROJECT_ROOT/logs/ollama.log" 2>&1 &
    sleep 5
else
    log "Ollama already running."
fi
# 3b. Voice‑Studio service
if ! systemctl --user is-active --quiet voice-studio.service; then
    log "Starting Voice‑Studio service..."
    systemctl --user start voice-studio.service
    sleep 3
else
    log "Voice‑Studio already active."
fi

# 4. Clear stale GPU lock (prevents stage3c blockage)
GPU_LOCK_PATH="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pipeline-gpu/gpu.lock"
if [ -f "$GPU_LOCK_PATH" ]; then
    log "Removing stale GPU lock at $GPU_LOCK_PATH"
    rm -f "$GPU_LOCK_PATH"
fi

# 5. Run the full pipeline
log "Running the full pipeline..."
# Create project via CLI (generates blueprint) if not already present
if [ ! -f "$PROJECT_ROOT/blueprint.json" ]; then
log "Creating project via pipeline CLI"
python -m olympus.engines.pipeline.run new-project demo_proj --script "$TEMP_SCRIPT" --fps 12
# Create a minimal brief for stage0 (required word_target)
BRIEF_FILE="$PROJECT_ROOT/input/brief.md"
cat > "$BRIEF_FILE" <<'BRIEF_EOF'
---
word_target: 200
---

A brief description of the story: a courier race in a sky city.
BRIEF_EOF
log "Brief written to $BRIEF_FILE"

else
    log "Project already exists, skipping creation"
fi
# Then run all stages (resume‑safe)
# Reduce resolution in blueprint to fit limited GPU
BLUEPRINT_PATH="$PROJECT_ROOT/blueprint.json"
if [ -f "$BLUEPRINT_PATH" ]; then
  sed -i 's/"resolution": \[1280, 720\]/"resolution": [640, 360]/' "$BLUEPRINT_PATH"
  log "Reduced blueprint resolution to 640x360"
fi
export COMFY_USE_CPU=1
log "Running all stages"
python -m olympus.engines.pipeline.run all demo_proj --brief "$BRIEF_FILE" > "$PROJECT_ROOT/logs/pipeline_all.log" 2>&1
log "Pipeline finished. Check $PROJECT_ROOT/logs/pipeline.log"

# 6. Open the final video
OUTPUT_VIDEO=$(find "$PROJECT_ROOT/output" -type f -name "*.mp4" | head -n 1)
if [ -n "$OUTPUT_VIDEO" ]; then
    log "Opening final video: $OUTPUT_VIDEO"
    xdg-open "$OUTPUT_VIDEO" >/dev/null 2>&1 &
else
    error "No output video found in $PROJECT_ROOT/output"
fi

log "Demo complete. Edit $PROJECT_ROOT/input/script.txt and re‑run if desired."
