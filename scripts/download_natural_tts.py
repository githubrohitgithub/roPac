#!/usr/bin/env python3
"""Download AI4Bharat Indic Parler-TTS for natural Hindi / Hinglish voice (~2GB)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tts_env import TTS_DIR, apply_local_voice_cache_env  # noqa: E402

apply_local_voice_cache_env()


def main() -> None:
    print("RoPac natural voice — AI4Bharat Indic Parler-TTS")
    print("Closer to modern assistants than Piper / system voice.")
    print("Fully offline after this one-time download.\n")

    venv_python = ROOT / ".venv" / "bin" / "python"
    py = str(venv_python if venv_python.is_file() else sys.executable)

    deps = [
        "torch>=2.1.0",
        "transformers>=4.46.0",
        "accelerate>=0.26.0",
        "soundfile>=0.12.0",
        "huggingface_hub>=0.23.0",
        "git+https://github.com/huggingface/parler-tts.git",
    ]
    print("==> Installing Python packages (may take a few minutes)...")
    subprocess.check_call([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-q", *deps])

    print(f"==> Downloading model to {TTS_DIR}/parler/ (inside RoPac folder) ...")
    print("    If install fails: brew install git-lfs && git lfs install")
    subprocess.check_call(
        [py, "-c", "from tts_parler import download_model; download_model()"],
        cwd=str(ROOT),
    )

    from tts_parler import parler_ready

    if parler_ready():
        print("\nDone. Restart RoPac and turn on the speaker icon.")
        print("First spoken reply may take a few seconds while the model loads.")
    else:
        print("\nWarning: install finished but parler_ready() is false.")
        sys.exit(1)


if __name__ == "__main__":
    main()
