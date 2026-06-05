#!/bin/bash
# bin/run_vani.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ── Find .venv ────────────────────────────────────────────────────────────────
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    VENV="$PROJECT_ROOT/.venv"
elif [ -f "$PROJECT_ROOT/venv311/bin/activate" ]; then
    VENV="$PROJECT_ROOT/venv311"
elif [ -f "$PROJECT_ROOT/venv311_new/bin/activate" ]; then
    VENV="$PROJECT_ROOT/venv311_new"
else
    echo "❌ Python virtual environment not found. Expected .venv or venv311."
    exit 1
fi

source "$VENV/bin/activate"

echo "✅ venv: $VENV"
echo "✅ Python: $(which python)"

# ── Low-power animated defaults ───────────────────────────────────────────────
# Keeps Vani visually alive with the optimized animated idle video, but avoids
# heavy startup video work and does not preload Ollama unless explicitly enabled.
export VANI_VOICE_BACKEND="${VANI_VOICE_BACKEND:-livekit}"
export VANI_LOW_POWER_UI="${VANI_LOW_POWER_UI:-1}"
export VANI_PREWARM_OLLAMA="${VANI_PREWARM_OLLAMA:-0}"
export VANI_USE_SILERO="${VANI_USE_SILERO:-0}"
export VANI_TEXT_TIMEOUT="${VANI_TEXT_TIMEOUT:-8}"
export VANI_REALTIME_TEMPERATURE="${VANI_REALTIME_TEMPERATURE:-0.65}"
export VANI_ENDPOINT_MIN_DELAY="${VANI_ENDPOINT_MIN_DELAY:-0.12}"
export VANI_ENDPOINT_MAX_DELAY="${VANI_ENDPOINT_MAX_DELAY:-0.45}"
export VANI_INTERRUPT_MIN_DURATION="${VANI_INTERRUPT_MIN_DURATION:-0.18}"
export VANI_FALSE_INTERRUPT_TIMEOUT="${VANI_FALSE_INTERRUPT_TIMEOUT:-0.8}"
export VANI_MAX_SPEECH_DURATION="${VANI_MAX_SPEECH_DURATION:-8.0}"
export VANI_WAIT_FOR_SPEECH_PLAYOUT="${VANI_WAIT_FOR_SPEECH_PLAYOUT:-0}"
export VANI_TIMEZONE="${VANI_TIMEZONE:-Asia/Kolkata}"
export TZ="${TZ:-Asia/Kolkata}"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements/mac.txt"

echo "✅ Low-power animated UI: $VANI_LOW_POWER_UI"
echo "✅ Ollama prewarm: $VANI_PREWARM_OLLAMA"
echo "✅ Silero VAD: $VANI_USE_SILERO"
echo "✅ Timezone: $VANI_TIMEZONE"
echo "✅ Voice: temp=$VANI_REALTIME_TEMPERATURE endpoint=${VANI_ENDPOINT_MIN_DELAY}-${VANI_ENDPOINT_MAX_DELAY}s max_speech=${VANI_MAX_SPEECH_DURATION}s"

# ── Kill old process ──────────────────────────────────────────────────────────
lsof -ti:8081 | xargs kill -9 2>/dev/null || true
lsof -ti:5500 | xargs kill -9 2>/dev/null || true
lsof -t /tmp/com.rudra.vani.lock | xargs kill -9 2>/dev/null || true
echo "✅ Ports 8081 and 5500 clear"
echo "✅ Launcher lock clear"

# ── Check dependencies ────────────────────────────────────────────────────────
echo ""
echo "📦 Checking dependencies…"

if [ "${VANI_INSTALL_DEPS:-0}" = "1" ]; then
    echo "📦 Installing dependencies from requirements/mac.txt…"
    pip install --quiet --exists-action i -r "$REQUIREMENTS_FILE"
else
python - <<'PY'
import importlib
import importlib.util
import sys

required = [
    "dotenv",
    "livekit",
    "livekit.agents",
    "livekit.plugins.google",
    "livekit.plugins.noise_cancellation",
    "livekit.plugins.silero",
    "google.genai",
    "langchain",
    "requests",
    "fuzzywuzzy",
]

missing = []
def has_module(module):
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False

for module in required:
    if not has_module(module):
        missing.append(module)

if missing:
    print("❌ Missing required Python packages:")
    for item in missing:
        print(f"   - {item}")
    print("")
    print("Run this once to install dependencies:")
    print("   VANI_INSTALL_DEPS=1 bin/run_vani.sh")
    print("This installs from requirements/mac.txt.")
    sys.exit(1)

optional = ["mss", "cv2", "paddleocr"]
optional_missing = []
for module in optional:
    if not has_module(module):
        optional_missing.append(module)
if optional_missing:
    print("⚠️  Optional screen OCR packages missing:", ", ".join(optional_missing))
    print("   Screen read still runs with fallback. Install with:")
    print("   VANI_INSTALL_DEPS=1 bin/run_vani.sh")
PY
fi

# ── Check & Download Kokoro Assets ────────────────────────────────────────────
echo "📦 Checking Kokoro TTS assets…"
python - <<'PY'
import os
import sys
import urllib.request
from pathlib import Path

cache_dir = Path.home() / ".cache" / "kokoro"
cache_dir.mkdir(parents=True, exist_ok=True)
onnx_path = cache_dir / "kokoro-v1.0.onnx"
voices_path = cache_dir / "voices-v1.0.bin"

def download_file(url, dest, expected_size):
    if dest.exists() and dest.stat().st_size == expected_size:
        return
    print(f"   Downloading Kokoro asset: {dest.name} (~{expected_size / (1024*1024):.1f}MB)...")
    try:
        if dest.exists():
            dest.unlink()
        urllib.request.urlretrieve(url, dest)
        print(f"   ✓ Downloaded {dest.name}")
    except Exception as e:
        print(f"   ✗ Failed to download {dest.name}: {e}")
        if dest.exists():
            dest.unlink()
        sys.exit(1)

download_file("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx", onnx_path, 325532387)
download_file("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin", voices_path, 28214398)
PY

if [ $? -ne 0 ]; then
    echo "❌ Failed to download Kokoro TTS assets."
    exit 1
fi
echo "✅ Kokoro TTS assets ready"
echo ""

echo "✅ All packages ready"
echo ""

# ── Launch ────────────────────────────────────────────────────────────────────
echo "🚀 Launching Vani…"
if [ "$(uname)" = "Darwin" ] && [ "${VANI_MAC_NOTIFICATIONS:-1}" = "1" ]; then
    osascript -e 'display notification "Vani start ho rahi hai. UI khulte hi text/image ready hoga; voice ready notification alag se aayega." with title "Vani"' >/dev/null 2>&1 || true
fi

python -m vani.launcher
