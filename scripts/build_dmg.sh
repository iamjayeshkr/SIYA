#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_NAME="Vani"
APP_DIR="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/$APP_NAME.dmg"
STAGING_DIR="$DIST_DIR/dmg-staging"

rm -rf "$APP_DIR" "$STAGING_DIR" "$DMG_PATH"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources" "$STAGING_DIR"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Vani</string>
  <key>CFBundleDisplayName</key>
  <string>Vani</string>
  <key>CFBundleIdentifier</key>
  <string>com.rudra.vani</string>
  <key>CFBundleVersion</key>
  <string>1.0.0</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleExecutable</key>
  <string>Vani</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Vani needs microphone access for realtime voice conversations.</string>
</dict>
</plist>
PLIST

cat > "$APP_DIR/Contents/MacOS/Vani" <<LAUNCHER
#!/bin/bash
set -e
PROJECT_ROOT="$PROJECT_ROOT"
cd "\$PROJECT_ROOT"
exec "\$PROJECT_ROOT/bin/run_vani.sh"
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/Vani"

cat > "$STAGING_DIR/README.txt" <<README
Vani.app launches the local project checkout at:
$PROJECT_ROOT

Keep that folder in place. This lightweight DMG does not bundle the 1.2 GB Python virtual environment or your private .env file.
README

cp -R "$APP_DIR" "$STAGING_DIR/"

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "$DMG_PATH"
