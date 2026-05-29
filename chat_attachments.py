"""
Extract text from files attached in chat (session-only, not saved to knowledge).
"""

from __future__ import annotations

import base64
import json
import re
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


def resolve_attachment_char_budgets(
    cfg: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """
    Derive safe attachment char budgets from the chat model context window.
    Returns (full_inline_budget, max_chunk_budget).
    Conservative for Qwen 3.5 256K context via Ollama.
    """
    cfg = cfg or load_attachment_config()
    model_name = cfg.get("model") or "roPac"
    provider = cfg.get("chat_provider") or "local"
    
    context_tokens = None
    if provider == "local":
        from model_manager import query_model_context_length
        context_tokens = query_model_context_length(model_name)
        
    cap = int(cfg.get("chat_model_context_tokens") or 0)
    if cap > 0:
        if context_tokens is not None:
            context_tokens = min(context_tokens, cap)
        else:
            context_tokens = cap
    else:
        context_tokens = context_tokens or 65536
        
    reserved = int(cfg.get("chat_context_reserved_tokens") or 10240)
    chars_per_token = float(cfg.get("chat_context_chars_per_token") or 3.5)
    attach_tokens = max(context_tokens - reserved, 4096)
    max_chars = int(attach_tokens * chars_per_token)
    full_ratio = float(cfg.get("chat_session_full_context_ratio") or 0.85)
    full_chars = int(max_chars * full_ratio)
    return full_chars, max_chars


def load_attachment_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        # Raised from 12000 → 60000 to match the full inline budget for 65k-token models.
        "chat_attachment_max_chars": 60000,
        "train_image_max_chars": 24000,
        "chat_attachments_enabled": True,
        "chat_session_max_files": 30,
        "chat_model_context_tokens": 65536,
        "chat_context_reserved_tokens": 10240,
        "chat_context_chars_per_token": 3.5,
        "chat_session_full_context_ratio": 0.85,
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


def read_attachment_full_text(path: str | Path) -> tuple[str, str]:
    """Read complete file content for session chat. Returns (text, kind)."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")
    if is_image_path(file_path):
        raw = _describe_image_with_ollama(file_path, for_training=False)
        if not raw.strip():
            raise ValueError("No text could be extracted from this image")
        return raw, "image"
    text = read_file(file_path)
    if not text.strip():
        raise ValueError("No text could be extracted from this file")
    return text, "text"


def read_session_files(paths: list[str]) -> list[tuple[str, str, str]]:
    """Read up to chat_session_max_files — full content each. Returns (name, text, kind)."""
    cfg = load_attachment_config()
    max_files = int(cfg.get("chat_session_max_files") or 30)
    out: list[tuple[str, str, str]] = []
    for raw in paths[:max_files]:
        path = Path(raw).expanduser()
        if not path.is_file():
            continue
        try:
            text, kind = read_attachment_full_text(path)
            out.append((path.name, text, kind))
        except (OSError, ValueError):
            continue
    return out


def session_files_total_chars(paths: list[str]) -> int:
    total = 0
    for _, text, _ in read_session_files(paths):
        total += len(text)
    return total


def session_attachment_mode(paths: list[str]) -> str:
    """'full' = every byte inline; 'chunked' = all indexed chunks; 'none' = no files."""
    files = read_session_files(paths)
    if not files:
        return "none"
    full_budget, _ = resolve_attachment_char_budgets()
    total = sum(len(text) for _, text, _ in files)
    return "full" if total <= full_budget else "chunked"


def extract_attachment_text(path: str | Path) -> dict[str, Any]:
    """
    Return {ok, name, kind, text, error}.
    kind is 'text' or 'image'. Used by parse_attachment API (may truncate).
    The truncation cap uses the dynamic context budget so it scales with the
    model's actual context window — not a static 12k char limit.
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
    # Use the dynamic full-inline budget so truncation scales with the model context.
    # Falls back to chat_attachment_max_chars (now 60k) if budget can't be resolved.
    try:
        full_budget, _ = resolve_attachment_char_budgets(cfg)
        max_chars = full_budget
    except Exception:
        max_chars = int(cfg.get("chat_attachment_max_chars") or 60000)

    if not file_path.is_file():
        return {
            "ok": False,
            "name": name,
            "kind": "unknown",
            "text": "",
            "error": f"File not found: {file_path}",
        }

    try:
        raw, kind = read_attachment_full_text(file_path)
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


def enumeration_query_tokens(query: str) -> set[str]:
    """Dynamically expand query tokens for count/list retrieval including singular/plural/stem forms."""
    from knowledge import _tokenize

    tokens = set(_tokenize(query))
    for token in list(tokens):
        # 1. Singular/Plural expansions (e.g. orders -> order, burger -> burgers)
        if token.endswith("s") and len(token) > 3:
            tokens.add(token[:-1])
        else:
            tokens.add(token + "s")
            
        # 2. Verb/Adjective suffix expansions (e.g. failed -> fail, success -> successful)
        if token.endswith("ed") and len(token) > 4:
            tokens.add(token[:-2])
            tokens.add(token[:-2] + "ing")
        elif token.endswith("ing") and len(token) > 5:
            tokens.add(token[:-3])
            tokens.add(token[:-3] + "ed")
            
        # 3. Handle common dynamic typos and variants (e.g. success -> successful, successfull)
        if "success" in token:
            tokens.update({"success", "successful", "successfull"})
            
    return tokens


def query_search_terms(query: str) -> tuple[list[str], list[str]]:
    """
    Extract quoted phrases and significant words from the user's question.
    No fixed domain vocabulary — works for food names, amounts, errors, anything.
    """
    from knowledge import _tokenize

    q = query.strip()
    phrases: list[str] = []
    for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', q):
        phrase = (match.group(1) or match.group(2) or "").strip()
        if len(phrase) >= 2:
            phrases.append(phrase)

    stop = frozenset(
        "a an the is are was were in on at to for of and or not can you u me my "
        "this that file files from with what which how do does did about any "
        "see tell show give please".split()
    )
    tokens: list[str] = []
    seen: set[str] = set()
    for token in enumeration_query_tokens(q):
        if len(token) < 2 or token in stop:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    # Also keep longer original tokens _tokenize may split (e.g. foodname keys in JSON)
    for token in _tokenize(q):
        if len(token) >= 3 and token not in stop and token not in seen:
            seen.add(token)
            tokens.append(token)
    return phrases, tokens


def grep_session_for_query(
    paths: list[str],
    query: str,
    *,
    max_chars: int | None = None,
) -> str:
    """
    Scan every attached file for lines matching the user's own words/phrases.
    Works for any keyword: food names, amounts, error classes, IDs, etc.
    """
    phrases, tokens = query_search_terms(query)
    if not phrases and not tokens:
        return ""

    files = read_session_files(paths)
    if not files:
        return ""

    _full, char_limit = resolve_attachment_char_budgets()
    limit = max_chars if max_chars is not None else char_limit

    def line_score(line: str) -> int:
        lower = line.lower()
        score = 0
        for phrase in phrases:
            if phrase.lower() in lower:
                score += 10
        for token in tokens:
            if token in lower:
                score += 1
        return score

    hit_blocks: list[str] = []
    clean_files: list[str] = []
    used = 0

    for name, text, _kind in files:
        is_log = name.lower().endswith(".log")
        scored: list[tuple[int, int, str]] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            score = line_score(stripped)
            if score > 0:
                scored.append((score, lineno, stripped))
        if not scored:
            clean_files.append(name)
            continue
        # For log files: preserve chronological order so counts/aggregations work correctly.
        # For other files: sort by score (most relevant first).
        per_file_cap = 300 if is_log else 80
        if is_log:
            scored.sort(key=lambda row: row[1])  # sort by line number, not score
        else:
            scored.sort(key=lambda row: (-row[0], row[1]))
        lines_out = [f"  L{lineno}: {text}" for _score, lineno, text in scored[:per_file_cap]]
        block = f"[{name}] ({len(scored)} matching line(s))\n" + "\n".join(lines_out)
        if len(scored) > per_file_cap:
            block += f"\n  [... {len(scored) - per_file_cap} more matching lines omitted ...]"

        if used + len(block) + 4 > limit:
            hit_blocks.append(
                block[: max(0, limit - used - 60)].rstrip()
                + "\n  [... truncated — ask a narrower question ...]"
            )
            used = limit
            break
        hit_blocks.append(block)
        used += len(block) + 2

    if not hit_blocks and not clean_files:
        return ""

    header = (
        "ATTACHED FILE SEARCH (literal matches for the user's question — "
        "do not invent text not shown here):"
    )
    parts = [header]
    if hit_blocks:
        parts.append("\n\n".join(hit_blocks))
    if clean_files:
        parts.append(
            "[Files with NO lines matching the user's search terms]\n"
            + ", ".join(clean_files)
        )
    return "\n\n".join(parts)


def should_include_attachment_body(query: str, paths: list[str]) -> bool:
    """Inline full file text only for non-trivial questions that fit the context budget."""
    from knowledge import _is_trivial_message

    if not paths:
        return False
    q = query.strip()
    if not q or _is_trivial_message(q):
        return False
    total = session_files_total_chars(paths)
    full_budget, _ = resolve_attachment_char_budgets()
    return total <= full_budget


def generate_file_outline(name: str, text: str, kind: str) -> str:
    """Generate a highly informative, compact structural outline of a file."""
    lines = text.splitlines()
    outline_lines = []

    # 0. Log files — summarise log levels, timestamps, components, and key event types
    if name.lower().endswith(".log") or (
        any(
            f"[{lvl}]" in text
            for lvl in ("Info", "Debug", "Error", "Warning", "Warn", "Fatal", "Verbose")
        )
        and not name.lower().endswith((".py", ".js", ".kt", ".java", ".ts"))
    ):
        import re as _re
        level_counts: dict[str, int] = {}
        components: dict[str, int] = {}
        first_ts = last_ts = ""
        order_successes = 0
        order_failures = 0
        error_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Timestamps like [HH:MM:SS +ZZZZ]
            ts_m = _re.match(r"\[(\d{2}:\d{2}:\d{2}[^\]]*)\]", stripped)
            if ts_m:
                ts = ts_m.group(1)
                if not first_ts:
                    first_ts = ts
                last_ts = ts
            # Level
            lv_m = _re.search(r"\[(Info|Debug|Error|Warning|Warn|Fatal|Verbose)\]", stripped)
            if lv_m:
                lvl = lv_m.group(1)
                level_counts[lvl] = level_counts.get(lvl, 0) + 1
            # Component
            comp_m = _re.findall(r"\[([A-Z][A-Za-z0-9_]+(?:ViewModel|Handler|Worker|Service|Engine|Sync|Screen|Manager|Observer|Repo|Init|Initialization)?)\]", stripped)
            for c in comp_m:
                if c not in ("Info", "Debug", "Error", "Warning", "Warn", "Fatal", "Verbose"):
                    components[c] = components.get(c, 0) + 1
            # Orders
            if "Place Order Success" in stripped:
                order_successes += 1
            if "Place Order Fail" in stripped or "result=failure" in stripped.lower():
                order_failures += 1
            # Errors
            if "[Error]" in stripped and len(error_lines) < 5:
                error_lines.append(f"  • {stripped[:160]}")
        outline_parts = [f"Log file — {len(lines)} lines"]
        if first_ts:
            outline_parts.append(f"Time range: {first_ts} → {last_ts}")
        if level_counts:
            level_str = ", ".join(f"{k}:{v}" for k, v in sorted(level_counts.items(), key=lambda x: -x[1]))
            outline_parts.append(f"Log levels: {level_str}")
        if order_successes or order_failures:
            outline_parts.append(f"Orders: {order_successes} successful, {order_failures} failed")
        if components:
            top_comps = sorted(components.items(), key=lambda x: -x[1])[:8]
            outline_parts.append(f"Top components: {', '.join(c for c, _ in top_comps)}")
        if error_lines:
            outline_parts.append("Sample errors:\n" + "\n".join(error_lines))
        outline_lines.append("\n".join(outline_parts))
        return "\n".join(outline_lines)

    # 1. Excel tabular text (marked by '## Sheet: ')
    if "## Sheet:" in text:

        sheets = []
        current_sheet = None
        for line in lines:
            if line.startswith("## Sheet:"):
                current_sheet = line.replace("## Sheet:", "").strip()
                sheets.append(f"  - Sheet: {current_sheet}")
            elif current_sheet and len(sheets) > 0 and "\t" in line:
                cols = [c.strip() for c in line.split("\t") if c.strip()]
                if cols and not sheets[-1].endswith(")"):
                    sheets[-1] += f" (Columns: {', '.join(cols[:8])}"
                    if len(cols) > 8:
                        sheets[-1] += "..."
                    sheets[-1] += ")"
                current_sheet = None
        outline_lines.append("Structure (Excel sheets & columns):\n" + "\n".join(sheets[:12]))
        
    # 2. CSV tabular text
    elif name.lower().endswith(".csv") and lines:
        cols = [c.strip() for c in lines[0].split("\t") if c.strip()]
        if len(cols) <= 1:
            cols = [c.strip() for c in lines[0].split(",") if c.strip()]
        outline_lines.append(f"Structure (CSV Columns): {', '.join(cols[:12])}")
        if len(lines) > 1:
            sample = lines[1].replace("\t", ", ")
            outline_lines.append(f"Sample Row: {sample[:150]}")
            
    # 3. Code files
    elif name.lower().endswith((".py", ".js", ".ts", ".java", ".kt", ".kts", ".gradle", ".cpp", ".h", ".go", ".cs", ".rb")):
        struct = []
        for line in lines[:250]:
            stripped = line.strip()
            if stripped.startswith(("class ", "def ", "interface ", "function ", "struct ", "enum ")):
                struct.append(f"  - {stripped}")
        if struct:
            outline_lines.append("Structure (Code elements):\n" + "\n".join(struct[:10]))
            if len(struct) > 10:
                outline_lines.append(f"  ... and {len(struct) - 10} more code definitions")
        else:
            preview = "\n".join(lines[:8])
            outline_lines.append(f"Preview:\n{preview[:350]}")
            
    # 4. Images
    elif kind == "image":
        outline_lines.append(f"Description: {text[:400]}")
        
    # 5. Documents (PDF, MD, Word, TXT)
    else:
        headings = []
        for line in lines[:400]:
            stripped = line.strip()
            if stripped.startswith(("#", "##", "###", "####")):
                headings.append(f"  - {stripped}")
            elif len(stripped) > 5 and stripped.isupper() and len(stripped) < 80:
                headings.append(f"  - {stripped}")
        if headings:
            outline_lines.append("Structure (Headings):\n" + "\n".join(headings[:10]))
            if len(headings) > 10:
                outline_lines.append(f"  ... and {len(headings) - 10} more headings")
        else:
            preview = []
            for line in lines:
                s = line.strip()
                if s:
                    preview.append(s)
                if len(preview) >= 6:
                    break
            outline_lines.append("Preview:\n" + "\n".join(preview[:6])[:400])
            
    return "\n".join(outline_lines)


def build_query_attachment_context(
    paths: list[str],
    *,
    query: str = "",
) -> str:
    """
    Session attachment prompt block.
    - Small enough total: complete text of every file (no truncation).
    - Too large: structural outline + indexed RAG chunks.
    - Casual chat (hi, thanks): structural outline only.
    """
    files = read_session_files(paths)
    if not files:
        return ""

    full_budget, max_budget = resolve_attachment_char_budgets()
    total = sum(len(text) for _, text, _ in files)
    names = ", ".join(name for name, _, _ in files)

    # Always generate lightweight structural outlines for all files to anchor context
    outlines = []
    for name, text, kind in files:
        outline = generate_file_outline(name, text, kind)
        outlines.append(f"[{name}]\n{outline}")
    outlines_block = "\n\n".join(outlines)

    if not should_include_attachment_body(query, paths):
        tail = (
            "Search results for your question are in ATTACHED FILES below."
            if total > full_budget
            else "Ask a question — RoPac searches all files using your words."
        )
        return (
            "SESSION ATTACHMENTS (active until New chat — structural map shown below):\n"
            f"- {len(files)} file(s): {names}\n"
            f"- Total: {total:,} chars\n\n"
            f"{outlines_block}\n\n"
            f"{tail}"
        )

    if total <= full_budget:
        blocks: list[str] = []
        for name, text, kind in files:
            label = "image description" if kind == "image" else "complete file"
            blocks.append(f"[{name} — {label}]\n{text}")
        header = (
            "SESSION ATTACHMENTS (complete content of all uploaded files — "
            f"{len(files)} file(s), {total:,} chars — active until New chat):\n\n"
        )
        return header + "\n\n---\n\n".join(blocks)

    return (
        "SESSION ATTACHMENTS (active until New chat):\n"
        f"- Files: {len(files)} ({names})\n"
        f"- Total size: {total:,} chars (inline limit {full_budget:,}, "
        f"chunk budget {max_budget:,})\n\n"
        "GLOBAL FILE OUTLINES (use this map to understand overall file schemas and layouts):\n"
        f"{outlines_block}\n\n"
        "- Complete file content is indexed below in ATTACHED FILES chunks — "
        "answer using every chunk from all files."
    )
