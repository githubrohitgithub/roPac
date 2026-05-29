"""
Offline neural TTS — Indic Parler-TTS (natural) with Piper fallback.
"""

from __future__ import annotations

import hashlib
import re
import wave
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

from tts_env import TTS_DIR, apply_local_voice_cache_env

apply_local_voice_cache_env()
ROPAC_ROOT = TTS_DIR.parent.parent

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Piper fallback voices (smaller, faster; less natural than Parler)
VOICES: dict[str, dict[str, str]] = {
    "en": {
        "id": "en_US-amy-medium",
        "path": "en/en_US/amy/medium",
        "label": "English (Amy)",
    },
    "hi": {
        "id": "hi_IN-rohan-medium",
        "path": "hi/hi_IN/rohan/medium",
        "label": "Hindi (Rohan)",
    },
}

_voice_cache: dict[str, Any] = {}

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def _voice_files(lang: str) -> tuple[Path, Path]:
    meta = VOICES[lang]
    vid = meta["id"]
    d = TTS_DIR / vid
    return d.with_suffix(".onnx"), d.with_suffix(".onnx.json")


def _voice_ready(lang: str) -> bool:
    onnx, cfg = _voice_files(lang)
    return onnx.is_file() and cfg.is_file() and onnx.stat().st_size > 1000


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1000:
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    urlretrieve(url, tmp)  # noqa: S310
    tmp.replace(dest)


def download_voices(langs: list[str] | None = None) -> list[str]:
    langs = langs or list(VOICES.keys())
    installed: list[str] = []
    for lang in langs:
        if lang not in VOICES:
            continue
        meta = VOICES[lang]
        vid = meta["id"]
        rel = meta["path"]
        onnx, cfg = _voice_files(lang)
        base = f"{HF_BASE}/{rel}/{vid}"
        _download_file(f"{base}.onnx", onnx)
        _download_file(f"{base}.onnx.json", cfg)
        installed.append(vid)
    return installed


def _active_engine() -> str:
    try:
        from tts_parler import parler_ready

        if parler_ready():
            return "parler"
    except ImportError:
        pass
    if _voice_ready("en"):
        return "piper"
    return "none"


def tts_status() -> dict[str, Any]:
    engine = _active_engine()
    try:
        from tts_parler import parler_installed, parler_deps_available

        parler_inst = parler_installed()
        parler_deps = parler_deps_available()
    except ImportError:
        parler_inst = False
        parler_deps = False

    ready_en = _voice_ready("en")
    ready_hi = _voice_ready("hi")
    return {
        "engine": engine,
        "ready": engine != "none",
        "ready_hindi": ready_hi or (engine == "parler"),
        "parler_installed": parler_inst,
        "parler_deps": parler_deps,
        "natural_voice_available": engine == "parler",
        "voices": [
            {
                "lang": lang,
                "id": VOICES[lang]["id"],
                "label": VOICES[lang]["label"],
                "installed": _voice_ready(lang),
            }
            for lang in VOICES
        ],
        "models_dir": str(TTS_DIR),
        "hint": (
            "Run ./scripts/download_natural_tts.py for human-like Hindi/English voice"
            if engine != "parler"
            else "Using AI4Bharat Indic Parler-TTS"
        ),
    }


def _pick_lang(text: str) -> str:
    if _DEVANAGARI.search(text):
        return "hi" if _voice_ready("hi") else "en"
    return "en"


def speak_voice_lang() -> str:
    """Default Piper voice for speak-aloud (settings: tts_voice_lang, default Rohan/hi)."""
    lang = "hi"
    try:
        from settings import load_settings

        raw = str(load_settings().get("tts_voice_lang", "hi")).strip().lower()
        if raw in VOICES:
            lang = raw
    except ImportError:
        pass
    if _voice_ready(lang):
        return lang
    if _voice_ready("hi"):
        return "hi"
    return "en"


def _load_voice(lang: str):
    from piper import PiperVoice

    if lang in _voice_cache:
        return _voice_cache[lang]
    if not _voice_ready(lang):
        download_voices([lang])
    onnx, _ = _voice_files(lang)
    voice = PiperVoice.load(str(onnx))
    _voice_cache[lang] = voice
    return voice


def _synthesize_piper(
    text: str, out_path: Path, *, voice_lang: str | None = None
) -> Path:
    lang = voice_lang or _pick_lang(text)
    if not _voice_ready(lang):
        download_voices([lang])

    voice = _load_voice(lang)
    with wave.open(str(out_path), "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return out_path


def synthesize_to_wav(text: str, *, voice_lang: str | None = None) -> Path:
    text = text.strip()
    if not text:
        raise ValueError("Empty text")
    if len(text) > 4000:
        text = text[:4000].rsplit(" ", 1)[0] + "…"

    out_dir = TTS_DIR / "cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    lang_key = voice_lang or _pick_lang(text)
    key = hashlib.sha256(f"{lang_key}:{text}".encode()).hexdigest()[:24]
    engine = _active_engine()
    out_path = out_dir / f"{engine}_{key}.wav"

    if out_path.is_file() and out_path.stat().st_size > 44:
        return out_path

    if engine == "parler":
        from tts_parler import synthesize_to_wav as parler_wav

        return parler_wav(text, out_path)

    if engine == "piper":
        return _synthesize_piper(text, out_path, voice_lang=voice_lang)

    download_voices(["en"])
    return _synthesize_piper(text, out_path, voice_lang=voice_lang)
