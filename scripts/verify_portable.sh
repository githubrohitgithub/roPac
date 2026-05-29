#!/usr/bin/env bash
# Check that RoPac portable layout is complete.
set -euo pipefail

ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROPAC_DIR"
# shellcheck source=scripts/ropac_env.sh
source "$ROPAC_DIR/scripts/ropac_env.sh"

ok=0
warn=0
fail=0

check() {
  local label="$1"
  local path="$2"
  local required="${3:-yes}"
  if [[ -e "$path" ]]; then
    echo "  OK   $label"
    ok=$((ok + 1))
  elif [[ "$required" == "yes" ]]; then
    echo "  FAIL $label (missing: $path)"
    fail=$((fail + 1))
  else
    echo "  WARN $label (optional, missing)"
    warn=$((warn + 1))
  fi
}

echo "RoPac portable verify: $ROPAC_DIR"
echo ""

echo "Core:"
check "bridge.py" "$ROPAC_DIR/bridge.py"
check "assistant.py" "$ROPAC_DIR/assistant.py"
check "config.json" "$ROPAC_DIR/config.json"
check "Modelfile" "$ROPAC_DIR/Modelfile"
check ".venv" "$ROPAC_DIR/.venv" "no"

echo ""
echo "Data:"
check "memory.json" "$ROPAC_DIR/data/memory.json" "no"
check "owner.auth" "$ROPAC_DIR/data/owner.auth" "no"
check "knowledge/" "$ROPAC_DIR/data/knowledge" "no"
check "settings.json" "$ROPAC_DIR/data/settings.json" "no"

echo ""
echo "Models (copy these when migrating):"
if [[ -d "$OLLAMA_MODELS/blobs" ]]; then
  sz=$(du -sh "$OLLAMA_MODELS" 2>/dev/null | cut -f1)
  echo "  OK   ollama_models/ ($sz)"
  ok=$((ok + 1))
else
  echo "  WARN ollama_models/ empty — run ./install.sh (needs internet if empty)"
  warn=$((warn + 1))
fi

if [[ -f "$TTS_DIR/en_US-amy-medium.onnx" ]] || [[ -f "$TTS_DIR/hi_IN-rohan-medium.onnx" ]]; then
  sz=$(du -sh "$TTS_DIR" 2>/dev/null | cut -f1)
  echo "  OK   data/tts/ ($sz)"
  ok=$((ok + 1))
else
  echo "  WARN data/tts/ no Piper voices — run: .venv/bin/python scripts/download_tts_voices.py"
  warn=$((warn + 1))
fi

echo ""
echo "Ollama link:"
if [[ -L "$HOME/.ollama/models" ]]; then
  target=$(readlink "$HOME/.ollama/models")
  echo "  OK   ~/.ollama/models -> $target"
  ok=$((ok + 1))
elif [[ -d "$HOME/.ollama/models" ]]; then
  echo "  WARN ~/.ollama/models is a real folder — run ./install.sh to link to ropac"
  warn=$((warn + 1))
else
  echo "  WARN no ~/.ollama/models — install Ollama, then ./install.sh"
  warn=$((warn + 1))
fi

if command -v ollama &>/dev/null && curl -sf http://127.0.0.1:11434/api/tags &>/dev/null; then
  MODEL=$(python3 -c "import json; print(json.load(open('config.json'))['model'])" 2>/dev/null || echo roPac)
  if ollama show "$MODEL" &>/dev/null; then
    echo "  OK   Ollama model '$MODEL' loaded"
    ok=$((ok + 1))
  else
    echo "  WARN Ollama running but '$MODEL' not found — run ./install.sh"
    warn=$((warn + 1))
  fi
else
  echo "  WARN Ollama not running"
  warn=$((warn + 1))
fi

echo ""
echo "Summary: $ok ok, $warn warnings, $fail failures"
if [[ $fail -gt 0 ]]; then
  exit 1
fi
