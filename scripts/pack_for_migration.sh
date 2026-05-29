#!/usr/bin/env bash
# Create ropac-portable.zip for USB / transfer (excludes .venv and build caches).
set -euo pipefail

ROPAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PARENT="$(dirname "$ROPAC_DIR")"
NAME="$(basename "$ROPAC_DIR")"
OUT="$PARENT/${NAME}-portable.zip"

echo "==> Packing $ROPAC_DIR"
echo "    Output: $OUT"
echo "    (This may take several minutes if ollama_models/ is large)"

cd "$PARENT"
zip -r "$OUT" "$NAME" \
  -x "$NAME/.venv/*" \
  -x "$NAME/**/__pycache__/*" \
  -x "$NAME/ropac_ui/build/*" \
  -x "$NAME/ropac_ui/.dart_tool/*" \
  -x "$NAME/**/*.part" \
  -x "$NAME/.DS_Store"

echo ""
echo "Done: $OUT"
du -sh "$OUT"
echo ""
echo "On the new Mac:"
echo "  unzip ${NAME}-portable.zip"
echo "  cd $NAME && ./install.sh"
