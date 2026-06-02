#!/bin/bash
# bin/listen_vani_wake.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    VENV="$PROJECT_ROOT/.venv"
elif [ -f "$PROJECT_ROOT/venv311/bin/activate" ]; then
    VENV="$PROJECT_ROOT/venv311"
else
    echo "Python virtual environment not found. Expected .venv or venv311."
    exit 1
fi

source "$VENV/bin/activate"

export VANI_LOW_POWER_UI="${VANI_LOW_POWER_UI:-1}"
export VANI_PREWARM_OLLAMA="${VANI_PREWARM_OLLAMA:-0}"
export VANI_USE_SILERO="${VANI_USE_SILERO:-0}"
export VANI_TIMEZONE="${VANI_TIMEZONE:-Asia/Kolkata}"
export TZ="${TZ:-Asia/Kolkata}"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python -m vani.wake_listener
