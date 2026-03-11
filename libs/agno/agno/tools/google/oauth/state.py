import base64
import hashlib
import hmac
import json
import time
import uuid
from os import getenv
from typing import Optional, Tuple

_STATE_TTL_SECONDS = 300  # 5 minutes


def _get_hmac_key(encryption_key: Optional[str] = None) -> bytes:
    key = encryption_key or getenv("GOOGLE_OAUTH_ENCRYPTION_KEY")
    if not key:
        raise ValueError("GOOGLE_OAUTH_ENCRYPTION_KEY required for OAuth state signing")
    # Derive a separate HMAC key from the encryption key
    return hashlib.sha256(f"hmac-state-{key}".encode()).digest()


def _sign(payload: bytes, hmac_key: bytes) -> str:
    return hmac.new(hmac_key, payload, hashlib.sha256).hexdigest()


def create_state(
    team_id: str,
    user_id: str,
    encryption_key: Optional[str] = None,
) -> str:
    hmac_key = _get_hmac_key(encryption_key)
    payload = {
        "team_id": team_id,
        "user_id": user_id,
        "nonce": uuid.uuid4().hex,
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    sig = _sign(payload_bytes, hmac_key)
    # Format: base64url(payload).signature
    encoded = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    return f"{encoded}.{sig}"


def verify_state(
    state: str,
    encryption_key: Optional[str] = None,
) -> Tuple[str, str]:
    """Returns (team_id, user_id) if valid, raises ValueError otherwise."""
    hmac_key = _get_hmac_key(encryption_key)

    parts = state.split(".", 1)
    if len(parts) != 2:
        raise ValueError("Invalid state format")

    encoded_payload, sig = parts

    # Restore base64 padding
    padded = encoded_payload + "=" * (4 - len(encoded_payload) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(padded)
    except Exception as e:
        raise ValueError(f"Invalid state encoding: {e}") from e

    expected_sig = _sign(payload_bytes, hmac_key)
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Invalid state signature — possible tampering")

    payload = json.loads(payload_bytes)

    if int(time.time()) > payload.get("exp", 0):
        raise ValueError("State expired — please try connecting again")

    return payload["team_id"], payload["user_id"]
