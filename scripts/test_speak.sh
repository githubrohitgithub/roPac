#!/usr/bin/env bash
# Quick offline voice test (Piper + playback with macOS fallbacks).
set -euo pipefail
ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROPAC_DIR"
PY="$ROPAC_DIR/.venv/bin/python"
TEXT="${1:-Hello Rohit. If you hear this, RoPac voice works.}"

echo "==> TTS status"
"$PY" bridge.py '{"action":"tts_status"}' | "$PY" -m json.tool

echo ""
echo "==> Synthesize + play"
out=$("$PY" bridge.py "{\"action\":\"tts_speak\",\"text\":$( "$PY" -c "import json,sys; print(json.dumps(sys.argv[1]))" "$TEXT" )}" | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('audio_path',''))")
if [[ -z "$out" || ! -f "$out" ]]; then
  echo "Synthesis failed" >&2
  exit 1
fi
echo "WAV: $out"

if [[ "$(uname -s)" == "Darwin" ]]; then
  engine=$("$ROPAC_DIR/scripts/play_audio_macos.sh" "$out" "$TEXT")
  echo "Played via: $engine"
else
  aplay "$out"
fi

echo ""
echo "Done."
