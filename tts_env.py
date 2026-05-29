"""Keep all voice-model downloads inside the RoPac folder (portable)."""

from __future__ import annotations

import os
from pathlib import Path

ROPAC_ROOT = Path(__file__).resolve().parent
TTS_DIR = ROPAC_ROOT / "data" / "tts"
HF_HOME = TTS_DIR / "huggingface"
TORCH_HOME = TTS_DIR / "torch"
PARLER_DIR = TTS_DIR / "parler"


def apply_local_voice_cache_env() -> dict[str, str]:
    """Point Hugging Face / torch caches at data/tts/ under RoPac."""
    for d in (TTS_DIR, HF_HOME, HF_HOME / "hub", TORCH_HOME, PARLER_DIR, TTS_DIR / "cache"):
        d.mkdir(parents=True, exist_ok=True)

    env = {
        "HF_HOME": str(HF_HOME),
        "HF_HUB_CACHE": str(HF_HOME / "hub"),
        "HUGGINGFACE_HUB_CACHE": str(HF_HOME / "hub"),
        "TRANSFORMERS_CACHE": str(HF_HOME / "transformers"),
        "TORCH_HOME": str(TORCH_HOME),
        "XDG_CACHE_HOME": str(TTS_DIR / "xdg_cache"),
    }
    for key, val in env.items():
        os.environ[key] = val
    return env
