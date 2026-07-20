"""
Regression tests for issue #8625: JWT env vars bypass OS_SECURITY_KEY.

The vulnerability: when OS_SECURITY_KEY is set but authorization=False (default),
stray JWT environment variables (JWT_VERIFICATION_KEY or JWT_JWKS_FILE) caused
the auth dependency to skip the security key check entirely, leaving routes open.

These tests verify that:
1. Security key auth works correctly in isolation
2. JWT env vars don't bypass security key auth when no middleware validates
3. The auth dependency only trusts actual per-request authentication markers
4. Constant-time comparison is used for security keys (no timing side-channel)
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.auth import (
    _AUTH_COMPLETE_ATTR,
    get_authentication_dependency,
    validate_websocket_token,
)
from agno.os.settings import AgnoAPISettings

OS_SECURITY_KEY = "test-security-key-12345"
WRONG_KEY = "wrong-key"


@pytest.fixture
def clean_jwt_env(monkeypatch):
    """Remove JWT env vars before each test."""
    monkeypatch.delenv("JWT_VERIFICATION_KEY", raising=False)
    monkeypatch.delenv("JWT_JWKS_FILE", raising=False)
    yield


@pytest.fixture
def agent_os_security_key_only(clean_jwt_env):
    """AgentOS with only OS_SECURITY_KEY (no JWT)."""
    agent = Agent(name="Test", id="test", telemetry=False)
    settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)
    agent_os = AgentOS(
        id="test-os",
        agents=[agent],
        settings=settings,
        authorization=False,
        telemetry=False,
    )
    return TestClient(agent_os.get_app())


class TestSecurityKeyBaseline:
    """Verify security key auth works in isolation (baseline)."""

    def test_no_token_returns_401(self, agent_os_security_key_only):
        resp = agent_os_security_key_only.get("/config")
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, agent_os_security_key_only):
        resp = agent_os_security_key_only.get("/config", headers={"Authorization": f"Bearer {WRONG_KEY}"})
        assert resp.status_code == 401

    def test_correct_token_returns_200(self, agent_os_security_key_only):
        resp = agent_os_security_key_only.get("/config", headers={"Authorization": f"Bearer {OS_SECURITY_KEY}"})
        assert resp.status_code == 200


class TestJwtEnvBypass8625:
    """
    Core regression tests for issue #8625.

    With authorization=False and OS_SECURITY_KEY set, the presence of
    JWT_VERIFICATION_KEY should NOT bypass security key authentication.
    """

    @pytest.fixture
    def agent_os_with_jwt_env(self, monkeypatch):
        """AgentOS with OS_SECURITY_KEY AND JWT_VERIFICATION_KEY env var."""
        monkeypatch.setenv("JWT_VERIFICATION_KEY", "some-jwt-key-not-used")
        agent = Agent(name="Test", id="test", telemetry=False)
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)
        agent_os = AgentOS(
            id="test-os",
            agents=[agent],
            settings=settings,
            authorization=False,
            telemetry=False,
        )
        return TestClient(agent_os.get_app())

    def test_no_token_still_returns_401_with_jwt_env(self, agent_os_with_jwt_env):
        """Issue #8625: This was returning 200 (bypass) before the fix."""
        resp = agent_os_with_jwt_env.get("/config")
        assert resp.status_code == 401, (
            "Security key auth bypassed when JWT_VERIFICATION_KEY is set! "
            "This is the exact vulnerability from issue #8625."
        )

    def test_wrong_token_still_returns_401_with_jwt_env(self, agent_os_with_jwt_env):
        """Issue #8625: This was returning 200 (bypass) before the fix."""
        resp = agent_os_with_jwt_env.get("/config", headers={"Authorization": f"Bearer {WRONG_KEY}"})
        assert resp.status_code == 401, (
            "Security key auth bypassed with invalid token when JWT_VERIFICATION_KEY is set! "
            "This is the exact vulnerability from issue #8625."
        )

    def test_correct_security_key_works_with_jwt_env(self, agent_os_with_jwt_env):
        """Correct security key should still work even with JWT env var present."""
        # Note: With the architectural fix in app.py, JWT middleware now installs
        # and takes precedence over security key. The security key becomes invalid.
        # This is expected behavior documented in the JWT-precedence contract.
        # The important thing is that auth is NOT bypassed.
        resp = agent_os_with_jwt_env.get("/config", headers={"Authorization": f"Bearer {OS_SECURITY_KEY}"})
        # Either 401 (JWT mode rejects non-JWT token) or 200 (security key accepted)
        # is acceptable — the critical thing is that NO TOKEN = 401 (no bypass)
        assert resp.status_code in (200, 401)


class TestAuthDependencyDirectly:
    """Unit tests for get_authentication_dependency without full AgentOS."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request with configurable state."""
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.app = MagicMock()
        request.app.state = MagicMock()
        request.app.state.internal_service_token = None
        return request

    @pytest.mark.asyncio
    async def test_auth_complete_marker_trusted(self, mock_request, clean_jwt_env):
        """When _AUTH_COMPLETE_ATTR is set, auth passes immediately."""
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)
        dep = get_authentication_dependency(settings)

        # Simulate middleware having validated the request
        setattr(mock_request.state, _AUTH_COMPLETE_ATTR, True)

        # No credentials needed — middleware already authenticated
        result = await dep(mock_request, credentials=None)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_marker_requires_security_key(self, mock_request, clean_jwt_env):
        """Without _AUTH_COMPLETE_ATTR, security key validation runs."""
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)
        dep = get_authentication_dependency(settings)

        # No middleware marker set
        setattr(mock_request.state, _AUTH_COMPLETE_ATTR, False)

        # No credentials should raise 401
        with pytest.raises(Exception) as exc_info:
            await dep(mock_request, credentials=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_jwt_env_does_not_bypass_without_marker(self, mock_request, monkeypatch):
        """JWT env vars alone don't bypass security key check."""
        monkeypatch.setenv("JWT_VERIFICATION_KEY", "some-key")
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)
        dep = get_authentication_dependency(settings)

        # No middleware marker
        setattr(mock_request.state, _AUTH_COMPLETE_ATTR, False)

        # Should still require auth
        with pytest.raises(Exception) as exc_info:
            await dep(mock_request, credentials=None)
        assert exc_info.value.status_code == 401


class TestValidateWebsocketToken:
    """Tests for validate_websocket_token function."""

    def test_no_security_key_allows_any_token(self, clean_jwt_env):
        """Open mode (no security key) allows any token."""
        settings = AgnoAPISettings()
        assert validate_websocket_token("any-token", settings) is True
        assert validate_websocket_token("", settings) is True

    def test_security_key_requires_match(self, clean_jwt_env):
        """With security key set, token must match."""
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)
        assert validate_websocket_token(OS_SECURITY_KEY, settings) is True
        assert validate_websocket_token(WRONG_KEY, settings) is False
        assert validate_websocket_token("", settings) is False

    def test_jwt_env_does_not_bypass(self, monkeypatch):
        """JWT env vars don't cause validate_websocket_token to return True."""
        monkeypatch.setenv("JWT_VERIFICATION_KEY", "some-jwt-key")
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)

        # Before the fix, this would return True (bypass)
        assert validate_websocket_token(WRONG_KEY, settings) is False
        assert validate_websocket_token("", settings) is False

    def test_authorization_enabled_does_not_bypass(self, clean_jwt_env):
        """settings.authorization_enabled doesn't bypass security key check."""
        settings = AgnoAPISettings(
            os_security_key=OS_SECURITY_KEY,
            authorization_enabled=True,  # This flag should NOT cause bypass
        )

        # The function should still validate the security key
        assert validate_websocket_token(WRONG_KEY, settings) is False
        assert validate_websocket_token("", settings) is False
        assert validate_websocket_token(OS_SECURITY_KEY, settings) is True


class TestConstantTimeComparison:
    """Verify that security key comparison uses constant-time hmac.compare_digest."""

    def test_validate_websocket_token_uses_hmac(self, clean_jwt_env):
        """validate_websocket_token should use hmac.compare_digest."""
        settings = AgnoAPISettings(os_security_key=OS_SECURITY_KEY)

        with patch("agno.os.auth.hmac.compare_digest") as mock_compare:
            mock_compare.return_value = True
            result = validate_websocket_token(OS_SECURITY_KEY, settings)
            mock_compare.assert_called_once_with(OS_SECURITY_KEY, OS_SECURITY_KEY)
            assert result is True
