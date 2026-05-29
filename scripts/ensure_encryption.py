#!/usr/bin/env python3
"""Setup-time encryption (called from setup.sh). App uses bridge personal_data_setup."""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

ROPAC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROPAC_ROOT))

from data_crypto import is_encryption_enabled  # noqa: E402
from ropac_personal_data import (  # noqa: E402
    crypto_deps_ok,
    enable_encryption,
    migration_status,
    setup_install_encrypt,
)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run during ./install.sh (uses ROPAC_OWNER_PASSWORD or prompt)",
    )
    args = parser.parse_args()

    if not crypto_deps_ok():
        print("WARN: cryptography not installed — run: pip install -r requirements.txt")
        return 0

    mig = migration_status()
    if mig.get("migration_hint"):
        print(f"==> {mig['migration_hint']}")

    if args.setup:
        password = os.environ.get("ROPAC_OWNER_PASSWORD", "").strip() or None
        if not password and sys.stdin.isatty():
            if is_encryption_enabled():
                print("==> Personal data encryption: already enabled")
                return 0
            print("")
            print("Encrypt memory & training files with your owner password?")
            print("(Same password you use for save/delete/train in RoPac.)")
            password = getpass("Owner password (Enter to skip for now): ").strip() or None
        code, msg = setup_install_encrypt(password)
        print(f"==> {msg}")
        return code

    if is_encryption_enabled():
        password = getpass("Owner password to unlock: ")
        from data_crypto import vault_unlock

        ok, msg = vault_unlock(password)
        print(msg)
        return 0 if ok else 1

    password = getpass("Owner password: ")
    ok, msg = enable_encryption(password)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
