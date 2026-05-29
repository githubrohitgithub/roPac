#!/usr/bin/env bash
# One-time (or repeat-safe) setup — everything lives inside this RoPac folder.
set -euo pipefail

ROPAC_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROPAC_DIR"

# shellcheck source=scripts/ropac_env.sh
source "$ROPAC_DIR/scripts/ropac_env.sh"
# shellcheck source=scripts/ollama_portable.sh
source "$ROPAC_DIR/scripts/ollama_portable.sh"

PYTHON="${PYTHON:-python3}"
echo ""
echo "=========================================="
echo "  RoPac setup — portable (all-in-folder)"
echo "  $ROPAC_DIR"
echo "=========================================="
echo ""

if ! command -v "$PYTHON" &>/dev/null; then
  echo "ERROR: Python 3 not found. Install Python 3.10+ and retry."
  exit 1
fi

link_ollama_models_to_ropac
write_ropac_env_file
echo "$ROPAC_DIR" >"$ROPAC_DIR/data/ropac_root.txt"
CONFIG_DIR="$HOME/Library/Application Support/com.ropac.ropac_ui"
mkdir -p "$CONFIG_DIR"
echo "$ROPAC_DIR" >"$CONFIG_DIR/ropac_root.txt"
configure_macos_ollama_env

if [[ ! -d .venv ]]; then
  echo "==> Creating Python virtual environment..."
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "==> Personal data encryption (cryptography)..."
python scripts/ensure_encryption.py --setup || {
  echo "WARN: Encryption setup skipped or failed (you can enable in the app)."
}

echo "==> Neural TTS voices (optional, offline)..."
python scripts/download_tts_voices.py || {
  echo "WARN: TTS download skipped or failed (voice optional)."
}

if ! command -v ollama &>/dev/null; then
  echo ""
  echo "ERROR: Ollama is not installed."
  echo "  1. Install from https://ollama.com"
  echo "  2. Run: ./setup.sh"
  exit 1
fi

if ! ensure_ollama_running; then
  echo ""
  echo "ERROR: Ollama did not start."
  echo "  Open the Ollama app manually, then run: ./setup.sh"
  exit 1
fi

export OLLAMA_MODELS
MODEL="$(python -c "import json; print(json.load(open('config.json'))['model'])")"
BASE="$(python -c "import json; print(json.load(open('config.json'))['base_model'])")"

if ollama show "$MODEL" &>/dev/null; then
  echo "==> Model '$MODEL' is ready (using $OLLAMA_MODELS)."
else
  if ollama show "$BASE" &>/dev/null || ollama_models_ready; then
    echo "==> Creating custom model '$MODEL' from Modelfile..."
    ollama create "$MODEL" -f Modelfile
  else
    echo "==> Pulling base model '$BASE' (needs internet once)..."
    ollama pull "$BASE"
    echo "==> Creating custom model '$MODEL'..."
    ollama create "$MODEL" -f Modelfile
  fi
fi

EMBED="$(python -c "import json; print(json.load(open('config.json')).get('embed_model','nomic-embed-text'))")"
if ollama show "$EMBED" &>/dev/null; then
  echo "==> Embed model '$EMBED' is ready."
else
  echo "==> Pulling embed model '$EMBED' (needs internet once)..."
  ollama pull "$EMBED" || {
    echo "WARN: Could not pull '$EMBED'. Document search falls back to keywords."
  }
fi

DOCS_COUNT="$(python -c "
from knowledge import list_documents
print(len(list_documents()))
" 2>/dev/null || echo 0)"
if [[ "$DOCS_COUNT" != "0" ]]; then
  echo "==> Building embeddings for $DOCS_COUNT trained document(s)..."
  python -c "
from knowledge import reindex_all_embeddings
r = reindex_all_embeddings()
print(f\"  Indexed: {r.get('indexed', 0)}, failed: {r.get('failed', 0)}\")
if r.get('error'):
    print(f\"  Note: {r['error']}\")
" || echo "WARN: Embedding reindex skipped."
fi

FACTS="$(python -c "
from ropac_personal_data import migration_status
from data_crypto import is_encryption_enabled, read_json_file
from assistant import MEMORY_PATH
m = migration_status()
if m.get('encryption_enabled'):
    d = read_json_file(MEMORY_PATH) or {}
    print(len(d.get('facts', [])) if isinstance(d, dict) else '?')
else:
    import json
    d = json.load(open('data/memory.json')) if __import__('pathlib').Path('data/memory.json').is_file() else {}
    print(len(d.get('facts', [])))
" 2>/dev/null || echo 0)"
DOCS="$(python -c "
from ropac_personal_data import migration_status
m = migration_status()
print(m.get('trained_documents', 0))
" 2>/dev/null || echo 0)"
ENC="$(python -c "from data_crypto import is_encryption_enabled; print('on' if is_encryption_enabled() else 'off')" 2>/dev/null || echo off)"

echo ""
echo "=========================================="
echo "  RoPac is ready"
echo "=========================================="
echo "  Models:  $OLLAMA_MODELS"
echo "  Memory:  $FACTS fact(s) in data/memory.json"
echo "  Trained: $DOCS document(s) in data/knowledge/"
echo "  Encrypt: $ENC (unlock in app after migrate)"
echo "  Voices:  $TTS_DIR"
echo ""
echo "  Migrate: copy this whole folder (data/ + ollama_models/)"
echo "           See docs/migration-guide.md"
echo ""
echo "  Terminal chat:  ./start.sh"
echo "  macOS app:      ./start_ui.sh  or  ./scripts/build_macos_app.sh"
echo ""
if [[ "$(uname -s)" == "Darwin" ]]; then
  echo "  If the app cannot see the model, quit Ollama (menu bar) and open it again."
  echo ""
fi
