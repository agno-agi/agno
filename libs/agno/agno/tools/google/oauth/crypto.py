import json
from datetime import datetime
from os import getenv
from typing import Optional

from agno.utils.cryptography import decrypt_data, encrypt_data
from agno.utils.log import log_error

try:
    from google.oauth2.credentials import Credentials
except ImportError:
    raise ImportError("google-auth required: pip install google-auth")


def _resolve_key(encryption_key: Optional[str] = None) -> str:
    key = encryption_key or getenv("GOOGLE_OAUTH_ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "Encryption key required. Set GOOGLE_OAUTH_ENCRYPTION_KEY env var "
            "or pass encryption_key parameter. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return key


def encrypt_credentials(creds: Credentials, encryption_key: Optional[str] = None) -> bytes:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    return encrypt_data(json.dumps(data).encode(), _resolve_key(encryption_key))


def decrypt_credentials(encrypted: bytes, encryption_key: Optional[str] = None) -> Optional[Credentials]:
    plaintext = decrypt_data(encrypted, _resolve_key(encryption_key))
    if plaintext is None:
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
