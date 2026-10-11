"""
Encryption at rest for Plaid access tokens.

A Plaid access_token is a long-lived credential for a user's bank data, so
it shouldn't sit in the database as plaintext - anyone who obtains the DB
file (a backup, a leaked volume) would otherwise get live bank access.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC, authenticated) using
a key from the ENCRYPTION_KEY environment variable. Stored values carry an
"enc:" prefix so legacy plaintext rows are recognised and still work; they
get re-encrypted the next time they are used.

Limits worth knowing: the key lives in the same environment as the app, so
this protects the database *file*, not a fully compromised server. A
production setup would use a managed KMS and support key rotation.
"""
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:"


def _fernet() -> Fernet:
    # Read at call time (not import time) so import order can't hide the key.
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set in .env. Generate one with: "
            "python3 -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"ENCRYPTION_KEY is not a valid Fernet key: {e}")


def is_encrypted(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(_PREFIX)


def encrypt_token(plaintext: str) -> str:
    return _PREFIX + _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(stored: str) -> str:
    """Return the plaintext token. Legacy (unprefixed) values pass through unchanged."""
    if not is_encrypted(stored):
        return stored
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        raise RuntimeError(
            "Could not decrypt a stored Plaid token - ENCRYPTION_KEY has changed "
            "since it was saved. Re-link the bank account."
        )