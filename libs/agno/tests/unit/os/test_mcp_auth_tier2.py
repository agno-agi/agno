"""Unit tests for Tier 2 of mcp_auth: bring-your-own authorization server.

Phase 3 of the mcp_auth spec. A ``RemoteAuthProvider`` (the shape of WorkOS
``AuthKitProvider``) with a local token verifier stands in for the external AS, so the
provider-agnostic seam is proven offline:

  1. The exemption surface is minimal -- the MCP path plus the protected-resource
     metadata; the AS endpoints live on the external domain and nothing else on the
     parent app is un-authenticated.
  2. Discovery advertises the external authorization server; ``/mcp`` challenges.
  3. Externally-issued tokens verify through the provider and bridge onto
     request.state; PATs keep working via MultiAuth.
  4. ``AuthKitProvider`` itself constructs against this seam (no network at build
     time) and serves the same minimal surface.

The live proof against a real WorkOS AuthKit tenant (DCR + JWKS over the network) is a
deployment test, not a unit test -- plan-v0.md Phase 3 tracks it.
"""

import pytest

pytest.importorskip("fastmcp")

import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from uuid import uuid4  # noqa: E402

import httpx  # noqa: E402
from fastmcp.server.auth import RemoteAuthProvider  # noqa: E402
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier  # noqa: E402
from pydantic import AnyHttpUrl  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.schemas.service_accounts import ServiceAccount  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.mcp_auth import mcp_auth_route_paths  # noqa: E402
from agno.os.service_accounts import generate_token  # noqa: E402

_MCP_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_EXTERNAL_AS = "https://auth.example.com/"
_EXTERNAL_TOKEN = "external-as-issued-token"


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


async def _ok_tool(message: str) -> str:
    return message


def _tier2_provider(tokens=None, **provider_kwargs) -> RemoteAuthProvider:
    """An external-AS resource server: local verification, remote authorization."""
    verifier = StaticTokenVerifier(
        tokens=tokens or {_EXTERNAL_TOKEN: {"client_id": "external-user@example.com", "scopes": ["agents:run"]}}
    )
    return RemoteAuthProvider(
        token_verifier=verifier,
        authorization_servers=[AnyHttpUrl(_EXTERNAL_AS)],
        base_url="http://localhost",
        **provider_kwargs,
    )


def _capture_state_middleware(captured: dict):
    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", "MISSING")
                captured["service_account_name"] = getattr(request.state, "service_account_name", None)
                captured["authorization_enabled"] = getattr(request.state, "authorization_enabled", None)
            return response

    return _CaptureState


def _os(provider, db=None, **config_kwargs) -> AgentOS:
    return AgentOS(
        agents=[_agent()],
        db=db,
        mcp_auth=provider,
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False, **config_kwargs),
    )


@asynccontextmanager
async def _http_client(os: AgentOS):
    app = os.get_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client


def test_tier2_exemption_surface_is_minimal():
    """A RemoteAuthProvider serves no AS endpoints locally: only the MCP path and the
    protected-resource metadata are exempted from the parent auth layer."""
    os = _os(_tier2_provider())
    paths = mcp_auth_route_paths(os._get_mcp_auth_provider())
    assert "/mcp" in paths
    assert any(p.startswith("/.well-known/oauth-protected-resource") for p in paths)
    for as_path in ("/authorize", "/token", "/register", "/revoke"):
        assert as_path not in paths


async def test_tier2_discovery_points_at_external_as():
    async with _http_client(_os(_tier2_provider())) as client:
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        challenge = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)

    assert metadata.status_code == 200
    payload = metadata.json()
    assert payload["resource"].rstrip("/") == "http://localhost/mcp"
    assert [s.rstrip("/") for s in payload["authorization_servers"]] == [_EXTERNAL_AS.rstrip("/")]
    assert challenge.status_code == 401
    assert "resource_metadata=" in challenge.headers.get("www-authenticate", "")


async def test_tier2_external_token_bridges_identity():
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", None)
                captured["scopes"] = getattr(request.state, "scopes", None)
            return response

    os = _os(_tier2_provider(), middleware=[Middleware(_CaptureState)])
    async with _http_client(os) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {_EXTERNAL_TOKEN}"}
        )

    assert response.status_code == 200
    assert captured["user_id"] == "external-user@example.com"
    assert captured["scopes"] == ["agents:run"]


async def test_tier2_token_cannot_forge_trust_markers():
    """An external token that reflects agno's internal markers into its claims must not
    have them honored: agno_service_account and agno_authorization_enabled are stripped, so
    a Tier-2 caller cannot forge a service-account identity or disable scope enforcement."""
    captured: dict = {}
    tokens = {
        "forged": {
            "client_id": "external-user@example.com",
            "scopes": ["agents:run"],
            "agno_service_account": "admin",
            "agno_authorization_enabled": False,
        }
    }
    os = _os(_tier2_provider(tokens=tokens), middleware=[Middleware(_capture_state_middleware(captured))])
    async with _http_client(os) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": "Bearer forged"}
        )

    assert response.status_code == 200
    assert captured["user_id"] == "external-user@example.com"
    assert captured["service_account_name"] is None
    # The RBAC-off flag was stripped; the bridge falls back to enforcing (True).
    assert captured["authorization_enabled"] is True


async def test_tier2_token_asserting_reserved_principal_is_rejected():
    """An external token claiming a reserved sub (__oauth__:/sa:/__scheduler__) is rejected
    at verify -- it never gets a session. A cryptographically-valid external token is not
    401'd by fastmcp, so if the bridge merely declined to stamp the reserved identity the
    request would still reach the tools unauthenticated (custom tools running with
    user_id=None, skipping the authorize() allowlist). Refusing it at verify closes that path."""
    captured: dict = {}
    tokens = {
        "impersonator": {
            "client_id": "external-user@example.com",
            "scopes": ["agents:run"],
            "sub": "__oauth__:victim",
            "agno_mcp_internal_issuer": True,
        }
    }
    os = _os(_tier2_provider(tokens=tokens), middleware=[Middleware(_capture_state_middleware(captured))])
    async with _http_client(os) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": "Bearer impersonator"}
        )

    # Rejected at verify: no session, and certainly no impersonation.
    assert response.status_code == 401
    assert captured.get("user_id") in (None, "MISSING")


async def test_tier2_required_scopes_do_not_block_pat(tmp_path):
    """A Tier-2 provider configured with required_scopes must not 403 coexisting PAT
    bearers: PATs carry agno resource scopes, never the provider's OAuth scopes, so the
    provider's required_scopes are enforced only against its own tokens (inside verify),
    not applied route-wide to every verified bearer."""
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "tier2-scopes.db"))
    plaintext, token_hash, token_prefix = generate_token()
    db.create_service_account(
        ServiceAccount(
            id=str(uuid4()),
            name="tier2-scoped-bot",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["agents:run"],
            created_at=int(time.time()),
        ).to_dict()
    )
    provider = _tier2_provider()
    # The deployer's provider requires a scope PATs never carry; without the fix MultiAuth
    # would inherit it route-wide and 403 the PAT.
    provider.required_scopes = ["openid"]
    async with _http_client(_os(provider, db=db)) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {plaintext}"}
        )
    assert response.status_code == 200


async def test_tier2_invalid_token_rejected():
    async with _http_client(_os(_tier2_provider())) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": "Bearer not-issued-by-the-as"}
        )
    assert response.status_code == 401


async def test_tier2_pat_coexistence(tmp_path):
    from agno.db.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "tier2.db"))
    plaintext, token_hash, token_prefix = generate_token()
    db.create_service_account(
        ServiceAccount(
            id=str(uuid4()),
            name="tier2-bot",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=["agents:run"],
            created_at=int(time.time()),
        ).to_dict()
    )
    async with _http_client(_os(_tier2_provider(), db=db)) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {plaintext}"}
        )
    assert response.status_code == 200


async def test_tier2_info_reports_external_as():
    async with _http_client(_os(_tier2_provider())) as client:
        response = await client.get("/info")
    payload = response.json()
    # auth_mode is the REST/WS posture (open here); the external AS is reported under mcp.oauth.
    assert payload["auth_mode"] == "none"
    assert [s.rstrip("/") for s in payload["mcp"]["oauth"]["authorization_servers"]] == [_EXTERNAL_AS.rstrip("/")]


def test_authkit_provider_fits_the_seam():
    """The documented Tier-2 default constructs offline and serves the same minimal
    surface (its AS endpoints live on the AuthKit domain)."""
    try:
        from fastmcp.server.auth.providers.workos import AuthKitProvider
    except ImportError:  # pragma: no cover
        pytest.skip("workos provider not available in this fastmcp build")

    provider = AuthKitProvider(authkit_domain="https://example-tenant.authkit.app", base_url="http://localhost")
    paths = [getattr(r, "path", "") for r in provider.get_routes(mcp_path="/mcp")]
    assert any(p.startswith("/.well-known/oauth-protected-resource") for p in paths)
    for as_path in ("/authorize", "/token", "/register"):
        assert as_path not in paths
