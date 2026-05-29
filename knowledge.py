"""
Local knowledge store for files trained via train this-> <path>
Retrieval uses Ollama embeddings (nomic-embed-text) with keyword fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingest import chunk_text, read_file

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "data" / "knowledge"
INDEX_PATH = KNOWLEDGE_DIR / "index.json"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
TOP_CHUNKS = 4
MAX_CONTEXT_CHARS = 6000

# Short pleasantries — skip embedding + full chunk scan (no trained-doc signal).
_TRIVIAL_PHRASES = frozenset(
    {
        "hi",
        "hi!",
        "hello",
        "hello!",
        "hey",
        "hey!",
        "hiya",
        "howdy",
        "sup",
        "yo",
        "thanks",
        "thanks!",
        "thank you",
        "thank you!",
        "thx",
        "ty",
        "ok",
        "ok!",
        "okay",
        "k",
        "bye",
        "bye!",
        "goodbye",
        "yes",
        "no",
        "yep",
        "nope",
        "nah",
        "sure",
        "lol",
        "np",
        "good morning",
        "good afternoon",
        "good evening",
        "gm",
        "gn",
        "night",
        "morning",
    }
)


def load_rag_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "rag_retrieval_enabled": True,
        "rag_skip_trivial_messages": True,
        "rag_min_cosine_similarity": 0.28,
        "rag_min_keyword_score": 0.10,
        "rag_chunk_citations": True,
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


def _rag_float(cfg: dict[str, Any], key: str, fallback: float) -> float:
    if key not in cfg:
        return fallback
    try:
        return float(cfg[key])
    except (TypeError, ValueError):
        return fallback


def _collapse_ws(text: str) -> str:
    return " ".join(text.strip().split())


def _is_trivial_message(text: str) -> bool:
    collapsed = _collapse_ws(text)
    low = collapsed.lower()
    if len(low) > 40:
        return False
    if low in _TRIVIAL_PHRASES:
        return True
    if re.fullmatch(r"[\s!?.…,;:\-—_🙂😊👍👋✅❤️]+", text.strip()):
        return True
    return False


def should_run_document_retrieval(
    user_query: str, *, has_chat_attachments: bool = False
) -> bool:
    """
    When False, skip retrieve_context (saves Ollama embed call + chunk scan).
    """
    if has_chat_attachments:
        return False
    cfg = load_rag_config()
    if not cfg.get("rag_retrieval_enabled", True):
        return False
    q = user_query.strip()
    if len(q) < 2:
        return False
    if not list_documents():
        return False
    if cfg.get("rag_skip_trivial_messages", True) and _is_trivial_message(q):
        return False
    return True

TRAIN_SUMMARY_PROMPT = """You read a document for a personal AI knowledge base.
Extract the most important facts, definitions, and takeaways as short bullet strings.
Max 12 bullets. No markdown. Return a JSON array of strings only."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def _doc_id(path: Path) -> str:
    raw = f"{path.resolve()}:{path.stat().st_mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _doc_path(doc_id: str) -> Path:
    return KNOWLEDGE_DIR / f"{doc_id}.json"


def _embeddings_path(doc_id: str) -> Path:
    return KNOWLEDGE_DIR / f"{doc_id}.embeddings.json"


def load_index(*, owner_password: str | None = None) -> dict[str, Any]:
    from data_crypto import read_json_file

    _ensure_dir()
    if not INDEX_PATH.exists():
        return {"documents": [], "updated_at": _utc_now()}
    data = read_json_file(INDEX_PATH, password=owner_password)
    if data is None:
        return {"documents": [], "updated_at": _utc_now()}
    if isinstance(data, list):
        return {"documents": data, "updated_at": _utc_now()}
    if not isinstance(data, dict):
        return {"documents": [], "updated_at": _utc_now()}
    if "documents" not in data:
        data["documents"] = []
    return data


def save_index(index: dict[str, Any], *, owner_password: str | None = None) -> None:
    from data_crypto import is_encryption_enabled, write_json_file

    _ensure_dir()
    index["updated_at"] = _utc_now()
    if is_encryption_enabled():
        write_json_file(INDEX_PATH, index, password=owner_password)
    else:
        INDEX_PATH.write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def list_documents(*, owner_password: str | None = None) -> list[dict[str, Any]]:
    return load_index(owner_password=owner_password).get("documents", [])


def clear_all_trained_documents(*, owner_password: str | None = None) -> dict[str, Any]:
    """Remove every trained document, its embeddings, and reset the index."""
    index = load_index(owner_password=owner_password)
    docs = list(index.get("documents", []) or [])
    source_names = [
        str(d.get("source_name") or "").strip()
        for d in docs
        if str(d.get("source_name") or "").strip()
    ]
    files_deleted = 0

    seen_ids: set[str] = set()
    for doc in docs:
        doc_id = str(doc.get("id") or "").strip()
        if not doc_id or doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        for path in (_doc_path(doc_id), _embeddings_path(doc_id)):
            if path.is_file():
                path.unlink()
                files_deleted += 1

    for path in KNOWLEDGE_DIR.glob("*.json"):
        if path.name in ("index.json", "memory.embeddings.json"):
            continue
        name = path.name
        stem = name[:- len(".embeddings.json")] if name.endswith(
            ".embeddings.json"
        ) else path.stem
        if re.fullmatch(r"[a-f0-9]{16}", stem) and path.is_file():
            path.unlink()
            files_deleted += 1

    save_index({"documents": []}, owner_password=owner_password)
    return {
        "ok": True,
        "documents_removed": len(docs),
        "files_deleted": files_deleted,
        "source_names": source_names,
    }


def _read_json_knowledge(path: Path, *, owner_password: str | None = None) -> Any:
    from data_crypto import read_json_file

    return read_json_file(path, password=owner_password)


def _write_json_knowledge(
    path: Path, payload: dict[str, Any], *, owner_password: str | None = None
) -> None:
    from data_crypto import is_encryption_enabled, write_json_file

    if is_encryption_enabled():
        write_json_file(path, payload, password=owner_password)
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _load_document_payload(
    doc_id: str, *, owner_password: str | None = None
) -> dict[str, Any] | None:
    doc_path = _doc_path(doc_id)
    if not doc_path.exists():
        return None
    payload = _read_json_knowledge(doc_path, owner_password=owner_password)
    if not isinstance(payload, dict):
        return None
    return payload


def load_embeddings(
    doc_id: str, *, owner_password: str | None = None
) -> dict[str, Any] | None:
    path = _embeddings_path(doc_id)
    if not path.exists():
        return None
    data = _read_json_knowledge(path, owner_password=owner_password)
    if not isinstance(data, dict):
        return None
    vectors = data.get("vectors")
    if not isinstance(vectors, list) or not vectors:
        return None
    return data


def save_embeddings(
    doc_id: str,
    vectors: list[list[float]],
    *,
    embed_model: str,
    owner_password: str | None = None,
) -> None:
    _ensure_dir()
    payload = {
        "id": doc_id,
        "embed_model": embed_model,
        "dimensions": len(vectors[0]) if vectors else 0,
        "vector_count": len(vectors),
        "embedded_at": _utc_now(),
        "vectors": vectors,
    }
    _write_json_knowledge(
        _embeddings_path(doc_id), payload, owner_password=owner_password
    )


def build_embeddings_for_chunks(chunks: list[str]) -> list[list[float]]:
    from embeddings import embed_model_name, embed_texts

    if not chunks:
        return []
    vectors = embed_texts(chunks)
    if len(vectors) != len(chunks):
        raise ValueError(
            f"Embedding count mismatch: {len(vectors)} vectors for {len(chunks)} chunks"
        )
    return vectors


def ensure_document_embeddings(
    doc_id: str,
    chunks: list[str],
    *,
    owner_password: str | None = None,
    force: bool = False,
) -> bool:
    """Build embeddings for a document if missing or stale. Returns True on success."""
    from embeddings import embed_model_name, embeddings_enabled

    if not embeddings_enabled() or not chunks:
        return False

    model = embed_model_name()
    existing = None if force else load_embeddings(doc_id, owner_password=owner_password)
    if (
        existing
        and existing.get("embed_model") == model
        and len(existing.get("vectors", [])) == len(chunks)
    ):
        return True

    try:
        vectors = build_embeddings_for_chunks(chunks)
        save_embeddings(
            doc_id, vectors, embed_model=model, owner_password=owner_password
        )
        return True
    except Exception:
        return False


def reindex_all_embeddings(
    *, owner_password: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Embed all trained documents (for migration or model change)."""
    from embeddings import embed_model_name, embedding_available

    ok, detail = embedding_available()
    if not ok:
        return {"ok": False, "error": detail, "indexed": 0, "failed": 0}

    indexed = 0
    failed = 0
    for doc in list_documents(owner_password=owner_password):
        doc_id = str(doc.get("id") or "")
        if not doc_id:
            continue
        payload = _load_document_payload(doc_id, owner_password=owner_password)
        if not payload:
            failed += 1
            continue
        chunks = payload.get("chunks") or []
        if ensure_document_embeddings(
            doc_id, chunks, owner_password=owner_password, force=force
        ):
            indexed += 1
        else:
            failed += 1

    return {
        "ok": failed == 0,
        "embed_model": embed_model_name(),
        "indexed": indexed,
        "failed": failed,
    }


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {w for w in words if len(w) > 2}


def _score_chunk(query_tokens: set[str], chunk: str) -> float:
    chunk_tokens = _tokenize(chunk)
    if not query_tokens or not chunk_tokens:
        return 0.0
    overlap = query_tokens & chunk_tokens
    return len(overlap) / (len(query_tokens) ** 0.5)


def _retrieve_context_keyword(query: str, top_k: int = TOP_CHUNKS) -> str:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return ""

    cfg = load_rag_config()
    min_kw = _rag_float(cfg, "rag_min_keyword_score", 0.10)

    scored: list[tuple[float, str, str, int]] = []
    for doc in list_documents():
        doc_id = str(doc.get("id") or "")
        payload = _load_document_payload(doc_id)
        if not payload:
            continue
        source = payload.get("source_name", doc.get("source_name", "document"))
        for chunk_i, chunk in enumerate(payload.get("chunks") or []):
            score = _score_chunk(query_tokens, chunk)
            if score > 0:
                scored.append((score, source, chunk, chunk_i))
    return _format_context(
        scored,
        top_k,
        min_score=min_kw,
        cite_chunks=bool(cfg.get("rag_chunk_citations", True)),
    )


def _retrieve_context_embeddings(query: str, top_k: int = TOP_CHUNKS) -> str | None:
    from embeddings import (
        cosine_similarity,
        embed_model_name,
        embed_query,
        embeddings_enabled,
    )

    if not embeddings_enabled() or not query.strip():
        return None

    cfg = load_rag_config()
    min_cos = _rag_float(cfg, "rag_min_cosine_similarity", 0.28)

    try:
        query_vec = embed_query(query)
    except Exception:
        return None

    model = embed_model_name()
    scored: list[tuple[float, str, str, int]] = []

    for doc in list_documents():
        doc_id = str(doc.get("id") or "")
        payload = _load_document_payload(doc_id)
        if not payload:
            continue
        chunks = payload.get("chunks") or []
        if not chunks:
            continue

        if not ensure_document_embeddings(doc_id, chunks):
            continue

        emb = load_embeddings(doc_id)
        if not emb or emb.get("embed_model") != model:
            if not ensure_document_embeddings(doc_id, chunks, force=True):
                continue
            emb = load_embeddings(doc_id)
        if not emb:
            continue

        vectors = emb.get("vectors") or []
        if len(vectors) != len(chunks):
            if not ensure_document_embeddings(doc_id, chunks, force=True):
                continue
            emb = load_embeddings(doc_id)
            vectors = (emb or {}).get("vectors") or []
            if len(vectors) != len(chunks):
                continue

        source = payload.get("source_name", doc.get("source_name", "document"))
        for chunk_i, (vec, chunk) in enumerate(zip(vectors, chunks)):
            score = cosine_similarity(query_vec, vec)
            if score > 0:
                scored.append((score, source, chunk, chunk_i))

    if not scored:
        return ""

    return _format_context(
        scored,
        top_k,
        min_score=min_cos,
        cite_chunks=bool(cfg.get("rag_chunk_citations", True)),
    )


def _format_context(
    scored: list[tuple[float, str, str, int]],
    top_k: int,
    *,
    min_score: float,
    cite_chunks: bool,
    max_chars: int | None = None,
) -> str:
    if not scored:
        return ""

    if min_score > 0:
        scored = [t for t in scored if t[0] >= min_score]
    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    parts: list[str] = []
    total = 0
    limit = max_chars if max_chars is not None else MAX_CONTEXT_CHARS
    for _score, source, chunk, chunk_i in scored[: top_k * 2]:
        if cite_chunks:
            header = f"[{source}#{chunk_i + 1}]"
        else:
            header = f"[{source}]"
        block = f"{header}\n{chunk}"
        if total + len(block) > limit:
            break
        parts.append(block)
        total += len(block)
        if len(parts) >= top_k:
            break

    return "\n\n---\n\n".join(parts)


def retrieve_context(query: str, top_k: int = TOP_CHUNKS) -> str:
    embedded = _retrieve_context_embeddings(query, top_k=top_k)
    if embedded is not None and embedded.strip():
        return embedded
    keyword = _retrieve_context_keyword(query, top_k=top_k)
    if keyword.strip():
        return keyword
    return embedded or ""


def train_file(
    path: str | Path,
    *,
    model: str,
    client: Any,
    owner_password: str | None = None,
) -> dict[str, Any]:
    """Ingest file into knowledge store and extract summary facts (caller saves to memory)."""
    from chat_attachments import read_path_for_training

    file_path = Path(path).expanduser()
    text, source_kind = read_path_for_training(file_path)
    if not text.strip():
        raise ValueError(f"No text extracted from: {file_path}")

    payload = ingest_file_from_text(file_path, text, owner_password=owner_password)
    payload["source_kind"] = source_kind
    facts = extract_facts_from_document(text, model, client)
    payload["extracted_facts"] = facts
    return payload


def ingest_file(path: str | Path) -> dict[str, Any]:
    from chat_attachments import read_path_for_training

    file_path = Path(path).expanduser()
    text, source_kind = read_path_for_training(file_path)
    if not text.strip():
        raise ValueError(f"No text extracted from: {file_path}")
    payload = ingest_file_from_text(file_path, text)
    payload["source_kind"] = source_kind
    return payload


def ingest_file_from_text(
    file_path: Path, text: str, *, owner_password: str | None = None
) -> dict[str, Any]:
    chunks = chunk_text(text)
    doc_id = _doc_id(file_path)
    _ensure_dir()

    payload = {
        "id": doc_id,
        "source_path": str(file_path.resolve()),
        "source_name": file_path.name,
        "chunk_count": len(chunks),
        "char_count": len(text),
        "trained_at": _utc_now(),
        "chunks": chunks,
    }
    _write_json_knowledge(_doc_path(doc_id), payload, owner_password=owner_password)

    embedded = ensure_document_embeddings(
        doc_id, chunks, owner_password=owner_password, force=True
    )
    payload["embeddings_stored"] = embedded

    index = load_index(owner_password=owner_password)
    docs = [d for d in index.get("documents", []) if d.get("id") != doc_id]
    docs.append(
        {
            "id": doc_id,
            "source_name": file_path.name,
            "source_path": str(file_path.resolve()),
            "chunk_count": len(chunks),
            "trained_at": payload["trained_at"],
            "embeddings": embedded,
        }
    )
    index["documents"] = docs
    save_index(index, owner_password=owner_password)
    return payload


def extract_facts_from_document(text: str, model: str, client: Any) -> list[str]:
    sample = text[:8000] if len(text) > 8000 else text
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TRAIN_SUMMARY_PROMPT},
            {"role": "user", "content": sample},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content or "[]"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        parsed = json.loads(match.group()) if match else []
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()]
    return []
