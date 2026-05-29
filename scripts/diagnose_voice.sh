#!/usr/bin/env bash
# Diagnose RoPac offline voice (models + synthesis + playback).
set -euo pipefail
ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROPAC_DIR"
PY="$ROPAC_DIR/.venv/bin/python"
PLAY="$ROPAC_DIR/scripts/play_audio_macos.sh"

echo "=== RoPac voice diagnose ==="
echo "Folder: $ROPAC_DIR"
echo ""

echo "1) TTS status"
"$PY" bridge.py '{"action":"tts_status"}' | "$PY" -m json.tool
echo ""

echo "2) Piper model files"
for id in en_US-amy-medium hi_IN-rohan-medium; do
  onnx="$ROPAC_DIR/data/tts/${id}.onnx"
  json="$ROPAC_DIR/data/tts/${id}.onnx.json"
  if [[ -f "$onnx" && -f "$json" ]]; then
    sz=$(du -sh "$onnx" | cut -f1)
    echo "  OK  $id ($sz)"
  else
    echo "  MISSING $id — run: $PY scripts/download_tts_voices.py"
  fi
done
echo ""

echo "3) Synthesize test WAV"
out=$("$PY" bridge.py '{"action":"tts_speak","text":"RoPac voice diagnose test."}' | "$PY" -c "import sys,json; print(json.load(sys.stdin).get('audio_path',''))")
if [[ -z "$out" || ! -f "$out" ]]; then
  echo "  FAIL synthesis"
  exit 1
fi
file "$out"
echo "  OK  Piper synthesis"
echo ""

echo "4) macOS playback"
echo "  4a) afplay (WAV file)…"
if /usr/bin/afplay "$out" 2>/dev/null; then
  echo "  OK  afplay — neural voice should work in RoPac"
  echo ""
  echo "All checks passed."
  exit 0
fi
echo "  FAIL afplay: AudioQueueStart (CoreAudio WAV playback broken on this Mac)"
echo ""

echo "  4b) system voice (say)…"
if /usr/bin/say -v Rishi "RoPac system voice test." 2>/dev/null; then
  echo "  OK  say — RoPac will use system voice until WAV playback is fixed"
else
  echo "  FAIL say — check System Settings → Sound → Output"
  exit 1
fi
echo ""

echo "  4c) Piper WAV via fallback player…"
if engine=$("$PLAY" "$out" "RoPac voice diagnose test." 2>/dev/null); then
  echo "  OK  played via $engine"
  echo ""
  echo "Synthesis OK. afplay broken; fallback worked."
  exit 0
fi
echo "  FAIL all WAV players"
echo ""
echo "=== How to fix CoreAudio (afplay) ==="
echo "  • System Settings → Sound → Output → MacBook Pro Speakers"
echo "  • Quit Microsoft Teams (virtual audio device can break WAV playback)"
echo "  • Restart audio daemon:"
echo "      sudo launchctl kickstart -kp system/com.apple.audio.coreaudiod"
echo "  • Or restart your Mac"
echo ""
echo "RoPac app: rebuild and use Speak aloud — falls back to system voice when Piper WAV cannot play."
echo "  ./scripts/build_macos_app.sh"
exit 1
