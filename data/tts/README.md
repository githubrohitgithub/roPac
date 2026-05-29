# Voice models (inside RoPac)

All speech models and caches live **only here** — nothing in `~/.cache` for RoPac.

| Path | Contents |
|------|----------|
| `*.onnx` | Piper voices (e.g. `en_US-amy-medium`, `hi_IN-rohan-medium`) |
| `parler/` | AI4Bharat Indic Parler-TTS (optional, human-like) |
| `huggingface/` | Hugging Face download cache (Parler) |
| `torch/` | PyTorch hub cache (if used) |
| `cache/` | Generated reply WAV files |

## Install Piper (small)

```bash
cd ~/ropac
.venv/bin/python scripts/download_tts_voices.py
```

## Install Parler (large, optional)

```bash
brew install git-lfs   # required once for Parler install
git lfs install
.venv/bin/python scripts/download_natural_tts.py
```

## Move to another Mac

Copy the whole **`ropac`** folder including **`data/tts/`**.
