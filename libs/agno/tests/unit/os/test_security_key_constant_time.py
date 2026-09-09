"""The AgentOS security key must be compared in constant time.

``JWTMiddleware`` already compares ``OS_SECURITY_KEY`` with ``hmac.compare_digest``
(see ``agno/os/middleware/jwt.py``). These tests pin the REST dependency and the
WebSocket validator to the same behaviour, so a byte-by-byte ``==`` cannot leak the
key one character at a time through response timing.
"""

import hmac
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from agno.os import auth as auth_module
from agno.os.auth import get_authentication_dependency, validate_websocket_token
from agno.os.settings import AgnoAPISettings

OS_KEY = "test-os-security-key"


@pytest.fixture(autouse=True)
def no_jwt_env(monkeypatch):
    """Keep the security-key branch reachable regardless of the ambient environment."""
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)


@pytest.fixture
def compare_digest_calls(monkeypatch):
    """Record every ``hmac.compare_digest`` call made while authenticating."""
    calls = []
    real_compare_digest = hmac.compare_digest

    def recording_compare_digest(a, b):
        calls.append((a, b))
        return real_compare_digest(a, b)

    monkeypatch.setattr(auth_module.hmac, "compare_digest", recording_compare_digest)
    return calls


def _as_bytes(value):
    return value if isinstance(value, bytes) else value.encode("utf-8", "surrogateescape")


def _compared_in_constant_time(calls, token: str, key: str) -> bool:
    return (_as_bytes(token), _as_bytes(key)) in {(_as_bytes(a), _as_bytes(b)) for a, b in calls}


def _request():
    """Minimal stand-in for a Starlette request with no internal service token set."""
    return SimpleNamespace(
        state=SimpleNamespace(),
        app=SimpleNamespace(state=SimpleNamespace(internal_service_token=None)),
    )


async def test_rest_dependency_compares_security_key_in_constant_time(compare_digest_calls):
    auth_dependency = get_authentication_dependency(AgnoAPISettings(os_security_key=OS_KEY))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")

    with pytest.raises(HTTPException) as exc_info:
        await auth_dependency(_request(), credentials)

    assert exc_info.value.status_code == 401
    assert _compared_in_constant_time(compare_digest_calls, "wrong-token", OS_KEY)


async def test_rest_dependency_still_accepts_the_security_key(compare_digest_calls):
    auth_dependency = get_authentication_dependency(AgnoAPISettings(os_security_key=OS_KEY))
    request = _request()

    assert await auth_dependency(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=OS_KEY)) is True
    assert request.state.authenticated is True
    assert _compared_in_constant_time(compare_digest_calls, OS_KEY, OS_KEY)


def test_websocket_validator_compares_security_key_in_constant_time(compare_digest_calls):
    settings = AgnoAPISettings(os_security_key=OS_KEY)

    assert validate_websocket_token("wrong-token", settings) is False
    assert validate_websocket_token(OS_KEY, settings) is True
    assert _compared_in_constant_time(compare_digest_calls, "wrong-token", OS_KEY)
    assert _compared_in_constant_time(compare_digest_calls, OS_KEY, OS_KEY)


def test_non_ascii_security_key_still_validates():
    """``hmac.compare_digest`` rejects non-ASCII ``str``; the key must be encoded first.

    Header values are latin-1 decoded by the ASGI server and the key comes from the
    environment, so either side can carry non-ASCII characters.
    """
    settings = AgnoAPISettings(os_security_key="clé-de-sécurité")

    assert validate_websocket_token("wrong-token", settings) is False
    assert validate_websocket_token("clé-de-sécurité", settings) is True
