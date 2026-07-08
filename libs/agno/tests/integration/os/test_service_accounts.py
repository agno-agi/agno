"""Integration tests for service account (agno_pat_) authentication in AgentOS."""

import json
import time
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.os.settings import AgnoAPISettings

JWT_SECRET = "test-secret-key-for-service-account-tests"

UNIFORM_401_DETAIL = "Invalid or expired service account token"


def _make_jwt(scopes, sub="human-admin"):
    payload = {
        "sub": sub,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _mock_run_output():
    return type(
        "MockRunOutput",
        (),
        {"to_dict": lambda self: {"content": "ok", "run_id": "test_run_1"}},
    )()


@pytest.fixture
def sqlite_db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "service_accounts_test.db"))


@pytest.fixture
def test_agent(sqlite_db):
    agent = Agent(id="sa-test-agent", name="sa-test-agent", db=sqlite_db)
    agent.deep_copy = lambda **kwargs: agent
    return agent


@pytest.fixture
def jwt_client(test_agent, sqlite_db):
    """AgentOS with a db and JWT middleware with authorization enabled."""
    agent_os = AgentOS(agents=[test_agent], db=sqlite_db)
    app = agent_os.get_app()
    app.add_middleware(
        JWTMiddleware,
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        authorization=True,
    )
    return TestClient(app)


def _scope_items(scopes):
    """POST /service-accounts takes the RBAC write shape: {scope, effect} objects."""
    return [{"scope": scope} for scope in scopes]


def _mint(client, auth_token, name="claude-code", **body_overrides):
    body = {"name": name, **body_overrides}
    if body.get("scopes"):
        body["scopes"] = _scope_items(body["scopes"])
    return client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {auth_token}"},
        json=body,
    )


class TestServiceAccountLifecycleWithJWT:
    def test_admin_mints_pat_and_pat_runs_agent_with_attribution(self, jwt_client, test_agent):
        admin_jwt = _make_jwt(["agent_os:admin"])
        response = _mint(jwt_client, admin_jwt)
        assert response.status_code == 201, response.text
        body = response.json()
        pat = body["token"]
        assert pat.startswith("agno_pat_")
        assert body["principal"] == "sa:claude-code"
        assert body["created_by"] == "human-admin"
        assert body["user_id"] == "human-admin"

        with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = _mock_run_output()
            run_response = jwt_client.post(
                "/agents/sa-test-agent/runs",
                headers={"Authorization": f"Bearer {pat}"},
                data={"message": "hello", "stream": "false"},
            )
        assert run_response.status_code == 200, run_response.text
        assert mock_arun.call_args.kwargs["user_id"] == "sa:claude-code"

    def test_pat_default_scopes_allow_session_read_but_not_delete(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        pat = _mint(jwt_client, admin_jwt).json()["token"]

        response = jwt_client.get("/sessions", headers={"Authorization": f"Bearer {pat}"})
        assert response.status_code == 200

        response = jwt_client.delete("/sessions", headers={"Authorization": f"Bearer {pat}"})
        assert response.status_code == 403

    def test_pat_cannot_mint_pats_by_default(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        pat = _mint(jwt_client, admin_jwt).json()["token"]
        response = _mint(jwt_client, pat, name="sneaky")
        assert response.status_code == 403

    def test_minter_cannot_escalate_beyond_own_scopes(self, jwt_client):
        minter_jwt = _make_jwt(["service_accounts:write", "agents:run"], sub="delegated-minter")
        # Granting a scope the minter holds works
        response = _mint(jwt_client, minter_jwt, name="ci-bot", scopes=["agents:run"])
        assert response.status_code == 201

        # Granting a scope the minter does not hold is rejected
        response = _mint(jwt_client, minter_jwt, name="ci-bot-2", scopes=["teams:run"])
        assert response.status_code == 403

        # The privileged flag alone cannot escalate either
        response = _mint(
            jwt_client, minter_jwt, name="ci-bot-3", scopes=["agent_os:admin"], allow_privileged_scopes=True
        )
        assert response.status_code == 403

    def test_revoked_pat_gets_uniform_401(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        minted = _mint(jwt_client, admin_jwt).json()

        revoke = jwt_client.delete(
            f"/service-accounts/{minted['id']}", headers={"Authorization": f"Bearer {admin_jwt}"}
        )
        assert revoke.status_code == 204

        response = jwt_client.get("/sessions", headers={"Authorization": f"Bearer {minted['token']}"})
        assert response.status_code == 401
        assert response.json()["detail"] == UNIFORM_401_DETAIL

    def test_revoke_invalidates_cached_token_immediately(self, jwt_client):
        # Use the token first so it is cached, then revoke: the revoking worker (this
        # process, default 30s cache TTL) must reject it at once, not serve the cache.
        admin_jwt = _make_jwt(["agent_os:admin"])
        minted = _mint(jwt_client, admin_jwt).json()

        assert jwt_client.get("/sessions", headers={"Authorization": f"Bearer {minted['token']}"}).status_code == 200

        revoke = jwt_client.delete(
            f"/service-accounts/{minted['id']}", headers={"Authorization": f"Bearer {admin_jwt}"}
        )
        assert revoke.status_code == 204

        response = jwt_client.get("/sessions", headers={"Authorization": f"Bearer {minted['token']}"})
        assert response.status_code == 401
        assert response.json()["detail"] == UNIFORM_401_DETAIL

    def test_expired_pat_gets_same_uniform_401(self, jwt_client, sqlite_db):
        # expires_at is immutable after mint (update_service_account whitelists only
        # last_used_at/revoked_at), so simulate expiry by inserting an account that
        # is already past its expiry, exactly as a real token ages out.
        import uuid

        from agno.db.schemas.service_accounts import ServiceAccount
        from agno.os.service_accounts import DEFAULT_SERVICE_ACCOUNT_SCOPES, generate_token

        plaintext, token_hash, token_prefix = generate_token()
        account = ServiceAccount(
            id=str(uuid.uuid4()),
            name="expired-sa",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=list(DEFAULT_SERVICE_ACCOUNT_SCOPES),
            created_at=int(time.time()) - 100,
            expires_at=int(time.time()) - 10,
        )
        sqlite_db.create_service_account(account.to_dict())

        response = jwt_client.get("/sessions", headers={"Authorization": f"Bearer {plaintext}"})
        assert response.status_code == 401
        assert response.json()["detail"] == UNIFORM_401_DETAIL

    def test_unknown_pat_gets_same_uniform_401(self, jwt_client):
        response = jwt_client.get(
            "/sessions", headers={"Authorization": "Bearer agno_pat_doesnotexist0000000000000000"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == UNIFORM_401_DETAIL

    def test_repeated_failed_lookups_get_throttled(self, jwt_client):
        last_status = None
        for _ in range(25):
            response = jwt_client.get(
                "/sessions", headers={"Authorization": "Bearer agno_pat_bruteforce000000000000000"}
            )
            last_status = response.status_code
        assert last_status == 429

    def test_name_reuse_after_revocation_rotates_identity(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        first = _mint(jwt_client, admin_jwt)
        assert first.status_code == 201

        # Duplicate active name is rejected
        duplicate = _mint(jwt_client, admin_jwt)
        assert duplicate.status_code == 409

        # After revocation the name can be reused (rotation)
        revoke = jwt_client.delete(
            f"/service-accounts/{first.json()['id']}", headers={"Authorization": f"Bearer {admin_jwt}"}
        )
        assert revoke.status_code == 204
        rotated = _mint(jwt_client, admin_jwt)
        assert rotated.status_code == 201
        assert rotated.json()["principal"] == first.json()["principal"]

    def test_list_never_exposes_hashes_or_tokens(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        pat = _mint(jwt_client, admin_jwt).json()["token"]

        response = jwt_client.get("/service-accounts", headers={"Authorization": f"Bearer {admin_jwt}"})
        assert response.status_code == 200
        assert pat not in response.text
        entry = response.json()["data"][0]
        assert "token" not in entry
        assert "token_hash" not in entry
        assert entry["token_prefix"] == pat[:16]

    def test_jwt_without_scope_cannot_manage_service_accounts(self, jwt_client):
        plain_jwt = _make_jwt(["agents:run"], sub="regular-user")
        assert _mint(jwt_client, plain_jwt).status_code == 403
        response = jwt_client.get("/service-accounts", headers={"Authorization": f"Bearer {plain_jwt}"})
        assert response.status_code == 403

    def test_admin_pat_can_manage_service_accounts_end_to_end(self, jwt_client):
        """A PAT minted with agent_os:admin scope must be able to mint, list, and revoke.

        The admin scope is the union of every RBAC action -- if a PAT holding it is 403'd on
        any of the three service-account operations, the admin bypass is inconsistent across
        endpoints. Regression: an admin PAT could POST + GET service-accounts but was 403'd
        on DELETE, forcing operators to grant the more granular service_accounts:delete on
        top of admin.
        """
        # An admin JWT mints an admin PAT.
        admin_jwt = _make_jwt(["agent_os:admin"])
        admin_pat = _mint(
            jwt_client,
            admin_jwt,
            name="admin-pat",
            scopes=["agent_os:admin"],
            allow_privileged_scopes=True,
        ).json()["token"]

        # The admin PAT can list.
        listing = jwt_client.get("/service-accounts", headers={"Authorization": f"Bearer {admin_pat}"})
        assert listing.status_code == 200, listing.text

        # The admin PAT can mint a further account without needing to spell out
        # service_accounts:write (the admin bypass covers it).
        minted = _mint(jwt_client, admin_pat, name="minted-by-admin-pat")
        assert minted.status_code == 201, minted.text
        minted_id = minted.json()["id"]

        # The admin PAT can revoke without needing service_accounts:delete.
        revoke = jwt_client.delete(f"/service-accounts/{minted_id}", headers={"Authorization": f"Bearer {admin_pat}"})
        assert revoke.status_code == 204, revoke.text


class TestInternalTokenRegression:
    """The internal scheduler token must behave identically after the RBAC refactor."""

    @pytest.fixture
    def internal_client(self, test_agent, sqlite_db):
        agent_os = AgentOS(agents=[test_agent], db=sqlite_db, internal_service_token="internal-test-token")
        app = agent_os.get_app()
        app.add_middleware(
            JWTMiddleware,
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            authorization=True,
        )
        return TestClient(app)

    def test_internal_token_allowed_for_granted_scopes(self, internal_client):
        response = internal_client.get("/agents", headers={"Authorization": "Bearer internal-test-token"})
        assert response.status_code == 200

    def test_internal_token_denied_outside_granted_scopes(self, internal_client):
        response = internal_client.get("/sessions", headers={"Authorization": "Bearer internal-test-token"})
        assert response.status_code == 403


class TestServiceAccountsInSecurityKeyMode:
    """PATs work without JWT middleware, and their scopes are still enforced."""

    @pytest.fixture
    def security_key_client(self, test_agent, sqlite_db):
        agent_os = AgentOS(
            agents=[test_agent],
            db=sqlite_db,
            settings=AgnoAPISettings(os_security_key="root-security-key"),
        )
        return TestClient(agent_os.get_app())

    def test_security_key_mints_and_pat_runs_with_attribution(self, security_key_client, test_agent):
        response = _mint(security_key_client, "root-security-key")
        assert response.status_code == 201, response.text
        pat = response.json()["token"]

        with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = _mock_run_output()
            run_response = security_key_client.post(
                "/agents/sa-test-agent/runs",
                headers={"Authorization": f"Bearer {pat}"},
                data={"message": "hello", "stream": "false"},
            )
        assert run_response.status_code == 200, run_response.text
        assert mock_arun.call_args.kwargs["user_id"] == "sa:claude-code"

    def test_pat_scopes_are_enforced_without_jwt_middleware(self, security_key_client):
        pat = _mint(security_key_client, "root-security-key").json()["token"]

        # Default scopes include sessions:read
        response = security_key_client.get("/sessions", headers={"Authorization": f"Bearer {pat}"})
        assert response.status_code == 200

        # But a run-and-read PAT is not a master key: it cannot mint more PATs
        response = _mint(security_key_client, pat, name="sneaky")
        assert response.status_code == 403

        # And it cannot delete sessions
        response = security_key_client.delete("/sessions", headers={"Authorization": f"Bearer {pat}"})
        assert response.status_code == 403

    def test_revoked_pat_rejected_in_security_key_mode(self, security_key_client):
        minted = _mint(security_key_client, "root-security-key").json()
        revoke = security_key_client.delete(
            f"/service-accounts/{minted['id']}",
            headers={"Authorization": "Bearer root-security-key"},
        )
        assert revoke.status_code == 204

        response = security_key_client.get("/sessions", headers={"Authorization": f"Bearer {minted['token']}"})
        assert response.status_code == 401
        assert response.json()["detail"] == UNIFORM_401_DETAIL


class TestServiceAccountsOnOpenInstance:
    """On an open dev instance a PAT that verifies still attributes the request;
    one that cannot be verified falls through to anonymous access (a stale token
    in a client must never lock out an instance the operator never put auth on)."""

    @pytest.fixture
    def open_client(self, test_agent, sqlite_db):
        agent_os = AgentOS(agents=[test_agent], db=sqlite_db)
        return TestClient(agent_os.get_app())

    def test_pat_authenticates_and_attributes_on_open_instance(self, open_client, test_agent, sqlite_db):
        # Anonymous mint is refused on an open instance (S4: a token minted with no auth would
        # be a durable credential surviving a later lockdown). A PAT reaches an open instance
        # only if it was minted earlier under a security key / JWT -- simulate that by inserting
        # the account directly. The point here is that the PAT AUTHENTICATES and attributes
        # correctly on an open box.
        import uuid

        from agno.db.schemas.service_accounts import ServiceAccount
        from agno.os.service_accounts import DEFAULT_SERVICE_ACCOUNT_SCOPES, generate_token

        plaintext, token_hash, token_prefix = generate_token()
        account = ServiceAccount(
            id=str(uuid.uuid4()),
            name="claude-code",
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=list(DEFAULT_SERVICE_ACCOUNT_SCOPES),
            created_at=int(time.time()),
        )
        sqlite_db.create_service_account(account.to_dict())
        pat = plaintext

        with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
            mock_arun.return_value = _mock_run_output()
            run_response = open_client.post(
                "/agents/sa-test-agent/runs",
                headers={"Authorization": f"Bearer {pat}"},
                data={"message": "hello", "stream": "false"},
            )
        assert run_response.status_code == 200
        assert mock_arun.call_args.kwargs["user_id"] == "sa:claude-code"

    def test_stale_pat_falls_through_anonymous_on_open_instance(self, open_client):
        # A PAT that cannot be verified is ignored on an open instance: the request
        # proceeds anonymously, exactly as if no token had been sent. This is what
        # keeps a stale token left in a client (e.g. browser localStorage from a
        # previously auth-enabled deployment) from locking out a server without auth.
        response = open_client.get("/sessions", headers={"Authorization": "Bearer agno_pat_invalid000000000000000000"})
        assert response.status_code == 200


# A minimal MCP initialize request - enough to reach (or be blocked before) the MCP machinery.
MCP_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.mark.skipif(find_spec("fastmcp") is None, reason="fastmcp is not installed")
class TestServiceAccountsOverMCP:
    """The mounted /mcp app enforces the same auth rules as REST in non-JWT modes.

    Router dependencies never run for mounted sub-apps, so /mcp carries its own auth
    middleware. These tests drive the full AgentOS app end to end: mint over REST,
    then call the MCP endpoint.
    """

    @pytest.fixture
    def mcp_security_key_client(self, test_agent, sqlite_db):
        agent_os = AgentOS(
            agents=[test_agent],
            db=sqlite_db,
            enable_mcp_server=True,
            settings=AgnoAPISettings(os_security_key="root-security-key"),
        )
        # Context manager so the MCP session manager lifespan runs. base_url sets the
        # Host header; localhost passes the default-on rebinding guard on open servers.
        with TestClient(agent_os.get_app(), base_url="http://localhost") as client:
            yield client

    @pytest.fixture
    def mcp_open_client(self, test_agent, sqlite_db):
        agent_os = AgentOS(agents=[test_agent], db=sqlite_db, enable_mcp_server=True)
        with TestClient(agent_os.get_app(), base_url="http://localhost") as client:
            yield client

    def _mcp_post(self, client, token=None):
        headers = dict(MCP_HEADERS)
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return client.post("/mcp", json=MCP_INIT_BODY, headers=headers)

    def test_mcp_rejects_request_without_token(self, mcp_security_key_client):
        response = self._mcp_post(mcp_security_key_client)
        assert response.status_code == 401
        assert response.json()["detail"] == "Authorization header required"

    def test_mcp_rejects_bad_token(self, mcp_security_key_client):
        response = self._mcp_post(mcp_security_key_client, token="not-the-key")
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authentication token"

    def test_mcp_accepts_security_key(self, mcp_security_key_client):
        response = self._mcp_post(mcp_security_key_client, token="root-security-key")
        assert response.status_code == 200

    def test_mcp_accepts_valid_pat(self, mcp_security_key_client):
        pat = _mint(mcp_security_key_client, "root-security-key").json()["token"]
        response = self._mcp_post(mcp_security_key_client, token=pat)
        assert response.status_code == 200

    def test_mcp_rejects_revoked_pat(self, mcp_security_key_client):
        minted = _mint(mcp_security_key_client, "root-security-key").json()
        revoke = mcp_security_key_client.delete(
            f"/service-accounts/{minted['id']}",
            headers={"Authorization": "Bearer root-security-key"},
        )
        assert revoke.status_code == 204

        response = self._mcp_post(mcp_security_key_client, token=minted["token"])
        assert response.status_code == 401
        assert response.json()["detail"] == UNIFORM_401_DETAIL

    def test_mcp_stays_open_without_security_key(self, mcp_open_client):
        assert self._mcp_post(mcp_open_client).status_code == 200

    def test_mcp_ignores_pat_on_open_instance(self, mcp_open_client):
        # No auth middleware installs on an open instance, and mounted sub-apps never
        # run route dependencies, so /mcp sees the token but nothing inspects it: the
        # request passes through anonymously (same stale-PAT tolerance as REST).
        response = self._mcp_post(mcp_open_client, token="agno_pat_invalid000000000000000000")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# WebSocket (/workflows/ws) coverage: PAT and security-key auth must mirror
# REST semantics -- prefix dispatch before JWT, scopes enforced in every mode,
# user_id pinned to the service-account principal.
# ---------------------------------------------------------------------------

WS_SECURITY_KEY = "ws-test-security-key"


@pytest.fixture
def security_key_client(test_agent, sqlite_db):
    """AgentOS in security-key mode (no JWT anywhere) with a db."""
    agent_os = AgentOS(agents=[test_agent], db=sqlite_db, settings=AgnoAPISettings(os_security_key=WS_SECURITY_KEY))
    return TestClient(agent_os.get_app())


@pytest.fixture
def open_client(test_agent, sqlite_db):
    """AgentOS with a db but no credential configured (open instance)."""
    agent_os = AgentOS(agents=[test_agent], db=sqlite_db)
    return TestClient(agent_os.get_app())


def _ws_authenticate(ws, token):
    """Drain the connected frame, send an authenticate action, return the settling frame."""
    connected = json.loads(ws.receive_text())
    assert connected["event"] == "connected"
    ws.send_text(json.dumps({"action": "authenticate", "token": token}))
    return json.loads(ws.receive_text())


class TestServiceAccountsOverWebSocket:
    def _mint_with_security_key(self, client, name="ws-sa", **body_overrides):
        response = _mint(client, WS_SECURITY_KEY, name=name, **body_overrides)
        assert response.status_code == 201, response.text
        return response.json()

    def test_security_key_authenticates_over_ws(self, security_key_client):
        # Regression: the single-auth-layer install for security-key/db modes must
        # not read as a JWT deployment to the WS config resolver, which previously
        # rejected every credential with "JWT authentication is misconfigured".
        with security_key_client.websocket_connect("/workflows/ws") as ws:
            frame = _ws_authenticate(ws, WS_SECURITY_KEY)
        assert frame["event"] == "authenticated", frame

    def test_wrong_security_key_rejected_over_ws(self, security_key_client):
        with security_key_client.websocket_connect("/workflows/ws") as ws:
            frame = _ws_authenticate(ws, "not-the-key")
        assert frame["event"] == "auth_error"

    def test_open_instance_with_db_needs_no_ws_auth(self, open_client):
        # A db alone (service-account verifier present) must not gate the WS.
        with open_client.websocket_connect("/workflows/ws") as ws:
            connected = json.loads(ws.receive_text())
            assert connected["requires_auth"] is False
            ws.send_text(json.dumps({"action": "ping"}))
            assert json.loads(ws.receive_text())["event"] == "pong"

    def test_bogus_pat_rejected_over_ws_even_on_open_instance(self, open_client):
        # An explicit PAT either verifies or is rejected -- never falls through.
        with open_client.websocket_connect("/workflows/ws") as ws:
            frame = _ws_authenticate(ws, "agno_pat_definitely_not_real0000")
        assert frame["event"] == "auth_error"
        assert frame["error"] == UNIFORM_401_DETAIL

    def test_pat_authenticates_over_ws_in_security_key_mode(self, security_key_client):
        minted = self._mint_with_security_key(security_key_client)
        with security_key_client.websocket_connect("/workflows/ws") as ws:
            frame = _ws_authenticate(ws, minted["token"])
            assert frame["event"] == "authenticated", frame
            identity = json.loads(ws.receive_text())
        assert identity["user_id"] == "sa:ws-sa"

    def test_pat_missing_workflows_run_rejected_on_start_workflow(self, security_key_client):
        # PAT scopes are first-party ACL data: enforced on the WS even in
        # security-key mode, exactly like REST and MCP.
        minted = self._mint_with_security_key(security_key_client, name="ws-limited", scopes=["sessions:read"])
        with (
            patch("agno.os.router.handle_workflow_via_websocket", new_callable=AsyncMock) as handler,
            security_key_client.websocket_connect("/workflows/ws") as ws,
        ):
            # Assert the auth frame: on auth failure no identity frame ever arrives
            # and the next receive_text() blocks the suite forever.
            auth_frame = _ws_authenticate(ws, minted["token"])
            assert auth_frame["event"] == "authenticated", auth_frame
            ws.receive_text()  # identity frame
            ws.send_text(json.dumps({"action": "start-workflow", "workflow_id": "wf", "message": "go"}))
            frame = json.loads(ws.receive_text())
        assert frame == {"event": "error", "error": "Insufficient permissions to run this workflow"}
        handler.assert_not_awaited()

    def test_pat_user_id_forced_to_principal_on_start_workflow(self, security_key_client):
        # Default scopes include workflows:run, so the RBAC gate passes and the
        # dispatcher must overwrite a client-spoofed user_id with sa:<name>.
        minted = self._mint_with_security_key(security_key_client, name="ws-forced")
        with (
            patch("agno.os.router.handle_workflow_via_websocket", new_callable=AsyncMock) as handler,
            security_key_client.websocket_connect("/workflows/ws") as ws,
        ):
            auth_frame = _ws_authenticate(ws, minted["token"])
            assert auth_frame["event"] == "authenticated", auth_frame
            ws.receive_text()  # identity frame
            ws.send_text(
                json.dumps({"action": "start-workflow", "workflow_id": "wf", "message": "go", "user_id": "mallory"})
            )
            # Actions are handled sequentially, so a pong guarantees the
            # start-workflow dispatch (and the mocked handler call) completed.
            ws.send_text(json.dumps({"action": "ping"}))
            assert json.loads(ws.receive_text())["event"] == "pong"
        handler.assert_awaited_once()
        forwarded_message = handler.await_args.args[1]
        assert forwarded_message["user_id"] == "sa:ws-forced"

    def test_pat_authenticates_over_ws_in_jwt_mode(self, jwt_client):
        # Regression: the JWT branch used to swallow every token, feeding the
        # opaque PAT to the JWT validator. Prefix dispatch now mirrors REST.
        admin_jwt = _make_jwt(["agent_os:admin"])
        minted = _mint(jwt_client, admin_jwt, name="ws-jwt-sa").json()
        with jwt_client.websocket_connect("/workflows/ws") as ws:
            frame = _ws_authenticate(ws, minted["token"])
            assert frame["event"] == "authenticated", frame
            identity = json.loads(ws.receive_text())
        assert identity["user_id"] == "sa:ws-jwt-sa"

    def test_pat_missing_scope_rejected_on_start_workflow_in_jwt_mode(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        minted = _mint(jwt_client, admin_jwt, name="ws-jwt-limited", scopes=["sessions:read"]).json()
        with jwt_client.websocket_connect("/workflows/ws") as ws:
            auth_frame = _ws_authenticate(ws, minted["token"])
            assert auth_frame["event"] == "authenticated", auth_frame
            ws.receive_text()  # identity frame
            ws.send_text(json.dumps({"action": "start-workflow", "workflow_id": "wf", "message": "go"}))
            frame = json.loads(ws.receive_text())
        assert frame["error"] == "Insufficient permissions to run this workflow"

    def test_revoked_pat_rejected_over_ws(self, jwt_client):
        admin_jwt = _make_jwt(["agent_os:admin"])
        minted = _mint(jwt_client, admin_jwt, name="ws-jwt-revoked").json()
        revoke = jwt_client.delete(
            f"/service-accounts/{minted['id']}", headers={"Authorization": f"Bearer {admin_jwt}"}
        )
        assert revoke.status_code == 204
        with jwt_client.websocket_connect("/workflows/ws") as ws:
            frame = _ws_authenticate(ws, minted["token"])
        assert frame["event"] == "auth_error"
        assert frame["error"] == UNIFORM_401_DETAIL
