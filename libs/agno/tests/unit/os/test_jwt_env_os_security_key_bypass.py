"""Regression tests for the JWT-env-var vs OS_SECURITY_KEY auth bypass.

When ``authorization=False`` AgentOS does not install JWT middleware, so the
mere presence of ``JWT_VERIFICATION_KEY`` / ``JWT_JWKS_FILE`` in the process
environment must not cause the configured ``OS_SECURITY_KEY`` check to be
skipped — otherwise the routes become unauthenticated. See issue #8625.
"""

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.auth import validate_websocket_token
from agno.os.middleware import JWTMiddleware
from agno.os.settings import AgnoAPISettings

OS_KEY = "test-os-security-key"
JWT_SECRET = "test-secret-key-for-os-security-key-bypass"


def _build_app(authorization: bool):
    agent = Agent(name="Test Agent", id="test-agent", telemetry=False)
    settings = AgnoAPISettings(os_security_key=OS_KEY)
    return AgentOS(
        id="os-test",
        agents=[agent],
        authorization=authorization,
        settings=settings,
        telemetry=False,
    ).get_app()


def test_os_security_key_enforced_without_jwt_env():
    """Baseline: OS_SECURITY_KEY alone protects routes."""
    client = TestClient(_build_app(authorization=False))

    assert client.get("/config").status_code == 401
    assert client.get("/config", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"}).status_code == 200


def test_jwt_env_does_not_bypass_os_security_key_when_authorization_disabled(monkeypatch):
    """JWT env var present + authorization=False: OS_SECURITY_KEY must still be enforced.

    No JWT middleware is installed in this configuration, so a JWT env var is not
    proof that authentication happened.
    """
    monkeypatch.setenv("JWT_VERIFICATION_KEY", "not-used-when-authorization-false")
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)

    client = TestClient(_build_app(authorization=False))

    assert client.get("/config").status_code == 401
    assert client.get("/config", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"}).status_code == 200


def test_jwt_jwks_file_env_does_not_bypass_os_security_key(monkeypatch):
    """The JWT_JWKS_FILE env var must not bypass OS_SECURITY_KEY either."""
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.setenv("JWT_JWKS_FILE", "/tmp/does-not-matter.json")

    client = TestClient(_build_app(authorization=False))

    assert client.get("/config").status_code == 401
    assert client.get("/config", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"}).status_code == 200


def test_manual_jwt_middleware_still_works_with_os_security_key():
    """A manually installed JWTMiddleware (authorization=False) must keep working.

    This locks the legitimate path the env-var bypass was meant to cover: the
    OS_SECURITY_KEY check is skipped via request.state.authenticated (set by the
    middleware), not via the mere presence of JWT env vars.
    """
    app = _build_app(authorization=False)
    app.add_middleware(JWTMiddleware, verification_keys=[JWT_SECRET], algorithm="HS256")
    client = TestClient(app)

    valid_jwt = jwt.encode({"sub": "user-1"}, JWT_SECRET, algorithm="HS256")

    # Valid JWT is authenticated by the middleware, so the route is reachable.
    assert client.get("/config", headers={"Authorization": f"Bearer {valid_jwt}"}).status_code == 200
    # No token / non-JWT bearer are rejected by the middleware.
    assert client.get("/config").status_code == 401
    assert client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"}).status_code == 401


def test_authorization_true_still_enforces_jwt(monkeypatch):
    """authorization=True installs JWT middleware, which keeps rejecting unauthenticated requests."""
    monkeypatch.setenv("JWT_VERIFICATION_KEY", "secret-signing-key")
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)

    client = TestClient(_build_app(authorization=True))

    # No token and a non-JWT bearer are both rejected by the JWT middleware.
    assert client.get("/config").status_code == 401
    assert client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"}).status_code == 401


@pytest.mark.parametrize("env_var", ["JWT_VERIFICATION_KEY", "JWT_JWKS_FILE"])
def test_validate_websocket_token_not_bypassed_by_jwt_env(monkeypatch, env_var):
    """validate_websocket_token must not accept arbitrary tokens just because a JWT env var is set."""
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)
    monkeypatch.setenv(env_var, "present")

    settings = AgnoAPISettings(os_security_key=OS_KEY)

    assert validate_websocket_token("wrong", settings) is False
    assert validate_websocket_token(OS_KEY, settings) is True
