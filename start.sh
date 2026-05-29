#!/usr/bin/env bash
# Single command: setup (if needed) + chat. Copy this folder anywhere and run.
set -euo pipefail

ROPAC_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROPAC_DIR"
# shellcheck source=scripts/ropac_env.sh
source "$ROPAC_DIR/scripts/ropac_env.sh"

if [[ ! -d .venv ]] || [[ ! -f .venv/bin/activate ]]; then
  ./setup.sh
fi

# shellcheck disable=SC1091
source .venv/bin/activate
export OLLAMA_MODELS

if ! curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
  echo "ERROR: Ollama is not running. Open Ollama app, then: ./start.sh"
  exit 1
fi

MODEL="$(python -c "import json; print(json.load(open('config.json'))['model'])")"
if ! ollama show "$MODEL" &>/dev/null; then
  echo "Model '$MODEL' missing — running setup..."
  ./setup.sh
fi

exec python assistant.py "$@"
