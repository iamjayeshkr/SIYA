#!/bin/bash
# build_dmg.sh — Builds a fully self-contained Vani.app + DMG
#
# Layout inside Vani.app:
#   Contents/
#     MacOS/vani          ← Tauri binary
#     Resources/
#       backend/          ← entire Python project (src/, modes/, bin/, etc.)
#         venv311_new/    ← Python venv
#         .env            ← your API keys (copied from project root)
#         src/            ← vani Python source
#         ...
#
# The Rust binary looks for Resources/backend/ relative to itself,
# so the app is 100% self-contained and works from /Applications.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

G="\033[32m" R="\033[31m" Y="\033[33m" N="\033[0m" BOLD="\033[1m"
ok()   { echo -e "  ${G}✓${N}  $1"; }
warn() { echo -e "  ${Y}⚠${N}  $1"; }
fail() { echo -e "  ${R}✗${N}  $1"; exit 1; }

echo -e "\n${BOLD}━━━  Vani — Self-Contained DMG Build  ━━━${N}\n"

cd "$PROJECT_ROOT"

# ── 1. Preflight checks ────────────────────────────────────────────────────────
command -v cargo &>/dev/null      || fail "cargo not found. Install: https://rustup.rs"
cargo tauri --version &>/dev/null || fail "tauri-cli missing. Run: cargo install tauri-cli --version '^2.0' --locked"

VENV=""
for v in venv311_new venv311 .venv; do
  [ -f "$PROJECT_ROOT/$v/bin/python" ] && VENV="$PROJECT_ROOT/$v" && break
done
[ -z "$VENV" ] && fail "No Python venv found (venv311_new/, venv311/, or .venv/)"
VENV_NAME=$(basename "$VENV")
ok "Venv: $VENV"

[ -f "$PROJECT_ROOT/.env" ] || warn ".env not found — API keys won't be bundled"

# ── 2. Build Tauri binary ──────────────────────────────────────────────────────
echo -e "\n${BOLD}Building Tauri binary…${N}"
cargo tauri build
ok "Tauri build complete"

APP_SRC=$(find "$PROJECT_ROOT/target/release/bundle/macos" -name "*.app" -maxdepth 1 2>/dev/null | head -1)
[ -z "$APP_SRC" ] && fail "Built .app not found in target/release/bundle/macos/"
APP_NAME=$(basename "$APP_SRC" .app)
ok "App: $APP_SRC"

# ── 3. Embed backend into .app/Contents/Resources/backend/ ────────────────────
echo -e "\n${BOLD}Embedding Python backend into .app bundle…${N}"

RESOURCES="$APP_SRC/Contents/Resources"
BACKEND_DST="$RESOURCES/backend"
rm -rf "$BACKEND_DST"
mkdir -p "$BACKEND_DST"

# Copy source code, modes, bin, requirements, config files
rsync -a \
  --exclude='target' \
  --exclude='dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='ui/node_modules' \
  --exclude="$VENV_NAME" \
  --exclude='venv311' \
  --exclude='venv311_new' \
  --exclude='.venv' \
  "$PROJECT_ROOT/" "$BACKEND_DST/"
ok "Source code embedded"

# Copy venv (this is the big one — may take a minute)
echo "  Copying venv (this may take 30-60s)…"
cp -R "$VENV" "$BACKEND_DST/$VENV_NAME"
ok "Venv embedded ($VENV_NAME)"

# Copy .env if present
[ -f "$PROJECT_ROOT/.env" ] && cp "$PROJECT_ROOT/.env" "$BACKEND_DST/.env" && ok ".env embedded"

# ── 4. Write a vani-backend path hint for the Rust binary ─────────────────────
# The Rust binary reads this file so project_root() is always exact, no guessing.
BINARY_PATH="$APP_SRC/Contents/MacOS/$APP_NAME"
# Lowercase app name as the binary is named after productName in tauri.conf.json
BINARY_PATH_LOWER="$APP_SRC/Contents/MacOS/$(echo $APP_NAME | tr '[:upper:]' '[:lower:]')"
[ -f "$BINARY_PATH_LOWER" ] && BINARY_PATH="$BINARY_PATH_LOWER"

echo "$BACKEND_DST" > "$RESOURCES/vani_backend_path.txt"
ok "Backend path hint written → vani_backend_path.txt"

# ── 5. Package into DMG ────────────────────────────────────────────────────────
echo -e "\n${BOLD}Creating DMG…${N}"

DIST="$PROJECT_ROOT/dist"
STAGING="$DIST/dmg-staging-final"
DMG_PATH="$DIST/${APP_NAME}-full.dmg"

rm -rf "$STAGING" "$DMG_PATH"
mkdir -p "$STAGING"

cp -R "$APP_SRC" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

cat > "$STAGING/README.txt" << README
Vani — Installation
===================
1. Drag Vani.app to your Applications folder.
2. Double-click to launch.

Everything (Python backend, venv, config) is bundled inside Vani.app.
Logs: ~/Library/Logs/vani_backend.log
README

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING" \
  -ov -format UDZO \
  "$DMG_PATH"

ok "DMG: $DMG_PATH"
echo -e "\n${BOLD}${G}✓ Done! Fully self-contained DMG ready.${N}\n"