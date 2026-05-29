#!/usr/bin/env bash
# Start RoPac Flutter UI (macOS) — fully offline
set -euo pipefail
ROPAC_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROPAC_DIR"

# Xcode in Downloads (before moving to /Applications)
if [[ -d "/Applications/Xcode.app" ]]; then
  export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
elif [[ -d "$HOME/Downloads/Xcode.app" ]]; then
  export DEVELOPER_DIR="$HOME/Downloads/Xcode.app/Contents/Developer"
fi
export PATH="/opt/homebrew/bin:${PATH:-}"

if [[ ! -d .venv ]]; then
  ./setup.sh
fi

if ! curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  echo "WARNING: Ollama is not running. Open the Ollama app first."
fi

cd ropac_ui
flutter pub get
exec flutter run -d macos
