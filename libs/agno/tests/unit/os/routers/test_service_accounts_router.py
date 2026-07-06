"""Tests for the service accounts REST API router."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from agno.os.routers.service_accounts import get_service_accounts_router
from agno.os.service_accounts import DEFAULT_EXPIRY_DAYS, DEFAULT_SERVICE_ACCOUNT_SCOPES, TOKEN_PREFIX
from agno.os.settings import AgnoAPISettings

# =============================================================================
# Fixtures
# =============================================================================


def _make_account_dict(**overrides):
    now = int(time.time())
    d = {
        "id": "sa-1",
        "name": "claude-code",
        "user_id": "admin-user",
        "token_hash": "a" * 64,
        "token_prefix": "agno_pat_abc1234",
        "scopes": list(DEFAULT_SERVICE_ACCOUNT_SCOPES),
        "created_at": now,
        "expires_at": now + 90 * 86400,
        "last_used_at": None,
        "revoked_at": None,
        "created_by": "admin-user",
    }
    d.update(overrides)
    return d


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_service_accounts = MagicMock(return_value=([], 0))
    db.get_service_account = MagicMock(return_value=None)
    db.get_service_account_by_name = MagicMock(return_value=None)
    db.create_service_account = MagicMock(side_effect=lambda data: data)
    db.update_service_account = MagicMock(return_value=_make_account_dict(revoked_at=int(time.time())))
    return db


@pytest.fixture
def settings():
    return AgnoAPISettings()


def _authenticated_app(mock_db, settings):
    """An app whose caller is an authenticated, unscoped root (os_security_key / JWT).

    Minting requires authentication, so the happy-path fixture authenticates. A middleware
    marks request.state.authenticated = True, standing in for the auth layer that would set
    it in production. Anonymous open-mode behaviour is covered separately by
    TestCreateServiceAccountUnauthenticatedOpenMode.
    """
    app = FastAPI()

    @app.middleware("http")
    async def set_authenticated(request, call_next):
        request.state.authenticated = True
        return await call_next(request)

    app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
    return app


@pytest.fixture
def client(mock_db, settings):
    return TestClient(_authenticated_app(mock_db, settings))


# =============================================================================
# Tests: POST /service-accounts
# =============================================================================


class TestCreateServiceAccount:
    def test_mint_with_defaults(self, client, mock_db):
        response = client.post("/service-accounts", json={"name": "claude-code"})
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "claude-code"
        assert body["principal"] == "sa:claude-code"
        assert [s["raw"] for s in body["scopes"]] == list(DEFAULT_SERVICE_ACCOUNT_SCOPES)
        # Scopes ride the shared RBAC read shape so governance and token UIs render alike
        assert body["scopes"][0] == {
            "id": None,
            "raw": "agents:run",
            "namespace": "agents",
            "sub_namespace": None,
            "permission": "run",
            "value": "allow",
        }
        assert body["token"].startswith(TOKEN_PREFIX)
        assert body["token_prefix"] == body["token"][:16]
        # Default expiry ~90 days out
        assert body["expires_at"] is not None
        expected = int(time.time()) + DEFAULT_EXPIRY_DAYS * 86400
        assert abs(body["expires_at"] - expected) < 60
        # Only the hash is persisted, never the plaintext
        stored = mock_db.create_service_account.call_args.args[0]
        assert body["token"] not in str(stored)
        assert stored["token_hash"] != body["token"]

    def test_mint_records_owner_and_creator(self, mock_db, settings):
        """A JWT-authenticated mint stamps both user_id (ownership) and created_by (audit)."""
        app = FastAPI()

        @app.middleware("http")
        async def set_authenticated_user(request, call_next):
            request.state.authenticated = True
            request.state.user_id = "alice"
            return await call_next(request)

        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        response = TestClient(app).post("/service-accounts", json={"name": "claude-code"})
        assert response.status_code == 201
        body = response.json()
        assert body["user_id"] == "alice"
        assert body["created_by"] == "alice"
        stored = mock_db.create_service_account.call_args.args[0]
        assert stored["user_id"] == "alice"
        assert stored["created_by"] == "alice"

    def test_mint_without_user_context_leaves_owner_unset(self, client, mock_db):
        """A root minted without a user context (os_security_key) has no owning user."""
        response = client.post("/service-accounts", json={"name": "claude-code"})
        assert response.status_code == 201
        assert response.json()["user_id"] is None
        stored = mock_db.create_service_account.call_args.args[0]
        assert stored["user_id"] is None

    def test_custom_expiry(self, client):
        response = client.post("/service-accounts", json={"name": "cursor", "expires_in_days": 7})
        assert response.status_code == 201
        expected = int(time.time()) + 7 * 86400
        assert abs(response.json()["expires_at"] - expected) < 60

    def test_never_expires_requires_explicit_flag(self, client):
        response = client.post("/service-accounts", json={"name": "cursor", "never_expires": True})
        assert response.status_code == 201
        assert response.json()["expires_at"] is None

    def test_invalid_name_rejected(self, client):
        for bad_name in ["Claude-Code", "__scheduler__", "sa:claude", "user@example.com"]:
            response = client.post("/service-accounts", json={"name": bad_name})
            assert response.status_code == 422, bad_name

    def test_unknown_scope_rejected(self, client):
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "bogus"}]})
        assert response.status_code == 400
        assert "Invalid scope" in response.json()["detail"]

    def test_privileged_scope_requires_flag(self, client):
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "sessions:write"}]})
        assert response.status_code == 400
        assert "allow_privileged_scopes" in response.json()["detail"]

    def test_admin_scope_requires_flag(self, client):
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "agent_os:admin"}]})
        assert response.status_code == 400

    def test_service_accounts_scope_requires_flag(self, client):
        response = client.post(
            "/service-accounts", json={"name": "ci", "scopes": [{"scope": "service_accounts:write"}]}
        )
        assert response.status_code == 400

    def test_privileged_scope_allowed_with_flag_for_authenticated_root(self, mock_db, settings):
        # A trusted root (os_security_key / internal token sets request.state.authenticated)
        # may mint a privileged token when the explicit flag is set. An UNauthenticated
        # (open-mode) caller may not -- see TestCreateServiceAccountUnauthenticatedOpenMode.
        from fastapi import Request

        app = FastAPI()

        @app.middleware("http")
        async def set_authenticated(request: Request, call_next):
            request.state.authenticated = True
            return await call_next(request)

        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        response = TestClient(app).post(
            "/service-accounts",
            json={"name": "ci", "scopes": [{"scope": "sessions:write"}], "allow_privileged_scopes": True},
        )
        assert response.status_code == 201
        assert [s["raw"] for s in response.json()["scopes"]] == ["sessions:write"]

    def test_mint_accepts_scope_objects(self, client):
        # The write shape is the shared RBAC payload: {scope, effect} objects (effect optional)
        response = client.post(
            "/service-accounts",
            json={"name": "ci", "scopes": [{"scope": "agents:run", "effect": "allow"}, {"scope": "sessions:read"}]},
        )
        assert response.status_code == 201
        assert [s["raw"] for s in response.json()["scopes"]] == ["agents:run", "sessions:read"]

    def test_mint_rejects_plain_string_scopes(self, client):
        # Objects-only by design: a bare string is a 422, keeping one canonical write shape
        response = client.post(
            "/service-accounts",
            json={"name": "ci", "scopes": ["agents:run"]},
        )
        assert response.status_code == 422

    def test_mint_rejects_unknown_effect(self, client):
        # effect is constrained at the model layer; typos like "Allow" are a 422
        response = client.post(
            "/service-accounts",
            json={"name": "ci", "scopes": [{"scope": "agents:run", "effect": "Allow"}]},
        )
        assert response.status_code == 422

    def test_mint_rejects_deny_effect(self, client):
        # Token scopes are pure grants; a deny rule belongs on a role, not a token
        response = client.post(
            "/service-accounts",
            json={"name": "ci", "scopes": [{"scope": "agents:run", "effect": "deny"}]},
        )
        assert response.status_code == 422
        assert "allow" in response.text

    def test_per_resource_scope_parses_into_sub_namespace(self, client):
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "agents:my-agent:run"}]})
        assert response.status_code == 201
        assert response.json()["scopes"][0] == {
            "id": None,
            "raw": "agents:my-agent:run",
            "namespace": "agents",
            "sub_namespace": "my-agent",
            "permission": "run",
            "value": "allow",
        }

    def test_duplicate_active_name_conflicts(self, client, mock_db):
        mock_db.get_service_account_by_name = MagicMock(return_value=_make_account_dict())
        response = client.post("/service-accounts", json={"name": "claude-code"})
        assert response.status_code == 409

    def test_integrity_error_maps_to_conflict(self, client, mock_db):
        mock_db.create_service_account = MagicMock(
            side_effect=IntegrityError("UNIQUE constraint failed", None, Exception())
        )
        response = client.post("/service-accounts", json={"name": "claude-code"})
        assert response.status_code == 409

    def test_db_without_support_returns_503(self, settings):
        db = MagicMock()
        db.get_service_account_by_name = MagicMock(side_effect=NotImplementedError)
        response = TestClient(_authenticated_app(db, settings)).post("/service-accounts", json={"name": "ci"})
        assert response.status_code == 503


class TestCreateServiceAccountSubsetRule:
    """The minted scopes must be held by the creator (unless admin or unscoped root)."""

    def _client_with_state(self, mock_db, settings, caller_scopes):
        from fastapi import Request

        app = FastAPI()

        @app.middleware("http")
        async def set_scopes(request: Request, call_next):
            request.state.scopes = caller_scopes
            request.state.authenticated = True
            return await call_next(request)

        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        return TestClient(app)

    def test_caller_cannot_grant_scopes_it_does_not_hold(self, mock_db, settings):
        client = self._client_with_state(mock_db, settings, ["service_accounts:write", "agents:run"])
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "teams:run"}]})
        assert response.status_code == 403
        assert "teams:run" in response.json()["detail"]

    def test_caller_can_grant_subset_of_own_scopes(self, mock_db, settings):
        client = self._client_with_state(mock_db, settings, ["service_accounts:write", "agents:run", "sessions:read"])
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "agents:run"}]})
        assert response.status_code == 201

    def test_admin_caller_can_grant_anything(self, mock_db, settings):
        client = self._client_with_state(mock_db, settings, ["agent_os:admin"])
        response = client.post(
            "/service-accounts",
            json={"name": "ci", "scopes": [{"scope": "sessions:delete"}], "allow_privileged_scopes": True},
        )
        assert response.status_code == 201

    def test_wildcard_scope_covers_per_resource_grant(self, mock_db, settings):
        client = self._client_with_state(mock_db, settings, ["agents:*:run"])
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "agents:my-agent:run"}]})
        assert response.status_code == 201

    def test_caller_can_grant_exact_per_resource_scope_it_holds(self, mock_db, settings):
        # Least-privilege delegation: holding exactly agents:my-agent:run must be
        # enough to grant agents:my-agent:run.
        client = self._client_with_state(mock_db, settings, ["service_accounts:write", "agents:my-agent:run"])
        response = client.post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "agents:my-agent:run"}]})
        assert response.status_code == 201

    def test_caller_cannot_grant_per_resource_scope_for_other_resource(self, mock_db, settings):
        client = self._client_with_state(mock_db, settings, ["service_accounts:write", "agents:my-agent:run"])
        response = client.post(
            "/service-accounts", json={"name": "ci", "scopes": [{"scope": "agents:other-agent:run"}]}
        )
        assert response.status_code == 403

    def test_unscoped_unauthenticated_caller_cannot_mint(self, mock_db, settings):
        # No request.state.scopes and not authenticated (an open dev instance). Even a plain
        # non-privileged token is refused: an anonymously-minted PAT persists as a durable
        # credential after the operator later enables auth. See
        # TestCreateServiceAccountUnauthenticatedOpenMode.
        app = FastAPI()
        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        response = TestClient(app).post("/service-accounts", json={"name": "ci", "scopes": [{"scope": "teams:run"}]})
        assert response.status_code == 401


class TestCreateServiceAccountUnauthenticatedOpenMode:
    """S4: on an OPEN instance (no security key, no JWT) request.state.authenticated is
    falsy and scopes is unset. Such an anonymous caller must NOT be able to mint ANY token
    -- privileged or not -- because a minted PAT persists as a durable credential even after
    the operator later enables auth (PAT scopes are enforced independently of the
    authorization flag). Minting requires a real credential (OS_SECURITY_KEY or JWT)."""

    @pytest.fixture
    def anon_client(self, mock_db, settings):
        app = FastAPI()
        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        return TestClient(app)

    def test_anonymous_cannot_mint_default_token(self, anon_client):
        response = anon_client.post("/service-accounts", json={"name": "ci"})
        assert response.status_code == 401
        assert "JWT authentication is required" in response.json()["detail"]

    def test_anonymous_cannot_mint_never_expiring_run_token(self, anon_client):
        # The durable-credential case: a never-expiring run/read token would survive the
        # operator later enabling auth. Refused even though its scopes are non-privileged.
        response = anon_client.post(
            "/service-accounts",
            json={
                "name": "backdoor",
                "scopes": [{"scope": "agents:run"}, {"scope": "sessions:read"}],
                "never_expires": True,
            },
        )
        assert response.status_code == 401

    def test_anonymous_cannot_mint_admin_even_with_flag(self, anon_client):
        response = anon_client.post(
            "/service-accounts",
            json={
                "name": "backdoor",
                "scopes": [{"scope": "agent_os:admin"}],
                "allow_privileged_scopes": True,
                "never_expires": True,
            },
        )
        assert response.status_code == 401
        assert "JWT authentication is required" in response.json()["detail"]

    def test_anonymous_cannot_mint_write_scope_even_with_flag(self, anon_client):
        response = anon_client.post(
            "/service-accounts",
            json={"name": "w", "scopes": [{"scope": "sessions:write"}], "allow_privileged_scopes": True},
        )
        assert response.status_code == 401

    def test_anonymous_cannot_mint_service_accounts_scope_even_with_flag(self, anon_client):
        response = anon_client.post(
            "/service-accounts",
            json={"name": "minter", "scopes": [{"scope": "service_accounts:write"}], "allow_privileged_scopes": True},
        )
        assert response.status_code == 401


class TestCreateServiceAccountSecurityKeyRoot:
    """A caller validated by the OS security key is a trusted, unscoped root: the auth
    dependency marks it authenticated, so it may mint privileged tokens. Regression test for
    the security-key path failing to set request.state.authenticated (which would falsely
    route a legitimate root through the fail-closed anonymous branch)."""

    def test_security_key_root_can_mint_privileged(self, mock_db):
        settings = AgnoAPISettings(os_security_key="root-key-123")
        app = FastAPI()
        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        response = TestClient(app).post(
            "/service-accounts",
            headers={"Authorization": "Bearer root-key-123"},
            json={"name": "ci", "scopes": [{"scope": "agent_os:admin"}], "allow_privileged_scopes": True},
        )
        assert response.status_code == 201, response.text
        assert [s["raw"] for s in response.json()["scopes"]] == ["agent_os:admin"]

    def test_invalid_security_key_is_rejected(self, mock_db):
        settings = AgnoAPISettings(os_security_key="root-key-123")
        app = FastAPI()
        app.include_router(get_service_accounts_router(os_db=mock_db, settings=settings))
        response = TestClient(app).post(
            "/service-accounts",
            headers={"Authorization": "Bearer wrong-key"},
            json={"name": "ci"},
        )
        assert response.status_code == 401


# =============================================================================
# Tests: GET /service-accounts
# =============================================================================


class TestListServiceAccounts:
    def test_empty_list(self, client):
        response = client.get("/service-accounts")
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["meta"]["total_count"] == 0

    def test_list_returns_metadata_never_secrets(self, client, mock_db):
        mock_db.get_service_accounts = MagicMock(return_value=([_make_account_dict()], 1))
        response = client.get("/service-accounts")
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        entry = body["data"][0]
        assert entry["token_prefix"] == "agno_pat_abc1234"
        assert entry["principal"] == "sa:claude-code"
        # List responses carry the same parsed scope shape as the create response
        assert [s["raw"] for s in entry["scopes"]] == list(DEFAULT_SERVICE_ACCOUNT_SCOPES)
        assert entry["scopes"][0]["namespace"] == "agents"
        assert entry["scopes"][0]["value"] == "allow"
        assert "token" not in entry
        assert "token_hash" not in entry
        assert "a" * 64 not in response.text

    def test_pagination_params_forwarded(self, client, mock_db):
        client.get("/service-accounts?limit=5&page=2&include_revoked=false&sort_by=name&sort_order=asc")
        kwargs = mock_db.get_service_accounts.call_args.kwargs
        assert kwargs["limit"] == 5
        assert kwargs["page"] == 2
        assert kwargs["include_revoked"] is False
        assert kwargs["sort_by"] == "name"
        assert kwargs["sort_order"] == "asc"


# =============================================================================
# Tests: DELETE /service-accounts/{id}
# =============================================================================


class TestRevokeServiceAccount:
    def test_unknown_id_returns_404(self, client):
        response = client.delete("/service-accounts/nope")
        assert response.status_code == 404

    def test_revoke_sets_revoked_at(self, client, mock_db):
        mock_db.get_service_account = MagicMock(return_value=_make_account_dict())
        response = client.delete("/service-accounts/sa-1")
        assert response.status_code == 204
        kwargs = mock_db.update_service_account.call_args.kwargs
        assert kwargs["revoked_at"] is not None

    def test_already_revoked_is_idempotent(self, client, mock_db):
        mock_db.get_service_account = MagicMock(return_value=_make_account_dict(revoked_at=int(time.time())))
        response = client.delete("/service-accounts/sa-1")
        assert response.status_code == 204
        mock_db.update_service_account.assert_not_called()
