#!/bin/bash
# start.sh — Launch Vani (Python backend + Tauri UI) with a single command
# Usage:  ./start.sh
#   --no-tauri   Run Python backend only (no desktop window)
#   --no-ui      Same as --no-tauri

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

NO_TAURI=0
for arg in "$@"; do
  [[ "$arg" == "--no-tauri" || "$arg" == "--no-ui" ]] && NO_TAURI=1
done

# ── Colours ───────────────────────────────────────────────────────────────────
G="\033[32m" R="\033[31m" Y="\033[33m" B="\033[34m" C="\033[36m" N="\033[0m" BOLD="\033[1m"

banner() { echo -e "\n${BOLD}${C}━━━  $1  ━━━${N}"; }
ok()     { echo -e "  ${G}✓${N}  $1"; }
warn()   { echo -e "  ${Y}⚠${N}  $1"; }
fail()   { echo -e "  ${R}✗${N}  $1"; }

banner "Vani OS — starting up"

# ── Source Cargo env (so cargo is on PATH in any shell) ───────────────────────
if [ -f "$HOME/.cargo/env" ]; then
  source "$HOME/.cargo/env"
fi

# ── Check Tauri availability ──────────────────────────────────────────────────
TAURI_OK=0
if [ "$NO_TAURI" = "0" ]; then
  if command -v cargo &>/dev/null && cargo tauri --version &>/dev/null 2>&1; then
    TAURI_OK=1
    ok "Tauri CLI found: $(cargo tauri --version 2>/dev/null)"
  else
    warn "Tauri/cargo not found — starting Python backend only"
    warn "Install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    warn "Then: cargo install tauri-cli --version '^2.0' --locked"
    NO_TAURI=1
  fi
fi

# ── Node deps check (needed for Tauri) ───────────────────────────────────────
if [ "$TAURI_OK" = "1" ]; then
  if [ ! -d "$SCRIPT_DIR/ui/node_modules" ]; then
    banner "Installing UI dependencies (first run)"
    cd "$SCRIPT_DIR/ui" && npm install && cd "$SCRIPT_DIR"
    ok "npm install done"
  fi
fi

# ── Kill any leftover processes ───────────────────────────────────────────────
banner "Cleaning up old processes"
lsof -ti:8081 | xargs kill -9 2>/dev/null || true
lsof -ti:5500 | xargs kill -9 2>/dev/null || true
lsof -ti:8765 | xargs kill -9 2>/dev/null || true
lsof -t /tmp/com.rudra.vani.lock | xargs kill -9 2>/dev/null || true
ok "Ports 8081 / 5500 / 8765 clear"

# ── Trap for clean shutdown ───────────────────────────────────────────────────
PYTHON_PID=""
TAURI_PID=""

cleanup() {
  echo ""
  banner "Shutting down Vani"
  [ -n "$TAURI_PID"  ] && kill "$TAURI_PID"  2>/dev/null && ok "Tauri stopped"
  [ -n "$PYTHON_PID" ] && kill "$PYTHON_PID" 2>/dev/null && ok "Python stopped"
  lsof -ti:8765 | xargs kill -9 2>/dev/null || true
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

# Wait for the FastAPI server on port 8765 to come up (max 30s)
echo -n "  Waiting for backend"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8765/state &>/dev/null; then
    echo ""
    ok "Backend ready on port 8765"
    break
  fi
  echo -n "."
  sleep 1
done

# ── Start Tauri UI ────────────────────────────────────────────────────────────
if [ "$TAURI_OK" = "1" ]; then
  banner "Starting Tauri desktop window"
  cargo tauri dev &
  TAURI_PID=$!
  ok "Tauri started (PID $TAURI_PID)"
  echo ""
  echo -e "  ${BOLD}Vani is running.${N}"
  echo -e "  ${G}Cmd+Shift+Space${N} — toggle window"
  echo -e "  ${G}Ctrl+C${N}           — quit everything"
else
  echo ""
  echo -e "  ${BOLD}Vani backend is running (no desktop window).${N}"
  echo -e "  ${G}Ctrl+C${N} to quit"
fi

# ── Keep script alive until Ctrl+C ───────────────────────────────────────────
wait $PYTHON_PID
