"""
Owner password verification for protected commands (e.g. forget this->).

The password is never stored in plain text — only a salted PBKDF2-SHA256 hash
that cannot be reversed (one-way, not encryption).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from getpass import getpass
from pathlib import Path
from typing import Any

AUTH_PATH = Path(__file__).resolve().parent / "data" / "owner.auth"
ITERATIONS = 600_000

# Default owner password hash (PBKDF2-SHA256). Plain password is not stored in code.
_BOOTSTRAP_SALT_B64 = "wMzs9mRE6ML7PHhV4BEJmj26bbeSsGApf/oqccN8e0s="
_BOOTSTRAP_HASH_B64 = "vu4w68SyOhTnRb+6D0w2IBADAWDfwhTA3vRvGRt7R1w="


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
    )


def _load_store() -> dict[str, Any] | None:
    if not AUTH_PATH.exists():
        return None
    return json.loads(AUTH_PATH.read_text(encoding="utf-8"))


def _save_store(salt: bytes, digest: bytes) -> None:
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "algorithm": "pbkdf2-sha256",
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode("ascii"),
        "hash": base64.b64encode(digest).decode("ascii"),
    }
    AUTH_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        AUTH_PATH.chmod(0o600)
    except OSError:
        pass


def set_owner_password(password: str) -> None:
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(32)
    digest = _hash_password(password, salt)
    _save_store(salt, digest)


def ensure_auth_store() -> None:
    """Create owner.auth on first run if missing (default owner password hash)."""
    if AUTH_PATH.exists():
        return
    salt = base64.b64decode(_BOOTSTRAP_SALT_B64)
    digest = base64.b64decode(_BOOTSTRAP_HASH_B64)
    _save_store(salt, digest)


def verify_owner_password(password: str) -> bool:
    store = _load_store()
    if store is None:
        ensure_auth_store()
        store = _load_store()
    if store is None:
        return False
    salt = base64.b64decode(store["salt"])
    expected = base64.b64decode(store["hash"])
    candidate = _hash_password(password, salt)
    return secrets.compare_digest(candidate, expected)


def check_owner_password(password: str | None = None) -> bool:
    """Verify password string (API/UI) or prompt interactively (terminal)."""
    if password is not None:
        return verify_owner_password(password)
    return prompt_owner_password()


def prompt_owner_password(*, max_attempts: int = 3) -> bool:
    print("Owner password required for forget.")
    for attempt in range(1, max_attempts + 1):
        password = getpass("Password: ")
        if verify_owner_password(password):
            try:
                from data_crypto import vault_unlock

                vault_unlock(password)
            except Exception:
                pass
            return True
        remaining = max_attempts - attempt
        if remaining:
            print(f"Incorrect password. {remaining} attempt(s) left.")
    print("Access denied.")
    return False
