import base64
import json
from datetime import datetime
from os import getenv
from typing import Optional

from agno.utils.log import log_error

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    raise ImportError("cryptography package required: pip install cryptography")

try:
    from google.oauth2.credentials import Credentials
except ImportError:
    raise ImportError("google-auth required: pip install google-auth")

# Fixed salt for key derivation from passphrase — changing this invalidates all stored tokens
_KDF_SALT = b"agno-google-oauth-v1"


def _get_fernet(encryption_key: Optional[str] = None) -> Fernet:
    key = encryption_key or getenv("GOOGLE_OAUTH_ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "Encryption key required. Set GOOGLE_OAUTH_ENCRYPTION_KEY env var "
            "or pass encryption_key parameter. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    # If it's a valid Fernet key (44 chars, base64), use directly
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except ValueError:
        pass

    # Otherwise treat as passphrase and derive a key via PBKDF2
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT, iterations=480_000)
    derived = base64.urlsafe_b64encode(kdf.derive(key.encode()))
    return Fernet(derived)


def encrypt_credentials(creds: Credentials, encryption_key: Optional[str] = None) -> bytes:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    plaintext = json.dumps(data).encode()
    f = _get_fernet(encryption_key)
    return f.encrypt(plaintext)


def decrypt_credentials(encrypted: bytes, encryption_key: Optional[str] = None) -> Optional[Credentials]:
    f = _get_fernet(encryption_key)
    try:
        plaintext = f.decrypt(encrypted)
    except InvalidToken:
        log_error("Failed to decrypt Google OAuth token — key mismatch or corrupt data")
        return None

    data = json.loads(plaintext)
    expiry = datetime.fromisoformat(data["expiry"]) if data.get("expiry") else None

    return Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        expiry=expiry,
    )
