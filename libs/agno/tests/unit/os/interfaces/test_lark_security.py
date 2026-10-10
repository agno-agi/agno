import base64
import hashlib
import json
import time

import pytest

from agno.os.interfaces.lark.security import (
    decrypt_event,
    maybe_decrypt_body,
    verify_lark_signature,
)

ENCRYPT_KEY = "test-encrypt-key"


def _make_signature(timestamp: str, nonce: str, encrypt_key: str, body: bytes) -> str:
    sig_basestring = (timestamp + nonce + encrypt_key).encode("utf-8") + body
    return hashlib.sha256(sig_basestring).hexdigest()


# === verify_lark_signature ===


def test_valid_signature():
    timestamp = str(int(time.time()))
    nonce = "abc123"
    body = b'{"event":"test"}'
    signature = _make_signature(timestamp, nonce, ENCRYPT_KEY, body)
    assert verify_lark_signature(timestamp, nonce, ENCRYPT_KEY, body, signature) is True


def test_invalid_signature():
    timestamp = str(int(time.time()))
    body = b'{"event":"test"}'
    assert verify_lark_signature(timestamp, "nonce", ENCRYPT_KEY, body, "deadbeef" * 8) is False


def test_missing_timestamp():
    body = b'{"event":"test"}'
    assert verify_lark_signature("", "nonce", ENCRYPT_KEY, body, "sig") is False


def test_missing_signature():
    timestamp = str(int(time.time()))
    body = b'{"event":"test"}'
    assert verify_lark_signature(timestamp, "nonce", ENCRYPT_KEY, body, "") is False


def test_missing_encrypt_key():
    timestamp = str(int(time.time()))
    body = b'{"event":"test"}'
    assert verify_lark_signature(timestamp, "nonce", "", body, "sig") is False


def test_stale_timestamp_rejected():
    old_timestamp = str(int(time.time()) - 600)
    body = b'{"event":"test"}'
    signature = _make_signature(old_timestamp, "nonce", ENCRYPT_KEY, body)
    assert verify_lark_signature(old_timestamp, "nonce", ENCRYPT_KEY, body, signature) is False


def test_wrong_encrypt_key():
    timestamp = str(int(time.time()))
    body = b'{"event":"test"}'
    signature = _make_signature(timestamp, "nonce", "wrong-key", body)
    assert verify_lark_signature(timestamp, "nonce", ENCRYPT_KEY, body, signature) is False


def test_non_numeric_timestamp():
    body = b'{"event":"test"}'
    assert verify_lark_signature("not-a-number", "nonce", ENCRYPT_KEY, body, "sig") is False


# === decrypt_event ===

# Requires the optional cryptography package (agno[lark-crypto]).
decrypt = pytest.importorskip("cryptography")


def _encrypt_payload(encrypt_key: str, plaintext: dict) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key = hashlib.sha256(encrypt_key.encode()).digest()
    iv = b"0123456789abcdef"
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padder = PKCS7(128).padder()
    padded = padder.update(json.dumps(plaintext).encode()) + padder.finalize()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


def test_decrypt_event_success():
    original = {"type": "url_verification", "challenge": "abc123"}
    encrypted = _encrypt_payload(ENCRYPT_KEY, original)
    result = decrypt_event(ENCRYPT_KEY, encrypted)
    assert result == original


def test_decrypt_event_wrong_key():
    encrypted = _encrypt_payload(ENCRYPT_KEY, {"type": "url_verification", "challenge": "x"})
    with pytest.raises(Exception):
        decrypt_event("wrong-key", encrypted)


def test_decrypt_event_invalid_base64():
    with pytest.raises(Exception):
        decrypt_event(ENCRYPT_KEY, "!!!not-base64!!!")


def test_decrypt_event_too_short():
    short_payload = base64.b64encode(b"short").decode()
    with pytest.raises(ValueError, match="too short"):
        decrypt_event(ENCRYPT_KEY, short_payload)


def test_decrypt_event_roundtrip_with_maybe_decrypt():
    original = {"header": {"event_type": "im.message.receive_v1"}, "event": {}}
    encrypted = _encrypt_payload(ENCRYPT_KEY, original)
    body = {"encrypt": encrypted}
    result = maybe_decrypt_body(ENCRYPT_KEY, body)
    assert result == original


# === maybe_decrypt_body ===


def test_maybe_decrypt_no_encrypt_key_returns_body():
    body = {"type": "url_verification", "challenge": "x"}
    assert maybe_decrypt_body(None, body) is body


def test_maybe_decrypt_no_encrypt_field_returns_body():
    body = {"header": {"event_type": "test"}}
    assert maybe_decrypt_body(ENCRYPT_KEY, body) is body


def test_maybe_decrypt_with_encrypt_key_decrypts():
    original = {"type": "url_verification", "challenge": "decrypted"}
    encrypted = _encrypt_payload(ENCRYPT_KEY, original)
    body = {"encrypt": encrypted}
    result = maybe_decrypt_body(ENCRYPT_KEY, body)
    assert result["challenge"] == "decrypted"
