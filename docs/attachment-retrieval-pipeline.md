# Attachment retrieval pipeline (30 files, large text)

How RoPac answers questions from uploaded session files.

## Flow

```
Upload (≤30 files) → session path store → read full text per file
    │
    ├─ Total ≤ inline budget (~67k chars at 32K context)
    │     → complete file text inline in prompt (no RAG)
    │
    └─ Total > inline budget (chunked mode)
          → line-aware chunking → embed all chunks → retrieve
                ├─ list/count questions → all chunks (up to max budget)
                └─ other questions → hybrid retrieval (below)
```

## 1. Chunking

| Setting | Default | Notes |
|---------|---------|-------|
| `rag_attachment_chunk_size` | 1500 | chars per chunk |
| `rag_attachment_chunk_overlap` | 200 | char overlap (logs use line overlap) |

- **`.log` / `.csv`**: line-boundary chunks — JSON log lines stay intact.
- **Other files**: sliding character windows (`ingest.chunk_text`).

## 2. Embeddings

| Setting | Default |
|---------|---------|
| `embed_model` | `nomic-embed-text` |
| `embeddings_enabled` | `true` |

- Queries: `search_query: …` prefix (nomic requirement).
- Indexed chunks: `search_document: …` prefix.
- Batched 32 at a time via Ollama `/v1/embeddings`.

**After Qwen 3.5**: keep `nomic-embed-text` or try `mxbai-embed-large` — embedding model is separate from chat model.

## 3. Vector search

- Cosine similarity over all session chunks (brute force — fine for tens of thousands of chunks).
- `rag_min_cosine_similarity`: 0.28 — minimum score after hybrid ranking.
- Keyword overlap blended in (`rag_hybrid_keyword_weight`: 0.35).

## 4. Hybrid retrieval (large uploads)

| Setting | Default | Purpose |
|---------|---------|---------|
| `rag_attachment_min_chunks_per_file` | 4 | every file represented |
| `rag_attachment_max_chunks` | 64 | cap per question |
| chunk char budget | auto | `(context_tokens − reserved) × 3.5` |

**List/count questions** (`list all items`, `how many`, …): dumps all indexed chunks up to context limit.

**Other questions**: hybrid = per-file minimum + global top scores.

## 5. Qwen 3.5 setup

In `config.json` after `ollama pull`:

```json
"base_model": "qwen3.5:latest",
"coder_model": "qwen3.5:latest"
```

Re-run **Start model** in the app. Larger context helps chunked mode include more data.

## Context budgets (safe for Qwen 3.5)

Limits are **derived from model context** — not hardcoded char caps.

| Setting | Default | Meaning |
|---------|---------|---------|
| `chat_model_context_tokens` | 32768 | Ollama safe default (24–48 GB VRAM) |
| `chat_context_reserved_tokens` | 10240 | system + history + reply headroom |
| `chat_context_chars_per_token` | 3.5 | conservative chars/token |
| `chat_session_full_context_ratio` | 0.85 | inline full-file threshold |

**Computed (default):**
- `max chunk budget` ≈ **78,848 chars** `(32768−10240)×3.5`
- `inline full files` ≈ **67,020 chars** (85% of max)

### If Ollama uses 256K context (48 GB+ VRAM)

```json
"chat_model_context_tokens": 262144
```

→ max chunk budget ≈ **881,664 chars** (auto-calculated).

Set `OLLAMA_CONTEXT_LENGTH=262144` when starting Ollama to match.

## Tuning for 30 large logs

Raise only `chat_model_context_tokens` to match **actual** Ollama `num_ctx` — do not guess a char limit.

```json
"rag_attachment_max_chunks": 96,
"rag_attachment_min_chunks_per_file": 6
```
