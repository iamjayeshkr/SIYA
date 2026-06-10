#!/bin/bash
# siya_gemini.sh — Siya in full Gemini Realtime mode (Hinglish, Gemini voice)
# Latency: ~400-800ms | Voice: Gemini Realtime audio | Language: Hinglish ✅
# Use this for: normal conversations, Hinglish, full personality

cd "$(dirname "$0")"

echo "=================================================="
echo "  Siya — Gemini Realtime Mode"
echo "  Voice: Gemini (Hinglish supported)"
echo "  Latency: 400-800ms"
echo "=================================================="

export VANI_LOCAL_TTS=0
export VANI_ENGLISH_ONLY=0
# Tightest endpointing for fastest feel
export VANI_ENDPOINT_MIN_DELAY=0.05
export VANI_ENDPOINT_MAX_DELAY=0.15
export VANI_INTERRUPT_MIN_DURATION=0.08

bash bin/run_vani.sh
