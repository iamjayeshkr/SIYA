#!/bin/bash
# bin/wake_vani.sh

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
export VANI_TEXT_TIMEOUT="${VANI_TEXT_TIMEOUT:-8}"
export VANI_REALTIME_TEMPERATURE="${VANI_REALTIME_TEMPERATURE:-0.65}"
export VANI_ENDPOINT_MIN_DELAY="${VANI_ENDPOINT_MIN_DELAY:-0.12}"
export VANI_ENDPOINT_MAX_DELAY="${VANI_ENDPOINT_MAX_DELAY:-0.45}"
export VANI_INTERRUPT_MIN_DURATION="${VANI_INTERRUPT_MIN_DURATION:-0.18}"
export VANI_TIMEZONE="${VANI_TIMEZONE:-Asia/Kolkata}"
export TZ="${TZ:-Asia/Kolkata}"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python -m vani.launcher --wake
