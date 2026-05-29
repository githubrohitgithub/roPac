#!/usr/bin/env bash
# Export docs/assets/*.svg → PNG for docs and thumbnails.
set -euo pipefail
ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS="$ROPAC_DIR/docs/assets"

_convert() {
  local svg="$1"
  local png="$2"
  local w="${3:-1280}"
  local h="${4:-800}"
  if [[ ! -f "$svg" ]]; then
    echo "Missing $svg"
    return 1
  fi
  if command -v rsvg-convert &>/dev/null; then
    rsvg-convert -w "$w" -h "$h" "$svg" -o "$png"
  elif command -v magick &>/dev/null; then
    magick -background none "$svg" -resize "${w}x${h}" "$png"
  else
    echo "Install librsvg: brew install librsvg"
    echo "SVG only: $svg"
    return 1
  fi
  echo "Wrote $png"
}

for spec in \
  "ropac-flow-diagrams.svg:ropac-flow-diagrams.png:1280:1100" \
  "ropac-personal-assistant.svg:ropac-personal-assistant.png:1280:900" \
  "ropac-data-security.svg:ropac-data-security.png:1280:920" \
  "ropac-system-design.svg:ropac-system-design.png:1280:800"; do
  IFS=: read -r svg png w h <<< "$spec"
  if [[ -f "$ASSETS/$svg" ]]; then
    _convert "$ASSETS/$svg" "$ASSETS/$png" "$w" "$h"
  fi
done
