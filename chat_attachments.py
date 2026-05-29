"""
Extract text from files attached in chat (session-only, not saved to knowledge).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from ingest import read_file

ROPAC_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROPAC_ROOT / "config.json"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}

VISION_MODEL = "moondream"

_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}


def load_attachment_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "chat_attachment_max_chars": 12000,
        "train_image_max_chars": 24000,
        "chat_attachments_enabled": True,
    }
    if not CONFIG_PATH.exists():
        return defaults
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    out = {**defaults}
    for key in defaults:
        if key in data:
            out[key] = data[key]
    return out


def is_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def _truncate(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 40].rstrip() + "\n\n[... truncated for chat context ...]"


def _describe_image_with_ollama(path: Path, *, for_training: bool = False) -> str:
    from assistant import get_client

    model = VISION_MODEL

    if for_training:
        prompt = (
            "Describe this image exhaustively for a permanent offline knowledge base. "
            "Include every visible word, number, label, table, diagram, and UI element. "
            "Transcribe text exactly where possible."
        )
    else:
        prompt = (
            "Describe this image in detail for question answering. "
            "Include all visible text, numbers, labels, tables, and layout."
        )

    suffix = path.suffix.lower().lstrip(".")
    mime = _MIME.get(suffix, "image/png")
    b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")

    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        joined = "\n".join(p for p in parts if p.strip())
        if joined.strip():
            return joined.strip()
    raise ValueError(f"Vision model '{model}' returned empty description")


def read_path_for_training(path: str | Path) -> tuple[str, str]:
    """
    Read a file for Train tab / knowledge ingest.
    Returns (text, kind) where kind is 'image' or 'document'.
    """
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    cfg = load_attachment_config()
    if is_image_path(file_path):
        raw = _describe_image_with_ollama(file_path, for_training=True)
        max_chars = int(cfg.get("train_image_max_chars") or 24000)
        return _truncate(raw, max_chars), "image"

    return read_file(file_path), "document"


def extract_attachment_text(path: str | Path) -> dict[str, Any]:
    """
    Return {ok, name, kind, text, error}.
    kind is 'text' or 'image'.
    """
    cfg = load_attachment_config()
    if not cfg.get("chat_attachments_enabled", True):
        return {
            "ok": False,
            "name": Path(path).name,
            "kind": "unknown",
            "text": "",
            "error": "Chat attachments disabled in config",
        }

    file_path = Path(path).expanduser()
    name = file_path.name
    max_chars = int(cfg.get("chat_attachment_max_chars") or 12000)

    if not file_path.is_file():
        return {
            "ok": False,
            "name": name,
            "kind": "unknown",
            "text": "",
            "error": f"File not found: {file_path}",
        }

    try:
        if is_image_path(file_path):
            raw = _describe_image_with_ollama(file_path, for_training=False)
            kind = "image"
        else:
            raw = read_file(file_path)
            kind = "text"
        if not raw.strip():
            return {
                "ok": False,
                "name": name,
                "kind": kind,
                "text": "",
                "error": "No text could be extracted from this file",
            }
        return {
            "ok": True,
            "name": name,
            "kind": kind,
            "text": _truncate(raw, max_chars),
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "name": name,
            "kind": "image" if is_image_path(file_path) else "text",
            "text": "",
            "error": str(e),
        }


def build_attachment_context(paths: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """Format attachment bodies for the system prompt. Returns (context, meta list)."""
    if not paths:
        return "", []

    blocks: list[str] = []
    meta: list[dict[str, Any]] = []
    for p in paths:
        result = extract_attachment_text(p)
        meta.append(result)
        if not result.get("ok"):
            blocks.append(
                f"[{result.get('name', 'file')}]\n"
                f"(Could not read: {result.get('error', 'unknown error')})"
            )
            continue
        kind = result.get("kind", "text")
        label = "image description" if kind == "image" else "file content"
        blocks.append(f"[{result['name']} — {label}]\n{result['text']}")

    if not blocks:
        return "", meta

    body = "\n\n---\n\n".join(blocks)
    header = (
        "ATTACHED FILES (user added in this chat only — not saved to long-term memory "
        "unless they use Train). Answer using this content when relevant.\n"
    )
    return header + body, meta


def build_log_scan_hints(paths: list[str]) -> str:
    """Backward-compatible alias — prefer build_log_analysis_context."""
    from log_analysis import build_log_analysis_context

    return build_log_analysis_context(paths)
