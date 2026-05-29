"""Optional web lookup (DuckDuckGo + Wikipedia). No API keys."""

from __future__ import annotations

import json
import re
import urllib.error
from pathlib import Path
import urllib.parse
import urllib.request
from typing import Any

_USER_AGENT = "RoPac/1.0 (local personal assistant)"
_TIMEOUT = 12
_MAX_CONTEXT = 4500


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _ddg_instant(query: str) -> list[str]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )
    try:
        data = _get_json(f"https://api.duckduckgo.com/?{params}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []

    parts: list[str] = []
    abstract = str(data.get("AbstractText") or "").strip()
    if abstract:
        src = str(data.get("AbstractSource") or "DuckDuckGo")
        parts.append(f"{src}: {abstract}")

    for topic in data.get("RelatedTopics") or []:
        if len(parts) >= 6:
            break
        if isinstance(topic, dict) and topic.get("Text"):
            parts.append(str(topic["Text"]).strip())
        elif isinstance(topic, dict):
            for sub in topic.get("Topics") or []:
                if isinstance(sub, dict) and sub.get("Text"):
                    parts.append(str(sub["Text"]).strip())
                    if len(parts) >= 6:
                        break
    return parts


def _wikipedia_extract(query: str) -> str:
    search_params = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": query,
            "limit": "1",
            "namespace": "0",
            "format": "json",
        }
    )
    try:
        search = _get_json(
            f"https://en.wikipedia.org/w/api.php?{search_params}"
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""

    if not isinstance(search, list) or len(search) < 2:
        return ""
    titles = search[1]
    if not titles:
        return ""
    title = titles[0]
    extract_params = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "titles": title,
            "format": "json",
        }
    )
    try:
        page_data = _get_json(
            f"https://en.wikipedia.org/w/api.php?{extract_params}"
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ""

    pages = page_data.get("query", {}).get("pages", {})
    for page in pages.values():
        extract = str(page.get("extract") or "").strip()
        if extract:
            return f"Wikipedia ({title}): {extract[:2000]}"
    return ""


def _should_search(message: str) -> bool:
    text = message.strip()
    if len(text) < 4:
        return False
    if re.match(r"(?i)^(remember|forget|train)\s+this\s*->", text):
        return False
    if re.match(r"(?i)^(?:please\s+remember|pls\s+remember)", text):
        return False
    return True


def fetch_web_context(query: str) -> str:
    """Return combined web snippets for injection into the system prompt."""
    if not _should_search(query):
        return ""

    snippets: list[str] = []
    wiki = _wikipedia_extract(query)
    if wiki:
        snippets.append(wiki)
    snippets.extend(_ddg_instant(query))

    if not snippets:
        return ""

    seen: set[str] = set()
    unique: list[str] = []
    for s in snippets:
        key = s[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)

    body = "\n\n".join(f"- {s}" for s in unique[:8])
    if len(body) > _MAX_CONTEXT:
        body = body[:_MAX_CONTEXT] + "\n…"
    return body


def persist_web_knowledge(
    query: str,
    web_context: str,
    assistant_reply: str,
    *,
    model: str,
    client: Any,
) -> list[str]:
    """Store web text in knowledge/ and add distilled facts to memory."""
    from assistant import add_facts
    from knowledge import extract_facts_from_document, ingest_file_from_text

    if not web_context.strip():
        return []

    safe = re.sub(r"[^\w\-]+", "_", query.strip())[:40] or "search"
    doc_name = f"web_{safe}.txt"
    combined = (
        f"Query: {query}\n\n"
        f"Web sources:\n{web_context}\n\n"
        f"Assistant summary:\n{assistant_reply[:4000]}"
    )
    ingest_file_from_text(Path(doc_name), combined)

    facts = extract_facts_from_document(combined, model, client)
    prefixed = [f"[web] {f}" for f in facts if f.strip()]
    return add_facts(prefixed)
