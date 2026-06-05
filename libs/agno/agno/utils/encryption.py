import base64
import hashlib
import json
import os
from typing import Any, Dict, Optional


def _derive_fernet_key(secret: str) -> bytes:
    # Fernet requires exactly 32 bytes, base64-encoded
    raw_key = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(raw_key)


def get_encryption_key() -> Optional[str]:
    return os.getenv("AGNO_ENCRYPTION_KEY")


def is_encrypted(data: Dict[str, Any]) -> bool:
    return isinstance(data, dict) and "encrypted" in data and len(data) == 1


def encrypt_dict(data: Dict[str, Any], key: Optional[str] = None) -> Dict[str, str]:
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
