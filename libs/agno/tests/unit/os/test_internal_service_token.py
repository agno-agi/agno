"""Tests for internal service token auth bypass in security key auth and JWT middleware."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agno.os.auth import get_authentication_dependency
from agno.os.settings import AgnoAPISettings


class TestInternalServiceTokenInAuth:
    """Test that the internal service token bypasses security key validation."""

    @pytest.fixture
    def app_with_security_key(self):
        settings = AgnoAPISettings(os_security_key="secret-key")
        auth_dep = get_authentication_dependency(settings)

        app = FastAPI()
        app.state.internal_service_token = "internal-tok-123"

        @app.get("/test")
        async def test_endpoint(request: Request, _=pytest.importorskip("fastapi").Depends(auth_dep)):
            authenticated = getattr(request.state, "authenticated", False)
            scopes = getattr(request.state, "scopes", [])
            return {"authenticated": authenticated, "scopes": scopes}

        return app

    def test_internal_token_bypasses_security_key(self, app_with_security_key):
        client = TestClient(app_with_security_key)
        resp = client.get("/test", headers={"Authorization": "Bearer internal-tok-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert "agent_os:admin" in data["scopes"]

    def test_wrong_token_rejected(self, app_with_security_key):
        client = TestClient(app_with_security_key)
        resp = client.get("/test", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 401

    def test_security_key_still_works(self, app_with_security_key):
        client = TestClient(app_with_security_key)
        resp = client.get("/test", headers={"Authorization": "Bearer secret-key"})
        assert resp.status_code == 200

    def test_no_internal_token_set(self):
        settings = AgnoAPISettings(os_security_key="secret-key")
        auth_dep = get_authentication_dependency(settings)

        app = FastAPI()
        # No internal_service_token on app.state

        @app.get("/test")
        async def test_endpoint(_=pytest.importorskip("fastapi").Depends(auth_dep)):
            return {"ok": True}

        client = TestClient(app)
        # Should fail with wrong token
        resp = client.get("/test", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
        # Should pass with security key
        resp = client.get("/test", headers={"Authorization": "Bearer secret-key"})
        assert resp.status_code == 200
