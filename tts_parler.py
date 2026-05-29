"""
Natural offline TTS — AI4Bharat Indic Parler-TTS (Hindi / English / Hinglish).
Optional: run scripts/download_natural_tts.py (~2GB download + torch).
"""

from __future__ import annotations

import re
import wave
from pathlib import Path
from typing import Any

from tts_env import HF_HOME, PARLER_DIR, apply_local_voice_cache_env

apply_local_voice_cache_env()
PARLER_MODEL_ID = "ai4bharat/indic-parler-tts"

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

_model: Any = None
_tokenizer: Any = None
_description_tokenizer: Any = None
_device_name: str | None = None

# Recommended Hindi speakers from model card: Rohit, Divya
_DESC_HINDI = (
    "Rohit speaks with a clear, warm, natural conversational Hindi male voice "
    "at a moderate pace. The recording is very high quality, close and expressive."
)
_DESC_ENGLISH = (
    "Rohit speaks with clear, natural Indian English in a warm conversational tone "
    "at moderate pace. Very high quality recording with no background noise."
)
_DESC_HINGLISH = (
    "Rohit delivers friendly conversational speech with a natural Indian accent, "
    "moderate pace, clear and expressive, very close high-quality recording."
)


def parler_installed() -> bool:
    marker = PARLER_DIR / "config.json"
    return marker.is_file()


def parler_deps_available() -> bool:
    try:
        import torch  # noqa: F401
        from parler_tts import ParlerTTSForConditionalGeneration  # noqa: F401
        import soundfile  # noqa: F401

        return True
    except ImportError:
        return False


def parler_ready() -> bool:
    return parler_installed() and parler_deps_available()


def _pick_description(text: str) -> str:
    has_hi = bool(_DEVANAGARI.search(text))
    has_lat = bool(re.search(r"[A-Za-z]", text))
    if has_hi and has_lat:
        return _DESC_HINGLISH
    if has_hi:
        return _DESC_HINDI
    return _DESC_ENGLISH


def _get_device() -> str:
    global _device_name
    if _device_name is not None:
        return _device_name
    import torch

    if torch.cuda.is_available():
        _device_name = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        _device_name = "mps"
    else:
        _device_name = "cpu"
    return _device_name


def _load() -> None:
    global _model, _tokenizer, _description_tokenizer
    if _model is not None:
        return
    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    dev = _get_device()
    _model = ParlerTTSForConditionalGeneration.from_pretrained(
        str(PARLER_DIR),
        local_files_only=True,
    ).to(dev)
    _tokenizer = AutoTokenizer.from_pretrained(str(PARLER_DIR), local_files_only=True)
    _description_tokenizer = AutoTokenizer.from_pretrained(
        _model.config.text_encoder._name_or_path
    )
    _model.eval()
    if dev == "mps":
        torch.mps.empty_cache()


def _split_chunks(text: str, max_len: int = 280) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?।\n])\s+", text)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(buf) + len(part) + 1 <= max_len:
            buf = f"{buf} {part}".strip() if buf else part
        else:
            if buf:
                chunks.append(buf)
            if len(part) <= max_len:
                buf = part
            else:
                for i in range(0, len(part), max_len):
                    chunks.append(part[i : i + max_len])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def _synthesize_chunk(prompt: str, description: str) -> Any:
    import torch

    dev = _get_device()
    desc_ids = _description_tokenizer(description, return_tensors="pt").to(dev)
    prompt_ids = _tokenizer(prompt, return_tensors="pt").to(dev)

    with torch.inference_mode():
        out = _model.generate(
            input_ids=desc_ids.input_ids,
            attention_mask=desc_ids.attention_mask,
            prompt_input_ids=prompt_ids.input_ids,
            prompt_attention_mask=prompt_ids.attention_mask,
        )
    return out.cpu().numpy().squeeze(), int(_model.config.sampling_rate)


def _write_wav(path: Path, audio: Any, sample_rate: int) -> None:
    import numpy as np
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(audio, dtype=np.float32).squeeze()
    sf.write(str(path), arr, sample_rate)


def _concat_wavs(paths: list[Path], out: Path, pause_ms: int = 120) -> Path:
    if not paths:
        raise ValueError("No audio chunks")
    if len(paths) == 1:
        return paths[0]

    import numpy as np
    import soundfile as sf

    segments: list[Any] = []
    rate = 24000
    for p in paths:
        data, rate = sf.read(str(p), dtype="float32")
        segments.append(data)
        if p != paths[-1]:
            gap = np.zeros(int(rate * pause_ms / 1000), dtype=np.float32)
            segments.append(gap)
    merged = np.concatenate(segments)
    sf.write(str(out), merged, rate)
    return out


def synthesize_to_wav(text: str, out_path: Path) -> Path:
    if not parler_ready():
        raise RuntimeError("Indic Parler-TTS not installed")

    _load()
    chunks = _split_chunks(text)
    if not chunks:
        raise ValueError("Empty text")

    description = _pick_description(text)
    cache_dir = PARLER_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    part_paths: list[Path] = []
    for i, chunk in enumerate(chunks):
        part = cache_dir / f"part_{hash(chunk) & 0xFFFFFFFF:08x}_{i}.wav"
        if part.is_file() and part.stat().st_size > 44:
            part_paths.append(part)
            continue
        audio, sr = _synthesize_chunk(chunk, description)
        _write_wav(part, audio, sr)
        part_paths.append(part)

    if len(part_paths) == 1:
        import shutil

        shutil.copy2(part_paths[0], out_path)
        return out_path

    return _concat_wavs(part_paths, out_path)


def download_model() -> Path:
    apply_local_voice_cache_env()
    PARLER_DIR.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=PARLER_MODEL_ID,
        local_dir=str(PARLER_DIR),
        local_dir_use_symlinks=False,
    )
    return PARLER_DIR
