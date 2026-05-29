#!/usr/bin/env python3
"""Change RoPac owner password (used for forget this->)."""

from getpass import getpass

from auth import prompt_owner_password, set_owner_password, verify_owner_password


def main() -> None:
    print("Change RoPac owner password")
    if not prompt_owner_password():
        return
    new_pw = getpass("New password: ")
    confirm = getpass("Confirm new password: ")
    if new_pw != confirm:
        print("Passwords do not match.")
        return
    if not new_pw:
        print("Password cannot be empty.")
        return
    set_owner_password(new_pw)
    print("Password updated. Stored as salted hash in data/owner.auth")


if __name__ == "__main__":
    main()
