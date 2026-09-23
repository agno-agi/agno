"""Hygiene fixes from the authorization review, each pinned by the behaviour it changes.

- Scope and slug validation: whitespace, a "*" resource type and a "/" in the type are refused
  on save; the legacy ``system:`` spelling is stored as ``config:`` so a managed role written
  with the old name satisfies the route.
- Reserved principals (the scheduler, service accounts, MCP OAuth clients) cannot hold a role.
- ``seed(admin=)`` does not re-grant a demoted bootstrap admin when admins live on tokens.
- Free-text search treats the caller's text as data, not a LIKE pattern.
- A token carrying thousands of roles is decided on SQLite instead of hitting its parameter cap.
- A sync ``DbAuditSink.record`` on an async database writes the row.
- The admin-approval gate fails closed when the approval state cannot be read.
- Error responses do not reflect an arbitrary Origin when no allow-list is configured.
- Security-key comparisons are constant time and tolerate non-ASCII input.
"""

import asyncio
import time

import jwt
import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sql.authz import _like_pattern  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.auth import run_continuation_blocked_reason, validate_websocket_token  # noqa: E402
from agno.os.authz import Authorization, UserDirectory  # noqa: E402
from agno.os.authz._scope_policy import scope_to_resource_action  # noqa: E402
from agno.os.authz.audit import AuditEvent, DbAuditSink  # noqa: E402
from agno.os.middleware.jwt import AuthMiddleware  # noqa: E402
from agno.os.settings import AgnoAPISettings  # noqa: E402

SECRET = "low-findings-secret-at-least-32-bytes!!"
OS_ID = "low-findings-os"


def _auth(sub: str, **claims) -> dict:
    payload = {"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600, **claims}
    return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}


def _managed(tmp_path, name="low", **kwargs) -> Authorization:
    db = SqliteDb(db_file=str(tmp_path / f"{name}.db"))
    return Authorization(db=db, verification_keys=[SECRET], audience=OS_ID, algorithm="HS256", **kwargs)


def _app(authz: Authorization, directory=None) -> TestClient:
    kwargs = {"user_directory": directory} if directory is not None else {}
    agent_os = AgentOS(id=OS_ID, db=authz._db, agents=[Agent(id="a", db=InMemoryDb())], authorization=authz, **kwargs)
    return TestClient(agent_os.get_app())


# ---------------------------------------------------------------- scopes and slugs


@pytest.mark.parametrize("scope", ["agents:*:read ", "agents: read", " agents:read", "*:read", "agents/x:read"])
def test_malformed_scopes_are_refused_on_save(scope):
    with pytest.raises(ValueError):
        scope_to_resource_action(scope)


def test_the_legacy_system_scope_is_stored_as_config():
    assert scope_to_resource_action("system:read") == ("config/*", "read")


def test_a_managed_role_written_with_the_legacy_spelling_reaches_config(tmp_path):
    authz = _managed(tmp_path)
    authz.define_role("legacy", ["system:read"])
    authz.assign("alice", "legacy")
    client = _app(authz)
    assert client.get("/config", headers=_auth("alice")).status_code == 200


@pytest.fixture
def admin_client(tmp_path):
    authz = _managed(tmp_path, "admin")
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:read"])
    authz.seed(admin="root")
    return _app(authz), _auth("root")


def test_a_scope_with_whitespace_is_refused_by_the_admin_api(admin_client):
    client, root = admin_client
    resp = client.put("/authz/roles/viewer/scopes", json={"scopes": ["agents:*:read "]}, headers=root)
    assert resp.status_code in (400, 422), resp.text
    assert client.get("/authz/roles/viewer", headers=root).json()["scopes"] != ["agents:*:read "]


@pytest.mark.parametrize("slug", ["admin ", "a b", "a/b"])
def test_a_role_slug_with_whitespace_or_a_slash_is_refused(tmp_path, slug):
    authz = _managed(tmp_path, "slug")
    authz.define_role("admin", ["agent_os:admin"])
    authz.seed(admin="root")
    client = _app(authz)
    resp = client.post("/authz/roles", json={"slug": slug, "scopes": ["agents:read"]}, headers=_auth("root"))
    assert resp.status_code in (400, 422), resp.text
    listing = client.get("/authz/roles", headers=_auth("root")).json()
    roles = listing if isinstance(listing, list) else listing.get("data") or listing.get("roles") or []
    assert slug not in [r["slug"] for r in roles]


@pytest.mark.parametrize("subject", ["__scheduler__", "sa:bot", "__oauth__:client-1", " alice"])
def test_reserved_or_padded_subjects_cannot_hold_a_role(admin_client, subject):
    client, root = admin_client
    resp = client.post(f"/authz/subjects/{subject}/roles", json={"role": "viewer"}, headers=root)
    assert resp.status_code == 400, resp.text
    assert client.get(f"/authz/subjects/{subject}/roles", headers=root).json()["role"] is None


def test_the_runtime_api_refuses_a_reserved_subject_too(tmp_path):
    authz = _managed(tmp_path, "runtime")
    authz.define_role("viewer", ["agents:read"])
    _app(authz)
    with pytest.raises(ValueError, match="reserved"):
        authz.set_role("__scheduler__", "viewer")


# ---------------------------------------------------------------- seed under token-based admins


def test_seed_does_not_regrant_a_demoted_admin_when_roles_live_on_tokens(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "seed.db"))

    def boot() -> Authorization:
        authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID, algorithm="HS256", roles_claim="roles")
        authz.define_role("admin", ["agent_os:admin"])
        authz.define_role("viewer", ["agents:read"])
        authz.seed(admin="root")
        AgentOS(id=OS_ID, db=db, agents=[Agent(id="a", db=InMemoryDb())], authorization=authz)
        return authz

    first = boot()
    assert first._store().roles_of("root") == ["admin"]
    first.set_role("root", "viewer")  # handover: admins now come from the IdP's roles claim
    second = boot()
    assert second._store().roles_of("root") == ["viewer"]


def test_seed_still_bootstraps_a_fresh_store_when_roles_live_on_tokens(tmp_path):
    authz = _managed(tmp_path, "fresh", roles_claim="roles")
    authz.define_role("admin", ["agent_os:admin"])
    authz.seed(admin="root")
    _app(authz)
    assert authz._store().roles_of("root") == ["admin"]


# ---------------------------------------------------------------- search


def test_search_text_is_data_not_pattern():
    assert _like_pattern("50%_\\") == "%50\\%\\_\\\\%"
    assert len(_like_pattern("x" * 10_000)) == 202


def test_user_search_treats_percent_and_underscore_literally(tmp_path):
    authz = _managed(tmp_path, "search")
    directory = UserDirectory(auto_provision=False)
    _app(authz, directory)
    for user_id in ("pct-50%", "pct-500", "a_b", "acb"):
        directory.upsert(user_id)
    assert [u["id"] for u in directory.list(search="50%")] == ["pct-50%"]
    assert [u["id"] for u in directory.list(search="a_b")] == ["a_b"]
    assert sorted(u["id"] for u in directory.list(search="PCT")) == ["pct-50%", "pct-500"]


def test_audit_search_is_case_insensitive_and_literal(tmp_path):
    from agno.db.sqlite import SqliteDb as _Sqlite

    sink = DbAuditSink(db=_Sqlite(db_file=str(tmp_path / "audit.db")))
    sink.record(AuditEvent(action="role.set_scopes", actor="Root", target="ops_team", timestamp=1))
    sink.record(AuditEvent(action="role.set_scopes", actor="Root", target="opsXteam", timestamp=2))
    assert [r["target"] for r in sink.read(search="ops_team")] == ["ops_team"]
    assert sink.count(search="ROOT") == 2


# ---------------------------------------------------------------- many roles on SQLite


def test_a_token_with_tens_of_thousands_of_roles_is_decided_on_sqlite(tmp_path):
    authz = _managed(tmp_path, "many")
    authz.define_role("viewer", ["agents:read"])
    _app(authz)
    engine = authz._store()._engine
    roles = [f"r{i}" for i in range(35_000)]
    assert engine.check_scope("agents:read", roles=roles) is False
    assert engine.check_scope("agents:read", roles=roles + ["viewer"]) is True


# ---------------------------------------------------------------- sync audit write on an async db


def test_sync_record_on_an_async_db_writes_the_row(tmp_path):
    from agno.db.sqlite import AsyncSqliteDb

    sink = DbAuditSink(db=AsyncSqliteDb(db_file=str(tmp_path / "async-audit.db")))
    sink.record(AuditEvent(action="role.set_scopes", actor="root", target="outside-loop", timestamp=1))

    async def inside_loop():
        sink.record(AuditEvent(action="role.set_scopes", actor="root", target="inside-loop", timestamp=2))
        await asyncio.gather(*sink._pending_writes)
        return await sink.aread()

    rows = asyncio.run(inside_loop())
    assert sorted(r["target"] for r in rows) == ["inside-loop", "outside-loop"]


def test_the_ignored_sink_arguments_are_called_out(tmp_path, monkeypatch):
    from agno.db.sqlite import SqliteDb as _Sqlite

    warnings: list = []
    monkeypatch.setattr("agno.os.authz.audit.log_warning", warnings.append)
    DbAuditSink(db=_Sqlite(db_file=str(tmp_path / "named.db")), table_name="my_audit")
    assert any("ignores table_name" in message for message in warnings)


# ---------------------------------------------------------------- approval gate


class _FailingApprovalsDb:
    def get_approvals(self, **kwargs):
        raise RuntimeError("database unreachable")


class _NoApprovalsDb:
    def get_approvals(self, **kwargs):
        raise NotImplementedError


def test_the_approval_gate_fails_closed_when_the_state_cannot_be_read():
    reason = asyncio.run(
        run_continuation_blocked_reason(_FailingApprovalsDb(), "run-1", authorization_enabled=True, user_scopes=[])
    )
    assert reason is not None and "could not be verified" in reason


def test_the_approval_gate_skips_a_db_without_approvals():
    reason = asyncio.run(
        run_continuation_blocked_reason(_NoApprovalsDb(), "run-1", authorization_enabled=True, user_scopes=[])
    )
    assert reason is None


# ---------------------------------------------------------------- CORS on error responses


def test_error_responses_do_not_reflect_an_origin_without_an_allow_list():
    middleware = AuthMiddleware.__new__(AuthMiddleware)
    resp = AuthMiddleware._create_error_response(
        middleware, 401, "no", origin="https://evil.example", cors_allowed_origins=None
    )
    assert "access-control-allow-origin" not in resp.headers
    resp = AuthMiddleware._create_error_response(
        middleware, 401, "no", origin="https://app.example", cors_allowed_origins=["https://app.example"]
    )
    assert resp.headers["access-control-allow-origin"] == "https://app.example"


# ---------------------------------------------------------------- security key compare


def test_security_key_compare_tolerates_non_ascii_input():
    settings = AgnoAPISettings(os_security_key="sec-key")
    assert validate_websocket_token("sec-key", settings) is True
    assert validate_websocket_token("sec-kéy", settings) is False
    assert validate_websocket_token("", settings) is False
