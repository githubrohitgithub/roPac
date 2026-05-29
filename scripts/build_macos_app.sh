#!/usr/bin/env bash
# Build RoPac macOS .app and install a Desktop launcher (RoPac.app).
set -euo pipefail

ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UI_DIR="$ROPAC_DIR/ropac_ui"
APP_NAME="RoPac"
DESKTOP_APP="$HOME/Desktop/${APP_NAME}.app"
BUILD_APP="$UI_DIR/build/macos/Build/Products/Release/ropac_ui.app"
CONFIG_DIR="$HOME/Library/Application Support/com.ropac.ropac_ui"

if [[ -d "/Applications/Xcode.app" ]]; then
  export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
elif [[ -d "$HOME/Downloads/Xcode.app" ]]; then
  export DEVELOPER_DIR="$HOME/Downloads/Xcode.app/Contents/Developer"
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-}"

echo "==> RoPac macOS build ($ROPAC_DIR)"

if ! command -v flutter &>/dev/null; then
  echo "ERROR: Flutter not found. Install Flutter SDK and retry."
  exit 1
fi

if [[ ! -d "$ROPAC_DIR/.venv" ]]; then
  echo "==> Running setup.sh (first time)..."
  "$ROPAC_DIR/setup.sh"
fi

echo "==> Saving RoPac folder path for the app..."
mkdir -p "$CONFIG_DIR"
echo "$ROPAC_DIR" > "$CONFIG_DIR/ropac_root.txt"

echo "==> Building release app (may take a few minutes)..."
cd "$UI_DIR"
flutter pub get
flutter build macos --release

if [[ ! -d "$BUILD_APP" ]]; then
  echo "ERROR: Build output not found at $BUILD_APP"
  exit 1
fi

echo "==> Installing to Desktop: $DESKTOP_APP"
rm -rf "$DESKTOP_APP"
cp -R "$BUILD_APP" "$DESKTOP_APP"

# Friendly name in Finder
/usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$DESKTOP_APP/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string $APP_NAME" "$DESKTOP_APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$DESKTOP_APP/Contents/Info.plist" 2>/dev/null || true

if command -v codesign &>/dev/null; then
  codesign --force --deep -s - "$DESKTOP_APP" 2>/dev/null || true
fi

echo ""
echo "Done."
echo "  Desktop app: $DESKTOP_APP"
echo "  RoPac data:  $ROPAC_DIR"
echo ""
echo "Before first launch:"
echo "  1. Open the Ollama app"
echo "  2. Double-click RoPac on your Desktop"
echo "  3. Tap Start model in the app"
echo ""
echo "If macOS blocks the app: System Settings → Privacy & Security → Open Anyway"
