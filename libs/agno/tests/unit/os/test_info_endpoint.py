"""Tests for the unauthenticated GET /info endpoint.

Covers the discovery fields used by external tooling (e.g. the agno CLI):
MCP server availability (enabled + mount path) and the effective auth mode
("none" / "security_key" / "jwt").
"""

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.os import AgentOS
from agno.os.auth import get_effective_auth_mode
from agno.os.config import AuthorizationConfig
from agno.os.settings import AgnoAPISettings

JWT_SECRET = "test-jwt-secret"


@pytest.fixture(autouse=True)
def clean_auth_env(monkeypatch):
    """Keep ambient auth env vars from leaking into these tests."""
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)


def _build_client(**kwargs) -> TestClient:
    agent = Agent(name="Info Agent", id="info-agent", telemetry=False)
    os_instance = AgentOS(agents=[agent], telemetry=False, **kwargs)
    return TestClient(os_instance.get_app())


class TestInfoEndpointBasics:
    def test_returns_version_and_counts(self):
        client = _build_client()
        resp = client.get("/info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agno_version"]
        assert body["agent_count"] == 1
        assert body["team_count"] == 0
        assert body["workflow_count"] == 0

    def test_returns_name_and_os_id(self):
        client = _build_client(name="Customer Support", id="os-123")
        body = client.get("/info").json()
        assert body["name"] == "Customer Support"
        assert body["os_id"] == "os-123"

    def test_name_omitted_and_os_id_generated(self):
        client = _build_client()
        body = client.get("/info").json()
        assert body["name"] is None
        # AgentOS auto-generates an id when none is passed, so os_id is always present.
        assert body["os_id"]


class TestInfoEndpointMcpDiscovery:
    def test_mcp_disabled_by_default(self):
        client = _build_client()
        body = client.get("/info").json()
        assert body["mcp"] == {"enabled": False, "path": None, "oauth": None}

    def test_mcp_enabled_reports_path(self):
        pytest.importorskip("fastmcp")
        client = _build_client(mcp_server=True)
        body = client.get("/info").json()
        assert body["mcp"] == {"enabled": True, "path": "/mcp", "oauth": None}


class TestInfoEndpointAuthMode:
    def test_auth_mode_none_by_default(self):
        client = _build_client()
        body = client.get("/info").json()
        assert body["auth_mode"] == "none"

    def test_auth_mode_security_key(self):
        client = _build_client(settings=AgnoAPISettings(os_security_key="test-key"))
        resp = client.get("/info")
        # /info stays unauthenticated even when a security key is enforced
        assert resp.status_code == 200
        assert resp.json()["auth_mode"] == "security_key"

    def test_auth_mode_jwt_via_authorization_flag(self):
        client = _build_client(
            authorization=True,
            authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        )
        resp = client.get("/info")
        # /info is excluded from JWT middleware and stays unauthenticated
        assert resp.status_code == 200
        assert resp.json()["auth_mode"] == "jwt"

    def test_authorization_true_without_jwt_source_fails_fast(self):
        """F1: authorization=True with no JWT key would silently serve an OPEN instance
        (JWT and anonymous requests fall through). It must fail at construction, not boot."""
        agent = Agent(name="Info Agent", id="info-agent", telemetry=False)
        with pytest.raises(ValueError, match="requires a JWT verification key"):
            AgentOS(agents=[agent], telemetry=False, authorization=True).get_app()

    def test_auth_mode_jwt_via_env_takes_precedence_over_security_key(self, monkeypatch):
        monkeypatch.setenv("JWT_VERIFICATION_KEY", JWT_SECRET)
        client = _build_client(settings=AgnoAPISettings(os_security_key="test-key"))
        body = client.get("/info").json()
        # JWT configured via env vars is effectively enforced, even without authorization=True
        assert body["auth_mode"] == "jwt"

    def test_auth_mode_jwt_via_manually_added_middleware(self):
        """Regression: JWTMiddleware installed via ``app.add_middleware`` must be detected.

        Some deployments configure JWT auth by calling ``app.add_middleware(JWTMiddleware, ...)``
        instead of using ``AgentOS(authorization=True)``. Before the fix, ``/info`` reported
        ``auth_mode: "none"`` for these deployments, and ``agno connect`` skipped the mint
        step and produced configs without a bearer token.
        """
        from agno.os.middleware import JWTMiddleware

        agent = Agent(name="Info Agent", id="info-agent", telemetry=False)
        os_instance = AgentOS(agents=[agent], telemetry=False)
        app = os_instance.get_app()
        app.add_middleware(
            JWTMiddleware,
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            authorization=True,
        )
        client = TestClient(app)
        body = client.get("/info").json()
        assert body["auth_mode"] == "jwt"


class TestInfoEndpointUserIsolation:
    """A client reads ``user_isolation`` with ``auth_mode`` to know whether it must name the user
    itself: under jwt the token does; under none / security_key the OS cannot tell who is asking."""

    def test_off_by_default_in_every_mode(self):
        assert _build_client().get("/info").json()["user_isolation"] is False
        keyed = _build_client(settings=AgnoAPISettings(os_security_key="test-key"))
        assert keyed.get("/info").json()["user_isolation"] is False

    def test_on_without_auth(self):
        body = _build_client(user_isolation=True).get("/info").json()
        assert (body["auth_mode"], body["user_isolation"]) == ("none", True)

    def test_on_with_a_security_key(self):
        client = _build_client(user_isolation=True, settings=AgnoAPISettings(os_security_key="test-key"))
        body = client.get("/info").json()  # still unauthenticated: a client needs it before it has a key
        assert (body["auth_mode"], body["user_isolation"]) == ("security_key", True)

    def test_on_under_jwt_via_the_top_level_flag(self):
        client = _build_client(
            user_isolation=True,
            authorization=True,
            authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        )
        body = client.get("/info").json()
        assert (body["auth_mode"], body["user_isolation"]) == ("jwt", True)

    def test_on_under_jwt_via_the_legacy_config_flag(self):
        """The released spelling, AuthorizationConfig(user_isolation=True), reports the same."""
        client = _build_client(
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=[JWT_SECRET], algorithm="HS256", user_isolation=True
            ),
        )
        assert client.get("/info").json()["user_isolation"] is True

    def test_a_directory_alone_does_not_turn_it_on(self):
        """user_directory and user_isolation are separate switches; the roster is not isolation."""
        import os
        import tempfile

        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=os.path.join(tempfile.mkdtemp(), "info.db"))
        body = _build_client(db=db, user_directory=True).get("/info").json()
        assert body["user_isolation"] is False


class TestGetEffectiveAuthMode:
    def test_none_when_settings_missing(self):
        assert get_effective_auth_mode(settings=None) == "none"

    def test_none_when_nothing_configured(self):
        assert get_effective_auth_mode(settings=AgnoAPISettings()) == "none"

    def test_security_key(self):
        settings = AgnoAPISettings(os_security_key="test-key")
        assert get_effective_auth_mode(settings=settings) == "security_key"

    def test_jwt_via_authorization_flag(self):
        settings = AgnoAPISettings(os_security_key="test-key")
        assert get_effective_auth_mode(settings=settings, authorization=True) == "jwt"

    def test_jwt_via_settings_flag(self):
        settings = AgnoAPISettings(authorization_enabled=True)
        assert get_effective_auth_mode(settings=settings) == "jwt"

    def test_jwt_via_jwks_env_var(self, monkeypatch):
        monkeypatch.setenv("JWT_JWKS_FILE", "/tmp/jwks.json")
        assert get_effective_auth_mode(settings=AgnoAPISettings()) == "jwt"
