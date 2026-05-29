# Ollama models path — use ~/.ollama/models (Ollama default).
# shellcheck shell=bash

dir_has_ollama_weights() {
  local dir="$1"
  [[ -d "$dir/blobs" ]] || [[ -d "$dir/manifests" ]]
}

ollama_models_ready() {
  dir_has_ollama_weights "$OLLAMA_MODELS"
}

link_ollama_models_to_ropac() {
  local ollama_home="${OLLAMA_HOME:-$HOME/.ollama}"
  mkdir -p "$ollama_home"
  local models_path="$ollama_home/models"

  # Default: real Ollama folder outside the RoPac project.
  if [[ -L "$models_path" ]]; then
    local link_target
    link_target="$(readlink "$models_path")"
    if [[ "$link_target" == *"/ropac/ollama_models"* ]] ||
      [[ "$link_target" == *"/roPac/ollama_models"* ]]; then
      echo "==> Old RoPac symlink detected — run: ./scripts/use_external_ollama_models.sh"
    fi
  fi

  mkdir -p "$models_path"
  OLLAMA_MODELS="$(cd "$models_path" && pwd -P 2>/dev/null || cd "$models_path" && pwd)"
  export OLLAMA_MODELS
  echo "==> Ollama models folder: $OLLAMA_MODELS"

  if [[ "${ROPAC_PORTABLE_MODELS:-0}" == "1" ]]; then
    echo "==> ROPAC_PORTABLE_MODELS=1 — linking into project (optional)."
    _link_portable_models "$models_path"
  fi
}

_link_portable_models() {
  local models_path="$1"
  local portable_target="$ROPAC_DIR/ollama_models"
  mkdir -p "$portable_target"
  local target_abs
  target_abs="$(cd "$portable_target" && pwd)"

  if [[ -L "$models_path" ]]; then
    rm -f "$models_path"
  elif [[ -d "$models_path" ]] && [[ ! -L "$models_path" ]]; then
    if dir_has_ollama_weights "$portable_target"; then
      echo "==> RoPac portable folder already has models."
    elif [[ -n "$(ls -A "$models_path" 2>/dev/null)" ]]; then
      echo "==> Copying Ollama models into RoPac folder..."
      if command -v rsync &>/dev/null; then
        rsync -a "$models_path/" "$portable_target/"
      else
        cp -R "$models_path/." "$portable_target/"
      fi
    fi
    rm -rf "$models_path"
  fi

  ln -sfn "$target_abs" "$models_path"
  export OLLAMA_MODELS="$target_abs"
  echo "==> Linked: $models_path -> $target_abs"
}

ensure_ollama_running() {
  if curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
    return 0
  fi
  echo "==> Starting Ollama..."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open -a Ollama 2>/dev/null || true
  else
    nohup ollama serve >/dev/null 2>&1 &
  fi
  local i
  for i in {1..30}; do
    if curl -sf "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

configure_macos_ollama_env() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 0
  fi
  if command -v launchctl &>/dev/null; then
    launchctl setenv OLLAMA_MODELS "$OLLAMA_MODELS" 2>/dev/null || true
  fi
}
