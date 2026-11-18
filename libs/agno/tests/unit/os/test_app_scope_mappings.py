"""Application scope mappings shared by authorization and discovery."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz.admin_router import get_roles_router
from agno.os.config import AuthorizationConfig
from agno.os.interfaces.base import BaseInterface
from agno.os.middleware.jwt import AuthMiddleware


class ScopedInterface(BaseInterface):
    type = "scope-test"
    prefix = "/custom-interface"

    def get_router(self, **kwargs):
        router = APIRouter(prefix=self.prefix)

        @router.get("/status")
        def status():
            return {"status": "ok"}

        return router

    def get_scope_mappings(self):
        return {f"GET {self.prefix}/status": ["custom:read"]}


class SelfAuthenticatingInterface(ScopedInterface):
    prefix = "/signed-interface"
    authenticates_own_requests = True


@pytest.mark.parametrize("company", [False, True])
def test_assembly_builds_one_map_for_all_consumers(tmp_path, monkeypatch, company):
    from datetime import datetime, timedelta, timezone

    import jwt

    from agno.os import auth, scopes
    from agno.os.middleware import jwt as jwt_middleware

    build = Mock(wraps=scopes.get_default_scope_mappings)
    monkeypatch.setattr(scopes, "get_default_scope_mappings", build)
    monkeypatch.setattr(auth, "get_default_scope_mappings", build)
    monkeypatch.setattr(jwt_middleware, "get_default_scope_mappings", build)
    secret = "shared-scope-map-test-secret-at-least-32-bytes"
    os = AgentOS(
        id="scope-map-test",
        db=SqliteDb(db_file=str(tmp_path / "app.db")),
        company=CompanyConfig() if company else None,
        interfaces=[ScopedInterface(), SelfAuthenticatingInterface()],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[secret], algorithm="HS256"),
        telemetry=False,
    )
    app = os.get_app()
    mappings = app.state.scope_mappings
    build.assert_called_once_with(company=company)
    assert ("GET /company/products" in mappings) is company
    assert mappings["GET /custom-interface/status"] == ["custom:read"]
    assert "GET /signed-interface/status" not in mappings

    router = get_roles_router(MagicMock())
    app.dependency_overrides[router.dependencies[0].dependency] = lambda: "admin"
    app.include_router(router)

    def headers(granted):
        token = jwt.encode(
            {"sub": "user", "aud": os.id, "scopes": granted, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            secret,
            algorithm="HS256",
        )
        return {"Authorization": "Bearer " + token}

    with TestClient(app) as client:
        assert client.get("/signed-interface/status").status_code == 200
        assert client.get("/custom-interface/status", headers=headers([])).status_code == 403
        assert client.get("/custom-interface/status", headers=headers(["custom:read"])).status_code == 200
        response = client.get("/authz/scopes", headers=headers(["agent_os:admin"]))
        assert response.status_code == 200
        catalog = {item["raw"] for item in response.json()}
        assert "custom:read" in catalog
        assert {scope for scope in catalog if scope.startswith("products:")} == (
            {"products:read", "products:write", "products:delete"} if company else set()
        )
        middleware = app.middleware_stack
        while not isinstance(middleware, AuthMiddleware):
            middleware = middleware.app
        assert middleware.scope_mappings is mappings
        assert middleware.service_account_scope_mappings is mappings

        authenticate = AsyncMock(return_value=None)
        monkeypatch.setattr(auth, "authenticate_service_account_request", authenticate)
        request = Request(
            {"type": "http", "app": app, "method": "GET", "path": "/custom-interface/status", "headers": []}
        )
        assert asyncio.run(auth._authenticate_service_account(request, "agno_pat_test"))
        assert authenticate.call_args.kwargs["scope_mappings"] is mappings

        os.resync(app)
        assert app.state.scope_mappings is mappings
        assert client.get("/custom-interface/status", headers=headers([])).status_code == 403
    build.assert_called_once_with(company=company)


def test_shared_map_does_not_enable_jwt_authorization(tmp_path):
    from agno.os.settings import AgnoAPISettings

    app = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "key-only.db")),
        company=CompanyConfig(),
        settings=AgnoAPISettings(os_security_key="test-key"),
        telemetry=False,
    ).get_app()
    with TestClient(app) as client:
        assert client.get("/company/products", headers={"Authorization": "Bearer test-key"}).status_code == 200
        middleware = app.middleware_stack
        while not isinstance(middleware, AuthMiddleware):
            middleware = middleware.app
        assert middleware.authorization is False
        assert middleware.scope_mappings is app.state.scope_mappings
        assert middleware.service_account_scope_mappings is app.state.scope_mappings
