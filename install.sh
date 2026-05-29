#!/usr/bin/env bash
# One command: configure Python, TTS, Ollama models, and link everything to this folder.
exec "$(cd "$(dirname "$0")" && pwd)/setup.sh" "$@"
