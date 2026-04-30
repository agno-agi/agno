import json
import time
from unittest.mock import Mock

import jwt
import pytest

from agno.tools.google.auth import GoogleAuth
from agno.utils.oauth_state import sign_state, verify_state


@pytest.fixture
def google_auth():
    ga = GoogleAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
        state_secret="test-state-secret-32-bytes-or-longer",
    )
    ga.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])
    return ga


def _fake_run_context(user_id):
    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.user_id = user_id
    return ctx


def _state_from_url(url: str) -> str:
    return url.split("state=")[1].split("&")[0]


def test_authenticate_google_produces_verifiable_state(google_auth):
    resp = json.loads(google_auth.authenticate_google(run_context=_fake_run_context("alice")))
    state = _state_from_url(resp["url"])
    payload = verify_state(state, secret="test-state-secret-32-bytes-or-longer")
    assert payload["user_id"] == "alice"
    assert payload["services"] == ["gmail"]
    assert "iat" in payload and "exp" in payload


def test_env_var_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_STATE_SECRET", "env-secret")
    ga = GoogleAuth(client_id="x")
    ga.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])
    resp = json.loads(ga.authenticate_google(run_context=_fake_run_context("alice")))
    state = _state_from_url(resp["url"])
    payload = verify_state(state, secret="env-secret")
    assert payload["user_id"] == "alice"


def test_kwarg_overrides_env_var(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_STATE_SECRET", "env-value")
    ga = GoogleAuth(client_id="x", state_secret="kwarg-wins")
    ga.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])
    resp = json.loads(ga.authenticate_google(run_context=_fake_run_context("alice")))
    state = _state_from_url(resp["url"])
    # Decodes with kwarg secret; raises with env secret
    assert verify_state(state, secret="kwarg-wins")["user_id"] == "alice"
    with pytest.raises(jwt.InvalidTokenError):
        verify_state(state, secret="env-value")


def test_fabricated_state_rejected(google_auth):
    forged = sign_state({"user_id": "victim", "services": ["gmail"]}, secret="attacker-key")
    mock_db = Mock()
    result = google_auth.handle_oauth_callback(code="unused", state=forged, db=mock_db)
    assert "error" in result
    assert "Invalid state" in result["error"]


def test_tampered_state_rejected(google_auth):
    resp = json.loads(google_auth.authenticate_google(run_context=_fake_run_context("alice")))
    state = _state_from_url(resp["url"])
    tampered = state[:-3] + ("A" if state[-3] != "A" else "B") + state[-2:]
    mock_db = Mock()
    result = google_auth.handle_oauth_callback(code="unused", state=tampered, db=mock_db)
    assert "error" in result
    assert "Invalid state" in result["error"]


def test_expired_state_rejected(google_auth):
    past = int(time.time()) - 3600
    # Manually craft an expired JWT with the right secret
    expired = jwt.encode(
        {"user_id": "alice", "services": ["gmail"], "iat": past, "exp": past + 60},
        __import__("hmac")
        .new(b"test-state-secret-32-bytes-or-longer", b"agno-state-token", __import__("hashlib").sha256)
        .digest(),
        algorithm="HS256",
    )
    mock_db = Mock()
    result = google_auth.handle_oauth_callback(code="unused", state=expired, db=mock_db)
    assert "error" in result
    assert "Invalid state" in result["error"]


def test_get_oauth_router_requires_state_secret(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_STATE_SECRET", raising=False)
    ga = GoogleAuth(client_id="id")
    with pytest.raises(RuntimeError, match="state signing secret"):
        ga.get_oauth_router()


def test_authenticate_google_without_state_secret_errors(monkeypatch):
    monkeypatch.delenv("GOOGLE_OAUTH_STATE_SECRET", raising=False)
    ga = GoogleAuth(client_id="id")
    ga.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])
    resp = json.loads(ga.authenticate_google())
    assert "error" in resp
    assert "state signing secret" in resp["error"].lower()
