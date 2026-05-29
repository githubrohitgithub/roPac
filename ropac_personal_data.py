"""
Personal data encryption: enable, migrate, and app-launch setup.
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path
from typing import Any

from auth import ensure_auth_store, verify_owner_password
from assistant import MEMORY_PATH, default_memory, ensure_data_dir, load_config
from data_crypto import (
    DATA_DIR,
    KNOWLEDGE_DIR,
    WRAPPED_KEY_PATH,
    crypto_status,
    encrypt_json,
    is_encrypted_envelope,
    is_encryption_enabled,
    is_session_unlocked,
    migrate_plain_file,
    save_crypto_meta,
    vault_unlock,
    _save_wrapped_key,
)

INDEX_PATH = KNOWLEDGE_DIR / "index.json"


def crypto_deps_ok() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def migration_status() -> dict[str, Any]:
    """Portable folder / new Mac migration hints."""
    cfg = load_config()
    has_memory = MEMORY_PATH.is_file()
    has_wrapped = WRAPPED_KEY_PATH.is_file()
    docs = 0
    if INDEX_PATH.is_file():
        try:
            raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if is_encrypted_envelope(raw):
                docs = -1
            else:
                docs = len(raw.get("documents", []))
        except Exception:
            docs = 0
    return {
        "portable_data_present": has_memory or KNOWLEDGE_DIR.is_dir(),
        "encryption_enabled": is_encryption_enabled(),
        "wrapped_key_present": has_wrapped,
        "auto_encrypt_on_setup": bool(cfg.get("auto_encrypt_on_setup", True)),
        "encrypt_personal_data": bool(cfg.get("encrypt_personal_data", True)),
        "trained_documents": docs,
        "migration_hint": (
            "Copied folder detected. Run ./install.sh on this Mac, then unlock "
            "with your owner password in the app."
            if has_wrapped
            else None
        ),
    }


def enable_encryption(password: str) -> tuple[bool, str]:
    """Encrypt memory + knowledge; unlock session for immediate use."""
    ensure_auth_store()
    if not crypto_deps_ok():
        return False, "Install cryptography: pip install -r requirements.txt"

    if not password:
        return False, "Owner password required"

    if not verify_owner_password(password):
        return False, "Incorrect owner password"

    if is_encryption_enabled():
        ok, msg = vault_unlock(password)
        return ok, msg if ok else "Encryption on but unlock failed"

    data_key = secrets.token_bytes(32)
    salt = secrets.token_bytes(32)
    save_crypto_meta(
        {
            "enabled": True,
            "algorithm": "aes-256-gcm",
            "kdf": "pbkdf2-sha256",
            "kdf_iterations": 600_000,
            "kdf_salt": base64.b64encode(salt).decode("ascii"),
        }
    )
    _save_wrapped_key(data_key, password)

    ensure_data_dir()
    if MEMORY_PATH.exists():
        migrate_plain_file(MEMORY_PATH, data_key)
    else:
        MEMORY_PATH.write_text(
            json.dumps(encrypt_json(default_memory(), data_key), indent=2) + "\n",
            encoding="utf-8",
        )

    if INDEX_PATH.exists():
        migrate_plain_file(INDEX_PATH, data_key)

    if KNOWLEDGE_DIR.is_dir():
        for doc_path in KNOWLEDGE_DIR.glob("*.json"):
            if doc_path.name == "index.json":
                continue
            migrate_plain_file(doc_path, data_key)

    ok, msg = vault_unlock(password)
    if not ok:
        return True, "Encrypted at rest. Unlock failed: " + msg
    return True, "Personal data is encrypted and unlocked for this session"


def personal_data_setup(password: str | None = None) -> dict[str, Any]:
    """
    Called on app launch: ensure deps, auto-enable if configured, unlock session.
  """
    cfg = load_config()
    mig = migration_status()
    status = crypto_status()
    out: dict[str, Any] = {
        "deps_ok": crypto_deps_ok(),
        "migration": mig,
        "crypto": status,
        "needs_enable": False,
        "needs_unlock": False,
        "unlocked": status.get("unlocked", True),
        "message": "",
    }

    if not out["deps_ok"]:
        out["message"] = "Run ./install.sh in the RoPac folder (installs cryptography)."
        return out

    want_encrypt = bool(cfg.get("encrypt_personal_data", True))

    if want_encrypt and not is_encryption_enabled():
        out["needs_enable"] = True
        if password:
            ok, msg = enable_encryption(password)
            out["message"] = msg
            if ok:
                out["needs_enable"] = False
                out["crypto"] = crypto_status()
                out["unlocked"] = is_session_unlocked()
            return out
        out["message"] = "Enable encryption with your owner password."
        return out

    if is_encryption_enabled() and not is_session_unlocked():
        out["needs_unlock"] = True
        if password:
            ok, msg = vault_unlock(password)
            out["message"] = msg
            out["needs_unlock"] = not ok
            out["unlocked"] = ok
            out["crypto"] = crypto_status()
            return out
        out["message"] = "Enter owner password to access personal data."
        return out

    out["unlocked"] = True
    out["message"] = "Personal data ready"
    return out


def setup_install_encrypt(password: str | None) -> tuple[int, str]:
    """Non-interactive setup.sh helper."""
    cfg = load_config()
    if not cfg.get("auto_encrypt_on_setup", True):
        return 0, "Auto-encrypt disabled in config.json"
    if not cfg.get("encrypt_personal_data", True):
        return 0, "encrypt_personal_data is false"
    if is_encryption_enabled():
        return 0, "Encryption already enabled"
    if not password:
        return 0, "Skipped (no password). Enable in app on first launch."
    ok, msg = enable_encryption(password)
    return (0 if ok else 1), msg
