#!/bin/bash
# start.sh — Launch Vani (Python backend + Web UI) with a single command
# Usage:  ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colours ───────────────────────────────────────────────────────────────────
G="\033[32m" R="\033[31m" Y="\033[33m" B="\033[34m" C="\033[36m" N="\033[0m" BOLD="\033[1m"

banner() { echo -e "\n${BOLD}${C}━━━  $1  ━━━${N}"; }
ok()     { echo -e "  ${G}✓${N}  $1"; }
warn()   { echo -e "  ${Y}⚠${N}  $1"; }
fail()   { echo -e "  ${R}✗${N}  $1"; }

banner "Vani OS — starting up"

# ── Kill any leftover processes ───────────────────────────────────────────────
banner "Cleaning up old processes"
lsof -ti:8081 | xargs kill -9 2>/dev/null || true
lsof -ti:5500 | xargs kill -9 2>/dev/null || true
lsof -t /tmp/com.rudra.vani.lock | xargs kill -9 2>/dev/null || true
ok "Ports 8081 / 5500 clear"

# ── Trap for clean shutdown ───────────────────────────────────────────────────
PYTHON_PID=""

cleanup() {
  echo ""
  banner "Shutting down Vani"
  [ -n "$PYTHON_PID" ] && kill "$PYTHON_PID" 2>/dev/null && ok "Python stopped"
  lsof -ti:5500 | xargs kill -9 2>/dev/null || true
  echo -e "\n${BOLD}${G}Vani stopped.${N}\n"
  exit 0
}
trap cleanup INT TERM

# ── Start Python backend ──────────────────────────────────────────────────────
banner "Starting Python backend"
bin/run_vani.sh &
PYTHON_PID=$!
ok "Python backend started (PID $PYTHON_PID)"

# Wait for the HTTP server on port 5500 to come up (max 30s)
echo -n "  Waiting for backend"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:5500/state &>/dev/null; then
    echo ""
    ok "Backend ready on port 5500"
    break
  fi
  echo -n "."
  sleep 1
done

echo ""
echo -e "  ${BOLD}Vani backend is running.${N}"
echo -e "  ${G}Ctrl+C${N} to quit"

# ── Keep script alive until Ctrl+C ───────────────────────────────────────────
wait $PYTHON_PID
