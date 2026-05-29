#!/usr/bin/env python3
"""Enable encryption (manual). Prefer: ./install.sh or app first-launch setup."""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

ROPAC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROPAC_ROOT))

from ropac_personal_data import enable_encryption, is_encryption_enabled  # noqa: E402


def main() -> int:
    if is_encryption_enabled():
        print("Encryption is already enabled.")
        password = getpass("Owner password to unlock: ")
    else:
        password = getpass("Owner password: ")
    ok, msg = enable_encryption(password)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
