#!/usr/bin/env python3
"""
Offline JSON bridge for RoPac Flutter UI.
One request on stdin, one JSON object on stdout. No network server.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROPAC_ROOT = Path(__file__).resolve().parent


def _play_wav_macos(wav: Path) -> str:
    """Play Piper WAV — afplay, osascript shell, Swift, then fail."""
    import shlex

    path = str(wav.resolve())
    r = subprocess.run(
        ["/usr/bin/afplay", path],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode == 0:
        return "afplay"

    script = f'do shell script "/usr/bin/afplay {shlex.quote(path)}"'
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=True,
            timeout=300,
        )
        return "afplay_shell"
    except subprocess.CalledProcessError:
        pass

    swift = ROPAC_ROOT / "scripts" / "play_wav.swift"
    if swift.is_file():
        r2 = subprocess.run(
            [str(swift), path],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r2.returncode == 0:
            return "native"

    raise subprocess.CalledProcessError(1, "afplay", "WAV playback failed")


def _play_wav_darwin(wav: Path, fallback_text: str = "") -> str:
    """Play WAV on macOS. Returns engine name. Falls back to `say` if [fallback_text]."""
    try:
        return _play_wav_macos(wav)
    except subprocess.CalledProcessError:
        pass

    text = (fallback_text or "").strip()[:800]
    if text:
        _say_macos(text)
        return "say"

    raise subprocess.CalledProcessError(
        1, "afplay", "AudioQueueStart failed and no fallback text"
    )


def _running_models(data: Any) -> list[Any]:
    """Ollama /api/ps may return {\"models\": [...]} or a bare list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        models = data.get("models")
        if isinstance(models, list):
            return models
    return []


def _model_entry_name(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("model") or "")
    if isinstance(entry, str):
        return entry
    return ""


def _is_model_loaded(model_name: str) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=3) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    base = model_name.split(":")[0]
    for entry in _running_models(data):
        name = _model_entry_name(entry)
        if not name:
            continue
        if name.split(":")[0] == base or name == model_name:
            return True
    return False


def _model_listed(model_name: str) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=5
        ) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False
    models = data.get("models")
    if not isinstance(models, list):
        return False
    base = model_name.split(":")[0]
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        if name == model_name or name.split(":")[0] == base:
            return True
    return False


def _warm_model(model_name: str, *, timeout_sec: float = 90.0) -> tuple[bool, str]:
    """Load weights with a ceiling so the UI does not hang forever."""
    import threading

    from assistant import local_chat_stream_text

    result: dict[str, Any] = {"ok": False, "err": ""}

    def worker() -> None:
        try:
            stream = local_chat_stream_text(
                model=model_name,
                messages=[{"role": "user", "content": " "}],
                temperature=0.0,
                max_tokens=8,
                timeout_sec=timeout_sec,
            )
            for _ in stream:
                result["ok"] = True
                return
            result["ok"] = True
        except Exception as e:
            result["err"] = str(e)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)
    if thread.is_alive():
        return (
            False,
            f"Still loading {model_name} — you can chat; the first reply may take a minute.",
        )
    if result["ok"]:
        return True, f"{model_name} is ready"
    err = str(result.get("err") or "").strip()
    return False, err or f"Could not load {model_name}"


def _ok(payload: dict[str, Any]) -> None:
    out = {"ok": True, **payload}
    print(json.dumps(out, ensure_ascii=False), flush=True)


def _err(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False), flush=True)
    sys.exit(1)


def _stream_event(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _say_macos(text: str) -> None:
    """Speak via macOS `say`, with osascript fallback (works when direct say is silent)."""
    import shlex

    text = text.strip()[:800]
    if not text:
        raise ValueError("Empty text")

    has_devanagari = any("\u0900" <= c <= "\u097f" for c in text)
    args = ["/usr/bin/say", "-v", "Lekha", text] if has_devanagari else ["/usr/bin/say", text]

    try:
        subprocess.run(args, check=True, timeout=300)
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    shell_cmd = " ".join(shlex.quote(a) for a in args)
    script = f"do shell script {shlex.quote(shell_cmd)}"
    subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=True,
        timeout=300,
    )


def _speak_aloud(text: str, *, prefer_piper: bool = True) -> dict[str, Any]:
    """Speak aloud: Piper (Amy / Rohan) when ready, else system `say`."""
    text = text.strip()
    if not text:
        return {"spoken": False, "engine": "none"}

    chunk = text[:2500]

    if sys.platform == "darwin":
        if prefer_piper:
            try:
                from tts_engine import VOICES, speak_voice_lang, synthesize_to_wav, tts_status

                st = tts_status()
                if st.get("ready"):
                    lang = speak_voice_lang()
                    voice_meta = VOICES.get(lang, VOICES["en"])
                    wav = synthesize_to_wav(chunk, voice_lang=lang)
                    play_engine = _play_wav_darwin(
                        wav.resolve(), fallback_text=chunk[:800]
                    )
                    if play_engine in ("afplay", "afplay_shell", "native"):
                        return {
                            "spoken": True,
                            "engine": "piper",
                            "voice": voice_meta["id"],
                            "label": voice_meta["label"],
                            "play": play_engine,
                        }
            except Exception as e:
                _say_macos(chunk)
                return {
                    "spoken": True,
                    "engine": "say",
                    "piper_note": str(e),
                }

        _say_macos(chunk)
        return {"spoken": True, "engine": "say"}

    if sys.platform.startswith("linux"):
        try:
            from tts_engine import synthesize_to_wav, tts_status

            if tts_status().get("ready"):
                wav = synthesize_to_wav(chunk)
                subprocess.run(["aplay", str(wav.resolve())], check=True, timeout=300)
                return {"spoken": True, "engine": "piper"}
        except Exception:
            pass
        subprocess.run(["espeak", chunk[:800]], check=False, timeout=300)
        return {"spoken": True, "engine": "espeak"}

    _err("Speech not supported on this platform")


def _attachment_paths_from_req(req: dict[str, Any]) -> list[str]:
    raw = req.get("attachment_paths")
    if raw is None:
        single = str(req.get("attachment_path", "")).strip()
        return [single] if single else []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _history_for_chat(req: dict[str, Any]) -> list:
    """Drop prior turns when starting fresh — old chat must not reach the model."""
    if req.get("fresh_session"):
        return []
    history = req.get("history") or []
    if not isinstance(history, list):
        return []
    return history


def _handle(req: dict[str, Any]) -> None:
    action = req.get("action")
    if not action:
        _err("Missing action")

    if action == "health":
        from assistant import get_client, load_config

        cfg = load_config()
        custom_model = str(cfg.get("model") or "roPac")
        include_catalog = bool(req.get("include_catalog", True))
        try:
            get_client().models.list()
            ollama_ok = True
            err = ""
        except Exception as e:
            ollama_ok = False
            err = str(e)
        loaded = _is_model_loaded(custom_model) if ollama_ok else False
        payload: dict[str, Any] = {
            "ollama": ollama_ok,
            "model": custom_model,
            "base_model": str(cfg.get("base_model") or ""),
            "model_loaded": loaded,
            "ropac_root": str(ROPAC_ROOT),
            "error": err,
        }
        if include_catalog:
            from model_manager import model_catalog

            payload["catalog"] = model_catalog()
        _ok(payload)
        return

    if action == "list_models":
        from model_manager import model_catalog

        _ok(model_catalog())
        return

    if action == "pull_model":
        from model_manager import pull_base_model

        base = str(req.get("base_model", "")).strip()
        if not base:
            _err("Missing base_model")
        try:
            result = pull_base_model(base)
        except Exception as e:
            _err(str(e))
        from model_manager import model_catalog

        _ok({**result, "catalog": model_catalog()})
        return

    if action == "set_base_model":
        from model_manager import model_catalog, set_base_model

        base = str(req.get("base_model", "")).strip()
        if not base:
            _err("Missing base_model")
        pull = bool(req.get("pull_if_missing", False))
        try:
            result = set_base_model(base, pull_if_missing=pull)
        except Exception as e:
            _err(str(e))
        _ok({**result, "catalog": model_catalog()})
        return

    if action == "start_model":
        from assistant import load_config, get_client

        cfg = load_config()
        custom = str(cfg.get("model") or "roPac")

        try:
            get_client().models.list()
        except Exception as e:
            _err(f"Ollama not reachable. Open the Ollama app first. ({e})")

        if not _model_listed(custom):
            _err(
                f"Model '{custom}' not found. Model tab → pick a base model, "
                f"or run: ollama create {custom} -f Modelfile"
            )

        if _is_model_loaded(custom):
            _ok(
                {
                    "model": custom,
                    "model_loaded": True,
                    "message": f"{custom} is ready",
                }
            )
            return

        ok, msg = _warm_model(custom, timeout_sec=90.0)
        loaded = ok or _is_model_loaded(custom)
        _ok(
            {
                "model": custom,
                "model_loaded": loaded,
                "message": msg,
            }
        )
        return

    if action == "interrupt":
        from assistant import load_config
        from ollama_paths import ollama_cmd

        DEFAULT_MODEL = str(load_config().get("model") or "roPac")
        subprocess.run(
            ollama_cmd("stop", DEFAULT_MODEL),
            capture_output=True,
            text=True,
            check=False,
        )
        _ok({"message": "Generation interrupted"})
        return

    if action == "stop_model":
        from assistant import load_config
        from ollama_paths import ollama_cmd

        DEFAULT_MODEL = str(load_config().get("model") or "roPac")
        subprocess.run(
            ollama_cmd("stop", DEFAULT_MODEL),
            capture_output=True,
            text=True,
            check=False,
        )
        _ok(
            {
                "model": DEFAULT_MODEL,
                "model_loaded": False,
                "message": f"Stopped {DEFAULT_MODEL}",
            }
        )
        return

    if action == "settings":
        from settings import load_settings

        _ok({"settings": load_settings()})
        return

    if action == "set_settings":
        from settings import load_settings, save_settings

        current = load_settings()
        if "internet_enabled" in req:
            current["internet_enabled"] = bool(req["internet_enabled"])
        if "speak_aloud_enabled" in req:
            current["speak_aloud_enabled"] = bool(req["speak_aloud_enabled"])
        if "memory_suggestions_enabled" in req:
            current["memory_suggestions_enabled"] = bool(
                req["memory_suggestions_enabled"]
            )
        if "chat_provider" in req:
            from assistant import normalize_chat_provider

            current["chat_provider"] = normalize_chat_provider(req.get("chat_provider"))
        save_settings(current)
        _ok({"settings": current})
        return

    if action == "crypto_status":
        from data_crypto import crypto_status

        _ok({"crypto": crypto_status()})
        return

    if action == "personal_data_setup":
        from ropac_personal_data import personal_data_setup

        password = str(req.get("password", "")).strip() or None
        result = personal_data_setup(password)
        if password and result.get("needs_enable") and "Incorrect" in str(
            result.get("message", "")
        ):
            _err(str(result.get("message", "Setup failed")))
        _ok(result)
        return

    if action == "enable_encryption":
        from ropac_personal_data import enable_encryption

        password = str(req.get("password", "")).strip()
        if not password:
            _err("Owner password required")
        ok, msg = enable_encryption(password)
        if not ok:
            _err(msg)
        from data_crypto import crypto_status

        _ok({"message": msg, "crypto": crypto_status()})
        return

    if action == "unlock_vault":
        from data_crypto import vault_unlock

        password = str(req.get("password", "")).strip()
        ok, msg = vault_unlock(password)
        if not ok:
            _err(msg)
        from data_crypto import crypto_status

        _ok({"message": msg, "crypto": crypto_status()})
        return

    if action == "lock_vault":
        from data_crypto import crypto_status, vault_lock

        vault_lock()
        _ok({"message": "Vault locked", "crypto": crypto_status()})
        return

    if action == "parse_attachment":
        from chat_attachments import extract_attachment_text

        path = str(req.get("path", "")).strip()
        if not path:
            _err("Missing path")
        p = Path(path).expanduser()
        if not p.is_file():
            _err(f"File not found: {path}")
        result = extract_attachment_text(p)
        _ok({"attachment": result})
        return

    if action == "chat":
        from assistant import chat, needs_personal_vault_for_message, resolve_chat_attachment_paths
        from data_crypto import require_unlocked_session

        message = str(req.get("message", "")).strip()
        attachment_paths = resolve_chat_attachment_paths(
            _attachment_paths_from_req(req),
            fresh_session=bool(req.get("fresh_session")),
        )
        if not message and not attachment_paths:
            _err("Empty message")
        if not message and attachment_paths:
            message = (
                "Answer using the attached file(s). Summarize key points "
                "and be ready for follow-up questions."
            )
        history = _history_for_chat(req)
        auto_learn = bool(req.get("auto_learn", True))
        use_internet = bool(req.get("use_internet", False))
        from assistant import normalize_chat_provider

        chat_provider = normalize_chat_provider(
            req.get("chat_provider"),
            use_server_model=bool(req.get("use_server_model", False)),
        )
        openai_key = str(req.get("openai_api_key", "")).strip() or None
        password = str(req.get("password", "")).strip() or None
        if password:
            require_unlocked_session(password=password)
        elif needs_personal_vault_for_message(message):
            ok, vault_msg = require_unlocked_session(password=None)
            if not ok:
                _err(f"VAULT_LOCKED: {vault_msg}")
        from rag import retrieve_rag_metadata
        rag_meta = retrieve_rag_metadata(
            message,
            attachment_paths=attachment_paths,
            has_chat_attachments=bool(attachment_paths),
            owner_password=password,
        )
        reply, _, _ = chat(
            message,
            history=history,
            auto_learn=auto_learn,
            owner_password=password,
            use_internet=use_internet,
            chat_provider=chat_provider,
            openai_api_key_override=openai_key,
            attachment_paths=attachment_paths,
        )
        _ok({"reply": reply, "rag_metadata": rag_meta})
        return

    if action == "save_memory_suggestions":
        from assistant import save_memory_suggestions
        from data_crypto import require_unlocked_session

        facts = req.get("facts") or []
        if not isinstance(facts, list):
            _err("facts must be a list")
        password = str(req.get("password", "")).strip() or None
        ok, vault_msg = require_unlocked_session(password=password)
        if not ok:
            _err(f"VAULT_LOCKED: {vault_msg}")
        cleaned = [str(f).strip() for f in facts if str(f).strip()]
        msg, items = save_memory_suggestions(cleaned, password)
        if "incorrect" in msg.lower():
            _err(msg)
        _ok({"message": msg, "items": items})
        return

    if action == "needs_personal_vault":
        from assistant import needs_personal_vault_for_message

        message = str(req.get("message", "")).strip()
        _ok({"needed": needs_personal_vault_for_message(message)})
        return

    if action == "chat_stream":
        from assistant import chat_stream, needs_personal_vault_for_message, resolve_chat_attachment_paths
        from data_crypto import require_unlocked_session

        message = str(req.get("message", "")).strip()
        attachment_paths = resolve_chat_attachment_paths(
            _attachment_paths_from_req(req),
            fresh_session=bool(req.get("fresh_session")),
        )
        if not message and not attachment_paths:
            _stream_event({"ok": False, "error": "Empty message"})
            return
        if not message and attachment_paths:
            message = (
                "Answer using the attached file(s). Summarize key points "
                "and be ready for follow-up questions."
            )
        history = _history_for_chat(req)
        auto_learn = bool(req.get("auto_learn", True))
        use_internet = bool(req.get("use_internet", False))
        from assistant import normalize_chat_provider

        chat_provider = normalize_chat_provider(
            req.get("chat_provider"),
            use_server_model=bool(req.get("use_server_model", False)),
        )
        openai_key = str(req.get("openai_api_key", "")).strip() or None
        password = str(req.get("password", "")).strip() or None
        if password:
            require_unlocked_session(password=password)
        elif needs_personal_vault_for_message(message):
            ok, vault_msg = require_unlocked_session(password=None)
            if not ok:
                _stream_event({"ok": False, "error": f"VAULT_LOCKED: {vault_msg}"})
                return
        try:
            stream_meta: dict[str, Any] = {}
            parts: list[str] = []
            for chunk in chat_stream(
                message,
                history=history,
                auto_learn=auto_learn,
                owner_password=password,
                use_internet=use_internet,
                chat_provider=chat_provider,
                openai_api_key_override=openai_key,
                attachment_paths=attachment_paths,
                stream_meta=stream_meta,
            ):
                parts.append(chunk)
                _stream_event({"type": "chunk", "text": chunk})
            suggestions = stream_meta.get("memory_suggestions") or []
            if suggestions:
                _stream_event(
                    {
                        "type": "memory_suggestions",
                        "facts": suggestions,
                    }
                )
            from rag import retrieve_rag_metadata
            rag_meta = retrieve_rag_metadata(
                message,
                attachment_paths=attachment_paths,
                has_chat_attachments=bool(attachment_paths),
                owner_password=password,
            )
            _stream_event(
                {
                    "ok": True,
                    "reply": "".join(parts),
                    "memory_suggestions": suggestions,
                    "rag_metadata": rag_meta,
                }
            )
        except Exception as e:
            _stream_event({"ok": False, "error": str(e)})
        return

    if action == "memory":
        from assistant import load_memory, memory_block
        from data_crypto import require_unlocked_session

        password = str(req.get("password", "")).strip() or None
        ok, vault_msg = require_unlocked_session(password=password)
        if not ok:
            _err(f"VAULT_LOCKED: {vault_msg}")
        data = load_memory(password=password)
        _ok(
            {
                "text": memory_block(),
                "facts": data.get("facts", []),
            }
        )
        return

    if action == "sources":
        from data_crypto import require_unlocked_session
        from knowledge import list_documents

        password = str(req.get("password", "")).strip() or None
        ok, vault_msg = require_unlocked_session(password=password)
        if not ok:
            _err(f"VAULT_LOCKED: {vault_msg}")
        _ok({"documents": list_documents(owner_password=password)})
        return

    if action == "reindex_embeddings":
        from data_crypto import require_unlocked_session
        from knowledge import reindex_all_embeddings

        password = str(req.get("password", "")).strip() or None
        ok, vault_msg = require_unlocked_session(password=password)
        if not ok:
            _err(f"VAULT_LOCKED: {vault_msg}")
        force = bool(req.get("force", False))
        result = reindex_all_embeddings(owner_password=password, force=force)
        if not result.get("ok") and result.get("error"):
            _err(str(result["error"]))
        _ok(result)
        return

    if action == "forget_all_trained":
        from assistant import forget_all_trained
        from data_crypto import require_unlocked_session

        password = str(req.get("password", "")).strip() or None
        ok, vault_msg = require_unlocked_session(password=password)
        if not ok:
            _err(f"VAULT_LOCKED: {vault_msg}")
        if not password:
            _err("Owner password required")
        msg, result = forget_all_trained(owner_password=password)
        _ok({"message": msg, **result})
        return

    if action == "clear_chat_session":
        from assistant import clear_chat_session

        msg, result = clear_chat_session()
        _ok({"message": msg, **result})
        return

    if action == "hard_reset_local_data":
        from assistant import hard_reset_local_data
        from data_crypto import require_unlocked_session

        password = str(req.get("password", "")).strip() or None
        ok, vault_msg = require_unlocked_session(password=password)
        if not ok:
            _err(f"VAULT_LOCKED: {vault_msg}")
        if not password:
            _err("Owner password required")
        try:
            msg, result = hard_reset_local_data(owner_password=password)
        except ValueError as e:
            _err(str(e))
        except Exception as e:
            _err(str(e))
        _ok({"message": msg, **result})
        return

    if action == "remember":
        from assistant import remember_explicit

        fact = str(req.get("fact", "")).strip()
        password = str(req.get("password", ""))
        if not fact:
            _err("Empty fact")
        if not password:
            _err("Owner password required")
        msg, items = remember_explicit(fact, password=password)
        if "incorrect" in msg.lower() or "cancelled" in msg.lower():
            _err(msg)
        _ok({"message": msg, "items": items})
        return

    if action == "forget":
        from assistant import forget_explicit

        query = str(req.get("query", "")).strip()
        password = str(req.get("password", ""))
        if not query:
            _err("Empty query")
        if not password:
            _err("Owner password required")
        msg, items = forget_explicit(query, password=password)
        if "incorrect" in msg.lower() or "cancelled" in msg.lower():
            _err(msg)
        _ok({"message": msg, "items": items})
        return

    if action == "train":
        from assistant import train_explicit

        path = str(req.get("path", "")).strip()
        if not path:
            _err("Missing path")
        password = str(req.get("password", "")).strip() or None
        p = Path(path).expanduser()
        if not p.is_file():
            _err(f"File not found: {path}")
        if not password:
            _err("Owner password required")
        msg, payload = train_explicit(str(p), owner_password=password)
        _ok({"message": msg, "items": payload.get("facts_added", [])})
        return

    if action == "tts_status":
        from tts_engine import tts_status

        _ok(tts_status())
        return

    if action == "tts_download":
        from tts_engine import download_voices, tts_status

        langs = req.get("langs")
        if langs is not None and not isinstance(langs, list):
            langs = None
        installed = download_voices(langs)
        _ok({"installed": installed, **tts_status()})
        return

    if action == "speak_aloud":
        text = str(req.get("text", "")).strip()
        if not text:
            _err("Empty text")
        prefer_piper = bool(req.get("prefer_piper", True))
        result = _speak_aloud(text, prefer_piper=prefer_piper)
        _ok(result)
        return

    if action == "tts_speak":
        from tts_engine import synthesize_to_wav, tts_status

        text = str(req.get("text", "")).strip()
        if not text:
            _err("Empty text")
        st = tts_status()
        if not st.get("ready"):
            _err(
                "Neural voice not installed. Run: ./setup.sh "
                "or python scripts/download_tts_voices.py"
            )
        try:
            wav = synthesize_to_wav(text)
        except Exception as e:
            _err(f"TTS failed: {e}")
        _ok({"audio_path": str(wav.resolve()), "engine": "piper"})
        return

    if action == "tts_speak_and_play":
        from tts_engine import synthesize_to_wav, tts_status

        text = str(req.get("text", "")).strip()
        if not text:
            _err("Empty text")
        st = tts_status()
        if not st.get("ready"):
            _err(
                "Neural voice not installed. Run: ./setup.sh "
                "or python scripts/download_tts_voices.py"
            )
        try:
            wav = synthesize_to_wav(text)
            wav = wav.resolve()
            play_engine = st.get("engine", "piper")
            if sys.platform == "darwin":
                play_engine = _play_wav_darwin(wav, fallback_text=text)
            elif sys.platform.startswith("linux"):
                subprocess.run(
                    ["aplay", str(wav)],
                    check=True,
                    timeout=300,
                )
        except subprocess.CalledProcessError as e:
            _err(f"Audio playback failed: {e}")
        except Exception as e:
            _err(f"TTS failed: {e}")
        _ok(
            {
                "audio_path": str(wav),
                "played": True,
                "engine": play_engine,
            }
        )
        return

    _err(f"Unknown action: {action}")


def _parse_request() -> dict[str, Any]:
    """Prefer argv[1] (Flutter/macOS); fall back to stdin."""
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()
    if not raw or not str(raw).strip():
        return {}
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        _err(f"Invalid JSON: {e}")
    if not isinstance(req, dict):
        _err("Request must be a JSON object")
    return req


def main() -> None:
    try:
        _handle(_parse_request())
    except Exception as e:
        _err(str(e))


if __name__ == "__main__":
    main()
