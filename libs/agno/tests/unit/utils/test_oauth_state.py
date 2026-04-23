import time

import jwt
import pytest

from agno.utils.oauth_state import sign_state, verify_state


def test_roundtrip():
    payload = {"user_id": "alice", "services": ["gmail"]}
    token = sign_state(payload, secret="shared-secret")
    decoded = verify_state(token, secret="shared-secret")
    assert decoded["user_id"] == "alice"
    assert decoded["services"] == ["gmail"]
    assert "iat" in decoded and "exp" in decoded


def test_different_secrets_fail_verify():
    token = sign_state({"user_id": "alice"}, secret="signer-secret")
    with pytest.raises(jwt.InvalidSignatureError):
        verify_state(token, secret="different-secret")


def test_expired_token_fails():
    # exp is set to now + ttl; use ttl=-60 to produce an already-expired token
    token = sign_state({"user_id": "alice"}, secret="s", ttl_seconds=-60)
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_state(token, secret="s")


def test_same_secret_produces_decryptable_tokens():
    # Two tokens with same secret must each verify even though they carry different iat
    t1 = sign_state({"user_id": "alice"}, secret="shared")
    time.sleep(1)
    t2 = sign_state({"user_id": "bob"}, secret="shared")
    assert verify_state(t1, secret="shared")["user_id"] == "alice"
    assert verify_state(t2, secret="shared")["user_id"] == "bob"
