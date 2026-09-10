"""Lark webhook signature verification and event decryption.

Lark offers two complementary security mechanisms for event subscriptions:

1. **Verification token** — a static token echoed in every event's
   ``header.token`` field. Checked in the router (cheap origin check).

2. **Encrypt key** (optional) — when configured, every event body arrives as
   ``{"encrypt": "<base64>"}`` AES-256-CBC encrypted, and each webhook request
   carries an ``X-Lark-Signature`` header computed as::

       sha256(timestamp + nonce + encrypt_key + body).hexdigest()

   Note: this is **plain SHA-256**, not HMAC. The ``encrypt_key`` is
   concatenated directly into the hash input.

References:
  - Signature: https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/event-subscription-guide/callback-subscription/receive-and-handle-callbacks
  - Encryption: https://open.larksuite.com/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-/encrypt-key-encryption-configuration-case
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Optional

# Reject webhook requests older than this to foil replay attacks.
# Lark does not document a strict window; 5 minutes mirrors the Slack interface.
_LARK_REPLAY_WINDOW_SECONDS = 300


def verify_lark_signature(
    timestamp: str,
    nonce: str,
    encrypt_key: str,
    body: bytes,
    signature: str,
) -> bool:
    """Verify an incoming Lark webhook request signature.

    Args:
        timestamp: Value of the ``X-Lark-Request-Timestamp`` header (seconds since epoch, as a string).
        nonce: Value of the ``X-Lark-Request-Nonce`` header.
        encrypt_key: The app's ``encrypt_key`` configured in the Lark console.
        body: Raw request body bytes.
        signature: Value of the ``X-Lark-Signature`` header (hex digest).

    Returns:
        ``True`` if the signature matches, ``False`` otherwise.
    """
    if not timestamp or not nonce or not signature or not encrypt_key:
        return False

    # Replay protection: drop requests with stale timestamps.
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = int(__import__("time").time())
    if abs(now - ts) > _LARK_REPLAY_WINDOW_SECONDS:
        return False

    # Lark's signature is sha256(timestamp + nonce + encrypt_key + body).
    # NOT HMAC — the key is concatenated into the hash input.
    sig_basestring = (timestamp + nonce + encrypt_key).encode("utf-8") + body
    computed = hashlib.sha256(sig_basestring).hexdigest()

    return hmac.compare_digest(computed, signature)


def decrypt_event(encrypt_key: str, encrypted_b64: str) -> dict:
    """Decrypt a Lark event payload encrypted with the app's ``encrypt_key``.

    Lark uses AES-256-CBC where:
      * key  = SHA256(encrypt_key)  (32 bytes → AES-256)
      * IV   = first 16 bytes of the base64-decoded ciphertext
      * data = remaining bytes, PKCS#7 padded

    Args:
        encrypt_key: The app's ``encrypt_key``.
        encrypted_b64: The base64 string from the ``{"encrypt": "..."}`` body.

    Returns:
        The decrypted event payload as a dict.

    Raises:
        ImportError: if ``cryptography`` is not installed.
        ValueError: if decryption fails or the payload is not valid JSON.
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError as e:
        raise ImportError("`cryptography` not installed. Please install using `pip install 'agno[lark-crypto]'`") from e

    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    raw = base64.b64decode(encrypted_b64)
    if len(raw) < 32:  # need at least IV (16) + one block (16)
        raise ValueError("Encrypted payload too short")

    iv, ciphertext = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    try:
        return json.loads(plaintext.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Decrypted payload is not valid JSON: {e}") from e


def maybe_decrypt_body(encrypt_key: Optional[str], body: dict) -> dict:
    """If ``body`` is an encrypted envelope (``{"encrypt": "..."}``), decrypt it.

    When ``encrypt_key`` is configured, *every* Lark webhook — including the
    URL verification challenge — arrives encrypted. This helper centralises the
    "is this encrypted?" check so the router can call it once.

    Args:
        encrypt_key: The app's ``encrypt_key``, or ``None`` if encryption is disabled.
        body: The parsed JSON body of the webhook request.

    Returns:
        The decrypted body dict if encryption was applied, otherwise ``body`` unchanged.
    """
    if not encrypt_key:
        return body
    encrypted = body.get("encrypt")
    if not encrypted:
        return body
    return decrypt_event(encrypt_key, encrypted)
