#!/bin/bash
# siya_native.sh — Siya in Native TTS mode (macOS 'say' / fast English)
# Latency: ~250-400ms | Voice: macOS Rishi (Indian accent) | Language: English
# Use this for: quick tasks, coding help, when speed matters more than Hinglish

cd "$(dirname "$0")"

echo "=================================================="
echo "  Siya — Native TTS Mode (Ultra-Fast)"
echo "  Voice: macOS ${VANI_MAC_VOICE:-Rishi} @ ${VANI_MAC_RATE:-210}wpm"
echo "  Latency: 250-400ms | English only"
echo "=================================================="

export VANI_LOCAL_TTS=1
export VANI_ENGLISH_ONLY=1
# Same tight endpointing
export VANI_ENDPOINT_MIN_DELAY=0.05
export VANI_ENDPOINT_MAX_DELAY=0.15
export VANI_INTERRUPT_MIN_DURATION=0.08

# Voice config — override via env if needed
# Available voices: Rishi (en-IN), Samantha (en-US), Karen (en-AU), Daniel (en-GB)
# Try: VANI_MAC_VOICE=Samantha bash siya_native.sh
export VANI_MAC_VOICE="${VANI_MAC_VOICE:-Rishi}"
export VANI_MAC_RATE="${VANI_MAC_RATE:-210}"

bash bin/run_vani.sh
