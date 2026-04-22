#!/usr/bin/env bash
# dialekt backend startup script (macOS / Linux)
# Activates the venv and starts the FastAPI server.
# Environment variables (all optional):
#   DIALEKT_COMFY_URL     — ComfyUI base URL (default: http://127.0.0.1:8188)
#   DIALEKT_COMFY_MAIN    — path to ComfyUI main.py
#   DIALEKT_COMFY_OUTPUT  — path to ComfyUI output directory
#   DIALEKT_COMFY_PYTHON  — path to ComfyUI venv python

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"

# Auto-detect or create venv
if [ ! -d "$VENV" ]; then
  echo "Creating Python venv..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
fi

# Activate and run
source "$VENV/bin/activate"
exec python3 "$SCRIPT_DIR/server.py" "$@"
