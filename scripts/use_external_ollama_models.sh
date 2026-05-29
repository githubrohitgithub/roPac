#!/usr/bin/env bash
# Move LLM weights out of ropac/ollama_models into ~/.ollama/models (Ollama default).
set -euo pipefail

ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OLLAMA_HOME="${OLLAMA_HOME:-$HOME/.ollama}"
SRC="$ROPAC_DIR/ollama_models"
REAL="$OLLAMA_HOME/models"

echo ""
echo "RoPac — use Ollama folder outside project"
echo "  From: $SRC"
echo "  To:   $REAL"
echo ""

if [[ ! -d "$SRC" ]] || [[ -z "$(ls -A "$SRC" 2>/dev/null | grep -v README)" ]]; then
  echo "Nothing to move in ollama_models/ (already empty)."
else
  mkdir -p "$OLLAMA_HOME"
  if [[ -L "$REAL" ]]; then
    link_target="$(readlink "$REAL")"
    echo "Removing symlink: $REAL -> $link_target"
    rm -f "$REAL"
  elif [[ -d "$REAL" ]] && [[ -n "$(ls -A "$REAL" 2>/dev/null)" ]]; then
    echo "ERROR: $REAL already exists and is not empty."
    echo "Merge manually, then delete: $SRC"
    exit 1
  elif [[ -d "$REAL" ]]; then
    rmdir "$REAL" 2>/dev/null || true
  fi

  mkdir -p "$REAL"
  echo "Copying models (may take a few minutes)..."
  if command -v rsync &>/dev/null; then
    rsync -a "$SRC/" "$REAL/"
  else
    cp -R "$SRC/." "$REAL/"
  fi
  echo "Removing project copy: $SRC"
  rm -rf "$SRC"
  mkdir -p "$SRC"
  echo "Models now live only under $REAL (not inside RoPac)." >"$SRC/README.md"
fi

# shellcheck source=scripts/ropac_env.sh
source "$ROPAC_DIR/scripts/ropac_env.sh"
write_ropac_env_file

echo ""
echo "Done."
echo "  Ollama models: $OLLAMA_MODELS"
echo "  Quit and reopen Ollama app, then restart RoPac."
echo ""
