#!/usr/bin/env bash
# Play a WAV on macOS — afplay, then Swift AppKit, then optional `say` fallback.
set -euo pipefail
WAV="${1:?usage: play_audio_macos.sh <file.wav> [fallback text for say]}"
FALLBACK_TEXT="${2:-}"
ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$WAV" ]]; then
  echo "missing: $WAV" >&2
  exit 2
fi

if /usr/bin/afplay "$WAV" 2>/dev/null; then
  echo "afplay"
  exit 0
fi

if [[ -x "$ROPAC_DIR/scripts/play_wav.swift" ]]; then
  if "$ROPAC_DIR/scripts/play_wav.swift" "$WAV" 2>/dev/null; then
    echo "native"
    exit 0
  fi
fi

if [[ -n "$FALLBACK_TEXT" ]]; then
  chunk="${FALLBACK_TEXT:0:800}"
  if /usr/bin/say -v Rishi "$chunk" 2>/dev/null; then
    echo "say"
    exit 0
  fi
fi

echo "All playback methods failed (CoreAudio WAV broken — try restarting coreaudiod or your Mac)" >&2
exit 1
