import hashlib
import hmac
from unittest.mock import patch

import pytest

from agno.os.interfaces.whatsapp.security import validate_webhook_signature

APP_SECRET = "test-app-secret"


def _make_signature(payload: bytes, secret: str = APP_SECRET) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.fixture(autouse=True)
def _set_env():
    with patch.dict("os.environ", {"WHATSAPP_APP_SECRET": APP_SECRET}):
        yield


# === Signature validation ===


def test_valid_signature():
    payload = b'{"test": "data"}'
    signature = _make_signature(payload)
    assert validate_webhook_signature(payload, signature) is True


def test_invalid_signature():
    payload = b'{"test": "data"}'
    signature = "sha256=deadbeef0000000000000000000000000000000000000000000000000000dead"
    assert validate_webhook_signature(payload, signature) is False


def test_missing_signature():
    payload = b'{"test": "data"}'
    assert validate_webhook_signature(payload, None) is False


def test_empty_signature():
    payload = b'{"test": "data"}'
    assert validate_webhook_signature(payload, "") is False


def test_signature_without_prefix():
    payload = b'{"test": "data"}'
    sig = hmac.new(APP_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    assert validate_webhook_signature(payload, sig) is False


def test_wrong_secret():
    payload = b'{"test": "data"}'
    signature = _make_signature(payload, secret="wrong-secret")
    assert validate_webhook_signature(payload, signature) is False


# === Dev bypass: skip validation when APP_SECRET is unset ===


def test_no_secret_bypasses_validation():
    with patch.dict("os.environ", {}, clear=True):
        assert validate_webhook_signature(b"anything", None) is True
        assert validate_webhook_signature(b"anything", "sha256=invalid") is True


def test_app_env_development_does_not_bypass():
    payload = b'{"test": "data"}'
    with patch.dict("os.environ", {"WHATSAPP_APP_SECRET": APP_SECRET, "APP_ENV": "development"}):
        assert validate_webhook_signature(payload, None) is False
        assert validate_webhook_signature(payload, "sha256=invalid") is False
