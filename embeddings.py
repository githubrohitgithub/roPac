"""
Local document embeddings via Ollama (OpenAI-compatible /v1/embeddings).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from openai import OpenAI

ROPAC_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROPAC_ROOT / "config.json"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
EMBED_BATCH_SIZE = 32


def load_embed_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "embed_model": DEFAULT_EMBED_MODEL,
        "ollama_base_url": "http://localhost:11434/v1",
        "embeddings_enabled": True,
    }
    if CONFIG_PATH.exists():
        merged = {**defaults, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
        return merged
    return defaults


def get_embed_client() -> OpenAI:
    cfg = load_embed_config()
    return OpenAI(base_url=str(cfg["ollama_base_url"]), api_key="ollama")


def embed_model_name() -> str:
    return str(load_embed_config().get("embed_model") or DEFAULT_EMBED_MODEL)


def _prepare_query_text(text: str) -> str:
    """Model-specific query prefix (nomic expects search_query:)."""
    q = text.strip()
    if not q:
        return q
    model = embed_model_name().lower()
    if "nomic" in model and not q.lower().startswith("search_query:"):
        return f"search_query: {q}"
    return q


def _prepare_document_text(text: str) -> str:
    """Model-specific document prefix for indexing."""
    doc = text.strip()
    if not doc:
        return doc
    model = embed_model_name().lower()
    if "nomic" in model and not doc.lower().startswith("search_document:"):
        return f"search_document: {doc}"
    return doc


def embed_texts(texts: list[str], *, for_documents: bool = False) -> list[list[float]]:
    """Embed one or more texts. Raises on Ollama/model errors."""
    prep = _prepare_document_text if for_documents else (lambda t: t.strip())
    cleaned = [prep(t) for t in texts if t and t.strip()]
    if not cleaned:
        return []

    client = get_embed_client()
    model = embed_model_name()
    vectors: list[list[float]] = []

    for start in range(0, len(cleaned), EMBED_BATCH_SIZE):
        batch = cleaned[start : start + EMBED_BATCH_SIZE]
        response = client.embeddings.create(model=model, input=batch)
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(item.embedding for item in ordered)

    return vectors


def embeddings_enabled() -> bool:
    return bool(load_embed_config().get("embeddings_enabled", True))


def embed_document_texts(texts: list[str]) -> list[list[float]]:
    """Embed chunks for indexing (applies document prefix when required)."""
    return embed_texts(texts, for_documents=True)


def embed_query(text: str) -> list[float]:
    vectors = embed_texts([_prepare_query_text(text)])
    if not vectors:
        raise ValueError("Empty query embedding")
    return vectors[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def embedding_available() -> tuple[bool, str]:
    """Check whether the embed model responds."""
    if not embeddings_enabled():
        return False, "Embeddings disabled in config"
    try:
        embed_query("ping")
        return True, embed_model_name()
    except Exception as e:
        return False, str(e)
