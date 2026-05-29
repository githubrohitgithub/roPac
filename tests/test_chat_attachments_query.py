"""Session attachments: full-file reads and chunked fallback."""

from pathlib import Path

import assistant as assistant_mod
from assistant import (
    build_session_attachment_context,
    clear_session_attachments,
    resolve_chat_attachment_paths,
)
from chat_attachments import (
    build_query_attachment_context,
    grep_session_for_query,
    query_search_terms,
    session_attachment_mode,
)


def test_full_mode_includes_complete_file(tmp_path):
    log_file = tmp_path / "kiosk.log"
    log_file.write_text("line one\nline two\nPorridge in cart\n", encoding="utf-8")

    assert session_attachment_mode([str(log_file)]) == "full"
    ctx = build_query_attachment_context([str(log_file)], query="Porridge in cart")
    assert "complete content" in ctx
    assert "Porridge in cart" in ctx


def test_chunked_mode_when_files_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "chat_attachments.load_attachment_config",
        lambda: {
            "chat_session_max_files": 30,
            "chat_model_context_tokens": 4096,
            "chat_context_reserved_tokens": 10240,
            "chat_context_chars_per_token": 3.5,
            "chat_session_full_context_ratio": 0.85,
        },
    )
    big = tmp_path / "big.log"
    big.write_text("x" * 15000, encoding="utf-8")
    assert session_attachment_mode([str(big)]) == "chunked"
    ctx = build_query_attachment_context([str(big)], query="find data")
    assert "ATTACHED FILES below" in ctx


def test_query_search_terms_extracts_user_words():
    phrases, tokens = query_search_terms('find "Hola Pollo Meal Deal" in logs')
    assert "Hola Pollo Meal Deal" in phrases
    assert "hola" in tokens or "pollo" in tokens


def test_follow_up_keeps_paths(tmp_path, monkeypatch):
    session_file = tmp_path / "chat_session_attachments.json"
    monkeypatch.setattr(assistant_mod, "CHAT_SESSION_ATTACHMENTS_PATH", session_file)

    log_file = tmp_path / "kiosk.log"
    log_file.write_text("Porridge in cart\n", encoding="utf-8")
    path = str(log_file)

    clear_session_attachments()
    first = resolve_chat_attachment_paths([path], fresh_session=True)
    follow_up = resolve_chat_attachment_paths([], fresh_session=False)
    assert follow_up == first

    session_ctx = build_session_attachment_context(follow_up, query="cart items")
    assert "Porridge" in session_ctx

    clear_session_attachments()


def test_build_system_prompt_keeps_full_file_when_memory_rag_hits(tmp_path, monkeypatch):
    log_file = tmp_path / "kiosk.log"
    log_file.write_text("line one\nHola Pollo Meal Deal\n", encoding="utf-8")
    path = str(log_file)
    ctx = build_query_attachment_context([path], query="Hola Pollo Meal Deal")

    def fake_retrieve_all_context(*_args, **_kwargs):
        return {"memory": "Owner often attaches kiosk.log for food-order checks."}

    monkeypatch.setattr("rag.retrieve_all_context", fake_retrieve_all_context)

    from assistant import build_system_prompt

    prompt = build_system_prompt(
        "can u see food name Hola Pollo Meal Deal",
        attachment_context=ctx,
        has_chat_attachments=True,
        attachment_paths=[path],
    )
    assert "Hola Pollo Meal Deal" in prompt
    assert "SESSION ATTACHMENTS" in prompt


def test_grep_session_for_query_reports_clean_files(tmp_path):
    clean = tmp_path / "log_08_00.log"
    clean.write_text("Info: started\nInfo: sync ok\n", encoding="utf-8")
    noisy = tmp_path / "log_11.log"
    noisy.write_text("Info: ok\nHola Pollo Meal Deal ordered\n", encoding="utf-8")

    report = grep_session_for_query([str(clean), str(noisy)], "Hola Pollo Meal Deal")
    assert "log_11.log" in report
    assert "Hola Pollo Meal Deal" in report
    assert "log_08_00.log" in report
    assert "NO lines matching" in report
