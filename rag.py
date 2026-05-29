"""
Unified RAG: documents, owner memory facts, and chat attachments.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingest import chunk_text

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "data" / "knowledge"
MEMORY_EMBED_PATH = KNOWLEDGE_DIR / "memory.embeddings.json"
SESSIONS_DIR = KNOWLEDGE_DIR / "sessions"
MEMORY_EMBED_ID = "__memory__"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dir() -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_rag_config() -> dict[str, Any]:
    from knowledge import load_rag_config as _base

    cfg = _base()
    defaults: dict[str, Any] = {
        "rag_memory_enabled": True,
        "rag_attachment_rag_enabled": True,
        "rag_top_memory_facts": 6,
        "rag_top_attachment_chunks": 4,
        "rag_min_memory_cosine_similarity": 0.22,
        "rag_min_memory_keyword_score": 0.08,
    }
    return {**defaults, **{k: cfg[k] for k in cfg}}


def _rag_int(cfg: dict[str, Any], key: str, fallback: int) -> int:
    try:
        return int(cfg.get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def _rag_float(cfg: dict[str, Any], key: str, fallback: float) -> float:
    from knowledge import _rag_float as kf

    return kf(cfg, key, fallback)


@dataclass
class RagHit:
    score: float
    source: str
    text: str
    chunk_index: int


def _format_hits(
    hits: list[RagHit],
    top_k: int,
    *,
    min_score: float,
    max_chars: int,
    cite_chunks: bool,
) -> str:
    from knowledge import _format_context

    scored = [
        (h.score, h.source, h.text, h.chunk_index)
        for h in hits
    ]
    return _format_context(
        scored,
        top_k,
        min_score=min_score,
        cite_chunks=cite_chunks,
        max_chars=max_chars,
    )


def _read_store(path: Path, *, owner_password: str | None = None) -> dict[str, Any] | None:
    from knowledge import _read_json_knowledge

    if not path.exists():
        return None
    data = _read_json_knowledge(path, owner_password=owner_password)
    return data if isinstance(data, dict) else None


def _write_store(
    path: Path, payload: dict[str, Any], *, owner_password: str | None = None
) -> None:
    from knowledge import _write_json_knowledge

    _write_store_path = path
    _write_json_knowledge(_write_store_path, payload, owner_password=owner_password)


# --- Memory embeddings ---


def sync_memory_embeddings(*, owner_password: str | None = None) -> bool:
    """Embed all owner memory facts (call after add/remove facts)."""
    from embeddings import embed_model_name, embeddings_enabled
    from assistant import load_memory

    if not embeddings_enabled():
        return False

    _ensure_dir()
    memory = load_memory(password=owner_password)
    facts = [str(f).strip() for f in memory.get("facts", []) if str(f).strip()]
    owner = str(memory.get("owner") or "")

    if not facts:
        if MEMORY_EMBED_PATH.exists():
            MEMORY_EMBED_PATH.unlink()
        return True

    try:
        from knowledge import build_embeddings_for_chunks

        vectors = build_embeddings_for_chunks(facts)
    except Exception:
        return False

    payload = {
        "id": MEMORY_EMBED_ID,
        "owner": owner,
        "embed_model": embed_model_name(),
        "chunks": facts,
        "vector_count": len(vectors),
        "embedded_at": _utc_now(),
        "vectors": vectors,
    }
    _write_store(MEMORY_EMBED_PATH, payload, owner_password=owner_password)
    return True


def _memory_facts_in_sync(
    emb: dict[str, Any], facts: list[str], model: str
) -> bool:
    return (
        emb.get("embed_model") == model
        and emb.get("chunks") == facts
        and len(emb.get("vectors") or []) == len(facts)
    )


def ensure_memory_embeddings(*, owner_password: str | None = None) -> bool:
    from embeddings import embed_model_name, embeddings_enabled
    from assistant import load_memory

    if not embeddings_enabled():
        return False
    memory = load_memory(password=owner_password)
    facts = [str(f).strip() for f in memory.get("facts", []) if str(f).strip()]
    if not facts:
        return True
    emb = _read_store(MEMORY_EMBED_PATH, owner_password=owner_password)
    if emb and _memory_facts_in_sync(emb, facts, embed_model_name()):
        return True
    return sync_memory_embeddings(owner_password=owner_password)


def _retrieve_memory_keyword(query: str, facts: list[str], top_k: int) -> list[RagHit]:
    from knowledge import _score_chunk, _tokenize

    tokens = _tokenize(query)
    if not tokens:
        return []
    scored: list[RagHit] = []
    for i, fact in enumerate(facts):
        score = _score_chunk(tokens, fact)
        if score > 0:
            scored.append(RagHit(score, "memory", fact, i))
    scored.sort(key=lambda h: h.score, reverse=True)
    return scored[:top_k]


def retrieve_memory_context(
    query: str,
    *,
    owner_password: str | None = None,
    top_k: int | None = None,
) -> str:
    from embeddings import cosine_similarity, embed_model_name, embed_query, embeddings_enabled
    from assistant import load_memory
    from knowledge import _is_trivial_message

    cfg = load_rag_config()
    if not cfg.get("rag_memory_enabled", True):
        return ""
    q = query.strip()
    if not q or _is_trivial_message(q):
        return ""

    memory = load_memory(password=owner_password)
    facts = [str(f).strip() for f in memory.get("facts", []) if str(f).strip()]
    if not facts:
        return ""

    k = top_k if top_k is not None else _rag_int(cfg, "rag_top_memory_facts", 6)
    cite = bool(cfg.get("rag_chunk_citations", True))

    if embeddings_enabled():
        ensure_memory_embeddings(owner_password=owner_password)
        emb = _read_store(MEMORY_EMBED_PATH, owner_password=owner_password)
        if emb and emb.get("chunks") == facts:
            try:
                qvec = embed_query(q)
                vectors = emb.get("vectors") or []
                hits: list[RagHit] = []
                for i, (vec, fact) in enumerate(zip(vectors, facts)):
                    score = cosine_similarity(qvec, vec)
                    if score > 0:
                        hits.append(RagHit(score, "memory", fact, i))
                min_cos = _rag_float(cfg, "rag_min_memory_cosine_similarity", 0.22)
                text = _format_hits(
                    hits,
                    k,
                    min_score=min_cos,
                    max_chars=4000,
                    cite_chunks=cite,
                )
                if text.strip():
                    return text
            except Exception:
                pass

    min_kw = _rag_float(cfg, "rag_min_memory_keyword_score", 0.08)
    hits = _retrieve_memory_keyword(q, facts, k)
    return _format_hits(hits, k, min_score=min_kw, max_chars=4000, cite_chunks=cite)


# --- Session attachment embeddings ---


def _attachment_session_key(paths: list[str]) -> str:
    parts: list[str] = []
    for raw in sorted(paths):
        p = Path(raw).expanduser()
        try:
            st = p.stat()
            parts.append(f"{p.resolve()}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(str(p))
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return digest[:16]


def _session_path(session_key: str) -> Path:
    return SESSIONS_DIR / f"{session_key}.json"


def index_attachment_paths(
    paths: list[str], *, owner_password: str | None = None
) -> bool:
    from chat_attachments import extract_attachment_text
    from embeddings import embed_model_name, embeddings_enabled
    from knowledge import build_embeddings_for_chunks

    if not embeddings_enabled() or not paths:
        return False

    _ensure_dir()
    session_key = _attachment_session_key(paths)
    path = _session_path(session_key)

    existing = _read_store(path, owner_password=owner_password)
    if existing and existing.get("paths") == paths:
        return True

    chunks: list[str] = []
    labels: list[str] = []
    for raw in paths:
        result = extract_attachment_text(raw)
        name = str(result.get("name") or Path(raw).name)
        if not result.get("ok"):
            continue
        text = str(result.get("text") or "").strip()
        if not text:
            continue
        file_chunks = chunk_text(text, size=800, overlap=100)
        for ci, ch in enumerate(file_chunks):
            chunks.append(ch)
            labels.append(f"{name}")

    if not chunks:
        return False

    try:
        vectors = build_embeddings_for_chunks(chunks)
    except Exception:
        return False

    payload = {
        "session_key": session_key,
        "paths": list(paths),
        "embed_model": embed_model_name(),
        "labels": labels,
        "chunks": chunks,
        "vectors": vectors,
        "indexed_at": _utc_now(),
    }
    _write_store(path, payload, owner_password=owner_password)
    return True


def retrieve_attachment_context(
    query: str,
    paths: list[str],
    *,
    owner_password: str | None = None,
    top_k: int | None = None,
) -> str:
    from embeddings import cosine_similarity, embed_query, embeddings_enabled
    from knowledge import _is_trivial_message, _score_chunk, _tokenize

    cfg = load_rag_config()
    if not cfg.get("rag_attachment_rag_enabled", True) or not paths:
        return ""
    q = query.strip()
    if not q or _is_trivial_message(q):
        return ""

    k = top_k if top_k is not None else _rag_int(cfg, "rag_top_attachment_chunks", 4)
    cite = bool(cfg.get("rag_chunk_citations", True))

    if not index_attachment_paths(paths, owner_password=owner_password):
        return ""

    session_key = _attachment_session_key(paths)
    store = _read_store(_session_path(session_key), owner_password=owner_password)
    if not store:
        return ""

    chunks = store.get("chunks") or []
    labels = store.get("labels") or []
    vectors = store.get("vectors") or []
    if not chunks:
        return ""

    hits: list[RagHit] = []
    if embeddings_enabled() and len(vectors) == len(chunks):
        try:
            qvec = embed_query(q)
            for i, (vec, ch) in enumerate(zip(vectors, chunks)):
                label = labels[i] if i < len(labels) else "attachment"
                score = cosine_similarity(qvec, vec)
                if score > 0:
                    hits.append(
                        RagHit(
                            score,
                            f"{label} — attachment",
                            ch,
                            i,
                        )
                    )
        except Exception:
            hits = []

    if not hits:
        tokens = _tokenize(q)
        for i, ch in enumerate(chunks):
            label = labels[i] if i < len(labels) else "attachment"
            score = _score_chunk(tokens, ch)
            if score > 0:
                hits.append(RagHit(score, f"{label} — attachment", ch, i))

    min_cos = _rag_float(cfg, "rag_min_cosine_similarity", 0.28)
    return _format_hits(
        hits,
        k,
        min_score=min_cos,
        max_chars=6000,
        cite_chunks=cite,
    )


# --- Unified retrieval ---


def retrieve_all_context(
    query: str,
    *,
    attachment_paths: list[str] | None = None,
    has_chat_attachments: bool = False,
    owner_password: str | None = None,
) -> dict[str, str]:
    """
    Run all enabled retrievers. Returns section_key -> formatted context.
    Keys: memory, documents, attachments
    """
    from knowledge import retrieve_context, should_run_document_retrieval

    cfg = load_rag_config()
    paths = [str(p).strip() for p in (attachment_paths or []) if str(p).strip()]
    has_attachments = has_chat_attachments or bool(paths)
    sections: dict[str, str] = {}

    if cfg.get("rag_memory_enabled", True):
        mem = retrieve_memory_context(
            query, owner_password=owner_password
        )
        if mem.strip():
            sections["memory"] = mem.strip()

    if (
        query.strip()
        and should_run_document_retrieval(query, has_chat_attachments=has_attachments)
    ):
        docs = retrieve_context(query)
        if docs.strip():
            sections["documents"] = docs.strip()

    if has_attachments and cfg.get("rag_attachment_rag_enabled", True):
        att = retrieve_attachment_context(
            query, paths, owner_password=owner_password
        )
        if att.strip():
            sections["attachments"] = att.strip()

    return sections


def format_rag_for_prompt(sections: dict[str, str]) -> str:
    if not sections:
        return ""

    parts: list[str] = []
    if sections.get("memory"):
        parts.append(
            "OWNER MEMORY (retrieved for this question — about the machine owner, "
            "not necessarily the person chatting):\n"
            + sections["memory"]
        )
    if sections.get("documents"):
        parts.append(
            "TRAINED DOCUMENTS (retrieved — prefer for document questions):\n"
            + sections["documents"]
        )
    if sections.get("attachments"):
        parts.append(
            "ATTACHED FILES (retrieved for this message — session only):\n"
            + sections["attachments"]
        )

    header = (
        "RETRIEVED KNOWLEDGE (RAG — use when relevant; cite bracketed source labels):\n\n"
    )
    return header + "\n\n".join(parts)


def owner_profile_preamble() -> str:
    """Owner name only — facts come from RAG memory section."""
    from assistant import load_memory, load_config

    memory = load_memory()
    owner = memory.get("owner") or load_config().get("owner", "Rohit")
    return (
        f"Machine owner (built RoPac): {owner}\n"
        "Owner-specific facts appear below only when retrieved for this question."
    )
