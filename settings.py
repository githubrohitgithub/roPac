"""Persisted RoPac UI settings (offline by default)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"

_PERSISTED_API_KEY_FIELDS = (
    "groq_api_key",
    "openai_api_key",
    "openrouter_api_key",
)


def _strip_persisted_api_keys(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove cloud API keys from settings dict (never store on disk)."""
    out = dict(data)
    changed = False
    for key in _PERSISTED_API_KEY_FIELDS:
        if key in out:
            out.pop(key, None)
            changed = True
    if out.get("chat_provider") in ("free_server", "groq", "coder"):
        out["chat_provider"] = "local"
        changed = True
    return out, changed


def default_settings() -> dict[str, Any]:
    return {
        "internet_enabled": False,
        "speak_aloud_enabled": False,
        "memory_suggestions_enabled": True,
        # Chat model: local | openai (API keys are session-only in the UI)
        "chat_provider": "local",
        # Piper voice for speak-aloud: "hi" = Rohan, "en" = Amy
        "tts_voice_lang": "hi",
    }


def load_settings() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        save_settings(default_settings())
        return default_settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_settings()
    if not isinstance(data, dict):
        return default_settings()
    merged = {**default_settings(), **data}
    merged, changed = _strip_persisted_api_keys(merged)
    if changed:
        save_settings(merged)
    return merged


def save_settings(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged, _ = _strip_persisted_api_keys({**default_settings(), **data})
    SETTINGS_PATH.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
