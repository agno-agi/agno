import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException

from agno.os.interfaces.slack import security as sec_mod
from agno.os.interfaces.slack.security import verify_slack_signature


def _sign(body: bytes, timestamp: str, secret: str) -> str:
    sig_base = f"v0:{timestamp}:{body.decode()}"
    return "v0=" + hmac.new(secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()


class TestVerifySlackSignature:
    def test_explicit_secret(self):
        body = b'{"test": true}'
        ts = str(int(time.time()))
        secret = "explicit-secret"
        sig = _sign(body, ts, secret)
        assert verify_slack_signature(body, ts, sig, signing_secret=secret) is True

    def test_env_fallback(self):
        body = b'{"test": true}'
        ts = str(int(time.time()))
        env_secret = "env-secret-value"
        sig = _sign(body, ts, env_secret)
        original = sec_mod.SLACK_SIGNING_SECRET
        try:
            sec_mod.SLACK_SIGNING_SECRET = env_secret
            assert verify_slack_signature(body, ts, sig) is True
        finally:
            sec_mod.SLACK_SIGNING_SECRET = original

    def test_empty_string_not_fallback(self):
        body = b'{"test": true}'
        ts = str(int(time.time()))
        original = sec_mod.SLACK_SIGNING_SECRET
        try:
            sec_mod.SLACK_SIGNING_SECRET = "env-secret"
            with pytest.raises(HTTPException) as exc_info:
                verify_slack_signature(body, ts, "v0=fake", signing_secret="")
            assert exc_info.value.status_code == 500
        finally:
            sec_mod.SLACK_SIGNING_SECRET = original

    def test_missing_secret_raises_500(self):
        body = b'{"test": true}'
        ts = str(int(time.time()))
        original = sec_mod.SLACK_SIGNING_SECRET
        try:
            sec_mod.SLACK_SIGNING_SECRET = None
            with pytest.raises(HTTPException) as exc_info:
                verify_slack_signature(body, ts, "v0=fake")
            assert exc_info.value.status_code == 500
        finally:
            sec_mod.SLACK_SIGNING_SECRET = original

    def test_stale_timestamp_rejected(self):
        body = b'{"test": true}'
        secret = "test-secret"
        stale_ts = str(int(time.time()) - 400)
        sig = _sign(body, stale_ts, secret)
        assert verify_slack_signature(body, stale_ts, sig, signing_secret=secret) is False

    def test_wrong_signature_rejected(self):
        body = b'{"test": true}'
        ts = str(int(time.time()))
        assert verify_slack_signature(body, ts, "v0=deadbeef", signing_secret="secret") is False

    def test_non_utf8_body_rejected(self):
        body = b"\x80\x81\x82\xff"
        ts = str(int(time.time()))
        assert verify_slack_signature(body, ts, "v0=deadbeef", signing_secret="secret") is False
