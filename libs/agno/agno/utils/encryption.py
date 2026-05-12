"""Fernet-based symmetric encryption for sensitive data at rest.

Used by OAuth toolkits to encrypt tokens stored in the database.
Key should be set via AGNO_ENCRYPTION_KEY environment variable or passed explicitly.

Requires: `pip install cryptography`
"""

import base64
import hashlib
import json
import os
from typing import Any, Dict, Optional


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from an arbitrary secret using SHA256."""
    raw_key = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(raw_key)


def get_encryption_key() -> Optional[str]:
    """Get the encryption key from environment. Returns None if not configured."""
    return os.getenv("AGNO_ENCRYPTION_KEY")


def is_encrypted(data: Dict[str, Any]) -> bool:
    """Check if data is wrapped in encryption envelope."""
    return isinstance(data, dict) and "encrypted" in data and len(data) == 1


def encrypt_dict(data: Dict[str, Any], key: Optional[str] = None) -> Dict[str, str]:
    """Encrypt a dict using Fernet (AES-128-CBC + HMAC-SHA256).

    Args:
        data: Dict to encrypt
        key: Encryption key (falls back to AGNO_ENCRYPTION_KEY env var)

    Returns:
        {"encrypted": "<base64-ciphertext>"} envelope

    Raises:
        ImportError: If cryptography package not installed
        ValueError: If no key provided and AGNO_ENCRYPTION_KEY not set
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError("`cryptography` not installed. Please install using `pip install cryptography`")

    secret = key or get_encryption_key()
    if not secret:
        raise ValueError("No encryption key provided. Set AGNO_ENCRYPTION_KEY or pass key=")

    fernet_key = _derive_fernet_key(secret)
    f = Fernet(fernet_key)
    plaintext = json.dumps(data).encode("utf-8")
    ciphertext = f.encrypt(plaintext)
    return {"encrypted": ciphertext.decode("ascii")}


def decrypt_dict(data: Dict[str, Any], key: Optional[str] = None) -> Dict[str, Any]:
    """Decrypt data if encrypted, pass through if plaintext.

    Args:
        data: Either {"encrypted": "..."} envelope or plaintext dict
        key: Encryption key (falls back to AGNO_ENCRYPTION_KEY env var)

    Returns:
        Decrypted dict (or original if not encrypted)

    Raises:
        ImportError: If data is encrypted but cryptography not installed
        ValueError: If encrypted but no key, or decryption fails
    """
    if not is_encrypted(data):
        return data

    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        raise ImportError("`cryptography` not installed. Please install using `pip install cryptography`")

    secret = key or get_encryption_key()
    if not secret:
        raise ValueError("Data is encrypted but no decryption key provided")

    try:
        fernet_key = _derive_fernet_key(secret)
        f = Fernet(fernet_key)
        ciphertext = data["encrypted"].encode("ascii")
        plaintext = f.decrypt(ciphertext)
        return json.loads(plaintext.decode("utf-8"))
    except InvalidToken:
        raise ValueError("Decryption failed: wrong key or corrupted data")
