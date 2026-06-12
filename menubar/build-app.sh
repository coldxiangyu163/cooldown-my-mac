#!/usr/bin/env bash
# Build CooldownBar and assemble a double-clickable, ad-hoc-signed .app bundle.
# Menu bar only (LSUIElement) — no Dock icon. Output: ./dist/<Name>.app
set -euo pipefail

cd "$(dirname "$0")"

NAME="${APP_NAME:-Cooldown}"
BUNDLE_ID="${BUNDLE_ID:-com.coldxiangyu.cooldownbar}"
CONFIG="${CONFIG:-release}"

echo "==> swift build -c $CONFIG"
swift build -c "$CONFIG"

BIN="$(swift build -c "$CONFIG" --show-bin-path)/CooldownBar"
[ -x "$BIN" ] || { echo "binary not found at $BIN" >&2; exit 1; }

APP="dist/${NAME}.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$BIN" "$APP/Contents/MacOS/${NAME}"

VERSION="${APP_VERSION:-0.1.0}"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${NAME}</string>
  <key>CFBundleDisplayName</key><string>${NAME}</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleExecutable</key><string>${NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHumanReadableCopyright</key><string>MIT © coldxiangyu</string>
</dict>
</plist>
PLIST

echo "==> ad-hoc codesign"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || codesign --force --sign - "$APP"

echo "==> built $APP"
echo "    open \"$APP\"   # to launch"
