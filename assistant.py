"""
RoPac personal assistant — Ollama + persistent memory in ./data/
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from auth import check_owner_password, ensure_auth_store, verify_owner_password

ROPAC_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROPAC_ROOT / "config.json"
DATA_DIR = ROPAC_ROOT / "data"
MEMORY_PATH = DATA_DIR / "memory.json"
HISTORY_PATH = DATA_DIR / "chat_history.jsonl"
LEGACY_MEMORY = Path.home() / ".roPac" / "memory.json"


def load_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "model": "roPac",
        "base_model": "qwen2.5-coder:latest",
        "embed_model": "nomic-embed-text",
        "embeddings_enabled": True,
        "ollama_base_url": "http://localhost:11434/v1",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "gpt-4o-mini",
        "coder_model": "qwen2.5-coder:latest",
        "owner": "Rohit",
        "assistant_name": "RoPac",
        "encrypt_personal_data": True,
        "auto_encrypt_on_setup": True,
    }
    if CONFIG_PATH.exists():
        merged = {**defaults, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
        return merged
    return defaults


def _load_ropac_env_file() -> None:
    """Merge ropac.env into os.environ (CLI / bridge without Flutter env)."""
    env_path = ROPAC_ROOT / "ropac.env"
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq <= 0:
            continue
        key = line[:eq].strip()
        if key and key not in os.environ:
            os.environ[key] = line[eq + 1 :].strip()


_load_ropac_env_file()
_CONFIG = load_config()
OLLAMA_BASE_URL = str(_CONFIG["ollama_base_url"])
OPENAI_BASE_URL = str(_CONFIG.get("openai_base_url") or "https://api.openai.com/v1")
OPENAI_MODEL = str(_CONFIG.get("openai_model") or "gpt-4o-mini")
DEFAULT_MODEL = str(_CONFIG["model"])

CHAT_PROVIDERS = frozenset({"local", "openai"})

REMEMBER_PATTERN = re.compile(r"(?i)^remember\s+this\s*->\s*(.+)$")
PLEASE_REMEMBER_PATTERN = re.compile(
    r"(?i)^(?:please\s+remember|pls\s+remember|remember\s+that)\b[\s,:—-]*(?:that\s+)?(.*)$",
    re.DOTALL,
)
SAVE_PATTERN = re.compile(r"(?i)^save\s+this\s*->\s*(.+)$")
PLEASE_SAVE_PATTERN = re.compile(
    r"(?i)^(?:please\s+save|pls\s+save|save\s+that)\b[\s,:—-]*(?:that\s+)?(.*)$",
    re.DOTALL,
)
FORGET_PATTERN = re.compile(r"(?i)^forget\s+this\s*->\s*(.+)$")
DELETE_PATTERN = re.compile(r"(?i)^delete\s+this\s*->\s*(.+)$")
TRAIN_PATTERN = re.compile(r"(?i)^train\s+this\s*->\s*(.+)$")
# Missing "this" (e.g. save-> or delete->) — not a memory command.
BROKEN_MEMORY_ARROW_PATTERN = re.compile(
    r"(?i)^(save|delete|forget|remember|train)\s*->"
)
VALID_MEMORY_ARROW_PATTERN = re.compile(
    r"(?i)^(save|delete|forget|remember|train)\s+this\s*->\s*.+"
)

MEMORY_ARROW_FORMAT_HINT = (
    'Use save this-> <text> or delete this-> <text>. '
    'The word "this" is required (save-> and delete-> are not valid).'
)

EXTRACT_PROMPT = """You maintain long-term memory for a personal AI assistant.
Given the latest user message and assistant reply, extract ONLY new durable facts
about the owner or their long-term projects (preferences, stack, goals, stable personal notes).
Skip small talk, greetings, one-off questions, and ephemeral guest chat.
Do NOT repeat facts already in EXISTING FACTS.

EXISTING FACTS:
{existing}

Return a JSON array of strings, e.g. ["Prefers Kotlin over Java"].
If nothing new worth saving, return [].
Output JSON only, no markdown."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def default_memory() -> dict[str, Any]:
    return {
        "owner": _CONFIG.get("owner", "Rohit"),
        "assistant_name": _CONFIG.get("assistant_name", "RoPac"),
        "facts": [
            "Expert native Android (Kotlin, Jetpack Compose, MVVM) and Flutter.",
            "Explains coding, geopolitics, and Indian history clearly.",
        ],
        "updated_at": _utc_now(),
    }


def _migrate_legacy_memory() -> None:
    if MEMORY_PATH.exists() or not LEGACY_MEMORY.exists():
        return
    ensure_data_dir()
    shutil.copy2(LEGACY_MEMORY, MEMORY_PATH)


def load_memory(*, password: str | None = None) -> dict[str, Any]:
    from data_crypto import is_encryption_enabled, read_json_file

    ensure_data_dir()
    _migrate_legacy_memory()
    if not MEMORY_PATH.exists():
        mem = default_memory()
        if not is_encryption_enabled():
            save_memory(mem)
        return mem
    data = read_json_file(MEMORY_PATH, password=password)
    if data is None:
        mem = default_memory()
        mem["facts"] = []
        return mem
    if isinstance(data, list):
        data = {"facts": [str(x) for x in data if str(x).strip()]}
    if not isinstance(data, dict):
        data = default_memory()
    if "facts" not in data:
        data["facts"] = []
    return data


def save_memory(data: dict[str, Any], *, password: str | None = None) -> None:
    from data_crypto import is_encryption_enabled, write_json_file

    ensure_data_dir()
    data["updated_at"] = _utc_now()
    if is_encryption_enabled():
        write_json_file(MEMORY_PATH, data, password=password)
    else:
        MEMORY_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def add_facts(
    new_facts: list[str], *, owner_password: str | None = None
) -> list[str]:
    if not new_facts:
        return []
    memory = load_memory(password=owner_password)
    existing = {f.strip().lower() for f in memory.get("facts", [])}
    added: list[str] = []
    for fact in new_facts:
        text = fact.strip()
        if not text or text.lower() in existing:
            continue
        memory.setdefault("facts", []).append(text)
        existing.add(text.lower())
        added.append(text)
    if added:
        save_memory(memory, password=owner_password)
        try:
            from rag import sync_memory_embeddings

            sync_memory_embeddings(owner_password=owner_password)
        except Exception:
            pass
    return added


def parse_remember_command(user_message: str) -> str | None:
    """Return fact text if message is 'remember this-> ...', else None."""
    match = REMEMBER_PATTERN.match(user_message.strip())
    if not match:
        return None
    return match.group(1).strip()

def parse_save_command(user_message: str) -> str | None:
    """Return fact text if message is 'save this-> ...', else None."""
    match = SAVE_PATTERN.match(user_message.strip())
    if not match:
        return None
    return match.group(1).strip()


def parse_please_remember_command(user_message: str) -> tuple[bool, str]:
    """
    Detect owner 'please remember …' trigger.
    Returns (is_trigger, body). body is empty if only the trigger phrase was sent.
    """
    match = PLEASE_REMEMBER_PATTERN.match(user_message.strip())
    if not match:
        return False, ""
    return True, match.group(1).strip()

def parse_please_save_command(user_message: str) -> tuple[bool, str]:
    """
    Detect owner 'please save …' trigger.
    Returns (is_trigger, body). body is empty if only the trigger phrase was sent.
    """
    match = PLEASE_SAVE_PATTERN.match(user_message.strip())
    if not match:
        return False, ""
    return True, match.group(1).strip()


def _memory_save_allowed(
    owner_password: str | None, *, require_password: bool = False
) -> bool:
    from data_crypto import is_encryption_enabled, is_session_unlocked, vault_unlock

    if not is_encryption_enabled():
        return True
    if is_session_unlocked():
        return True
    if owner_password is not None:
        if not verify_owner_password(owner_password):
            return False
        vault_unlock(owner_password)
        return True
    if require_password:
        return False
    return False


def remember_explicit(fact: str, password: str | None = None) -> tuple[str, list[str]]:
    from data_crypto import vault_unlock

    if not fact:
        return "Nothing to save. Example: remember this-> I prefer Jetpack Compose", []
    if not _memory_save_allowed(password, require_password=True):
        return "Remember cancelled — owner password required.", []
    added = add_facts([fact], owner_password=password)
    if added:
        return f"Saved to memory: {added[0]}", added
    return f"Already in memory: {fact}", []


def parse_forget_command(user_message: str) -> str | None:
    match = FORGET_PATTERN.match(user_message.strip())
    if not match:
        return None
    return match.group(1).strip()

def parse_delete_command(user_message: str) -> str | None:
    match = DELETE_PATTERN.match(user_message.strip())
    if not match:
        return None
    return match.group(1).strip()


def _fact_matches_forget_query(fact: str, query: str) -> bool:
    """Avoid accidental deletes (e.g. query 'eer' matching 'Engineer')."""
    q = query.strip().lower()
    if not q:
        return False
    f = fact.lower()
    if f == q:
        return True
    if len(q) < 4:
        return bool(re.search(rf"\b{re.escape(q)}\b", f))
    return q in f or f in q


def remove_facts(query: str, *, owner_password: str | None = None) -> list[str]:
    if not query:
        return []
    memory = load_memory(password=owner_password)
    facts: list[str] = memory.get("facts", [])
    kept: list[str] = []
    removed: list[str] = []
    for fact in facts:
        if _fact_matches_forget_query(fact, query):
            removed.append(fact)
        else:
            kept.append(fact)
    if removed:
        memory["facts"] = kept
        save_memory(memory, password=owner_password)
        try:
            from rag import sync_memory_embeddings

            sync_memory_embeddings(owner_password=owner_password)
        except Exception:
            pass
    return removed


def parse_train_command(user_message: str) -> str | None:
    match = TRAIN_PATTERN.match(user_message.strip())
    if not match:
        return None
    return match.group(1).strip().strip('"').strip("'")


def forget_all_trained(
    *, owner_password: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Clear trained RAG documents and remove their extracted memory facts."""
    from data_crypto import vault_unlock
    from knowledge import clear_all_trained_documents

    if owner_password:
        vault_unlock(owner_password)

    result = clear_all_trained_documents(owner_password=owner_password)
    docs_removed = int(result.get("documents_removed") or 0)
    source_names = list(result.get("source_names") or [])

    facts_removed = 0
    if source_names:
        memory = load_memory(password=owner_password)
        facts: list[str] = memory.get("facts", [])
        prefixes = [f"[{name}]" for name in source_names]
        kept: list[str] = []
        for fact in facts:
            if any(str(fact).startswith(prefix) for prefix in prefixes):
                facts_removed += 1
            else:
                kept.append(fact)
        if facts_removed:
            memory["facts"] = kept
            save_memory(memory, password=owner_password)
            try:
                from rag import sync_memory_embeddings

                sync_memory_embeddings(owner_password=owner_password)
            except Exception:
                pass

    if docs_removed == 0:
        return "No trained files to forget.", result

    msg = (
        f"Forgot {docs_removed} trained file(s).\n"
        f"  RAG chunks removed: {result.get('files_deleted', 0)}\n"
        f"  Memory facts removed: {facts_removed}"
    )
    result["facts_removed"] = facts_removed
    return msg, result


def hard_reset_local_data(
    *, owner_password: str | None = None
) -> tuple[str, dict[str, Any]]:
    """Wipe memory facts, RAG documents, embeddings, sessions, and chat history."""
    from data_crypto import vault_lock, vault_unlock
    from knowledge import KNOWLEDGE_DIR, clear_all_trained_documents

    if not owner_password:
        raise ValueError("Owner password required")
    if not verify_owner_password(owner_password):
        raise ValueError("Incorrect owner password")

    vault_unlock(owner_password)

    rag_result = clear_all_trained_documents(owner_password=owner_password)
    docs_removed = int(rag_result.get("documents_removed") or 0)
    files_deleted = int(rag_result.get("files_deleted") or 0)

    memory_embed = KNOWLEDGE_DIR / "memory.embeddings.json"
    if memory_embed.is_file():
        memory_embed.unlink()
        files_deleted += 1

    sessions_dir = KNOWLEDGE_DIR / "sessions"
    sessions_removed = 0
    if sessions_dir.is_dir():
        for path in sessions_dir.glob("*.json"):
            path.unlink()
            sessions_removed += 1

    memory = load_memory(password=owner_password)
    facts_removed = len(memory.get("facts", []))
    memory["facts"] = []
    save_memory(memory, password=owner_password)

    history_cleared = False
    if HISTORY_PATH.exists():
        HISTORY_PATH.write_text("", encoding="utf-8")
        history_cleared = True

    vault_lock()
    vault_unlock(owner_password)

    msg = (
        "Hard reset complete.\n"
        f"  Memory facts removed: {facts_removed}\n"
        f"  Trained documents removed: {docs_removed}\n"
        f"  RAG files deleted: {files_deleted}\n"
        f"  Chat attachment sessions removed: {sessions_removed}\n"
        f"  Chat history cleared: {'yes' if history_cleared else 'no'}"
    )
    return msg, {
        "ok": True,
        "facts_removed": facts_removed,
        "documents_removed": docs_removed,
        "files_deleted": files_deleted,
        "sessions_removed": sessions_removed,
        "chat_history_cleared": history_cleared,
    }


def train_explicit(
    path_str: str,
    *,
    model: str = DEFAULT_MODEL,
    owner_password: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if not path_str:
        return "Usage: train this-> /full/path/to/file.pdf", {}
    try:
        from data_crypto import vault_unlock
        from knowledge import train_file

        if owner_password:
            vault_unlock(owner_password)
        payload = train_file(
            path_str,
            model=model,
            client=get_client(),
            owner_password=owner_password,
        )
        name = payload.get("source_name", Path(path_str).name)
        extracted_facts = [f"[{name}] {f}" for f in payload.get("extracted_facts", [])]

        added: list[str] = []
        if extracted_facts and _memory_save_allowed(owner_password):
            added = add_facts(extracted_facts, owner_password=owner_password)

        payload["facts_added"] = added
        embed_note = (
            "yes"
            if payload.get("embeddings_stored")
            else "no (keyword search until reindex)"
        )
        kind = payload.get("source_kind", "document")
        kind_note = (
            "image (vision model → text → chunks)"
            if kind == "image"
            else "document"
        )
        msg = (
            f"Trained on: {payload['source_name']}\n"
            f"  Type: {kind_note}\n"
            f"  Chunks stored: {payload['chunk_count']}\n"
            f"  Embeddings stored: {embed_note}\n"
            f"  Characters: {payload['char_count']}\n"
            f"  Facts added to memory: {len(added)}"
        )

        if extracted_facts and not added:
            msg += "\n  Owner password required to save extracted facts to memory."

        if added:
            msg += "\n  " + "\n  ".join(f"- {a}" for a in added[:8])
            if len(added) > 8:
                msg += f"\n  ... and {len(added) - 8} more"

        return msg, payload
    except FileNotFoundError:
        return f"File not found: {path_str}", {}
    except ImportError as e:
        return f"{e}", {}
    except Exception as e:
        return f"Training failed: {e}", {}


def forget_explicit(query: str, password: str | None = None) -> tuple[str, list[str]]:
    from data_crypto import vault_unlock

    if not query:
        return "Nothing to forget. Example: forget this-> my dog", []
    if not _memory_save_allowed(password, require_password=True):
        return "Forget cancelled — owner password required.", []
    removed = remove_facts(query, owner_password=password)
    if removed:
        lines = "\n".join(f"  - {f}" for f in removed)
        return f"Removed {len(removed)} fact(s):\n{lines}", removed
    return f"No memory matched: {query}", []


def memory_block() -> str:
    memory = load_memory()
    owner = memory.get("owner", "the owner")
    facts = memory.get("facts", [])
    lines = [
        f"Machine owner (built RoPac): {owner}",
        "Profile facts (about the owner / their projects — NOT about whoever is chatting now):",
    ]
    lines.extend(f"- {f}" for f in facts)
    return "\n".join(lines)


def build_system_prompt(
    user_query: str = "",
    *,
    attachment_context: str = "",
    has_chat_attachments: bool = False,
    attachment_paths: list[str] | None = None,
) -> str:
    from rag import format_rag_for_prompt, owner_profile_preamble, retrieve_all_context

    owner = _CONFIG.get("owner", "Rohit")
    base = f"""You are RoPac, a local AI assistant on {owner}'s computer.

WHO IS CHATTING (critical):
- Anyone may use this chat (guests, friends, colleagues). They are NOT automatically {owner}.
- Do NOT call the person "{owner}" or "owner" unless they clearly say they are {owner}.
- If they say they are not {owner}, believe them. Ask their name if polite; do not insist.
- Owner background below is private — use only when relevant to the question.

MEMORY RULES (critical):
- Do NOT update, save, or offer to update long-term memory from normal chat.
- Do NOT say "I will update my memory" or "let me fix my notes" for casual corrections.
- Persistent memory changes ONLY when the owner uses password-protected commands:
  "save this->", "delete this->", Train tab, or a message starting with "please save …".
- If a guest shares personal info, answer in the thread only — do not treat it as saved forever.

LANGUAGE:
- Hindi / Hinglish / English as the user uses. Hindi replies in Devanagari when appropriate.
- Tone: friendly, clear, modern Indian English or Hindi.

OWNER PROFILE (not the current user unless they say so):
{owner_profile_preamble()}
"""
    paths = attachment_paths or []
    rag_sections = retrieve_all_context(
        user_query,
        attachment_paths=paths if paths else None,
        has_chat_attachments=has_chat_attachments,
    )
    rag_text = format_rag_for_prompt(rag_sections)
    if rag_text.strip():
        base += f"""

{rag_text.strip()}
"""
    elif attachment_context.strip():
        base += f"""

{attachment_context.strip()}
"""

    needs_attachment_fallback = (has_chat_attachments or bool(paths)) and not (
        rag_sections.get("attachments") or attachment_context.strip()
    )
    if needs_attachment_fallback:
        from chat_attachments import build_attachment_context

        fallback, meta = build_attachment_context(paths)
        if fallback.strip():
            base += f"""

{fallback.strip()}
"""
        elif meta:
            unreadable = ", ".join(
                str(m.get("name") or "file")
                for m in meta
                if not m.get("ok")
            )
            if unreadable:
                base += f"""

ATTACHED FILES: User attached {unreadable}, but RoPac could not read them.
Say what failed (missing file, permissions, or unsupported format) and ask them to re-attach.
"""

    if has_chat_attachments or paths:
        from log_analysis import build_log_analysis_context, is_log_path

        log_paths = [p for p in paths if is_log_path(p)]
        if log_paths:
            log_report = build_log_analysis_context(log_paths, query=user_query)
            if log_report.strip():
                base += f"""

{log_report.strip()}
"""

        has_file_content = (
            "ATTACHED FILES" in base
            or "ATTACHED FILES (retrieved" in base
            or bool(rag_sections.get("attachments"))
            or bool(log_paths)
        )
        if has_file_content:
            base += """

ATTACHMENT RULES (critical):
- File content and/or LOG ANALYSIS is already in this prompt. Do NOT ask the user to attach again.
- Answer the user's question directly using LOG ANALYSIS numbers (orders placed, failures, payments, issues).
- For "total orders" use "Total orders placed (unique IDs)" from LOG ANALYSIS.
- For failures/issues use ISSUES / ERRORS and order failure counts from LOG ANALYSIS.
- Never say "let me scan", "please wait", or "allow me a moment".
- Give counts, order IDs, and findings in this reply — do not defer to a follow-up.
"""
    return base


def normalize_chat_provider(value: Any = None, *, use_server_model: bool = False) -> str:
    """local (default) or openai."""
    if use_server_model:
        return "local"
    raw = str(value or "local").strip().lower()
    if raw in ("groq", "free_server", "coder"):
        return "local"
    if raw in CHAT_PROVIDERS:
        return raw
    return "local"


def resolve_openai_api_key(override: str | None = None) -> str:
    """Runtime only — passed per chat request from the UI, never read from disk."""
    return (override or "").strip()


def resolve_chat_model(*, chat_provider: str = "local") -> str:
    provider = normalize_chat_provider(chat_provider)
    if provider == "openai":
        return OPENAI_MODEL
    return DEFAULT_MODEL


def chat_completion_kwargs(*, chat_provider: str = "local") -> dict[str, Any]:
    """Avoid local models stopping mid-answer on long log/file replies."""
    _ = normalize_chat_provider(chat_provider)
    return {"max_tokens": 4096}


def get_client(
    *,
    chat_provider: str = "local",
    openai_api_key_override: str | None = None,
) -> OpenAI:
    provider = normalize_chat_provider(chat_provider)
    if provider == "openai":
        api_key = resolve_openai_api_key(openai_api_key_override)
        if not api_key:
            raise ValueError(
                "OpenAI API key required. Enter your key when you send a message."
            )
        return OpenAI(base_url=OPENAI_BASE_URL, api_key=api_key)
    return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")


def append_history(role: str, content: str) -> None:
    ensure_data_dir()
    row = {"ts": _utc_now(), "role": role, "content": content}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _parse_facts_json(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        parsed = json.loads(match.group())
    if isinstance(parsed, list):
        return [str(x) for x in parsed if str(x).strip()]
    return []


def memory_arrow_format_error(user_message: str) -> str | None:
    """Return help text if user typed save-> / delete-> without 'this'."""
    text = user_message.strip()
    if not text:
        return None
    if VALID_MEMORY_ARROW_PATTERN.match(text) or _is_memory_command(text):
        return None
    if BROKEN_MEMORY_ARROW_PATTERN.match(text):
        return MEMORY_ARROW_FORMAT_HINT
    return None


def _is_memory_command(user_message: str) -> bool:
    text = user_message.strip()
    if not text:
        return False
    please_remember, _ = parse_please_remember_command(text)
    please_save, _ = parse_please_save_command(text)
    return (
        please_remember
        or please_save
        or parse_save_command(text) is not None
        or parse_remember_command(text) is not None
        or parse_delete_command(text) is not None
        or parse_forget_command(text) is not None
        or parse_train_command(text) is not None
    )


def is_memory_write_command(user_message: str) -> bool:
    """save/delete/train or please save/remember."""
    if memory_arrow_format_error(user_message):
        return False
    return _is_memory_command(user_message)


_PERSONAL_VAULT_HINTS = re.compile(
    r"(?i)(?:\b("
    r"about me|who am i|what do you know about me|my profile|my memory|my facts|"
    r"my resume|my cv|my phone|my email|my address|my name is|"
    r"trained documents?|knowledge base|from my files?|"
    r"save this|delete this|forget this|remember this|train this|"
    r"please save|please remember"
    r")\b|\bmy\s+\w+)"
)


def needs_personal_vault_for_message(user_message: str) -> bool:
    """
    True when chat should unlock encrypted personal data before replying.
    Casual guest chat can stay locked; owner-specific questions and memory writes unlock.
    """
    from data_crypto import is_encryption_enabled, is_session_unlocked

    if is_memory_write_command(user_message):
        return True
    if not is_encryption_enabled() or is_session_unlocked():
        return False
    text = user_message.strip()
    if not text:
        return False
    return bool(_PERSONAL_VAULT_HINTS.search(text))


def _memory_suggestions_enabled(*, auto_learn: bool = True) -> bool:
    from settings import load_settings

    if not auto_learn:
        return False
    return bool(load_settings().get("memory_suggestions_enabled", True))


def propose_new_facts(
    user: str,
    assistant: str,
    model: str = DEFAULT_MODEL,
    *,
    owner_password: str | None = None,
) -> list[str]:
    from data_crypto import require_unlocked_session

    ok, _ = require_unlocked_session(password=owner_password)
    if not ok:
        return []

    memory = load_memory(password=owner_password)
    existing = {f.strip().lower() for f in memory.get("facts", [])}
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT.format(existing=existing)},
            {"role": "user", "content": f"User:\n{user}\n\nAssistant:\n{assistant}"},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content or "[]"
    candidates = _parse_facts_json(raw)
    return [
        fact.strip()
        for fact in candidates
        if fact.strip() and fact.strip().lower() not in existing
    ]


def save_memory_suggestions(
    facts: list[str], password: str | None = None
) -> tuple[str, list[str]]:
    cleaned = [f.strip() for f in facts if f and f.strip()]
    if not cleaned:
        return "Nothing to save.", []
    if not _memory_save_allowed(password, require_password=True):
        return "Incorrect owner password.", []
    added = add_facts(cleaned, owner_password=password)
    if added:
        return f"Saved {len(added)} fact(s) to memory.", added
    return "Those facts are already in memory.", []


def extract_new_facts(
    user: str,
    assistant: str,
    model: str = DEFAULT_MODEL,
    *,
    owner_password: str | None = None,
) -> list[str]:
    proposed = propose_new_facts(
        user,
        assistant,
        model=model,
        owner_password=owner_password,
    )
    return add_facts(proposed, owner_password=owner_password)


def _command_reply_if_any(
    user_message: str,
    history: list[dict[str, str]] | None,
    *,
    model: str = DEFAULT_MODEL,
    owner_password: str | None = None,
) -> str | None:
    """Instant replies for memory update commands."""
    format_err = memory_arrow_format_error(user_message)
    if format_err:
        append_history("user", user_message)
        append_history("assistant", format_err)
        return format_err

    please_remember, please_remember_body = parse_please_remember_command(
        user_message,
    )
    please_save, please_save_body = parse_please_save_command(user_message)

    if (please_remember or please_save) and (please_remember_body or please_save_body):
        body = please_remember_body or please_save_body
        reply, _ = remember_explicit(body, password=owner_password)
        append_history("user", user_message)
        append_history("assistant", reply)
        return reply

    save_fact = parse_save_command(user_message)
    if save_fact is not None:
        reply, _ = remember_explicit(save_fact, password=owner_password)
        append_history("user", user_message)
        append_history("assistant", reply)
        return reply

    remember_fact = parse_remember_command(user_message)
    if remember_fact is not None:
        reply, _ = remember_explicit(remember_fact, password=owner_password)
        append_history("user", user_message)
        append_history("assistant", reply)
        return reply

    delete_query = parse_delete_command(user_message)
    if delete_query is not None:
        reply, _ = forget_explicit(delete_query, password=owner_password)
        append_history("user", user_message)
        append_history("assistant", reply)
        return reply

    forget_query = parse_forget_command(user_message)
    if forget_query is not None:
        reply, _ = forget_explicit(forget_query, password=owner_password)
        append_history("user", user_message)
        append_history("assistant", reply)
        return reply

    train_path = parse_train_command(user_message)
    if train_path is not None:
        reply, _ = train_explicit(
            train_path,
            model=model,
            owner_password=owner_password,
        )
        append_history("user", user_message)
        append_history("assistant", reply)
        return reply

    return None


def _normalize_attachment_paths(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    out: list[str] = []
    for p in paths:
        text = str(p).strip()
        if text and text not in out:
            out.append(text)
    return out


def _build_chat_messages(
    user_message: str,
    history: list[dict[str, str]] | None,
    *,
    use_internet: bool = False,
    chat_provider: str = "local",
    openai_api_key_override: str | None = None,
    attachment_paths: list[str] | None = None,
) -> tuple[list[dict[str, str]], str, OpenAI]:
    client = get_client(
        chat_provider=chat_provider,
        openai_api_key_override=openai_api_key_override,
    )
    paths = _normalize_attachment_paths(attachment_paths)
    attachment_context = ""
    use_attachment_rag = False
    if paths:
        from rag import load_rag_config

        use_attachment_rag = bool(
            load_rag_config().get("rag_attachment_rag_enabled", True)
        )
        if not use_attachment_rag:
            from chat_attachments import build_attachment_context

            attachment_context, _ = build_attachment_context(paths)
    system = build_system_prompt(
        user_message,
        attachment_context=attachment_context,
        has_chat_attachments=bool(paths),
        attachment_paths=paths if use_attachment_rag else [],
    )
    web_context = ""
    if use_internet:
        from web_research import fetch_web_context

        web_context = fetch_web_context(user_message)
        if web_context:
            system += f"""

LIVE WEB CONTEXT (user enabled Internet mode — cite when useful, note if unsure):
{web_context}
"""

    user_content = user_message
    if paths:
        from pathlib import Path

        names = ", ".join(Path(p).name for p in paths)
        if names and names not in user_message:
            user_content = f"[Attached files: {names}]\n\n{user_message}".strip()

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *(history or []),
        {"role": "user", "content": user_content},
    ]
    return messages, web_context, client


def _finalize_chat_reply(
    user_message: str,
    reply: str,
    history: list[dict[str, str]] | None,
    *,
    model: str = DEFAULT_MODEL,
    auto_learn: bool = True,
    owner_password: str | None = None,
    use_internet: bool = False,
    web_context: str = "",
    client: OpenAI | None = None,
) -> tuple[str, list[str]]:
    please_remember, _ = parse_please_remember_command(user_message)
    please_save, _ = parse_please_save_command(user_message)
    web_note = ""
    if use_internet and web_context:
        from web_research import persist_web_knowledge

        if client is None:
            client = get_client(chat_provider="local")
        added = persist_web_knowledge(
            user_message,
            web_context,
            reply,
            model=model,
            client=client,
        )
        if added:
            web_note = f"\n\n[Web knowledge saved locally: {len(added)} fact(s)]"

    append_history("user", user_message)
    append_history("assistant", reply)

    memory_note = ""
    suggestions: list[str] = []
    if please_remember or please_save:
        if _memory_save_allowed(owner_password):
            added = extract_new_facts(
                user_message, reply, model=model, owner_password=owner_password
            )
            if added:
                memory_note = f"\n\n[Saved to memory: {', '.join(added)}]"
        else:
            memory_note = "\n\n[Memory not saved — owner password required.]"
    elif _memory_suggestions_enabled(auto_learn=auto_learn) and not _is_memory_command(
        user_message
    ):
        if _memory_save_allowed(owner_password):
            proposed = propose_new_facts(
                user_message,
                reply,
                model=model,
                owner_password=owner_password,
            )
            if proposed:
                add_facts(proposed, owner_password=owner_password)

    return reply + memory_note + web_note, suggestions


def chat_stream(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    auto_learn: bool = True,
    owner_password: str | None = None,
    use_internet: bool = False,
    chat_provider: str = "local",
    openai_api_key_override: str | None = None,
    attachment_paths: list[str] | None = None,
    stream_meta: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Yield reply text as Ollama generates it (for live UI streaming)."""
    chat_model = resolve_chat_model(chat_provider=chat_provider)
    instant = _command_reply_if_any(
        user_message,
        history,
        model=model,
        owner_password=owner_password,
    )
    if instant is not None:
        if stream_meta is not None:
            stream_meta["memory_suggestions"] = []
        yield instant
        return

    messages, web_context, client = _build_chat_messages(
        user_message,
        history,
        use_internet=use_internet,
        chat_provider=chat_provider,
        openai_api_key_override=openai_api_key_override,
        attachment_paths=attachment_paths,
    )
    stream = client.chat.completions.create(
        model=chat_model,
        messages=messages,
        stream=True,
        **chat_completion_kwargs(chat_provider=chat_provider),
    )
    parts: list[str] = []
    for event in stream:
        delta = event.choices[0].delta.content or ""
        if not delta:
            continue
        parts.append(delta)
        yield delta

    reply = "".join(parts)
    full, suggestions = _finalize_chat_reply(
        user_message,
        reply,
        history,
        model=model,
        auto_learn=auto_learn,
        owner_password=owner_password,
        use_internet=use_internet,
        web_context=web_context,
        client=get_client(chat_provider="local"),
    )
    suffix = full[len(reply) :]
    if suffix:
        yield suffix
    if stream_meta is not None:
        stream_meta["memory_suggestions"] = suggestions


def chat(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    auto_learn: bool = True,
    owner_password: str | None = None,
    use_internet: bool = False,
    chat_provider: str = "local",
    openai_api_key_override: str | None = None,
    attachment_paths: list[str] | None = None,
) -> tuple[str, list[dict[str, str]], list[str]]:
    chat_model = resolve_chat_model(chat_provider=chat_provider)
    instant = _command_reply_if_any(
        user_message,
        history,
        model=model,
        owner_password=owner_password,
    )
    if instant is not None:
        updated = [
            *(history or []),
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": instant},
        ]
        return instant, updated, []

    messages, web_context, client = _build_chat_messages(
        user_message,
        history,
        use_internet=use_internet,
        chat_provider=chat_provider,
        openai_api_key_override=openai_api_key_override,
        attachment_paths=attachment_paths,
    )
    response = client.chat.completions.create(
        model=chat_model,
        messages=messages,
        **chat_completion_kwargs(chat_provider=chat_provider),
    )
    reply = response.choices[0].message.content or ""
    full, suggestions = _finalize_chat_reply(
        user_message,
        reply,
        history,
        model=model,
        auto_learn=auto_learn,
        owner_password=owner_password,
        use_internet=use_internet,
        web_context=web_context,
        client=get_client(chat_provider="local"),
    )
    updated_history = [
        *(history or []),
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply},
    ]
    return full, updated_history, suggestions


def show_memory() -> None:
    print(memory_block())
    print(f"\nMemory file: {MEMORY_PATH}")


def show_sources() -> None:
    from knowledge import list_documents

    docs = list_documents()
    if not docs:
        print("No trained files yet. Use: train this-> /path/to/file")
        return
    print("Trained files:")
    for d in docs:
        print(
            f"  - {d.get('source_name')} "
            f"({d.get('chunk_count', 0)} chunks) "
            f"[{d.get('trained_at', '')[:10]}]"
        )
    print(f"\nKnowledge store: {DATA_DIR / 'knowledge'}")


def repl(model: str = DEFAULT_MODEL, *, auto_learn: bool = False) -> None:
    ensure_auth_store()
    print(f"RoPac ({model}) — folder: {ROPAC_ROOT}")
    print("Commands: /memory | /sources | quit")
    print("Learn:  save this-> <fact>  (owner password required)")
    print("Train:  train this-> /path/to/file.pdf")
    print("Forget: delete this-> <text>  (owner password required)\n")
    history: list[dict[str, str]] = []
    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user:
            continue
        if user.lower() in {"quit", "exit", "q"}:
            break
        if user.lower() == "/memory":
            show_memory()
            continue
        if user.lower() == "/sources":
            show_sources()
            continue
        reply, history, suggestions = chat(
            user, history, model=model, auto_learn=auto_learn
        )
        print(f"\nRoPac: {reply}\n")
        if suggestions:
            print("Suggested facts to save:")
            for i, fact in enumerate(suggestions, 1):
                print(f"  {i}. {fact}")
            print("Save with: save this-> <fact>  (owner password required)\n")


def main() -> None:
    import argparse

    ensure_auth_store()

    parser = argparse.ArgumentParser(
        description="RoPac — portable personal Ollama assistant",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--show-memory", action="store_true")
    parser.add_argument("--message", "-m", help="Single message, then exit")
    parser.add_argument("--no-auto-learn", action="store_true")
    parser.add_argument("--train", help="Train from file path, then exit")
    parser.add_argument("--sources", action="store_true", help="List trained files")
    args = parser.parse_args()

    if args.sources:
        show_sources()
    elif args.train:
        text, _ = train_explicit(args.train, model=args.model)
        print(text)
    elif args.show_memory:
        show_memory()
    elif args.message:
        text, _, _ = chat(
            args.message,
            model=args.model,
            auto_learn=not args.no_auto_learn,
        )
        print(text)
    else:
        repl(model=args.model, auto_learn=not args.no_auto_learn)


if __name__ == "__main__":
    main()
