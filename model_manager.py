"""
Ollama base-model selection for RoPac (config.json + Modelfile + ollama create).
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROPAC_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROPAC_ROOT / "config.json"
MODELFILE_PATH = ROPAC_ROOT / "Modelfile"

# Default when Ollama downloads models (macOS/Linux).
DEFAULT_OLLAMA_MODELS_DIR = Path.home() / ".ollama" / "models"
ROPAC_OLLAMA_MODELS_DIR = ROPAC_ROOT / "ollama_models"

# Curated presets (sidebar). Any installed Ollama model can also be chosen.
MODEL_PRESETS: list[dict[str, str]] = [
    {
        "id": "gemma3:2b",
        "label": "Gemma 3 2B",
        "tier": "Fast · smallest",
    },
    {
        "id": "llama3.2:3b",
        "label": "Llama 3.2 3B",
        "tier": "Fast",
    },
    {
        "id": "qwen2.5-coder:latest",
        "label": "Qwen 2.5 Coder",
        "tier": "Code · default",
    },
    {
        "id": "llama3.1:8b",
        "label": "Llama 3.1 8B",
        "tier": "Balanced",
    },
    {
        "id": "mistral:7b",
        "label": "Mistral 7B",
        "tier": "Balanced",
    },
    {
        "id": "qwen2.5:7b",
        "label": "Qwen 2.5 7B",
        "tier": "Strong",
    },
    {
        "id": "llama3.1:70b",
        "label": "Llama 3.1 70B",
        "tier": "Largest · slowest",
    },
]


def load_config() -> dict[str, Any]:
    from assistant import load_config as _load

    return _load()


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    cfg.update(updates)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return cfg


def _ollama_tags() -> list[dict[str, Any]]:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=5
        ) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    models = data.get("models")
    return models if isinstance(models, list) else []


def _ollama_dir_has_weights(path: Path) -> bool:
    return (path / "manifests").is_dir() or (path / "blobs").is_dir()


def _ollama_models_root() -> Path:
    """Prefer ~/.ollama/models (normal `ollama pull` location)."""
    import os

    home_default = DEFAULT_OLLAMA_MODELS_DIR
    if home_default.is_dir() and _ollama_dir_has_weights(home_default):
        return home_default

    explicit = os.environ.get("OLLAMA_MODELS")
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            return p

    if ROPAC_OLLAMA_MODELS_DIR.is_dir() and _ollama_dir_has_weights(ROPAC_OLLAMA_MODELS_DIR):
        return ROPAC_OLLAMA_MODELS_DIR

    if home_default.is_dir():
        return home_default
    return home_default


def _manifest_path(model_name: str) -> Path | None:
    base, tag = (model_name.split(":") + ["latest"])[:2]
    for root in _all_model_roots():
        manifest = (
            root / "manifests" / "registry.ollama.ai" / "library" / base / tag
        )
        if manifest.is_file() or manifest.is_dir():
            return manifest
    return None


def _model_disk_path(model_name: str) -> str:
    """Best-effort path to this model under Ollama's models directory."""
    manifest = _manifest_path(model_name)
    if manifest is not None:
        return str(manifest.resolve())
    return str(_ollama_models_root().resolve())


def resolve_installed_ref(requested: str) -> str | None:
    """Map preset name to an installed Ollama model name, if present."""
    requested = requested.strip()
    if not requested:
        return None
    installed = list_installed_base_models()
    if requested in installed:
        return requested
    req_base = requested.split(":")[0]
    for name in installed:
        if name.split(":")[0] == req_base:
            return name
    return None


def normalize_from_ref(ref: str) -> str:
    """FROM line value: filesystem path or Ollama model name."""
    ref = ref.strip().strip('"').strip("'")
    if not ref:
        raise ValueError("Empty model path or name")
    path = Path(ref).expanduser()
    if path.exists():
        return str(path.resolve())
    resolved = resolve_installed_ref(ref)
    if resolved:
        return resolved
    return ref


def installed_model_entries() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "ref": name,
            "path": _model_disk_path(name),
        }
        for name in list_installed_base_models()
    ]


def _skip_model_base(base: str) -> bool:
    custom = str(load_config().get("model") or "roPac")
    lower = base.lower()
    if "embed" in lower or base.startswith("nomic-"):
        return True
    return base == custom


def _all_model_roots() -> list[Path]:
    import os

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in (
        DEFAULT_OLLAMA_MODELS_DIR,
        os.environ.get("OLLAMA_MODELS"),
        str(ROPAC_OLLAMA_MODELS_DIR),
    ):
        if not candidate:
            continue
        p = Path(candidate).expanduser()
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen or not p.is_dir():
            continue
        seen.add(key)
        roots.append(p)
    return roots


def _models_from_disk() -> list[str]:
    """List models from every Ollama models dir on disk (API not required)."""
    names: list[str] = []
    for root in _all_model_roots():
        library = root / "manifests" / "registry.ollama.ai" / "library"
        if not library.is_dir():
            continue
        for base_dir in sorted(library.iterdir()):
            if not base_dir.is_dir():
                continue
            base = base_dir.name
            if _skip_model_base(base):
                continue
            for tag_entry in sorted(base_dir.iterdir()):
                if tag_entry.is_file() or tag_entry.is_dir():
                    tag = f"{base}:{tag_entry.name}"
                    if tag not in names:
                        names.append(tag)
    return names


def _manifest_exists_on_disk(model_name: str) -> bool:
    return _manifest_path(model_name) is not None


def _models_from_ollama_cli() -> list[str]:
    """`ollama list` — same models the Ollama app shows when the daemon is up."""
    from ollama_paths import ollama_cmd

    try:
        proc = subprocess.run(
            ollama_cmd("list"),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    custom = str(load_config().get("model") or "roPac")
    names: list[str] = []
    for line in proc.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        name = line.split()[0].strip()
        if not name or name.upper() == "NAME":
            continue
        lower = name.lower()
        if "embed" in lower or name.startswith("nomic-"):
            continue
        if name.split(":")[0] == custom:
            continue
        names.append(name)
    return names


def list_installed_base_models() -> list[str]:
    names: list[str] = []
    custom = str(load_config().get("model") or "roPac")
    for entry in _ollama_tags():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        lower = name.lower()
        if "embed" in lower or name.startswith("nomic-"):
            continue
        if name.split(":")[0] == custom:
            continue
        names.append(name)
    for name in _models_from_ollama_cli():
        if name not in names:
            names.append(name)
    for name in _models_from_disk():
        if name not in names:
            names.append(name)
    return sorted(set(names))


def is_base_model_installed(base_model: str) -> bool:
    base_model = base_model.strip()
    if not base_model:
        return False
    if Path(base_model).expanduser().exists():
        return True
    if _manifest_exists_on_disk(base_model):
        return True
    base = base_model.split(":")[0]
    if _manifest_exists_on_disk(f"{base}:latest"):
        return True
    if _ollama_show_ok(base_model):
        return True
    for name in list_installed_base_models():
        if name == base_model or name.split(":")[0] == base:
            return True
    return False


def model_catalog() -> dict[str, Any]:
    cfg = load_config()
    current = str(cfg.get("base_model") or "qwen2.5-coder:latest")
    installed = list_installed_base_models()
    installed_set = set(installed)
    preset_ids = {p["id"] for p in MODEL_PRESETS}
    presets: list[dict[str, Any]] = []
    for p in MODEL_PRESETS:
        entry = dict(p)
        entry["installed"] = is_base_model_installed(p["id"])
        presets.append(entry)
    extra = [m for m in installed if m not in preset_ids]
    current_path = ""
    if is_base_model_installed(current):
        p = Path(current).expanduser()
        if p.exists():
            current_path = str(p.resolve())
        else:
            current_path = _model_disk_path(
                resolve_installed_ref(current) or current
            )
    coder_model = str(cfg.get("coder_model") or "qwen2.5-coder:latest").strip()
    return {
        "custom_model": str(cfg.get("model") or "roPac"),
        "current_base_model": current,
        "current_base_path": current_path,
        "coder_model": coder_model,
        "coder_installed": is_base_model_installed(coder_model),
        "presets": presets,
        "installed_extra": extra,
        "installed_models": installed,
        "installed_entries": installed_model_entries(),
        "ollama_models_dir": str(_ollama_models_root().resolve()),
        "default_ollama_models_dir": str(DEFAULT_OLLAMA_MODELS_DIR.resolve()),
        "ollama_store_path": str(DEFAULT_OLLAMA_MODELS_DIR.resolve()),
        "ollama_reachable": bool(_ollama_tags()),
    }


def query_model_context_length(model_name: str) -> int | None:
    """Query local Ollama api/show for the context length of a model."""
    import json
    import urllib.request
    try:
        url = "http://127.0.0.1:11434/api/show"
        data = json.dumps({"name": model_name}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            model_info = res.get("model_info", {})
            for k, v in model_info.items():
                if k.endswith(".context_length"):
                    return int(v)
    except Exception:
        pass
    return None


def update_modelfile_from(base_model: str) -> None:
    if not MODELFILE_PATH.is_file():
        raise FileNotFoundError(f"Modelfile not found: {MODELFILE_PATH}")
    text = MODELFILE_PATH.read_text(encoding="utf-8")
    if not re.search(r"^FROM\s+", text, flags=re.MULTILINE):
        raise ValueError("Modelfile has no FROM line")
    
    # 1. Update FROM line
    new_text = re.sub(
        r"^FROM\s+.+$",
        f"FROM {base_model}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    
    # 2. Dynamically fetch and update PARAMETER num_ctx line if possible
    ctx_len = query_model_context_length(base_model)
    if ctx_len:
        cfg = load_config()
        # Cap it using user-defined cap if present (defaults to 131072 for safety if not set)
        cap = int(cfg.get("chat_model_context_tokens") or 131072)
        ctx_len = min(ctx_len, cap)
        
        if re.search(r"^PARAMETER\s+num_ctx\s+\d+", new_text, flags=re.MULTILINE):
            new_text = re.sub(
                r"^PARAMETER\s+num_ctx\s+\d+",
                f"PARAMETER num_ctx {ctx_len}",
                new_text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            new_text += f"\nPARAMETER num_ctx {ctx_len}\n"
            
    MODELFILE_PATH.write_text(new_text, encoding="utf-8")


def _ollama_show_ok(name: str) -> bool:
    from ollama_paths import ollama_cmd

    r = subprocess.run(
        ollama_cmd("show", name),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.returncode == 0


def pull_base_model(base_model: str) -> dict[str, Any]:
    """Download a base model from Ollama (no switch)."""
    base_model = base_model.strip()
    if not base_model:
        raise ValueError("Empty base model")
    if is_base_model_installed(base_model):
        return {
            "base_model": base_model,
            "installed": True,
            "message": f"{base_model} is already on this Mac",
        }
    from ollama_paths import ollama_cmd

    pull = subprocess.run(
        ollama_cmd("pull", base_model),
        capture_output=True,
        text=True,
        timeout=900,
    )
    if pull.returncode != 0:
        err = (pull.stderr or pull.stdout or "pull failed").strip()
        raise RuntimeError(f"Could not download '{base_model}': {err}")
    return {
        "base_model": base_model,
        "installed": True,
        "message": f"Downloaded {base_model}",
    }


def ensure_base_model_available(base_model: str) -> None:
    if is_base_model_installed(base_model):
        return
    pull_base_model(base_model)


def rebuild_custom_model() -> str:
    from ollama_paths import ollama_cmd

    cfg = load_config()
    custom = str(cfg.get("model") or "roPac")
    r = subprocess.run(
        ollama_cmd("create", custom, "-f", str(MODELFILE_PATH)),
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROPAC_ROOT),
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "create failed").strip()
        raise RuntimeError(f"Failed to build '{custom}': {err}")
    return custom


def stop_custom_model() -> None:
    from ollama_paths import ollama_cmd

    custom = str(load_config().get("model") or "roPac")
    subprocess.run(
        ollama_cmd("stop", custom),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def set_base_model(base_model: str, *, pull_if_missing: bool = False) -> dict[str, Any]:
    raw = base_model.strip()
    if not raw:
        raise ValueError("Empty base model")

    path = Path(raw).expanduser()
    if path.exists() and path.is_file():
        suffix = path.suffix.lower()
        if suffix not in {".gguf", ".bin", ""}:
            raise RuntimeError(
                f"Unsupported model file '{path.name}'. Use .gguf or .bin."
            )

    from_ref = normalize_from_ref(raw)
    if path.exists():
        store_key = from_ref
    else:
        store_key = resolve_installed_ref(raw) or raw
        if pull_if_missing:
            ensure_base_model_available(store_key)
        elif not is_base_model_installed(store_key):
            raise RuntimeError(
                f"'{store_key}' is not on this Mac. Pick a downloaded model path or Download first."
            )

    stop_custom_model()
    update_modelfile_from(from_ref)
    save_config({"base_model": store_key})
    custom = rebuild_custom_model()

    disk = store_key if path.exists() else _model_disk_path(store_key)
    return {
        "base_model": store_key,
        "from_ref": from_ref,
        "model_path": disk,
        "custom_model": custom,
        "message": f"Using {store_key} (personality: {custom})",
    }
