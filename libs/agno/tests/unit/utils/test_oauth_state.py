import jwt
import pytest

from agno.utils.oauth_state import sign_state, verify_state


def test_sign_and_verify_roundtrip():
    payload = {"user_id": "alice", "services": ["gmail"]}
    token = sign_state(payload, secret="shared-secret")
    decoded = verify_state(token, secret="shared-secret")
    assert decoded["user_id"] == "alice"
    assert decoded["services"] == ["gmail"]
    assert "iat" in decoded and "exp" in decoded


def test_verify_with_wrong_secret_raises_error():
    token = sign_state({"user_id": "alice"}, secret="signer-secret")
    with pytest.raises(jwt.InvalidSignatureError):
        verify_state(token, secret="different-secret")


def test_verify_expired_token_raises_error():
    token = sign_state({"user_id": "alice"}, secret="s", ttl_seconds=-60)
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_state(token, secret="s")


def test_same_secret_verifies_multiple_tokens():
    t1 = sign_state({"user_id": "alice"}, secret="shared")
    t2 = sign_state({"user_id": "bob"}, secret="shared")
    assert verify_state(t1, secret="shared")["user_id"] == "alice"
    assert verify_state(t2, secret="shared")["user_id"] == "bob"
