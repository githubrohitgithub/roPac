#!/usr/bin/env python3
"""Download Piper neural TTS voices for RoPac (offline, one-time)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tts_env import apply_local_voice_cache_env  # noqa: E402

apply_local_voice_cache_env()

from tts_engine import TTS_DIR, download_voices, tts_status  # noqa: E402


def main() -> None:
    print("RoPac neural TTS (Piper fallback)")
    print(f"Models folder: {TTS_DIR}")
    print("For human-like voice, run: ./scripts/download_natural_tts.py")
    print("Downloading English + Hindi Piper voices…")
    installed = download_voices()
    for vid in installed:
        print(f"  ✓ {vid}")
    st = tts_status()
    if st["ready"]:
        print("Done. Natural voice is ready for the app.")
    else:
        print("Warning: English voice missing — check network and retry.")
        sys.exit(1)


if __name__ == "__main__":
    main()
