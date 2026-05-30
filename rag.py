"""
Unified RAG: documents, owner memory facts, and chat attachments.

FAISS is used for attachment chunk retrieval when available.  The
faiss_index module wraps every FAISS call in try/except so a missing
or broken faiss-cpu installation falls back transparently to the
original O(N) cosine similarity loop — no change in behaviour.

Conflict handling:
  Level 1 — Source priority labels + conflict rule injected into the LLM
             prompt when multiple sources are present (format_rag_for_prompt).
  Level 2 — Cross-chunk deduplication and inline conflict annotations
             applied to every hit list before it reaches the LLM
             (_deduplicate_hits, _detect_conflicts).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingest import chunk_text_for_path

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
        "rag_top_attachment_chunks": 8,
        "rag_attachment_chunk_size": 1500,
        "rag_attachment_chunk_overlap": 200,
        "rag_attachment_min_chunks_per_file": 4,
        "rag_attachment_max_chunks": 64,
        "rag_hybrid_keyword_weight": 0.35,
        "rag_min_memory_cosine_similarity": 0.22,
        "rag_min_memory_keyword_score": 0.08,
        # FAISS: use IndexFlatIP for attachment chunk retrieval when available.
        # Set false to always use the brute-force cosine loop (pure Python).
        "rag_use_faiss": True,
        # Conflict handling thresholds.
        # Chunks with similarity >= rag_dedup_sim_threshold are near-duplicates
        # (only the higher-scored copy is kept in the prompt).
        "rag_dedup_sim_threshold": 0.92,
        # Chunks from *different* files with similarity in [low, high) are flagged
        # as potential conflicts and annotated with an inline warning.
        "rag_conflict_sim_low": 0.75,
        "rag_conflict_sim_high": 0.92,
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
    # Populated by _detect_conflicts — label of the conflicting source, if any
    conflict_with: str = ""
    cosine_score: float = 0.0


# ---------------------------------------------------------------------------
# Level 2 helpers: deduplication + conflict detection
# ---------------------------------------------------------------------------


def _cosine_similarity_vecs(a: list[float], b: list[float]) -> float:
    """
    Pure-Python cosine similarity between two pre-embedded vectors.
    Used for cross-chunk comparison without an Ollama round-trip.
    Returns 0.0 if vectors are empty or mismatched.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _source_file_label(source: str) -> str:
    """Extract the bare filename from a source label like 'report.pdf — attachment'."""
    return source.split(" — ")[0].strip()


def _deduplicate_hits(
    hits: list[RagHit],
    vectors: dict[int, list[float]] | None = None,
    *,
    sim_threshold: float = 0.92,
) -> list[RagHit]:
    """
    Remove near-duplicate chunks across any source.

    Two hits are considered duplicates when their cosine similarity
    exceeds `sim_threshold` (default 0.92 — near-identical wording).
    When duplicates are found, only the higher-scored hit is kept.

    If `vectors` (chunk_index -> embedding) is not provided, falls back
    to a fast character-level token-overlap heuristic that requires no
    embeddings at all.
    """
    if len(hits) <= 1:
        return hits

    kept: list[RagHit] = []
    dropped: set[int] = set()  # indices into `hits`

    for i, hi in enumerate(hits):
        if i in dropped:
            continue
        for j, hj in enumerate(hits):
            if j <= i or j in dropped:
                continue
            sim = 0.0
            if vectors and hi.chunk_index in vectors and hj.chunk_index in vectors:
                sim = _cosine_similarity_vecs(
                    vectors[hi.chunk_index], vectors[hj.chunk_index]
                )
            else:
                # Character-level overlap heuristic (fast, no embeddings)
                set_i = set(hi.text.lower().split())
                set_j = set(hj.text.lower().split())
                union = set_i | set_j
                if union:
                    sim = len(set_i & set_j) / len(union)

            if sim >= sim_threshold:
                # Keep the higher-scored hit; drop the other
                if hi.score >= hj.score:
                    dropped.add(j)
                else:
                    dropped.add(i)
                    break  # hi is dropped; skip checking its other pairs
        if i not in dropped:
            kept.append(hi)

    return kept


def _detect_conflicts(
    hits: list[RagHit],
    vectors: dict[int, list[float]] | None = None,
    *,
    low: float = 0.75,
    high: float = 0.92,
) -> list[RagHit]:
    """
    Flag cross-source near-matches as potential conflicts.

    When two chunks from *different source files* have cosine similarity
    in the range [low, high) they cover the same topic but may state
    different facts.  The lower-ranked hit gets `conflict_with` set to
    the filename of the higher-ranked counterpart so the formatter can
    add an inline warning.

    Chunks from the *same* file are never flagged (same file cannot
    conflict with itself).
    """
    if len(hits) <= 1:
        return hits

    for i, hi in enumerate(hits):
        for j, hj in enumerate(hits):
            if j <= i:
                continue
            # Only flag cross-file pairs
            if _source_file_label(hi.source) == _source_file_label(hj.source):
                continue
            sim = 0.0
            if vectors and hi.chunk_index in vectors and hj.chunk_index in vectors:
                sim = _cosine_similarity_vecs(
                    vectors[hi.chunk_index], vectors[hj.chunk_index]
                )
            else:
                set_i = set(hi.text.lower().split())
                set_j = set(hj.text.lower().split())
                union = set_i | set_j
                if union:
                    sim = len(set_i & set_j) / len(union)

            if low <= sim < high:
                # Tag the lower-ranked chunk as the conflicting one
                loser = hj if hi.score >= hj.score else hi
                winner = hi if hi.score >= hj.score else hj
                if not loser.conflict_with:
                    loser.conflict_with = _source_file_label(winner.source)

    return hits


def _format_hits(
    hits: list[RagHit],
    top_k: int,
    *,
    min_score: float,
    max_chars: int,
    cite_chunks: bool,
    vectors: dict[int, list[float]] | None = None,
    dedup_threshold: float = 0.92,
    conflict_low: float = 0.75,
    conflict_high: float = 0.92,
) -> str:
    """
    Deduplicate, detect conflicts, then format the top-k hits.

    `vectors` is an optional mapping of chunk_index -> embedding vector
    used for cosine-based dedup/conflict detection.  When absent a
    fast token-overlap heuristic is used instead.
    """
    # --- Level 2a: remove near-identical duplicates ---
    hits = _deduplicate_hits(hits, vectors, sim_threshold=dedup_threshold)

    # --- Level 2b: annotate cross-source topic conflicts ---
    hits = _detect_conflicts(hits, vectors, low=conflict_low, high=conflict_high)

    # --- Format with optional conflict warnings inline ---
    from knowledge import _format_context

    scored = []
    for h in hits:
        text = h.text
        if h.conflict_with:
            text = (
                f"⚠️ [CONFLICT: This chunk from '{_source_file_label(h.source)}' "
                f"covers the same topic as '{h.conflict_with}' but may state "
                f"different facts. Prefer the higher-priority source.]\n{text}"
            )
        scored.append((h.score, h.source, text, h.chunk_index))

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
    from embeddings import embed_model_name

    parts: list[str] = [embed_model_name()]
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
    from chat_attachments import read_attachment_full_text
    from embeddings import embed_model_name, embeddings_enabled
    from knowledge import build_embeddings_for_chunks

    cfg = load_rag_config()
    chunk_size = _rag_int(cfg, "rag_attachment_chunk_size", 1500)
    chunk_overlap = _rag_int(cfg, "rag_attachment_chunk_overlap", 200)
    use_faiss = bool(cfg.get("rag_use_faiss", True))

    if not embeddings_enabled() or not paths:
        return False

    _ensure_dir()
    session_key = _attachment_session_key(paths)
    path = _session_path(session_key)

    existing = _read_store(path, owner_password=owner_password)
    if existing and existing.get("paths") == paths:
        # Re-use cached store — but build FAISS index if it's missing and
        # FAISS was requested (handles upgrade from pre-FAISS session cache).
        if (
            use_faiss
            and not existing.get("faiss_index_b64")
            and existing.get("vectors")
        ):
            _attach_faiss_index_to_store(existing, path, owner_password=owner_password)
        return True

    chunks: list[str] = []
    labels: list[str] = []
    for raw in paths:
        file_path = Path(raw).expanduser()
        name = file_path.name
        try:
            text, _kind = read_attachment_full_text(file_path)
        except (OSError, ValueError):
            continue
        text = text.strip()
        if not text:
            continue
        file_chunks = chunk_text_for_path(
            file_path, text, size=chunk_size, overlap=chunk_overlap
        )
        for ch in file_chunks:
            chunks.append(ch)
            labels.append(name)

    if not chunks:
        return False

    try:
        vectors = build_embeddings_for_chunks(chunks)
    except Exception:
        return False

    payload: dict[str, Any] = {
        "session_key": session_key,
        "paths": list(paths),
        "embed_model": embed_model_name(),
        "labels": labels,
        "chunks": chunks,
        "vectors": vectors,
        "indexed_at": _utc_now(),
    }

    # --- Build and serialise FAISS index (attachment-only optimisation) ---
    if use_faiss:
        from faiss_index import build_flat_index, faiss_available, serialize_index

        if faiss_available():
            faiss_idx = build_flat_index(vectors)
            if faiss_idx is not None:
                b64 = serialize_index(faiss_idx)
                if b64:
                    payload["faiss_index_b64"] = b64

    _write_store(path, payload, owner_password=owner_password)
    return True


def _attach_faiss_index_to_store(
    store: dict[str, Any],
    store_path: Path,
    *,
    owner_password: str | None = None,
) -> None:
    """
    Retroactively build and persist a FAISS index into an existing session
    store that was created before FAISS support was added.
    Called only when rag_use_faiss=True and faiss_index_b64 is missing.
    """
    from faiss_index import build_flat_index, faiss_available, serialize_index

    if not faiss_available():
        return
    vectors = store.get("vectors") or []
    if not vectors:
        return
    faiss_idx = build_flat_index(vectors)
    if faiss_idx is None:
        return
    b64 = serialize_index(faiss_idx)
    if not b64:
        return
    store["faiss_index_b64"] = b64
    try:
        _write_store(store_path, store, owner_password=owner_password)
    except Exception:
        pass


def retrieve_attachment_context(
    query: str,
    paths: list[str],
    *,
    owner_password: str | None = None,
    top_k: int | None = None,
    max_chars: int | None = None,
) -> str:
    from embeddings import cosine_similarity, embed_query, embeddings_enabled
    from knowledge import _is_trivial_message, _score_chunk, _tokenize

    cfg = load_rag_config()
    if not cfg.get("rag_attachment_rag_enabled", True) or not paths:
        return ""
    q = query.strip()
    if not q or _is_trivial_message(q):
        return ""

    k = top_k if top_k is not None else _rag_int(cfg, "rag_top_attachment_chunks", 8)
    cite = bool(cfg.get("rag_chunk_citations", True))
    use_faiss = bool(cfg.get("rag_use_faiss", True))

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

    # --- FAISS path: fast ANN search on attachment chunks ---
    if use_faiss and embeddings_enabled() and store.get("faiss_index_b64"):
        from faiss_index import deserialize_index, faiss_available, search_index

        if faiss_available():
            try:
                qvec = embed_query(q)
                faiss_idx = deserialize_index(store["faiss_index_b64"])
                if faiss_idx is not None:
                    # Retrieve a generous candidate pool then let score-floor filter
                    candidate_k = min(k * 4, len(chunks))
                    scores, idxs = search_index(faiss_idx, qvec, candidate_k)
                    for score, i in zip(scores, idxs):
                        if i < len(chunks):
                            label = labels[i] if i < len(labels) else "attachment"
                            hits.append(RagHit(score, f"{label} — attachment", chunks[i], i))
            except Exception:
                hits = []  # fall through to cosine loop

    # --- Cosine fallback: O(N) brute-force (also used when FAISS unavailable) ---
    if not hits and embeddings_enabled() and len(vectors) == len(chunks):
        try:
            qvec = embed_query(q)
            for i, (vec, ch) in enumerate(zip(vectors, chunks)):
                label = labels[i] if i < len(labels) else "attachment"
                score = cosine_similarity(qvec, vec)
                if score > 0:
                    hits.append(RagHit(score, f"{label} — attachment", ch, i))
        except Exception:
            hits = []

    # --- Keyword fallback: pure token overlap (no Ollama needed) ---
    if not hits:
        tokens = _tokenize(q)
        for i, ch in enumerate(chunks):
            label = labels[i] if i < len(labels) else "attachment"
            score = _score_chunk(tokens, ch)
            if score > 0:
                hits.append(RagHit(score, f"{label} — attachment", ch, i))

    min_cos = _rag_float(cfg, "rag_min_cosine_similarity", 0.28)
    char_limit = max_chars if max_chars is not None else 6000
    # Build chunk_index -> vector map for cosine-based dedup/conflict detection
    vec_map: dict[int, list[float]] | None = None
    if vectors and len(vectors) == len(chunks):
        vec_map = {i: vectors[i] for i in range(len(vectors))}
    return _format_hits(
        hits,
        k,
        min_score=min_cos,
        max_chars=char_limit,
        cite_chunks=cite,
        vectors=vec_map,
        dedup_threshold=_rag_float(cfg, "rag_dedup_sim_threshold", 0.92),
        conflict_low=_rag_float(cfg, "rag_conflict_sim_low", 0.75),
        conflict_high=_rag_float(cfg, "rag_conflict_sim_high", 0.92),
    )


def _blend_attachment_score(
    cosine: float, keyword: float, *, keyword_weight: float
) -> float:
    kw = min(keyword / 2.0, 1.0)
    return (1.0 - keyword_weight) * cosine + keyword_weight * kw


def _attachment_file_label(hit: RagHit) -> str:
    return hit.source.split(" — ", 1)[0]


def retrieve_attachment_hybrid(
    query: str,
    paths: list[str],
    *,
    owner_password: str | None = None,
    max_chars: int | None = None,
) -> str:
    """
    Hybrid vector + keyword retrieval with per-file minimum coverage.
    Ensures all uploaded files contribute chunks, not only the top global matches.

    When FAISS is available (rag_use_faiss=True), the vector similarity
    component is computed via IndexFlatIP instead of the O(N) cosine loop.
    Keyword blending and per-file coverage guarantees are unchanged.
    """
    from chat_attachments import resolve_attachment_char_budgets
    from embeddings import cosine_similarity, embed_query, embeddings_enabled
    from knowledge import _is_trivial_message, _score_chunk, _tokenize

    cfg = load_rag_config()
    if not cfg.get("rag_attachment_rag_enabled", True) or not paths:
        return ""
    q = query.strip()
    if not q or _is_trivial_message(q):
        return ""

    use_faiss = bool(cfg.get("rag_use_faiss", True))

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

    kw_weight = _rag_float(cfg, "rag_hybrid_keyword_weight", 0.35)
    min_per_file = _rag_int(cfg, "rag_attachment_min_chunks_per_file", 4)
    max_chunks = _rag_int(cfg, "rag_attachment_max_chunks", 64)
    tokens = _tokenize(q)
    if len(tokens) >= 4:
        max_chunks = max(max_chunks, min(len(chunks), 120))

    char_limit = max_chars
    if char_limit is None:
        _full, char_limit = resolve_attachment_char_budgets()

    cite = bool(cfg.get("rag_chunk_citations", True))
    min_cos = _rag_float(cfg, "rag_min_cosine_similarity", 0.28)

    hits: list[RagHit] = []

    # ----------------------------------------------------------------
    # FAISS-accelerated hybrid path
    # ----------------------------------------------------------------
    # Strategy: use FAISS to retrieve a large candidate pool (up to
    # max_chunks * 3 or all chunks, whichever is smaller) for the
    # vector component, then blend each candidate's cosine score with
    # its keyword score exactly as the original loop does.
    # Chunks not in the FAISS pool are still considered for keyword
    # matching so per-file coverage stays guaranteed.
    # ----------------------------------------------------------------
    if use_faiss and embeddings_enabled() and store.get("faiss_index_b64"):
        from faiss_index import deserialize_index, faiss_available, search_index

        if faiss_available():
            try:
                qvec = embed_query(q)
                faiss_idx = deserialize_index(store["faiss_index_b64"])
                if faiss_idx is not None:
                    # Retrieve a generous candidate pool for blending.
                    candidate_k = min(max_chunks * 3, len(chunks))
                    faiss_scores, faiss_idxs = search_index(faiss_idx, qvec, candidate_k)

                    # Build a score map: chunk_index -> cosine score from FAISS
                    faiss_cos: dict[int, float] = {}
                    for cos_score, idx in zip(faiss_scores, faiss_idxs):
                        if idx < len(chunks):
                            faiss_cos[idx] = cos_score

                    # Blend FAISS cosine with keyword score for every chunk
                    for i, ch in enumerate(chunks):
                        label = labels[i] if i < len(labels) else "attachment"
                        cos = faiss_cos.get(i, 0.0)
                        kw = _score_chunk(tokens, ch)
                        score = _blend_attachment_score(cos, kw, keyword_weight=kw_weight)
                        if score > 0:
                            hits.append(RagHit(score, f"{label} — attachment", ch, i, cosine_score=cos))
            except Exception:
                hits = []  # fall through to cosine loop

    # ----------------------------------------------------------------
    # Cosine loop fallback (FAISS unavailable / disabled / failed)
    # ----------------------------------------------------------------
    if not hits and embeddings_enabled() and len(vectors) == len(chunks):
        try:
            qvec = embed_query(q)
            for i, (vec, ch) in enumerate(zip(vectors, chunks)):
                label = labels[i] if i < len(labels) else "attachment"
                cos = cosine_similarity(qvec, vec)
                kw = _score_chunk(tokens, ch)
                score = _blend_attachment_score(cos, kw, keyword_weight=kw_weight)
                if score > 0:
                    hits.append(RagHit(score, f"{label} — attachment", ch, i, cosine_score=cos))
        except Exception:
            hits = []

    # ----------------------------------------------------------------
    # Pure keyword fallback (no Ollama / embeddings)
    # ----------------------------------------------------------------
    if not hits:
        for i, ch in enumerate(chunks):
            label = labels[i] if i < len(labels) else "attachment"
            kw = _score_chunk(tokens, ch)
            if kw > 0:
                hits.append(RagHit(kw, f"{label} — attachment", ch, i, cosine_score=0.0))

    if not hits:
        return ""

    hits.sort(key=lambda h: h.score, reverse=True)
    by_file: dict[str, list[RagHit]] = {}
    for hit in hits:
        by_file.setdefault(_attachment_file_label(hit), []).append(hit)

    selected: list[RagHit] = []
    picked: set[int] = set()

    # Guarantee minimum coverage per file (round-robin first N rounds)
    for _round in range(min_per_file):
        for file_hits in by_file.values():
            if _round >= len(file_hits):
                continue
            hit = file_hits[_round]
            if hit.chunk_index in picked:
                continue
            selected.append(hit)
            picked.add(hit.chunk_index)

    # Fill remaining slots up to max_chunks
    for hit in hits:
        if len(selected) >= max_chunks:
            break
        if hit.chunk_index in picked:
            continue
            
        # Check pure cosine score component when embeddings are used, otherwise check blended score
        is_embedded = embeddings_enabled() and len(vectors) == len(chunks)
        has_cosine = hit.cosine_score > 0.0
        
        if is_embedded and has_cosine:
            if hit.cosine_score < min_cos and len(selected) >= min_per_file * max(len(by_file), 1):
                continue
        elif len(selected) >= min_per_file * max(len(by_file), 1):
            if hit.score < 0.05:
                continue
                
        selected.append(hit)
        picked.add(hit.chunk_index)

    selected.sort(key=lambda h: h.score, reverse=True)
    # Build chunk_index -> vector map for cosine-based dedup/conflict detection
    vec_map: dict[int, list[float]] | None = None
    if vectors and len(vectors) == len(chunks):
        vec_map = {i: vectors[i] for i in range(len(vectors))}
    return _format_hits(
        selected,
        len(selected),
        min_score=0.0,
        max_chars=char_limit,
        cite_chunks=cite,
        vectors=vec_map,
        dedup_threshold=_rag_float(cfg, "rag_dedup_sim_threshold", 0.92),
        conflict_low=_rag_float(cfg, "rag_conflict_sim_low", 0.75),
        conflict_high=_rag_float(cfg, "rag_conflict_sim_high", 0.92),
    )


def retrieve_attachment_query_budget(
    query: str,
    paths: list[str],
    *,
    owner_password: str | None = None,
    max_chars: int | None = None,
) -> str:
    """
    For count/list questions: pack the context budget with the most query-relevant
    chunks from ALL files (not sequential dump from file 1 first).
    """
    from embeddings import cosine_similarity, embed_query, embeddings_enabled
    from knowledge import _is_trivial_message, _score_chunk, _tokenize

    cfg = load_rag_config()
    if not cfg.get("rag_attachment_rag_enabled", True) or not paths:
        return ""
    q = query.strip()
    if not q or _is_trivial_message(q):
        return ""

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

    from chat_attachments import enumeration_query_tokens, resolve_attachment_char_budgets

    char_limit = max_chars
    if char_limit is None:
        _full, char_limit = resolve_attachment_char_budgets()

    kw_weight = 0.7
    cite = bool(cfg.get("rag_chunk_citations", True))
    tokens = enumeration_query_tokens(q)

    hits: list[RagHit] = []
    if embeddings_enabled() and len(vectors) == len(chunks):
        try:
            qvec = embed_query(q)
            for i, (vec, ch) in enumerate(zip(vectors, chunks)):
                label = labels[i] if i < len(labels) else "attachment"
                cos = cosine_similarity(qvec, vec)
                kw = _score_chunk(tokens, ch)
                score = _blend_attachment_score(cos, kw, keyword_weight=kw_weight)
                hits.append(RagHit(score, f"{label} — attachment", ch, i))
        except Exception:
            hits = []

    if not hits:
        for i, ch in enumerate(chunks):
            label = labels[i] if i < len(labels) else "attachment"
            kw = _score_chunk(tokens, ch)
            hits.append(RagHit(kw, f"{label} — attachment", ch, i))

    hits.sort(key=lambda h: h.score, reverse=True)
    # Build chunk_index -> vector map for cosine-based dedup/conflict detection
    vec_map_q: dict[int, list[float]] | None = None
    if vectors and len(vectors) == len(chunks):
        vec_map_q = {i: vectors[i] for i in range(len(vectors))}
    return _format_hits(
        hits,
        len(hits),
        min_score=0.0,
        max_chars=char_limit,
        cite_chunks=cite,
        vectors=vec_map_q,
        dedup_threshold=_rag_float(cfg, "rag_dedup_sim_threshold", 0.92),
        conflict_low=_rag_float(cfg, "rag_conflict_sim_low", 0.75),
        conflict_high=_rag_float(cfg, "rag_conflict_sim_high", 0.92),
    )


def retrieve_attachment_all_chunks(
    paths: list[str],
    *,
    owner_password: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Return indexed chunks from ALL session files (not top-k sampling)."""
    from chat_attachments import resolve_attachment_char_budgets

    cfg = load_rag_config()
    if not cfg.get("rag_attachment_rag_enabled", True) or not paths:
        return ""

    if not index_attachment_paths(paths, owner_password=owner_password):
        return ""

    session_key = _attachment_session_key(paths)
    store = _read_store(_session_path(session_key), owner_password=owner_password)
    if not store:
        return ""

    chunks = store.get("chunks") or []
    labels = store.get("labels") or []
    if not chunks:
        return ""

    from chat_attachments import resolve_attachment_char_budgets

    char_limit = max_chars
    if char_limit is None:
        _full, char_limit = resolve_attachment_char_budgets()

    cite = bool(cfg.get("rag_chunk_citations", True))
    parts: list[str] = []
    used = 0
    omitted = 0
    for i, ch in enumerate(chunks):
        label = labels[i] if i < len(labels) else "attachment"
        header = f"[{label}#{i + 1}]" if cite else f"[{label}]"
        block = f"{header}\n{ch}"
        if used + len(block) + 2 > char_limit:
            omitted = len(chunks) - i
            break
        parts.append(block)
        used += len(block) + 2

    if not parts:
        return ""

    body = "\n\n".join(parts)
    if omitted > 0:
        body += (
            f"\n\n[... {omitted} more chunks omitted — raise chat_model_context_tokens "
            f"in config.json if Ollama uses a larger context (e.g. 262144 for 256K) ...]"
        )

    return (
        "ATTACHED FILES (complete indexed content from all session files):\n\n"
        + body
    )


_SYNONYMS = {
    "refund": ["reimbursement", "return", "refunds", "refunded", "chargeback"],
    "refunds": ["reimbursement", "return", "refund", "refunded", "chargeback"],
    "reimbursement": ["refund", "reimbursements", "expense", "payback"],
    "reimbursements": ["refund", "reimbursement", "expense", "payback"],
    "payment": ["payments", "paid", "transaction", "invoice", "receipt", "billing"],
    "payments": ["payment", "paid", "transaction", "invoice", "receipt", "billing"],
    "price": ["cost", "charge", "rate", "fee", "pricing"],
    "cost": ["price", "charge", "rate", "fee", "pricing"],
    "charge": ["price", "cost", "rate", "fee", "billing"],
    "invoice": ["bill", "invoices", "receipt", "payment"],
    "invoices": ["bill", "invoice", "receipt", "payment"],
    "receipt": ["invoice", "bill", "payment", "proof"],
    "receipts": ["invoice", "bill", "payment", "proof"],
    "error": ["errors", "fail", "failed", "failure", "bug", "crash", "exception"],
    "errors": ["error", "fail", "failed", "failure", "bug", "crash", "exception"],
    "fail": ["failed", "failure", "error", "bug", "crash"],
    "failed": ["fail", "failure", "error", "bug", "crash"],
    "failure": ["fail", "failed", "error", "bug", "crash"],
    "bug": ["error", "fail", "failed", "issue", "defect"],
    "bugs": ["error", "fail", "failed", "issue", "defect"],
    "issue": ["bug", "error", "problem", "defect"],
    "issues": ["bug", "error", "problem", "defect"],
    "order": ["orders", "purchase", "transaction", "cart"],
    "orders": ["order", "purchase", "transaction", "cart"],
    "purchase": ["order", "buy", "transaction"],
    "food": ["meal", "order", "foodname", "dish", "menu"],
    "meal": ["food", "order", "dish", "menu"],
    "salary": ["pay", "wage", "income", "compensation"],
    "pay": ["salary", "wage", "income", "compensation"],
    "wage": ["salary", "pay", "income", "compensation"],
    "income": ["salary", "pay", "wage", "compensation"],
    "address": ["location", "place", "street", "residence"],
    "location": ["address", "place", "street", "residence"],
    "phone": ["mobile", "cell", "contact", "number", "telephone"],
    "mobile": ["phone", "cell", "contact", "number", "telephone"],
    "contact": ["phone", "mobile", "email", "address", "number"],
    "email": ["mail", "contact", "message"],
    "mail": ["email", "contact", "message"],
}


def _expand_query(query: str) -> str:
    """Expand short/vague queries with common synonyms to improve RAG recall."""
    from knowledge import _tokenize

    q = query.strip()
    if not q:
        return q

    words = _tokenize(q)
    expanded = list(words)
    for word in words:
        low = word.lower()
        if low in _SYNONYMS:
            for syn in _SYNONYMS[low]:
                if syn not in expanded:
                    expanded.append(syn)

    if len(expanded) > len(words):
        # Append unique synonyms to preserve the query's natural sentence embedding
        # but enrich it with key terminology.
        new_terms = [w for w in expanded if w not in words]
        return q + " " + " ".join(new_terms)
    return q


# --- Unified retrieval ---


def retrieve_attachment_for_query(
    query: str,
    paths: list[str],
    *,
    owner_password: str | None = None,
    max_chars: int | None = None,
) -> str:
    """
    Generic attachment retrieval: literal grep from user's words + semantic hybrid fallback.
    No hardcoded question-type patterns.
    """
    from chat_attachments import grep_session_for_query, resolve_attachment_char_budgets
    from knowledge import _is_trivial_message

    q = _expand_query(query.strip())
    if not q or _is_trivial_message(q) or not paths:
        return ""

    _full, limit = resolve_attachment_char_budgets()
    budget = max_chars if max_chars is not None else limit

    # Guarantee a minimum budget of 2000 chars for hybrid/FAISS (or less if the total budget is tiny)
    min_hybrid = min(2000, budget // 2)
    target_hybrid = max(min_hybrid, budget // 2)
    target_grep = max(0, budget - target_hybrid)

    grep_part = grep_session_for_query(paths, q, max_chars=target_grep)
    used = len(grep_part)
    remaining = max(budget - used - 4, 0)
    hybrid_part = ""
    if remaining >= 800:
        hybrid_part = retrieve_attachment_hybrid(
            q, paths, owner_password=owner_password, max_chars=remaining
        )
    parts = [part.strip() for part in (grep_part, hybrid_part) if part.strip()]
    return "\n\n".join(parts)


def retrieve_all_context(
    query: str,
    *,
    attachment_paths: list[str] | None = None,
    has_chat_attachments: bool = False,
    owner_password: str | None = None,
    session_attachment_mode: str = "none",
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

    # Owner memory can contradict fresh attachments (e.g. old log summaries) — skip when files attached.
    if cfg.get("rag_memory_enabled", True) and not has_attachments:
        mem = retrieve_memory_context(
            query, owner_password=owner_password
        )
        if mem.strip():
            sections["memory"] = mem.strip()

    if (
        query.strip()
        and should_run_document_retrieval(
            query,
            has_chat_attachments=has_attachments,
            attachment_paths=paths,
        )
    ):
        docs = retrieve_context(query)
        if docs.strip():
            sections["documents"] = docs.strip()

    if has_attachments and cfg.get("rag_attachment_rag_enabled", True):
        from knowledge import _is_trivial_message

        needs_search = bool(query.strip()) and not _is_trivial_message(query)
        if needs_search:
            if session_attachment_mode == "full":
                # For full mode, retrieve a smaller set of highly relevant excerpts (e.g. top-k chunks)
                # to prepend above the full text, so the model sees the best matches first.
                att = retrieve_attachment_for_query(
                    query, paths, owner_password=owner_password, max_chars=8000
                )
                if att.strip():
                    sections["attachments"] = "HIGH-RELEVANCE EXCERPTS FROM ATTACHED FILES:\n" + att.strip()
            else:
                att = retrieve_attachment_for_query(
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
            "OWNER MEMORY [Priority: Low — long-term personal facts, may be outdated]:\n"
            + sections["memory"]
        )
    if sections.get("documents"):
        parts.append(
            "TRAINED DOCUMENTS [Priority: Medium — use for document-specific questions]:\n"
            + sections["documents"]
        )
    if sections.get("attachments"):
        parts.append(
            "ATTACHED FILES [Priority: High — most current source, prefer over others]:\n"
            + sections["attachments"]
        )

    # Build conflict notice when multiple sources are present
    source_count = len([s for s in ("memory", "documents", "attachments") if sections.get(s)])
    conflict_instruction = ""
    if source_count > 1:
        conflict_instruction = (
            "\n⚠ CONFLICT RULE: If the sources above give different answers to the same "
            "question, prefer the higher-priority source (Attached Files > Trained Documents "
            "> Owner Memory). Always explicitly mention the discrepancy to the user, e.g.: "
            "\"Note: [file A] says X, but [file B] says Y — the attached file takes priority.\""
            "\n"
        )

    header = (
        "RETRIEVED KNOWLEDGE (RAG — use when relevant; cite bracketed source labels):\n"
        + conflict_instruction
        + "\n"
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


def retrieve_rag_metadata(
    query: str,
    *,
    attachment_paths: list[str] | None = None,
    has_chat_attachments: bool = False,
    owner_password: str | None = None,
) -> dict[str, Any]:
    """
    Retrieves RAG hits in a structured format suitable for building a retrieved knowledge graph.
    """
    from knowledge import should_run_document_retrieval, list_documents, _load_document_payload, load_embeddings, ensure_document_embeddings
    from embeddings import cosine_similarity, embed_query, embeddings_enabled, embed_model_name
    from assistant import load_memory
    
    cfg = load_rag_config()
    q = query.strip()
    if not q:
        return {"nodes": [], "conflicts": []}

    nodes = []
    paths = [str(p).strip() for p in (attachment_paths or []) if str(p).strip()]
    has_attachments = has_chat_attachments or bool(paths)
    
    # 1. Memory facts
    if cfg.get("rag_memory_enabled", True) and not has_attachments:
        try:
            memory = load_memory(password=owner_password)
            facts = [str(f).strip() for f in memory.get("facts", []) if str(f).strip()]
            if facts and embeddings_enabled():
                ensure_memory_embeddings(owner_password=owner_password)
                emb = _read_store(MEMORY_EMBED_PATH, owner_password=owner_password)
                if emb and emb.get("chunks") == facts:
                    qvec = embed_query(q)
                    vectors = emb.get("vectors") or []
                    hits = []
                    for i, (vec, fact) in enumerate(zip(vectors, facts)):
                        score = cosine_similarity(qvec, vec)
                        if score > 0:
                            hits.append(RagHit(score, "memory", fact, i))
                    
                    min_cos = _rag_float(cfg, "rag_min_memory_cosine_similarity", 0.22)
                    hits = [h for h in hits if h.score >= min_cos]
                    hits.sort(key=lambda h: h.score, reverse=True)
                    for idx, h in enumerate(hits[:6]):
                        nodes.append({
                            "id": f"memory_{idx}",
                            "type": "memory",
                            "source": "Memory",
                            "text": h.text,
                            "score": float(round(h.score, 3)),
                            "conflict_with": ""
                        })
        except Exception:
            pass

    # 2. Trained documents
    if should_run_document_retrieval(q, has_chat_attachments=has_attachments, attachment_paths=paths):
        try:
            if embeddings_enabled():
                min_cos = _rag_float(cfg, "rag_min_cosine_similarity", 0.28)
                query_vec = embed_query(q)
                model = embed_model_name()
                doc_hits = []
                for doc in list_documents():
                    doc_id = str(doc.get("id") or "")
                    payload = _load_document_payload(doc_id)
                    if not payload:
                        continue
                    chunks = payload.get("chunks") or []
                    if not chunks or not ensure_document_embeddings(doc_id, chunks):
                        continue
                    emb = load_embeddings(doc_id)
                    if not emb or emb.get("embed_model") != model:
                        continue
                    vectors = emb.get("vectors") or []
                    source = payload.get("source_name", doc.get("source_name", "document"))
                    for chunk_i, (vec, chunk) in enumerate(zip(vectors, chunks)):
                        score = cosine_similarity(query_vec, vec)
                        if score >= min_cos:
                            doc_hits.append((score, source, chunk, chunk_i))
                doc_hits.sort(key=lambda x: x[0], reverse=True)
                for idx, (score, source, chunk, chunk_i) in enumerate(doc_hits[:6]):
                    nodes.append({
                        "id": f"document_{idx}",
                        "type": "document",
                        "source": source,
                        "text": chunk,
                        "score": float(round(score, 3)),
                        "conflict_with": ""
                    })
        except Exception:
            pass

    # 3. Attachments
    if has_attachments and cfg.get("rag_attachment_rag_enabled", True):
        try:
            if paths:
                if index_attachment_paths(paths, owner_password=owner_password):
                    session_key = _attachment_session_key(paths)
                    store = _read_store(_session_path(session_key), owner_password=owner_password)
                    if store:
                        chunks = store.get("chunks") or []
                        labels = store.get("labels") or []
                        vectors = store.get("vectors") or []
                        if chunks:
                            from chat_attachments import query_search_terms
                            from knowledge import _score_chunk, _tokenize
                            kw_weight = _rag_float(cfg, "rag_hybrid_keyword_weight", 0.35)
                            min_per_file = _rag_int(cfg, "rag_attachment_min_chunks_per_file", 4)
                            max_chunks = _rag_int(cfg, "rag_attachment_max_chunks", 64)
                            min_cos = _rag_float(cfg, "rag_min_cosine_similarity", 0.28)
                            tokens = _tokenize(q)
                            use_faiss = bool(cfg.get("rag_use_faiss", True))
                            
                            hits = []
                            if use_faiss and embeddings_enabled() and store.get("faiss_index_b64"):
                                from faiss_index import deserialize_index, faiss_available, search_index
                                if faiss_available():
                                    qvec = embed_query(q)
                                    faiss_idx = deserialize_index(store["faiss_index_b64"])
                                    if faiss_idx is not None:
                                        candidate_k = min(max_chunks * 3, len(chunks))
                                        faiss_scores, faiss_idxs = search_index(faiss_idx, qvec, candidate_k)
                                        faiss_cos = {idx: cs for cs, idx in zip(faiss_scores, faiss_idxs) if idx < len(chunks)}
                                        for i, ch in enumerate(chunks):
                                            label = labels[i] if i < len(labels) else "attachment"
                                            cos = faiss_cos.get(i, 0.0)
                                            kw = _score_chunk(tokens, ch)
                                            score = _blend_attachment_score(cos, kw, keyword_weight=kw_weight)
                                            if score > 0:
                                                hits.append(RagHit(score, f"{label} — attachment", ch, i, cosine_score=cos))
                            
                            if not hits and embeddings_enabled() and len(vectors) == len(chunks):
                                qvec = embed_query(q)
                                for i, (vec, ch) in enumerate(zip(vectors, chunks)):
                                    label = labels[i] if i < len(labels) else "attachment"
                                    cos = cosine_similarity(qvec, vec)
                                    kw = _score_chunk(tokens, ch)
                                    score = _blend_attachment_score(cos, kw, keyword_weight=kw_weight)
                                    if score > 0:
                                        hits.append(RagHit(score, f"{label} — attachment", ch, i, cosine_score=cos))
                                        
                            if not hits:
                                for i, ch in enumerate(chunks):
                                    label = labels[i] if i < len(labels) else "attachment"
                                    kw = _score_chunk(tokens, ch)
                                    if kw > 0:
                                        hits.append(RagHit(kw, f"{label} — attachment", ch, i, cosine_score=0.0))
                                        
                            if hits:
                                hits.sort(key=lambda h: h.score, reverse=True)
                                by_file = {}
                                for h in hits:
                                    by_file.setdefault(_attachment_file_label(h), []).append(h)
                                
                                selected = []
                                picked = set()
                                for _round in range(min_per_file):
                                    for file_hits in by_file.values():
                                        if _round < len(file_hits):
                                            h = file_hits[_round]
                                            if h.chunk_index not in picked:
                                                selected.append(h)
                                                picked.add(h.chunk_index)
                                                
                                for h in hits:
                                    if len(selected) >= max_chunks:
                                        break
                                    if h.chunk_index in picked:
                                        continue
                                    is_embedded = embeddings_enabled() and len(vectors) == len(chunks)
                                    has_cosine = h.cosine_score > 0.0
                                    if is_embedded and has_cosine:
                                        if h.cosine_score < min_cos and len(selected) >= min_per_file * max(len(by_file), 1):
                                            continue
                                    elif len(selected) >= min_per_file * max(len(by_file), 1):
                                        if h.score < 0.05:
                                            continue
                                    selected.append(h)
                                    picked.add(h.chunk_index)
                                
                                selected.sort(key=lambda h: h.score, reverse=True)
                                vec_map = None
                                if vectors and len(vectors) == len(chunks):
                                    vec_map = {i: vectors[i] for i in range(len(vectors))}
                                selected = _detect_conflicts(
                                    selected, vec_map,
                                    low=_rag_float(cfg, "rag_conflict_sim_low", 0.75),
                                    high=_rag_float(cfg, "rag_conflict_sim_high", 0.92)
                                )
                                
                                for idx, h in enumerate(selected[:12]):
                                    nodes.append({
                                        "id": f"attachment_{idx}",
                                        "type": "attachment",
                                        "source": _attachment_file_label(h),
                                        "text": h.text,
                                        "score": float(round(h.score, 3)),
                                        "conflict_with": h.conflict_with
                                    })
        except Exception:
            pass

    conflicts = []
    for n1 in nodes:
        if n1.get("conflict_with"):
            for n2 in nodes:
                if n2["id"] != n1["id"] and n2["source"].lower() == n1["conflict_with"].lower():
                    conflicts.append({
                        "node_id_1": n1["id"],
                        "node_id_2": n2["id"],
                        "reason": f"Discrepancy between {n1['source']} and {n2['source']}"
                    })
                    break

    return {"nodes": nodes, "conflicts": conflicts}
