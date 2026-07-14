"""Unit tests for OAuth on the AgentOS MCP endpoint (``AgentOS(mcp_auth=...)``).

Phase 1 of the mcp_auth spec, proven against fastmcp's ``InMemoryOAuthProvider``:

  1. The provider's discovery + OAuth routes resolve at the public root through the
     existing root mount (no parent-side route code), and survive a router resync.
  2. ``POST /mcp`` without a token gets the RFC 9728 challenge
     (401 + ``WWW-Authenticate: Bearer resource_metadata="..."``).
  3. The full DCR -> authorize -> token flow issues a token that runs MCP requests,
     with the identity bridged onto request.state.
  4. PAT coexistence: ``agno_pat_`` bearers still authenticate via MultiAuth.
  5. An OAuth-only deployment is not treated as an open server (no localhost-only host
     guard); /info keeps ``auth_mode`` reporting the REST/WS posture ("none" here) with the
     OAuth discovery details under ``mcp.oauth``.
  6. ``mcp_auth`` unset leaves the existing paths byte-for-byte unchanged (covered by
     the pre-existing suites in test_mcp_server.py; asserted structurally here).
"""

import pytest

pytest.importorskip("fastmcp")

import base64  # noqa: E402
import hashlib  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402
from uuid import uuid4  # noqa: E402

import httpx  # noqa: E402
from fastmcp.server.auth import AccessToken  # noqa: E402
from fastmcp.server.auth.auth import ClientRegistrationOptions  # noqa: E402
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.schemas.service_accounts import ServiceAccount  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.mcp import _mcp_server_is_open, get_mcp_server  # noqa: E402
from agno.os.mcp_auth import (  # noqa: E402
    AUTHORIZATION_ENABLED_CLAIM,
    SERVICE_ACCOUNT_CLAIM,
    JWTBearerTokenVerifier,
    MCPIdentityBridgeMiddleware,
    ServiceAccountTokenVerifier,
    mcp_auth_route_paths,
)
from agno.os.service_accounts import generate_token  # noqa: E402
from agno.os.settings import AgnoAPISettings  # noqa: E402

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
_REDIRECT_URI = "http://localhost:9999/callback"


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


async def _ok_tool(message: str) -> str:
    return message


def _oauth_provider(**kwargs) -> InMemoryOAuthProvider:
    # DCR is off by default on the in-memory provider; connector clients need it.
    kwargs.setdefault("base_url", "http://localhost")
    kwargs.setdefault("client_registration_options", ClientRegistrationOptions(enabled=True))
    return InMemoryOAuthProvider(**kwargs)


def _oauth_os(provider=None, db=None, security_key=None, **config_kwargs) -> AgentOS:
    return AgentOS(
        agents=[_agent()],
        db=db,
        mcp_auth=provider or _oauth_provider(),
        settings=AgnoAPISettings(os_security_key=security_key),
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False, **config_kwargs),
    )


def _sqlite_db(tmp_path):
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=str(tmp_path / "mcp_oauth_test.db"))


def _mint_pat(db, name="mcp-bot", scopes=None):
    plaintext, token_hash, token_prefix = generate_token()
    account = ServiceAccount(
        id=str(uuid4()),
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=scopes or ["agents:run"],
        created_at=int(time.time()),
    )
    db.create_service_account(account.to_dict())
    return plaintext


def _bearer(token: str) -> dict:
    return {**_MCP_HEADERS, "Authorization": f"Bearer {token}"}


@asynccontextmanager
async def _http_client(os: AgentOS):
    """Drive the full AgentOS app so the parent middleware and the mount both run."""
    app = os.get_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client


async def _obtain_oauth_token(client: httpx.AsyncClient, scope: str = "agents:run") -> tuple:
    """Run the connector dance by hand: DCR -> authorize (PKCE) -> token exchange."""
    registration = await client.post(
        "/register",
        json={
            "redirect_uris": [_REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": scope,
        },
    )
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    authorization = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": _REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s",
            "scope": scope,
        },
        follow_redirects=False,
    )
    assert authorization.status_code in (302, 307), authorization.text
    code = parse_qs(urlparse(authorization.headers["location"]).query)["code"][0]

    token_response = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token_response.status_code == 200, token_response.text
    return token_response.json()["access_token"], client_id


# ==================== Constructor validation ====================


def test_mcp_auth_requires_mcp_server():
    with pytest.raises(ValueError, match="mcp_server=True"):
        AgentOS(agents=[_agent()], mcp_auth=_oauth_provider())


def test_mcp_auth_builtin_requires_postgres(monkeypatch):
    """AgentOSBuiltinAuth.from_env() (unbound) on an AgentOS with no db errors clearly
    when resolved, rather than 500ing later."""
    from agno.os import AgentOSBuiltinAuth

    monkeypatch.setenv("AGENTOS_URL", "https://my-os.example.com")
    monkeypatch.setenv("MCP_CONNECT_SECRET", "test-connect-secret")
    os = AgentOS(agents=[_agent()], mcp_server=True, mcp_auth=AgentOSBuiltinAuth.from_env())
    with pytest.raises(ValueError, match="needs a database"):
        os.get_app()


def test_mcp_auth_builtin_never_binds_an_agent_db(tmp_path, monkeypatch):
    """The built-in AS binds only the AgentOS-level db (os.db) -- never an agent's db,
    which is that agent's data store, not the platform's OAuth state. With no AgentOS db
    but an agent that has one, resolution still errors."""
    from agno.os import AgentOSBuiltinAuth

    monkeypatch.setenv("AGENTOS_URL", "https://my-os.example.com")
    monkeypatch.setenv("MCP_CONNECT_SECRET", "test-connect-secret")
    agent_with_db = Agent(id="a", name="A", db=_sqlite_db(tmp_path))
    os = AgentOS(agents=[agent_with_db], mcp_server=True, mcp_auth=AgentOSBuiltinAuth.from_env())
    with pytest.raises(ValueError, match="needs a database"):
        os.get_app()


def test_mcp_auth_string_rejected_with_hint():
    """The string form is gone: mcp_auth takes an object, and the error points at it."""
    os = AgentOS(agents=[_agent()], mcp_server=True, mcp_auth="builtin")
    with pytest.raises(TypeError, match="AgentOSBuiltinAuth"):
        os.get_app()


# ==================== Manual auth middleware on base_app ====================


def _manual_jwt_base_app(**mw_kwargs):
    from fastapi import FastAPI

    from agno.os.middleware.jwt import JWTMiddleware

    base = FastAPI()
    base.add_middleware(JWTMiddleware, verification_keys=["a-secret"], algorithm="HS256", **mw_kwargs)
    return base


def _base_app_oauth_os(base_app, provider=None):
    return AgentOS(
        base_app=base_app,
        agents=[_agent()],
        mcp_auth=provider or _oauth_provider(),
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
    )


def test_manual_auth_middleware_without_exemptions_fails_fast():
    """A JWT/auth middleware installed manually on a base_app carries its own exclusions
    that AgentOS can't amend; without the OAuth routes exempted it 401s connector discovery
    silently. Fail fast at get_app with the exact paths, not a broken flow."""
    os = _base_app_oauth_os(_manual_jwt_base_app())
    with pytest.raises(ValueError, match="excluded_route_paths"):
        os.get_app()


async def test_manual_auth_middleware_with_exemptions_works():
    """The documented fix: wiring os's exempt paths into the manual middleware's
    excluded_route_paths makes the OAuth flow work -- while REST stays protected."""
    provider = _oauth_provider()
    exempt = mcp_auth_route_paths(provider)
    defaults = ["/", "/health", "/info", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]
    base = _manual_jwt_base_app(excluded_route_paths=[*defaults, *exempt])
    os = _base_app_oauth_os(base, provider=provider)

    async with _http_client(os) as client:
        well_known = await client.get("/.well-known/oauth-authorization-server")
        token, _ = await _obtain_oauth_token(client)
        mcp = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(token))
        challenge = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)
        rest_unauthed = await client.get("/agents")  # manual JWT still guards REST

    assert well_known.status_code == 200
    assert mcp.status_code == 200
    assert challenge.status_code == 401 and "www-authenticate" in challenge.headers
    assert rest_unauthed.status_code == 401


def test_mcp_auth_exempt_paths_helper():
    """The public helper lists the routes to exempt; empty when mcp_auth is unset."""
    os = _oauth_os()
    paths = os.mcp_auth_exempt_paths()
    for expected in ("/mcp", "/authorize", "/token", "/register"):
        assert expected in paths

    no_oauth = AgentOS(
        agents=[_agent()],
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
    )
    assert no_oauth.mcp_auth_exempt_paths() == []


def test_agentos_managed_auth_does_not_trip_the_guard(tmp_path):
    """When AgentOS installs the auth middleware itself (security key / JWT), it already
    carries the exemptions, so the composition guard must not fire."""
    db = _sqlite_db(tmp_path)
    os = _oauth_os(db=db, security_key="k")
    os.get_app()  # no raise; exemptions are on AgentOS's own middleware
    assert any(m.cls.__name__ == "AuthMiddleware" for m in os.get_app().user_middleware)


def test_mcp_auth_rejects_non_provider():
    os = AgentOS(agents=[_agent()], mcp_server=True, mcp_auth=object())
    with pytest.raises(TypeError, match="AuthProvider"):
        os.get_app()


# ==================== Discovery routes ====================


async def test_well_known_resolves_at_public_root():
    """The provider's discovery routes are served by the sub-app through the root mount --
    no parent-side route code -- and advertise the provider's issuer."""
    async with _http_client(_oauth_os()) as client:
        authorization_server = await client.get("/.well-known/oauth-authorization-server")
        protected_resource = await client.get("/.well-known/oauth-protected-resource/mcp")

    assert authorization_server.status_code == 200
    assert authorization_server.json()["issuer"].rstrip("/") == "http://localhost"
    assert protected_resource.status_code == 200
    assert protected_resource.json()["resource"].rstrip("/") == "http://localhost/mcp"


async def test_well_known_survives_router_resync():
    """_reprovision_routers strips parent routes on resync; the provider routes live in
    the mounted sub-app, so discovery keeps working."""
    os = _oauth_os()
    app = os.get_app()
    os._reprovision_routers(app)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            response = await client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200


def test_provider_route_paths_are_exempted_exactly():
    """The AuthMiddleware exemption set is derived from the provider routes: the MCP path
    plus every OAuth/discovery endpoint, as exact paths (no wildcards)."""
    os = _oauth_os()
    paths = mcp_auth_route_paths(os._get_mcp_auth_provider())
    for expected in (
        "/mcp",
        "/authorize",
        "/token",
        "/register",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp",
    ):
        assert expected in paths, f"{expected} missing from {paths}"
    assert not any("*" in p for p in paths)


# ==================== The 401 challenge ====================


async def test_mcp_401_challenge_carries_resource_metadata():
    async with _http_client(_oauth_os()) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)

    assert response.status_code == 401
    challenge = response.headers.get("www-authenticate", "")
    assert challenge.startswith("Bearer")
    assert "resource_metadata=" in challenge


# ==================== The OAuth flow end to end ====================


async def test_oauth_flow_issues_token_that_runs_mcp():
    """DCR -> authorize -> token -> initialize, with the identity bridged to request.state."""
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", None)
                captured["scopes"] = getattr(request.state, "scopes", None)
                captured["authorization_enabled"] = getattr(request.state, "authorization_enabled", None)
            return response

    os = _oauth_os(middleware=[Middleware(_CaptureState)])
    async with _http_client(os) as client:
        token, client_id = await _obtain_oauth_token(client)
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(token))

    assert response.status_code == 200
    # The in-memory provider's tokens carry no ``sub`` claim, so the bridge falls back
    # to the DCR client id as the caller identity.
    assert captured["user_id"] == client_id
    assert captured["scopes"] == ["agents:run"]
    assert captured["authorization_enabled"] is True


async def test_oauth_invalid_token_rejected():
    async with _http_client(_oauth_os()) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer("not-a-real-token"))
    assert response.status_code == 401


# ==================== The authorize gate under mcp_auth ====================


async def test_authorize_gate_sees_bridged_identity():
    """The gate runs inside fastmcp auth, after the bridge: a predicate keyed on the
    OAuth identity passes for a valid token."""
    os = _oauth_os(authorize=lambda user_id: bool(user_id))
    async with _http_client(os) as client:
        token, _ = await _obtain_oauth_token(client)
        allowed = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(token))
    assert allowed.status_code == 200


async def test_authorize_gate_still_rejects():
    os = _oauth_os(authorize=lambda user_id: False)
    async with _http_client(os) as client:
        token, _ = await _obtain_oauth_token(client)
        rejected = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(token))
    assert rejected.status_code == 401
    assert "not authorized" in rejected.text.lower()


async def test_authorize_gate_defers_unauthenticated_to_the_challenge():
    """An unauthenticated request must still get the RFC 9728 challenge (connector
    discovery depends on it), not a bare 401 from the authorize gate."""
    os = _oauth_os(authorize=lambda user_id: False)
    async with _http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers.get("www-authenticate", "")


def test_authorize_with_mcp_auth_does_not_warn(monkeypatch):
    """The authorize-without-JWT warning is about a missing identity source; mcp_auth IS
    an identity source, so it must not fire."""
    warnings: list = []
    monkeypatch.setattr("agno.utils.log.log_warning", lambda msg, *a, **kw: warnings.append(msg))
    get_mcp_server(_oauth_os(authorize=lambda user_id: True))
    assert not [w for w in warnings if "authorization=False" in w]


# ==================== PAT coexistence (MultiAuth) ====================


async def test_pat_still_works_with_mcp_auth(tmp_path):
    """Enabling OAuth must not break the deployment's existing PAT clients: the provider
    is composed with the service-account verifier, and the bridge restores the full
    service-account identity."""
    db = _sqlite_db(tmp_path)
    pat = _mint_pat(db)
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", None)
                captured["service_account_name"] = getattr(request.state, "service_account_name", None)
            return response

    os = _oauth_os(db=db, middleware=[Middleware(_CaptureState)])
    async with _http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(pat))

    assert response.status_code == 200
    assert captured["user_id"] == "sa:mcp-bot"
    assert captured["service_account_name"] == "mcp-bot"


async def test_revoked_pat_rejected_with_mcp_auth(tmp_path):
    db = _sqlite_db(tmp_path)
    plaintext, token_hash, token_prefix = generate_token()
    account = ServiceAccount(
        id=str(uuid4()),
        name="revoked-bot",
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=["agents:run"],
        created_at=int(time.time()),
        revoked_at=int(time.time()),
    )
    db.create_service_account(account.to_dict())

    async with _http_client(_oauth_os(db=db)) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(plaintext))
    assert response.status_code == 401


# ==================== JWT coexistence (MultiAuth) ====================


def _mint_jwt(secret="test-jwt-secret", sub="user-42", scopes=None, **extra):
    import jwt as pyjwt

    payload = {"sub": sub, "scopes": scopes or ["agents:run"], "exp": int(time.time()) + 3600, **extra}
    return pyjwt.encode(payload, secret, algorithm="HS256")


def _jwt_os(**os_kwargs) -> AgentOS:
    from agno.os.config import AuthorizationConfig

    return AgentOS(
        agents=[_agent()],
        mcp_auth=_oauth_provider(),
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["test-jwt-secret"], algorithm="HS256"),
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
        **os_kwargs,
    )


async def test_jwt_bearer_still_works_with_mcp_auth():
    """Enabling OAuth on a JWT-mode deployment must not break existing agno-JWT MCP
    clients: the JWT verifier is composed into MultiAuth and the identity bridges."""
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", None)
                captured["authorization_enabled"] = getattr(request.state, "authorization_enabled", None)
            return response

    from agno.os.config import AuthorizationConfig

    os = AgentOS(
        agents=[_agent()],
        mcp_auth=_oauth_provider(),
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["test-jwt-secret"], algorithm="HS256"),
        mcp_server=MCPServerConfig(
            tools=[_ok_tool], enable_builtin_tools=False, middleware=[Middleware(_CaptureState)]
        ),
    )
    async with _http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt()))

    assert response.status_code == 200
    assert captured["user_id"] == "user-42"
    assert captured["authorization_enabled"] is True


async def test_invalid_jwt_rejected_with_mcp_auth():
    async with _http_client(_jwt_os()) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt(secret="wrong")))
    assert response.status_code == 401


async def test_jwt_cannot_smuggle_trust_markers():
    """A signature-valid deployment JWT that carries agno's internal trust markers
    (agno_service_account / agno_mcp_internal_issuer / agno_authorization_enabled) must not
    have them reach the identity bridge: they are stripped before the payload is bridged,
    so the caller cannot forge a service-account identity or flip the RBAC-off flag."""
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", None)
                captured["service_account_name"] = getattr(request.state, "service_account_name", None)
                captured["authorization_enabled"] = getattr(request.state, "authorization_enabled", None)
                captured["claims"] = getattr(request.state, "claims", None)
            return response

    from agno.os.config import AuthorizationConfig

    os = AgentOS(
        agents=[_agent()],
        mcp_auth=_oauth_provider(),
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["test-jwt-secret"], algorithm="HS256"),
        mcp_server=MCPServerConfig(
            tools=[_ok_tool], enable_builtin_tools=False, middleware=[Middleware(_CaptureState)]
        ),
    )
    token = _mint_jwt(
        sub="user-42",
        agno_service_account="admin",
        agno_mcp_internal_issuer=True,
        agno_authorization_enabled=False,
    )
    async with _http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(token))

    assert response.status_code == 200
    assert captured["user_id"] == "user-42"
    # None of the smuggled markers took effect.
    assert captured["service_account_name"] is None
    assert captured["authorization_enabled"] is True
    assert "agno_service_account" not in (captured["claims"] or {})
    assert "agno_mcp_internal_issuer" not in (captured["claims"] or {})


async def test_subless_jwt_bridges_to_none_user_id():
    """A JWT with no sub bridges to user_id=None -- matching the parent REST AuthMiddleware
    -- rather than collapsing every sub-less caller onto the shared "agno-jwt" principal
    (which user-isolation would treat as a single shared identity)."""
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            if request.url.path == "/mcp":
                captured["user_id"] = getattr(request.state, "user_id", "MISSING")
            return response

    from agno.os.config import AuthorizationConfig

    os = AgentOS(
        agents=[_agent()],
        mcp_auth=_oauth_provider(),
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["test-jwt-secret"], algorithm="HS256"),
        mcp_server=MCPServerConfig(
            tools=[_ok_tool], enable_builtin_tools=False, middleware=[Middleware(_CaptureState)]
        ),
    )
    import jwt as pyjwt

    # A JWT with the sub claim absent entirely (pyjwt rejects an explicit null sub).
    subless = pyjwt.encode(
        {"scopes": ["agents:run"], "exp": int(time.time()) + 3600}, "test-jwt-secret", algorithm="HS256"
    )
    async with _http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(subless))

    assert response.status_code == 200
    assert captured["user_id"] is None


@pytest.mark.parametrize("reserved_sub", ["sa:deploy", "__oauth__:evil", "__scheduler__"])
async def test_jwt_claiming_reserved_principal_rejected(reserved_sub):
    """Parity with the parent middleware: a JWT must not impersonate any server-assigned
    principal (service account, MCP-OAuth client, or the scheduler)."""
    async with _http_client(_jwt_os()) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt(sub=reserved_sub)))
    assert response.status_code == 401


async def test_jwt_audience_falls_back_to_agent_os_id():
    """Parity with the parent middleware: verify_audience with no explicit audience
    enforces the AgentOS id as the expected audience on /mcp, not only on REST."""
    from agno.os.config import AuthorizationConfig

    os = AgentOS(
        id="mcp-audience-os",
        agents=[_agent()],
        mcp_auth=_oauth_provider(),
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=["test-jwt-secret"], algorithm="HS256", verify_audience=True
        ),
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
    )
    async with _http_client(os) as client:
        matching = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt(aud="mcp-audience-os")))
        mismatched = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt(aud="other-os")))
        missing_aud = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt()))

    assert matching.status_code == 200
    assert mismatched.status_code == 401
    assert missing_aud.status_code == 401


async def test_jwt_verifier_mirrors_authorization_flag():
    """JWT scopes are enforced only when RBAC is on (parity with the parent middleware,
    which sets authorization_enabled = os.authorization for JWT identities)."""

    class _Validator:
        def validate_token(self, token, expected_audience=None):
            return {"sub": "user-1", "scopes": ["agents:run"]}

        def extract_claims(self, payload):
            return {"user_id": payload["sub"], "scopes": payload["scopes"], "session_id": None, "audience": None}

    token_rbac_off = await JWTBearerTokenVerifier(_Validator(), authorization=False).verify_token("t")
    token_rbac_on = await JWTBearerTokenVerifier(_Validator(), authorization=True).verify_token("t")

    assert token_rbac_off is not None and token_rbac_off.claims[AUTHORIZATION_ENABLED_CLAIM] is False
    assert token_rbac_on is not None and token_rbac_on.claims[AUTHORIZATION_ENABLED_CLAIM] is True
    assert (await _bridged_state(token_rbac_off))["authorization_enabled"] is False
    assert (await _bridged_state(token_rbac_on))["authorization_enabled"] is True


# ==================== Fail-closed tool gates ====================


def _fake_http_request(state: dict, mcp_auth_enabled: bool):
    app_state = SimpleNamespace(agno_mcp_auth_enabled=True) if mcp_auth_enabled else SimpleNamespace()
    return SimpleNamespace(state=SimpleNamespace(**state), app=SimpleNamespace(state=app_state))


def test_scope_gate_fails_closed_when_bridge_absent(monkeypatch):
    """Under mcp_auth, a provider-verified request with no bridged identity means the
    bridge did not run (an ordering regression): the gate must deny, not skip."""
    import fastmcp.server.dependencies as deps

    from agno.os import mcp as mcp_mod

    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request({}, mcp_auth_enabled=True))
    with pytest.raises(Exception, match="identity bridge did not"):
        mcp_mod._require_tool_scopes("GET", "/config")


def test_scope_gate_stays_open_without_mcp_auth(monkeypatch):
    """Without mcp_auth the skip is the intended open/security-key behavior."""
    import fastmcp.server.dependencies as deps

    from agno.os import mcp as mcp_mod

    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request({}, mcp_auth_enabled=False))
    mcp_mod._require_tool_scopes("GET", "/config")


async def test_continue_run_gate_fails_closed_when_bridge_absent(monkeypatch):
    """The run-continuation (HITL) gate is what stops a run's initiator self-approving an
    admin-required pause over MCP. Under mcp_auth, a verified request with no bridged
    identity must fail closed there too, not just at the scope gate."""
    import fastmcp.server.dependencies as deps

    from agno.os import mcp as mcp_mod

    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request({}, mcp_auth_enabled=True))
    with pytest.raises(Exception, match="identity bridge did not"):
        await mcp_mod._enforce_run_continuation_allowed(db=None, run_id="run-1")


async def test_continue_run_gate_allows_authenticated_rbac_off(monkeypatch):
    """A bridged RBAC-off caller proceeds past the fail-closed guard (it only fires when
    the bridge did not run)."""
    import fastmcp.server.dependencies as deps

    from agno.os import auth as auth_mod
    from agno.os import mcp as mcp_mod

    async def _no_block(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_mod, "run_continuation_blocked_reason", _no_block)
    state = {"authenticated": True, "user_id": "alice", "scopes": [], "authorization_enabled": False}
    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request(state, mcp_auth_enabled=True))
    # No exception: the guard does not fire for an authenticated caller.
    await mcp_mod._enforce_run_continuation_allowed(db=None, run_id="run-1")


def test_scope_gate_enforces_bridged_identity(monkeypatch):
    """A bridged identity with insufficient scopes is denied, sufficient passes."""
    import fastmcp.server.dependencies as deps

    from agno.os import mcp as mcp_mod

    insufficient = {"user_id": "u", "scopes": ["sessions:read"], "authorization_enabled": True}
    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request(insufficient, mcp_auth_enabled=True))
    with pytest.raises(Exception, match="[Ii]nsufficient"):
        mcp_mod._require_tool_scopes("POST", "/agents/demo-agent/runs")

    sufficient = {"user_id": "u", "scopes": ["agents:run"], "authorization_enabled": True}
    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request(sufficient, mcp_auth_enabled=True))
    mcp_mod._require_tool_scopes("POST", "/agents/demo-agent/runs")


def test_scope_gate_allows_authenticated_rbac_off_caller(monkeypatch):
    """A caller the bridge DID authenticate but whose token carries no RBAC (an RBAC-off
    agno JWT, or an external Tier-2 token) is a legitimate unenforced caller -- the
    fail-closed gate must NOT deny it (that only fires when the bridge did not run)."""
    import fastmcp.server.dependencies as deps

    from agno.os import mcp as mcp_mod

    rbac_off = {"authenticated": True, "user_id": "alice", "scopes": ["agents:run"], "authorization_enabled": False}
    monkeypatch.setattr(deps, "get_http_request", lambda: _fake_http_request(rbac_off, mcp_auth_enabled=True))
    # No exception: enforcement is skipped exactly as on a non-mcp_auth RBAC-off deploy.
    mcp_mod._require_tool_scopes("POST", "/agents/demo-agent/runs")


async def test_rbac_off_jwt_bearer_runs_tools_under_mcp_auth(tmp_path):
    """End-to-end coexistence: on an authorization=False deployment, an agno-JWT bearer
    still reaches a built-in tool over an OAuth-enabled /mcp (the fail-closed gate must
    not deny it just because RBAC is off)."""
    from agno.os.config import AuthorizationConfig

    db = _sqlite_db(tmp_path)
    os = AgentOS(
        agents=[_agent()],
        db=db,
        mcp_server=True,
        mcp_auth=_oauth_provider(),
        authorization=False,
        authorization_config=AuthorizationConfig(verification_keys=["test-jwt-secret"], algorithm="HS256"),
    )
    async with _http_client(os) as client:
        init = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(_mint_jwt()))
    assert init.status_code == 200


# ==================== Parent auth stays intact around the exemptions ====================


async def test_parent_auth_unaffected_by_mcp_exemptions(tmp_path):
    """With a security key configured, the OAuth surface is exempt (browsers carry no agno
    bearer) while every other route still requires the key."""
    db = _sqlite_db(tmp_path)
    pat = _mint_pat(db)
    os = _oauth_os(db=db, security_key="test-key")
    async with _http_client(os) as client:
        well_known = await client.get("/.well-known/oauth-authorization-server")
        registration = await client.post(
            "/register",
            json={
                "redirect_uris": [_REDIRECT_URI],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        rest_unauthenticated = await client.get("/agents")
        rest_authenticated = await client.get("/agents", headers={"Authorization": "Bearer test-key"})
        pat_on_mcp = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(pat))

    assert well_known.status_code == 200
    assert registration.status_code == 201
    assert rest_unauthenticated.status_code == 401
    assert rest_authenticated.status_code == 200
    assert pat_on_mcp.status_code == 200


# ==================== Open-server detection + host guard ====================


def test_oauth_deploy_is_not_open():
    os = _oauth_os()
    assert _mcp_server_is_open(os) is False


def test_oauth_deploy_gets_no_localhost_host_guard():
    """An OAuth-only deployment must serve its deployed hostname: the localhost-only
    transport guard is for OPEN servers, and this one is not open."""
    names = [m.cls.__name__ for m in get_mcp_server(_oauth_os()).user_middleware]
    assert "_MCPTransportSecurityMiddleware" not in names


async def test_oauth_deploy_serves_deployed_hostname():
    """A request with a non-localhost Host reaches the auth challenge (401), not the
    open-server host guard (400 invalid_host)."""
    async with _http_client(_oauth_os()) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Host": "myapp.example.com"})
    assert response.status_code == 401
    assert "www-authenticate" in response.headers


# ==================== /info discovery ====================


async def test_info_reports_oauth_discovery_under_mcp():
    async with _http_client(_oauth_os()) as client:
        response = await client.get("/info")

    assert response.status_code == 200
    payload = response.json()
    # auth_mode describes the REST/WS plane only (here open); the MCP OAuth signal lives
    # under mcp.oauth so it does not mask the true REST posture.
    assert payload["auth_mode"] == "none"
    assert payload["mcp"]["enabled"] is True
    oauth_info = payload["mcp"]["oauth"]
    assert [s.rstrip("/") for s in oauth_info["authorization_servers"]] == ["http://localhost"]
    assert oauth_info["resource"].rstrip("/") == "http://localhost/mcp"


# ==================== The identity bridge (unit) ====================


async def _bridged_state(access_token, admin_scope="agent_os:admin", user_isolation=False) -> dict:
    scope: dict = {"type": "http", "user": SimpleNamespace(access_token=access_token)}

    async def app(s, r, sd):
        return None

    await MCPIdentityBridgeMiddleware(app, admin_scope=admin_scope, user_isolation=user_isolation)(scope, None, None)
    return scope.get("state", {})


async def test_identity_bridge_sets_the_full_contract():
    """The tool gates are fail-open on a missing authorization_enabled flag, so the
    bridge must set the whole contract, not just user_id."""
    token = AccessToken(token="t", client_id="client-1", scopes=["agents:run"], claims={"sub": "user-1"})
    state = await _bridged_state(token)
    assert state["user_id"] == "user-1"
    assert state["scopes"] == ["agents:run"]
    assert state["authorization_enabled"] is True
    assert state["admin_scope"] == "agent_os:admin"
    assert state["authenticated"] is True
    assert state["user_isolation_enabled"] is False
    assert state["session_id"] is None
    assert state["claims"] == {"sub": "user-1"}
    assert "service_account_name" not in state


async def test_identity_bridge_stamps_user_isolation():
    """Session pinning (get_scoped_user_id) keys on this flag, exactly as under the
    parent middleware -- omitting it would silently disable per-user isolation."""
    token = AccessToken(token="t", client_id="client-1", scopes=[], claims={"sub": "user-1"})
    assert (await _bridged_state(token, user_isolation=True))["user_isolation_enabled"] is True


async def test_identity_bridge_falls_back_to_client_id():
    token = AccessToken(token="t", client_id="client-1", scopes=[])
    assert (await _bridged_state(token))["user_id"] == "client-1"


async def test_identity_bridge_restores_service_account_identity():
    token = AccessToken(
        token="t",
        client_id="sa:bot",
        scopes=["agents:run"],
        claims={"sub": "sa:bot", SERVICE_ACCOUNT_CLAIM: "bot"},
    )
    state = await _bridged_state(token)
    assert state["user_id"] == "sa:bot"
    assert state["service_account_name"] == "bot"
    # Parity with the parent PAT path, which does not expose claims on request.state.
    assert "claims" not in state


async def test_identity_bridge_leaves_unauthenticated_requests_untouched():
    """No verified token (the OAuth flow endpoints, the 401 challenge) -> no identity and,
    critically, no authorization flags on request.state."""
    state = await _bridged_state(None)
    assert "user_id" not in state
    assert "authorization_enabled" not in state


async def test_identity_bridge_rejects_external_token_claiming_reserved_principal():
    """An external (Tier-2) provider token whose sub falls in a server-reserved namespace
    (sa:/__oauth__:/__scheduler__) must NOT be honored -- the bridge leaves the identity
    unset so the fail-closed gates deny it, rather than letting it impersonate the principal."""
    from agno.os.mcp_auth import INTERNAL_ISSUER_CLAIM

    for reserved in ("sa:admin", "__oauth__:evil", "__scheduler__"):
        token = AccessToken(token="t", client_id="ext", scopes=["agents:run"], claims={"sub": reserved})
        state = await _bridged_state(token)
        assert "user_id" not in state, f"{reserved} should not be bridged"
        assert "authenticated" not in state

    # But a first-party built-in-AS token (marked with the internal-issuer claim) is trusted
    # to carry its own __oauth__: principal.
    trusted = AccessToken(
        token="t", client_id="c", scopes=["agents:run"], claims={"sub": "__oauth__:c", INTERNAL_ISSUER_CLAIM: True}
    )
    state = await _bridged_state(trusted)
    assert state["user_id"] == "__oauth__:c"
    assert state["authenticated"] is True


# ==================== The PAT verifier (unit) ====================


class _FakeAccount:
    principal = "sa:bot"
    name = "bot"
    scopes = ["agents:run", "sessions:read"]


class _FakeVerifier:
    def __init__(self, ok=True, account=_FakeAccount()):
        self._ok = ok
        self._account = account
        self.calls: list = []

    async def verify(self, token, client_key=None):
        self.calls.append(token)
        return SimpleNamespace(ok=self._ok, account=self._account if self._ok else None)


async def test_pat_verifier_maps_account_to_access_token():
    verifier = ServiceAccountTokenVerifier(_FakeVerifier())
    token = await verifier.verify_token("agno_pat_sometoken")
    assert token is not None
    assert token.client_id == "sa:bot"
    assert token.scopes == ["agents:run", "sessions:read"]
    assert token.claims["sub"] == "sa:bot"
    assert token.claims[SERVICE_ACCOUNT_CLAIM] == "bot"


async def test_pat_verifier_ignores_non_pat_bearers():
    fake = _FakeVerifier()
    verifier = ServiceAccountTokenVerifier(fake)
    assert await verifier.verify_token("some-oauth-token") is None
    assert fake.calls == []  # never hits the store for non-PAT tokens


async def test_pat_verifier_returns_none_on_failed_verification():
    verifier = ServiceAccountTokenVerifier(_FakeVerifier(ok=False))
    assert await verifier.verify_token("agno_pat_bad") is None


# ==================== Unset path unchanged ====================


def test_without_mcp_auth_nothing_is_attached():
    os = AgentOS(
        agents=[_agent()],
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
    )
    assert os._get_mcp_auth_provider() is None
    mcp_app = get_mcp_server(os)
    names = [m.cls.__name__ for m in mcp_app.user_middleware]
    assert "MCPIdentityBridgeMiddleware" not in names
