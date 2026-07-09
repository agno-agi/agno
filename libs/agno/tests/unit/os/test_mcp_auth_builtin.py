"""Unit tests for the Built-in Authorization Server (Tier 1 of mcp_auth).

Phase 2 of the mcp_auth spec, exercised over the full AgentOS app on SQLite (the same
SQLAlchemy store code paths as Postgres):

  1. The full connector dance: DCR -> /authorize -> consent page (secret + CSRF) ->
     code -> PKCE token exchange -> MCP request with the identity bridged.
  2. The consent gate is real: wrong secret rejected (and throttled), CSRF mismatch
     rejected, deny redirects with access_denied, the page never renders without a
     valid pending transaction, and framing is denied.
  3. Token lifecycle: codes are single-use; refresh tokens rotate on every use (a
     replayed refresh token fails); server-decided scopes (client requests never
     expand the grant); revocation deletes refresh state.
  4. Persistence: tokens survive a "redeploy" (a second provider instance on the same
     database verifies tokens issued by the first -- the two-replica smoke), and
     nothing replayable is stored in the database (hash-at-rest).
"""

import pytest

pytest.importorskip("fastmcp")

import base64  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.mcp_auth_builtin import CONSENT_PATH, DEFAULT_GRANT_SCOPES, AgentOSBuiltinAuth  # noqa: E402

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
_SECRET = "test-connect-secret"


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


async def _ok_tool(message: str) -> str:
    return message


def _db(tmp_path):
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=str(tmp_path / "built-in_as.db"))


def _provider(db, **kwargs) -> AgentOSBuiltinAuth:
    kwargs.setdefault("url", "http://localhost")
    kwargs.setdefault("secret", _SECRET)
    return AgentOSBuiltinAuth(db=db, **kwargs)


def _os(provider, db=None, security_key=None) -> AgentOS:
    from agno.os.settings import AgnoAPISettings

    return AgentOS(
        agents=[_agent()],
        db=db,
        mcp_auth=provider,
        settings=AgnoAPISettings(os_security_key=security_key),
        mcp_server=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
    )


@asynccontextmanager
async def _http_client(os: AgentOS):
    app = os.get_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def _register(client, scope="agents:run sessions:read", auth_method="none"):
    response = await client.post(
        "/register",
        json={
            "client_name": "Test Connector",
            "redirect_uris": [_REDIRECT_URI],
            "token_endpoint_auth_method": auth_method,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": scope,
        },
    )
    return response


async def _start_authorization(client, client_id, scope="agents:run"):
    """DCR client drives /authorize and lands on the consent page. Returns (page, txn, csrf, verifier)."""
    verifier, challenge = _pkce_pair()
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
    consent_url = authorization.headers["location"]
    assert CONSENT_PATH in consent_url
    page = await client.get(consent_url)
    assert page.status_code == 200
    txn = re.search(r'name="txn" value="([^"]+)"', page.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return page, txn, csrf, verifier


async def _approve(client, txn, csrf, secret=_SECRET, action="approve"):
    return await client.post(
        CONSENT_PATH,
        data={"txn": txn, "csrf": csrf, "secret": secret, "action": action},
        follow_redirects=False,
    )


async def _exchange_code(client, client_id, code, verifier):
    return await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


async def _full_flow(client, scope="agents:run"):
    """DCR -> authorize -> consent approve -> token. Returns the token payload + client_id."""
    registration = await _register(client)
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]
    _, txn, csrf, verifier = await _start_authorization(client, client_id, scope=scope)
    approved = await _approve(client, txn, csrf)
    assert approved.status_code == 302, approved.text
    query = parse_qs(urlparse(approved.headers["location"]).query)
    assert "code" in query, approved.headers["location"]
    token_response = await _exchange_code(client, client_id, query["code"][0], verifier)
    assert token_response.status_code == 200, token_response.text
    return token_response.json(), client_id


# ==================== The full connector dance ====================


async def test_full_flow_connects_and_runs_mcp(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, client_id = await _full_flow(client)
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )

    assert response.status_code == 200
    assert tokens["token_type"].lower() == "bearer"
    assert tokens["refresh_token"]
    # Access tokens are short-lived (spec: <= 1h) so a leaked one has a bounded window.
    assert 0 < tokens["expires_in"] <= 3600


async def test_discovery_and_challenge(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        metadata = await client.get("/.well-known/oauth-authorization-server")
        challenge = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)

    assert metadata.status_code == 200
    assert metadata.json()["issuer"].rstrip("/") == "http://localhost"
    assert challenge.status_code == 401
    assert "resource_metadata=" in challenge.headers.get("www-authenticate", "")


async def test_metadata_advertises_public_client_auth(tmp_path):
    """The AS metadata must advertise the client-auth methods it actually accepts. This AS
    is public-clients-only (it rejects confidential DCR), so token_endpoint_auth_methods_
    supported must include "none" and NOT the confidential methods -- otherwise a spec-strict
    connector (claude.ai) reads the metadata, registers with client_secret_post, and gets a
    400 ("Couldn't register with the sign-in service")."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        metadata = await client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    body = metadata.json()
    methods = body["token_endpoint_auth_methods_supported"]
    assert "none" in methods
    assert "client_secret_post" not in methods and "client_secret_basic" not in methods
    # Revocation is public too.
    assert body.get("revocation_endpoint_auth_methods_supported") == ["none"]


async def test_full_flow_behind_active_parent_auth_middleware(tmp_path):
    """The spec's #1 failure mode: with a parent security key installed, the built-in AS's
    own routes (/register, /authorize, /token, the consent page) must be exempt from the
    parent AuthMiddleware -- otherwise a JWT/security-key deploy 401s the OAuth flow
    before the provider runs. Drive the whole flow and assert provider-level statuses."""
    db = _db(tmp_path)
    provider = _provider(db)
    os = _os(provider, db=db, security_key="parent-key")

    # The provider's routes are in the mechanically-derived AuthMiddleware exemption set.
    from agno.os.mcp_auth import mcp_auth_route_paths

    paths = mcp_auth_route_paths(os._get_mcp_auth_provider())
    assert CONSENT_PATH in paths
    for provider_path in ("/register", "/authorize", "/token"):
        assert provider_path in paths

    async with _http_client(os) as client:
        # A REST route still requires the key (the exemptions are scoped, not blanket).
        assert (await client.get("/agents")).status_code == 401
        # The whole OAuth flow completes with provider-level statuses, never a parent 401.
        tokens, _ = await _full_flow(client)
        assert tokens["access_token"]
        # And the issued token runs MCP requests through the same secured app.
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )
    assert response.status_code == 200


# ==================== The consent gate ====================


async def test_wrong_secret_rejected_then_throttled(tmp_path):
    db = _db(tmp_path)
    provider = _provider(db, max_login_failures_per_ip=3)
    async with _http_client(_os(provider, db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        _, txn, csrf, _ = await _start_authorization(client, client_id)

        first = await _approve(client, txn, csrf, secret="wrong")
        assert first.status_code == 200
        assert "Wrong connect secret" in first.text

        # Keep sending wrong secrets (fresh CSRF from each re-render) until throttled.
        status = 200
        for _ in range(5):
            match = re.search(r'name="csrf" value="([^"]+)"', first.text)
            csrf = match.group(1) if match else csrf
            first = await _approve(client, txn, csrf, secret="wrong")
            status = first.status_code
            if status == 429:
                break
        assert status == 429


async def test_correct_secret_is_never_throttled(tmp_path):
    """The limiter shapes only the FAILURE response: a flood of wrong-secret attempts
    (the DCR/authorize endpoints are unauthenticated) must not lock out a correct login."""
    db = _db(tmp_path)
    # A global limiter of 1 is saturated by a single wrong attempt from any source.
    provider = _provider(db, max_login_failures_global=1)
    async with _http_client(_os(provider, db=db)) as client:
        reg_a = await _register(client)
        _, txn_a, csrf_a, _ = await _start_authorization(client, reg_a.json()["client_id"])
        saturate = await _approve(client, txn_a, csrf_a, secret="wrong")
        assert saturate.status_code in (200, 429)

        # A fresh, legitimate connection with the correct secret still succeeds.
        reg_b = await _register(client)
        _, txn_b, csrf_b, _ = await _start_authorization(client, reg_b.json()["client_id"])
        approved = await _approve(client, txn_b, csrf_b, secret=_SECRET)
    assert approved.status_code == 302
    assert "code=" in approved.headers["location"]


async def test_csrf_mismatch_rejected(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        _, txn, _, _ = await _start_authorization(client, client_id)
        response = await _approve(client, txn, csrf="forged-token")
    assert response.status_code == 400


async def test_deny_redirects_with_access_denied(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        _, txn, csrf, _ = await _start_authorization(client, client_id)
        response = await _approve(client, txn, csrf, action="deny")
    assert response.status_code == 302
    assert "error=access_denied" in response.headers["location"]


async def test_consent_page_requires_valid_transaction(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        response = await client.get(f"{CONSENT_PATH}?txn=not-a-real-transaction")
    assert response.status_code == 404


async def test_consent_page_denies_framing(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        page, _, _, _ = await _start_authorization(client, client_id)
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


async def test_consent_csp_does_not_restrict_form_action(tmp_path):
    """The consent CSP must NOT set `form-action` (e.g. 'self'): Chromium enforces
    form-action on the redirect that FOLLOWS the form POST, so it would silently block the
    post-approval 302 to the client's cross-origin callback (claude.ai / ChatGPT) and
    strand the flow before the token exchange. The page runs no JS, so form-action adds no
    protection here."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        page, _, _, _ = await _start_authorization(client, client_id)
    assert "form-action" not in page.headers["content-security-policy"]


async def test_confidential_client_registration_rejected(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        response = await _register(client, auth_method="client_secret_post")
    assert response.status_code == 400
    assert "public clients" in response.text


async def test_dcr_client_omitting_auth_method_onboards_as_public(tmp_path):
    """A DCR connector (Claude Code / mcp-remote) that omits token_endpoint_auth_method
    must onboard as a public client -- the SDK defaults an omitted method to
    client_secret_post + mints a secret, which would otherwise 400 the whole flow."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await client.post(
            "/register",
            json={
                "client_name": "Claude Code",
                "redirect_uris": ["http://127.0.0.1:51111/callback"],
                # NOTE: no token_endpoint_auth_method (a legal RFC 7591 omission).
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert registration.status_code == 201, registration.text
        info = registration.json()
        # Registered as public: no client secret minted or returned.
        assert info["token_endpoint_auth_method"] == "none"
        assert not info.get("client_secret")

        # And the full PKCE flow works end to end (no client secret required at /token).
        client_id = info["client_id"]
        verifier, challenge = _pkce_pair()
        authorization = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:51111/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s",
            },
            follow_redirects=False,
        )
        page = await client.get(authorization.headers["location"])
        txn = re.search(r'name="txn" value="([^"]+)"', page.text).group(1)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        approved = await _approve(client, txn, csrf)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        token_response = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1:51111/callback",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
    assert token_response.status_code == 200, token_response.text


async def test_pending_transactions_are_capped(tmp_path):
    """/authorize is reachable unauthenticated after one DCR registration; the pending
    transactions table is bounded (oldest evicted) rather than growing by rate x TTL."""
    db = _db(tmp_path)
    provider = _provider(db)
    provider._max_pending_transactions = 3
    from sqlalchemy import func, select

    async with _http_client(_os(provider, db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        for _ in range(6):
            await _start_authorization(client, client_id)

    txns = db._get_table("mcp_oauth_transactions", create_table_if_not_found=True)
    with db.db_engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(txns)).scalar()
    assert count <= 3


def test_transaction_eviction_is_mysql_safe(tmp_path):
    """The oldest-eviction DELETE must be a derived-table subquery, not a bare
    self-referential one -- MySQL rejects "DELETE FROM t WHERE x IN (SELECT ... FROM t)"
    (error 1093). Assert the rendered SQL wraps the subquery in a derived table on MySQL."""
    from sqlalchemy import delete, select
    from sqlalchemy.dialects import mysql

    db = _db(tmp_path)
    _provider(db)
    t = db._get_table("mcp_oauth_transactions", create_table_if_not_found=True)
    oldest = select(t.c.txn_id).order_by(t.c.expires_at.asc()).limit(2).subquery()
    stmt = delete(t).where(t.c.txn_id.in_(select(oldest.c.txn_id)))
    rendered = " ".join(str(stmt.compile(dialect=mysql.dialect())).split())
    assert "FROM (SELECT" in rendered  # derived table -> MySQL-safe


# ==================== HTTPS / consent-cookie hardening ====================


def test_plaintext_deployment_cannot_be_constructed(tmp_path):
    """A plaintext (http, non-localhost) origin is refused at construction by the SDK's
    issuer-URL validation, so the consent page is inherently served over a secure origin
    -- no per-request HTTPS gate needed (which would misfire behind a TLS proxy)."""
    provider = _provider(_db(tmp_path), url="http://my-os.example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        provider.get_routes(mcp_path="/mcp")


def test_consent_cookie_is_secure_for_https_deployment(tmp_path):
    """The CSRF cookie is marked Secure when the deployment origin is HTTPS -- keyed on
    the deployer-declared base_url, so it holds even when the app sees plain http from a
    TLS-terminating proxy (Railway/PaaS). A localhost dev deploy gets a non-Secure cookie
    so the dev flow works."""
    https_provider = _provider(_db(tmp_path), url="https://my-os.up.railway.app")
    assert https_provider._deployment_is_https() is True
    payload = {"client_id": "c", "redirect_uri": _REDIRECT_URI, "state": "s"}
    https_cookie = https_provider._render_consent_page(
        "txn", payload, "c", secure_cookie=https_provider._deployment_is_https()
    ).headers.get("set-cookie", "")
    assert "Secure" in https_cookie
    assert "HttpOnly" in https_cookie

    local_provider = _provider(_db(tmp_path / "local"), url="http://localhost")
    (tmp_path / "local").mkdir(exist_ok=True)
    assert local_provider._deployment_is_https() is False
    local_cookie = local_provider._render_consent_page(
        "txn", payload, "c", secure_cookie=local_provider._deployment_is_https()
    ).headers.get("set-cookie", "")
    assert "Secure" not in local_cookie


async def test_consent_served_on_proxy_terminated_https_deploy(tmp_path):
    """Regression: on a proxy-terminated-TLS deploy (base_url https, app sees http), the
    consent page must still serve -- gating on the per-request scheme would 400 the whole
    connector flow on the primary production target."""
    db = _db(tmp_path)
    provider = _provider(db, url="https://my-os.up.railway.app")
    os = _os(provider, db=db)
    async with _http_client(os) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        _, challenge = _pkce_pair()
        authorization = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": _REDIRECT_URI,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s",
            },
            follow_redirects=False,
        )
        # The app receives a plain-http request with the public (non-loopback) Host.
        consent_path = authorization.headers["location"].split(str(provider.base_url).rstrip("/"))[-1]
        page = await client.get(consent_path, headers={"Host": "my-os.up.railway.app"})
    assert page.status_code == 200
    assert 'name="csrf"' in page.text


# ==================== Token lifecycle ====================


async def test_authorization_code_is_single_use(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        _, txn, csrf, verifier = await _start_authorization(client, client_id)
        approved = await _approve(client, txn, csrf)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]

        first = await _exchange_code(client, client_id, code, verifier)
        replay = await _exchange_code(client, client_id, code, verifier)

    assert first.status_code == 200
    assert replay.status_code in (400, 401)


async def test_refresh_rotates_and_old_token_dies(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, client_id = await _full_flow(client)

        refreshed = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert refreshed.status_code == 200, refreshed.text
        new_tokens = refreshed.json()
        assert new_tokens["refresh_token"] != tokens["refresh_token"]

        replay = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert replay.status_code in (400, 401)

        # The rotated pair works: the new access token runs MCP requests.
        response = await client.post(
            "/mcp",
            json=_MCP_INIT_BODY,
            headers={**_MCP_HEADERS, "Authorization": f"Bearer {new_tokens['access_token']}"},
        )
        assert response.status_code == 200


async def test_reused_refresh_token_revokes_the_family(tmp_path):
    """Presenting a rotated-away refresh token is reuse detection (OAuth 2.1 / RFC 9700):
    it is refused AND revokes the whole rotation family, so the legitimate current refresh
    token dies too and the client must re-consent."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, client_id = await _full_flow(client)
        # Legitimate rotation: token1 -> token2.
        rotated = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert rotated.status_code == 200, rotated.text
        token2 = rotated.json()["refresh_token"]

        # Reuse of the rotated-away token1 is refused AND trips family revocation.
        replay = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert replay.status_code in (400, 401)

        # token2 was the legitimate current token, but the family was revoked, so it is dead too.
        after = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": token2, "client_id": client_id},
        )
        assert after.status_code in (400, 401)


async def test_scopes_are_server_decided(tmp_path):
    """A client requesting broader scopes (admin) gets exactly the configured grant."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, _ = await _full_flow(client, scope="agents:run sessions:read")
    assert set(tokens["scope"].split()) == set(DEFAULT_GRANT_SCOPES)


async def test_revocation_kills_refresh(tmp_path):
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, client_id = await _full_flow(client)
        # The SDK's RevocationRequest requires the client_secret field to be present
        # (str | None with no default); a public client sends it empty.
        revocation = await client.post(
            "/revoke",
            data={"token": tokens["refresh_token"], "client_id": client_id, "client_secret": ""},
        )
        assert revocation.status_code == 200, revocation.text
        replay = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
    assert replay.status_code in (400, 401)


# ==================== Persistence ====================


async def test_tokens_survive_redeploy_and_verify_on_second_replica(tmp_path):
    """A second provider instance on the same database (a redeploy, or another replica)
    verifies tokens issued by the first: the signing key is persisted and shared, and
    access-token verification is stateless."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, client_id = await _full_flow(client)

    replica_os = _os(_provider(db), db=db)
    async with _http_client(replica_os) as client:
        access_ok = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )
        refreshed = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )

    assert access_ok.status_code == 200
    assert refreshed.status_code == 200, refreshed.text


async def test_nothing_replayable_stored_in_db(tmp_path):
    """Hash-at-rest: neither the issued tokens nor the authorization code appear in the
    database; only their SHA-256 hashes do."""
    db = _db(tmp_path)
    provider = _provider(db)
    async with _http_client(_os(provider, db=db)) as client:
        registration = await _register(client)
        client_id = registration.json()["client_id"]
        _, txn, csrf, verifier = await _start_authorization(client, client_id)
        approved = await _approve(client, txn, csrf)
        code = parse_qs(urlparse(approved.headers["location"]).query)["code"][0]
        token_response = await _exchange_code(client, client_id, code, verifier)
        tokens = token_response.json()

    engine = db.db_engine
    tables = [t for t in sa_inspect(engine).get_table_names() if t.startswith("agno_mcp_oauth")]
    assert tables
    with engine.connect() as conn:
        for table in tables:
            for row in conn.execute(text(f"SELECT * FROM {table}")):  # noqa: S608 - test-only introspection
                row_text = " ".join(str(v) for v in row)
                assert code not in row_text
                assert tokens["refresh_token"] not in row_text
                assert tokens["access_token"] not in row_text
        # The stored client is public: its metadata carries no client_secret.
        for row in conn.execute(text("SELECT client_metadata FROM agno_mcp_oauth_clients")):
            metadata = json.loads(row[0])
            assert not metadata.get("client_secret")
            assert metadata.get("token_endpoint_auth_method") == "none"


async def test_unconsummated_registration_is_pruned(tmp_path):
    """A pending (never-consented) DCR registration is aged out, so an abandoned or
    flood registration does not accumulate. Verified by backdating created_at past the
    unconsummated TTL and triggering the prune with a fresh /register."""
    from sqlalchemy import func, select, update

    db = _db(tmp_path)
    provider = _provider(db)
    async with _http_client(_os(provider, db=db)) as client:
        stale = await _register(client)
        stale_id = stale.json()["client_id"]
        # Backdate the pending row well past the unconsummated TTL.
        from agno.os.mcp_auth_builtin import DEFAULT_UNCONSUMED_CLIENT_TTL

        old = int(time.time()) - DEFAULT_UNCONSUMED_CLIENT_TTL - 60
        clients = db._get_table("mcp_oauth_clients", create_table_if_not_found=True)
        with db.db_engine.connect() as conn:
            conn.execute(update(clients).where(clients.c.client_id == stale_id).values(created_at=old))
            conn.commit()
        # A fresh registration triggers the prune.
        await _register(client)

    with db.db_engine.connect() as conn:
        remaining = conn.execute(
            select(func.count()).select_from(clients).where(clients.c.client_id == stale_id)
        ).scalar()
    assert remaining == 0


async def test_env_signing_key_is_primary(tmp_path, monkeypatch):
    """With AGENTOS_MCP_SIGNING_KEY set, two providers on different databases issue
    mutually verifiable tokens (same derived key + issuer) -- the env-primary path."""
    provider_a = _provider(_db(tmp_path), signing_key_material="a-high-entropy-material-of-sufficient-length")
    db_b = _db(tmp_path / "b")
    (tmp_path / "b").mkdir(exist_ok=True)
    provider_b = _provider(db_b, signing_key_material="a-high-entropy-material-of-sufficient-length")

    db_a = _db(tmp_path)
    async with _http_client(_os(provider_a, db=db_a)) as client:
        tokens, _ = await _full_flow(client)

    async with _http_client(_os(provider_b, db=db_b)) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )
    assert response.status_code == 200


# ==================== Construction ====================


def test_requires_secret(tmp_path):
    with pytest.raises(ValueError, match="requires a secret"):
        AgentOSBuiltinAuth(url="http://localhost", db=_db(tmp_path), secret="")


def test_short_secret_rejected(tmp_path):
    """The connect secret is the sole gate on the consent page, so a trivially short one
    is refused at construction rather than deploying a guessable gate."""
    with pytest.raises(ValueError, match="too short"):
        AgentOSBuiltinAuth(url="http://localhost", db=_db(tmp_path), secret="short")


def test_db_without_oauth_store_methods_rejected():
    """A SQLAlchemy-backed db that exposes a sync db_engine but does NOT implement the
    BaseDb OAuth store methods (MySQLDb, SingleStoreDb, ...) must be rejected at
    construction -- otherwise it passes the engine checks and only 500s with
    NotImplementedError on the first /register."""
    from sqlalchemy import create_engine

    from agno.db.base import BaseDb

    class _StoreLessDb:
        # Sync engine (passes the engine + not-async checks), but the OAuth store method
        # is BaseDb's inherited NotImplementedError stub (not overridden).
        db_engine = create_engine("sqlite://")
        create_mcp_oauth_client = BaseDb.create_mcp_oauth_client

    with pytest.raises(ValueError, match="does not implement the built-in MCP OAuth store"):
        AgentOSBuiltinAuth(url="http://localhost", secret=_SECRET, db=_StoreLessDb())


def test_weak_signing_key_rejected(tmp_path):
    """A low-entropy AGENTOS_MCP_SIGNING_KEY is offline-brute-forceable (derive_jwt_key
    treats it as high-entropy material), so a sub-32-char value is refused at construction."""
    with pytest.raises(ValueError, match="AGENTOS_MCP_SIGNING_KEY is too short"):
        AgentOSBuiltinAuth(url="http://localhost", db=_db(tmp_path), secret=_SECRET, signing_key_material="connect-me")


async def test_from_env_binds_agentos_db_and_runs(tmp_path, monkeypatch):
    """The object form: AgentOSBuiltinAuth.from_env() constructs without a db, AgentOS
    binds its Postgres/SQLite db, and the full connector flow works. This is the
    documented, string-free way to enable the built-in server."""
    monkeypatch.setenv("AGENTOS_URL", "http://localhost")
    monkeypatch.setenv("MCP_CONNECT_SECRET", _SECRET)
    provider = AgentOSBuiltinAuth.from_env()
    assert provider.is_db_bound() is False

    db = _db(tmp_path)
    os = _os(provider, db=db)
    async with _http_client(os) as client:
        # Resolution bound the AgentOS db.
        assert os._get_mcp_auth_provider() is not None
        assert provider.is_db_bound() is True
        tokens, _ = await _full_flow(client)
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )
    assert response.status_code == 200


def test_explicit_db_is_not_overridden(tmp_path):
    """A db passed to the constructor wins; bind_db is a no-op once bound."""
    db_a = _db(tmp_path)
    provider = _provider(db_a)
    assert provider.is_db_bound() is True
    provider.bind_db(_db(tmp_path / "other"))  # ignored
    assert provider._db is db_a


def test_from_env_can_take_db_directly(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_URL", "http://localhost")
    monkeypatch.setenv("MCP_CONNECT_SECRET", _SECRET)
    provider = AgentOSBuiltinAuth.from_env(db=_db(tmp_path))
    assert provider.is_db_bound() is True


def test_from_env_requires_public_url(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTOS_URL", raising=False)
    monkeypatch.delenv("MCP_CONNECT_SECRET", raising=False)
    with pytest.raises(ValueError, match="AGENTOS_URL"):
        AgentOSBuiltinAuth.from_env(db=_db(tmp_path))


def test_from_env_requires_connect_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_URL", "https://my-os.example.com")
    monkeypatch.delenv("MCP_CONNECT_SECRET", raising=False)
    with pytest.raises(ValueError, match="MCP_CONNECT_SECRET"):
        AgentOSBuiltinAuth.from_env(db=_db(tmp_path))


def test_async_db_rejected_at_construction(tmp_path):
    """An async db must fail clearly at construction, not with an opaque 500 on the first
    request (the sync store paths cannot drive an AsyncEngine)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "async.db"))
    db = AsyncSqliteDb(db_engine=engine)
    with pytest.raises(ValueError, match="async databases"):
        _provider(db)


# ==================== RFC 8252 loopback redirect (Claude Code / mcp-remote) ====================


async def test_loopback_redirect_port_may_vary(tmp_path):
    """A CLI client registers a loopback callback, then authorizes from a different
    ephemeral port on a later run -- the second port must be accepted (RFC 8252)."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        registration = await client.post(
            "/register",
            json={
                "client_name": "Claude Code",
                "redirect_uris": ["http://127.0.0.1:51111/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        client_id = registration.json()["client_id"]

        _, challenge = _pkce_pair()
        # Same client_id, a DIFFERENT loopback port.
        authorization = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:60222/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s",
            },
            follow_redirects=False,
        )
    assert authorization.status_code in (302, 307), authorization.text
    assert CONSENT_PATH in authorization.headers["location"]


# ==================== DCR table cap (anti-flood, not a lifetime limit) ====================


async def test_client_cap_bounds_pending_not_lifetime(tmp_path):
    """The cap bounds PENDING (unconsummated) registrations only, so a run of legitimate
    consumed connections never wedges /register for new clients."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db, max_clients=3), db=db)) as client:
        # Four full, consented connections -- each consumes its client row.
        for _ in range(4):
            tokens, _ = await _full_flow(client)
            assert tokens["access_token"]
        # A fresh registration still succeeds despite max_clients=3, because consumed
        # rows do not count against the pending cap.
        registration = await _register(client)
    assert registration.status_code == 201


async def test_consumed_client_survives_later_registrations(tmp_path):
    """A consumed client's row is never pruned, so a long-lived connector keeps refreshing
    even as other clients register (a fixed-TTL prune would 401 its live refresh token)."""
    db = _db(tmp_path)
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, client_id = await _full_flow(client)
        # Simulate many later onboardings (each calls /register, the only prune trigger).
        for _ in range(3):
            await _full_flow(client)
        # The original client's refresh token still works -- its row was not pruned.
        refreshed = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
    assert refreshed.status_code == 200, refreshed.text


# ==================== Refresh across access-token expiry (forced short TTL) ====================


async def test_refresh_survives_access_token_expiry_across_replicas(tmp_path):
    """plan Phase 2 proof: with a forced-short access TTL, a connector keeps working
    across expiry via refresh -- observed on a SECOND provider instance (shared DB +
    stateless verify), with the old refresh token rejected there."""
    import asyncio

    db = _db(tmp_path)
    async with _http_client(_os(_provider(db, access_token_ttl=1), db=db)) as client:
        tokens, client_id = await _full_flow(client)

    await asyncio.sleep(1.2)  # let the access token expire

    replica = _os(_provider(db, access_token_ttl=1), db=db)
    async with _http_client(replica) as client:
        expired = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert expired.status_code == 401  # stateless expiry check on the second replica

        refreshed = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert refreshed.status_code == 200, refreshed.text
        new_access = refreshed.json()["access_token"]

        # The old refresh token is rejected on the second replica (rotation is shared).
        replay = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert replay.status_code in (400, 401)

        # The freshly refreshed access token runs MCP requests.
        ok = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {new_access}"}
        )
        assert ok.status_code == 200


# ==================== Signing-key rotation overlap ====================


async def test_signing_key_rotation_overlap(tmp_path):
    """Adding a new signing key (env-primary) keeps tokens signed by the persisted key
    verifiable during the overlap, so rotation is graceful rather than a hard cut."""
    db = _db(tmp_path)
    # First instance: no env key, so it generates+persists a db key and signs with it.
    async with _http_client(_os(_provider(db), db=db)) as client:
        tokens, _ = await _full_flow(client)

    # Rotation: a new env-primary key is added. The persisted key is still active, so the
    # old token keeps verifying (overlap); new tokens are signed by the env key.
    rotated = _os(_provider(db, signing_key_material="freshly-rotated-in-key-material-32b+"), db=db)
    async with _http_client(rotated) as client:
        old_still_valid = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        )
    assert old_still_valid.status_code == 200


# ==================== Reserved principal ====================


def test_oauth_principal_is_reserved():
    """A deployment JWT must not be able to claim an __oauth__: principal the built-in AS
    assigns to its connected clients."""
    from agno.os.middleware.jwt import is_reserved_principal

    assert is_reserved_principal("__oauth__:claude-ai") is True
    assert is_reserved_principal("sa:bot") is True
    assert is_reserved_principal("regular-user") is False


def test_loopback_redirect_matching():
    """Redirect validation (a security control) is owned locally, not delegated to a
    private fastmcp symbol. A registered loopback URI may vary only in port (RFC 8252);
    everything else stays strict exact-match, and mismatches are refused."""
    from agno.os.mcp_auth_builtin import _redirect_uri_matches_registered as matches

    reg = "http://127.0.0.1:51111/callback"
    # Accepted: exact match, and a loopback host with only the port differing.
    assert matches(reg, reg) is True
    assert matches("http://127.0.0.1:62000/callback", reg) is True
    assert matches("http://localhost:62000/cb", "http://localhost:51111/cb") is True
    # Refused: different path, non-loopback host, and a scheme change on a non-loopback URI.
    assert matches("http://127.0.0.1:62000/evil", reg) is False
    assert matches("http://evil.example.com:51111/callback", reg) is False
    assert matches("https://claude.ai/cb", "http://claude.ai/cb") is False
    # Refused: userinfo in the URI must never participate in matching.
    assert matches("http://x@127.0.0.1:62000/callback", reg) is False
