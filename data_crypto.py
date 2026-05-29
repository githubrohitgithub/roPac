"""
Encrypt memory & knowledge at rest. Owner password unlocks a **session cache**
of decrypted JSON under data/.vault_session/ (deleted on lock / app quit).

Password → unwrap data key → decrypt into session files → fast reads until lock.
No Keychain persistence across app restarts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import shutil
from pathlib import Path
from typing import Any

from auth import verify_owner_password

ROPAC_ROOT = Path(__file__).resolve().parent
DATA_DIR = ROPAC_ROOT / "data"
CRYPTO_PATH = DATA_DIR / "crypto.json"
WRAPPED_KEY_PATH = DATA_DIR / "wrapped_key.json"
SESSION_DIR = DATA_DIR / ".vault_session"
SESSION_KEY_PATH = SESSION_DIR / ".data_key"
SESSION_KNOWLEDGE_DIR = SESSION_DIR / "knowledge"

MEMORY_PATH = DATA_DIR / "memory.json"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"

KDF_ITERATIONS = 600_000
ENVELOPE_VERSION = 1
ALGORITHM = "aes-256-gcm"

VAULT_LOCKED_MSG = (
    "Personal data is locked. Enter your owner password to unlock for this session."
)


def _require_crypto() -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise ImportError(
            "Encryption requires the cryptography package. Run: pip install cryptography"
        ) from e
    return AESGCM


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        KDF_ITERATIONS,
        dklen=32,
    )


def load_crypto_meta() -> dict[str, Any]:
    if not CRYPTO_PATH.exists():
        return {"version": 1, "enabled": False}
    return json.loads(CRYPTO_PATH.read_text(encoding="utf-8"))


def save_crypto_meta(meta: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    meta["version"] = 1
    CRYPTO_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    try:
        CRYPTO_PATH.chmod(0o600)
    except OSError:
        pass


def is_encryption_enabled() -> bool:
    return bool(load_crypto_meta().get("enabled"))


def is_encrypted_envelope(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("v") == ENVELOPE_VERSION
        and data.get("alg") == ALGORITHM
        and "nonce" in data
        and "ct" in data
    )


def encrypt_bytes(plaintext: bytes, data_key: bytes) -> dict[str, Any]:
    AESGCM = _require_crypto()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(data_key).encrypt(nonce, plaintext, None)
    return {
        "v": ENVELOPE_VERSION,
        "alg": ALGORITHM,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
    }


def decrypt_bytes(envelope: dict[str, Any], data_key: bytes) -> bytes:
    if not is_encrypted_envelope(envelope):
        raise ValueError("Not an encrypted envelope")
    AESGCM = _require_crypto()
    nonce = base64.b64decode(envelope["nonce"])
    ct = base64.b64decode(envelope["ct"])
    return AESGCM(data_key).decrypt(nonce, ct, None)


def encrypt_json(obj: Any, data_key: bytes) -> dict[str, Any]:
    return encrypt_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"), data_key)


def decrypt_json(envelope: dict[str, Any], data_key: bytes) -> Any:
    return json.loads(decrypt_bytes(envelope, data_key).decode("utf-8"))


def _load_wrapped_key() -> dict[str, Any] | None:
    if not WRAPPED_KEY_PATH.exists():
        return None
    return json.loads(WRAPPED_KEY_PATH.read_text(encoding="utf-8"))


def _save_wrapped_key(data_key: bytes, password: str) -> None:
    meta = load_crypto_meta()
    salt = base64.b64decode(meta["kdf_salt"])
    wrap_key = _derive_key(password, salt)
    wrapped = encrypt_bytes(data_key, wrap_key)
    wrapped["purpose"] = "data_key"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WRAPPED_KEY_PATH.write_text(json.dumps(wrapped, indent=2) + "\n", encoding="utf-8")
    try:
        WRAPPED_KEY_PATH.chmod(0o600)
    except OSError:
        pass


def _unwrap_data_key(password: str) -> bytes | None:
    blob = _load_wrapped_key()
    if not blob:
        return None
    meta = load_crypto_meta()
    salt = base64.b64decode(meta["kdf_salt"])
    wrap_key = _derive_key(password, salt)
    try:
        key = decrypt_bytes(blob, wrap_key)
    except Exception:
        return None
    return key if len(key) == 32 else None


def _session_path_for(source: Path) -> Path | None:
    source = source.resolve()
    if source == MEMORY_PATH.resolve():
        return SESSION_DIR / "memory.json"
    try:
        source.relative_to(KNOWLEDGE_DIR.resolve())
    except ValueError:
        return None
    return SESSION_KNOWLEDGE_DIR / source.name


def is_session_unlocked() -> bool:
    return SESSION_KEY_PATH.is_file() and SESSION_KEY_PATH.stat().st_size == 32


def get_active_data_key() -> bytes | None:
    if not is_session_unlocked():
        return None
    key = SESSION_KEY_PATH.read_bytes()
    return key if len(key) == 32 else None


def _write_session_key(data_key: bytes) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_KEY_PATH.write_bytes(data_key)
    try:
        SESSION_DIR.chmod(0o700)
        SESSION_KEY_PATH.chmod(0o600)
    except OSError:
        pass


def _decrypt_file_to_session(source: Path, data_key: bytes) -> None:
    if not source.exists():
        return
    parsed = json.loads(source.read_text(encoding="utf-8"))
    if not is_encrypted_envelope(parsed):
        plain = parsed
    else:
        plain = decrypt_json(parsed, data_key)
    dest = _session_path_for(source)
    if dest is None:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(plain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        dest.chmod(0o600)
    except OSError:
        pass


def _build_session_cache(data_key: bytes) -> None:
    vault_lock()
    _write_session_key(data_key)
    SESSION_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    _decrypt_file_to_session(MEMORY_PATH, data_key)
    if KNOWLEDGE_DIR.is_dir():
        for path in KNOWLEDGE_DIR.glob("*.json"):
            _decrypt_file_to_session(path, data_key)
    marker = SESSION_DIR / ".unlocked"
    marker.write_text(json.dumps({"v": 1}), encoding="utf-8")


def vault_lock() -> None:
    """Delete all decrypted session files (call when app closes)."""
    if SESSION_DIR.exists():
        shutil.rmtree(SESSION_DIR, ignore_errors=True)
    try:
        import keyring

        keyring.delete_password(
            "ropac",
            f"data_key:{hashlib.sha256(str(ROPAC_ROOT).encode()).hexdigest()[:16]}",
        )
    except Exception:
        pass


def vault_unlock(password: str) -> tuple[bool, str]:
    if not password:
        return False, "Password required"
    if not verify_owner_password(password):
        return False, "Incorrect owner password"
    if not is_encryption_enabled():
        return True, "Encryption is not enabled"

    data_key = _unwrap_data_key(password)
    if data_key is None:
        return False, "Could not unlock (wrong password or missing wrapped_key)"

    _build_session_cache(data_key)
    return True, "Personal data unlocked for this session"


def crypto_status() -> dict[str, Any]:
    enabled = is_encryption_enabled()
    return {
        "enabled": enabled,
        "unlocked": is_session_unlocked() if enabled else True,
        "session_dir": str(SESSION_DIR),
        "wrapped_key_present": WRAPPED_KEY_PATH.is_file(),
    }


def require_unlocked_session(*, password: str | None = None) -> tuple[bool, str]:
    if not is_encryption_enabled():
        return True, ""
    if is_session_unlocked():
        return True, ""
    if password:
        return vault_unlock(password)
    return False, VAULT_LOCKED_MSG


def ensure_data_key(password: str | None = None) -> bytes | None:
    if not is_encryption_enabled():
        return None
    key = get_active_data_key()
    if key is not None:
        return key
    if password:
        ok, _ = vault_unlock(password)
        if ok:
            return get_active_data_key()
    return None


def read_json_file(path: Path, *, password: str | None = None) -> Any | None:
    if not path.exists():
        return None

    if not is_encryption_enabled():
        return json.loads(path.read_text(encoding="utf-8"))

    ok, _ = require_unlocked_session(password=password)
    if not ok:
        return None

    session = _session_path_for(path)
    if session is not None and session.is_file():
        return json.loads(session.read_text(encoding="utf-8"))

    key = get_active_data_key()
    if key is None:
        return None
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if is_encrypted_envelope(parsed):
        return decrypt_json(parsed, key)
    return parsed


def write_json_file(path: Path, obj: Any, *, password: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not is_encryption_enabled():
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    ok, msg = require_unlocked_session(password=password)
    if not ok:
        raise PermissionError(msg)

    key = get_active_data_key()
    if key is None:
        raise PermissionError(VAULT_LOCKED_MSG)

    envelope = encrypt_json(obj, key)
    path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass

    session = _session_path_for(path)
    if session is not None:
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            session.chmod(0o600)
        except OSError:
            pass


def migrate_plain_file(path: Path, data_key: bytes) -> None:
    if not path.exists():
        return
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if is_encrypted_envelope(parsed):
        return
    envelope = encrypt_json(parsed, data_key)
    path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
