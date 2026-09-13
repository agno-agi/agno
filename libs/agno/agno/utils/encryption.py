import json
import os
from typing import Any, Dict, Optional


def generate_encryption_key() -> str:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError("`cryptography` not installed. Install with `pip install cryptography`")

    return Fernet.generate_key().decode()


def _validate_fernet_key(secret: str) -> bytes:
    """Validate that secret is a valid Fernet key. No KDF — key is used directly."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError("`cryptography` not installed. Install with `pip install cryptography`")

    try:
        key = secret.encode("ascii")
        Fernet(key)  # Validates: 44 chars, base64url, decodes to 32 bytes
        return key
    except Exception:
        raise ValueError("Invalid encryption key. Use generate_encryption_key() to create a valid Fernet key.")


def get_encryption_key() -> Optional[str]:
    return os.getenv("AGNO_ENCRYPTION_KEY")


def is_encrypted(data: Dict[str, Any]) -> bool:
    return isinstance(data, dict) and "encrypted" in data and len(data) == 1


def encrypt_dict(data: Dict[str, Any], key: Optional[str] = None) -> Dict[str, str]:
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError("`cryptography` not installed. Install with `pip install cryptography`")

    secret = key or get_encryption_key()
    if not secret:
        raise ValueError("No encryption key provided. Set AGNO_ENCRYPTION_KEY or pass key=")

    fernet_key = _validate_fernet_key(secret)
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
        raise ImportError("`cryptography` not installed. Install with `pip install cryptography`")

    secret = key or get_encryption_key()
    if not secret:
        raise ValueError("Data is encrypted but no decryption key provided")

    try:
        fernet_key = _validate_fernet_key(secret)
        f = Fernet(fernet_key)
        ciphertext = data["encrypted"].encode("ascii")
        plaintext = f.decrypt(ciphertext)
        return json.loads(plaintext.decode("utf-8"))
    except InvalidToken:
        raise ValueError("Decryption failed: wrong key or corrupted data")
