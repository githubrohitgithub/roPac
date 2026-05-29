#!/usr/bin/env bash
# Play WAV on macOS; fall back to `say` when CoreAudio WAV playback is broken.
# Usage: play_audio_mac.sh <wav> [spoken_fallback_text]
set -euo pipefail

wav="${1:?wav path required}"
text="${2:-}"

if [[ ! -f "$wav" ]]; then
  echo "play_audio_mac: file not found: $wav" >&2
  exit 1
fi

if /usr/bin/afplay "$wav" 2>/dev/null; then
  exit 0
fi

ropac_dir="$(cd "$(dirname "$0")/.." && pwd)"
swift_play="$ropac_dir/scripts/play_wav.swift"
if [[ -x "$swift_play" || -f "$swift_play" ]]; then
  if "$swift_play" "$wav" 2>/dev/null; then
    exit 0
  fi
fi

if [[ -n "$text" ]]; then
  chunk="$text"
  if [[ ${#chunk} -gt 800 ]]; then
    chunk="${chunk:0:800}…"
  fi
  echo "WAV playback failed (CoreAudio). Using system voice instead." >&2
  /usr/bin/say -v Rishi "$chunk"
  exit 0
fi

echo "WAV playback failed. Install fix: see docs/voice-troubleshooting.md" >&2
exit 1
