import time
from os import getenv

from fastapi import HTTPException

DISCORD_PUBLIC_KEY = getenv("DISCORD_PUBLIC_KEY")


# Raises HTTPException on configuration errors to match the framework convention
# used across all interface security modules (see also: slack/security.py).
def verify_discord_signature(body: bytes, timestamp: str, signature: str) -> bool:
    if not DISCORD_PUBLIC_KEY:
        raise HTTPException(status_code=500, detail="DISCORD_PUBLIC_KEY is not set")

    try:
        from nacl.exceptions import BadSignatureError  # type: ignore[import-not-found]
        from nacl.signing import VerifyKey  # type: ignore[import-not-found]
    except ImportError:
        raise HTTPException(status_code=500, detail="PyNaCl is not installed. Install with: pip install PyNaCl")

    # Replay protection: reject requests older than 5 minutes
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False

    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except BadSignatureError:
        # Cryptographic verification failed — signature doesn't match body+timestamp
        return False
    except (ValueError, TypeError):
        # Malformed hex in public key or signature string
        return False
