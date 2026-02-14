import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

from agno.os.interfaces.whatsapp.security import get_app_secret, validate_webhook_signature

APP_SECRET = "test-app-secret"


def _make_signature(payload: bytes, secret: str = APP_SECRET) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


@pytest.fixture(autouse=True)
def _set_env():
    with patch.dict("os.environ", {"WHATSAPP_APP_SECRET": APP_SECRET}):
        yield


# === get_app_secret ===


def test_get_app_secret():
    assert get_app_secret() == APP_SECRET


def test_get_app_secret_missing():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="WHATSAPP_APP_SECRET"):
            get_app_secret()


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


# === Replay protection ===


def test_replay_protection_current_timestamp():
    payload = b'{"test": "data"}'
    signature = _make_signature(payload)
    timestamp = int(time.time())
    assert validate_webhook_signature(payload, signature, timestamp=timestamp) is True


def test_replay_protection_old_timestamp():
    payload = b'{"test": "data"}'
    signature = _make_signature(payload)
    old_timestamp = int(time.time()) - 400
    assert validate_webhook_signature(payload, signature, timestamp=old_timestamp) is False


def test_replay_protection_future_timestamp():
    payload = b'{"test": "data"}'
    signature = _make_signature(payload)
    future_timestamp = int(time.time()) + 400
    assert validate_webhook_signature(payload, signature, timestamp=future_timestamp) is False


def test_replay_protection_none_timestamp_skips_check():
    payload = b'{"test": "data"}'
    signature = _make_signature(payload)
    assert validate_webhook_signature(payload, signature, timestamp=None) is True


def test_no_dev_mode_bypass():
    payload = b'{"test": "data"}'
    with patch.dict("os.environ", {"WHATSAPP_APP_SECRET": APP_SECRET, "APP_ENV": "development"}):
        assert validate_webhook_signature(payload, None) is False
        assert validate_webhook_signature(payload, "sha256=invalid") is False
