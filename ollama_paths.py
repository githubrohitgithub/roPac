"""Resolve the ollama CLI when PATH is minimal (macOS .app launches)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_MAC_CANDIDATES = (
    "/opt/homebrew/bin/ollama",
    "/usr/local/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
)


def resolve_ollama_bin() -> str:
    for key in ("OLLAMA_BIN", "OLLAMA_EXECUTABLE"):
        raw = os.environ.get(key, "").strip()
        if raw and Path(raw).is_file():
            return str(Path(raw).resolve())

    found = shutil.which("ollama")
    if found:
        return found

    for candidate in _MAC_CANDIDATES:
        p = Path(candidate)
        if p.is_file():
            return str(p.resolve())

    raise FileNotFoundError(
        "ollama not found. Install from https://ollama.com or open the Ollama app."
    )


def ollama_cmd(*args: str) -> list[str]:
    return [resolve_ollama_bin(), *args]
