"""
FAISS vector index helpers for RoPac attachment RAG.

This module is intentionally thin:
  - All FAISS-specific logic lives here (not scattered across rag.py).
  - Every public function catches ImportError / Exception so callers
    never crash if faiss-cpu is not installed or fails to build.
  - The index type used is IndexFlatIP (exact inner-product / cosine
    similarity after L2-normalisation).  This gives the *same* ranking
    as the brute-force cosine loop but is substantially faster for
    large attachment corpora (hundreds of chunks).

Upgrade path: swap IndexFlatIP for IndexIVFFlat when chunk counts
routinely exceed ~20 000.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def faiss_available() -> bool:
    """Return True only if faiss and numpy can be imported successfully."""
    try:
        import faiss  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


def build_flat_index(vectors: list[list[float]]) -> Any | None:
    """
    Build a FAISS IndexFlatIP from a list of float vectors.

    Vectors are L2-normalised in-place so that inner-product search
    equals cosine similarity.

    Returns the faiss.Index object, or None on any failure.
    """
    if not vectors:
        return None
    try:
        import faiss
        import numpy as np

        mat = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(mat)           # cosine ≡ inner-product after normalisation
        dim = mat.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(mat)
        return index
    except Exception as exc:
        log.warning("FAISS build_flat_index failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_index(
    index: Any,
    query_vector: list[float],
    top_k: int,
) -> tuple[list[float], list[int]]:
    """
    Query the FAISS index.

    The query vector is L2-normalised before search (matching how
    document vectors were normalised during build_flat_index).

    Returns (scores, indices) — both plain Python lists of length ≤ top_k.
    Returns ([], []) on any error so callers fall back gracefully.
    """
    try:
        import faiss
        import numpy as np

        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)
        distances, flat_indices = index.search(q, top_k)
        # distances / flat_indices are 2-D arrays — unwrap the single row
        scores = [float(s) for s in distances[0] if s > -1e9]
        idxs   = [int(i)   for i in flat_indices[0] if i >= 0]
        # Trim to same length (in case some slots are -1 padding)
        min_len = min(len(scores), len(idxs))
        return scores[:min_len], idxs[:min_len]
    except Exception as exc:
        log.warning("FAISS search_index failed: %s", exc)
        return [], []


# ---------------------------------------------------------------------------
# Serialisation helpers (for session cache JSON)
# ---------------------------------------------------------------------------


def serialize_index(index: Any) -> str | None:
    """
    Serialise a FAISS index to a base64-encoded string suitable for
    embedding directly in a JSON session file.

    Uses faiss.serialize_index() which writes to a numpy uint8 buffer
    — the stable, cross-platform API available in all faiss-cpu wheels.

    Returns None on failure.
    """
    try:
        import faiss
        import numpy as np

        # serialize_index returns a numpy uint8 array
        buf: np.ndarray = faiss.serialize_index(index)
        return base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception as exc:
        log.warning("FAISS serialize_index failed: %s", exc)
        return None


def deserialize_index(b64_data: str) -> Any | None:
    """
    Deserialise a FAISS index from the base64-encoded string previously
    produced by serialize_index.

    Returns None on failure.
    """
    try:
        import faiss
        import numpy as np

        raw = base64.b64decode(b64_data)
        buf = np.frombuffer(raw, dtype=np.uint8)
        return faiss.deserialize_index(buf)
    except Exception as exc:
        log.warning("FAISS deserialize_index failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Convenience: index size
# ---------------------------------------------------------------------------


def index_ntotal(index: Any) -> int:
    """Return the number of vectors stored in the index (0 on error)."""
    try:
        return int(index.ntotal)
    except Exception:
        return 0
