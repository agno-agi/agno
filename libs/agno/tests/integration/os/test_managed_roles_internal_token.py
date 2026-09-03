"""Regression tests: the internal service token (scheduler executor) must pass the
per-resource handler gate under a managed-roles (EngineAuthorizationProvider)
deployment, while a normal user with no role is still denied at that same gate.

Background: the scheduler executor POSTs to ``/agents/{id}/runs`` (and team/workflow
equivalents) with ``Authorization: Bearer <internal_service_token>``. The JWT
middleware authorizes that token at the route gate via ``INTERNAL_SERVICE_SCOPES``.
But those run endpoints ALSO carry a per-resource handler gate
(``require_resource_access`` -> ``check_resource_access`` -> ``provider.check``).
Under managed roles, ``provider.check`` keys off the subject (``__scheduler__``) and
token-carried roles, ignoring scopes — and ``__scheduler__`` has no assignment, so
the handler gate used to return 403 even though the route gate passed.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "managed-roles-internal-token-test-secret-at-least-256-bits-long"
OS_ID = "managed-roles-internal-token-os"
INTERNAL_TOKEN = "internal-service-token-for-scheduler-test-xxxxxxxxxxxxxxxx"


def _db_url() -> str:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".authz.db")
    os.close(fd)
    return f"sqlite:///{path}"


def _user_token(sub: str) -> str:
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def client_and_store():
    store = ManagedRoleStore(db_url=_db_url())
    # A real user with NO role assigned — should be denied at the per-resource gate.
    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        internal_service_token=INTERNAL_TOKEN,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
        ),
    )
    app = agent_os.get_app()
    return TestClient(app), store


def _get_run(client: TestClient, token: str) -> int:
    """Hit a per-resource-gated endpoint. The handler gate runs before the body, so:
    403 => denied at the gate; anything else (404 for missing run) => gate passed."""
    return client.get(
        "/agents/research-agent/runs/nonexistent-run",
        params={"session_id": "s1"},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code


def test_internal_token_passes_per_resource_gate(client_and_store):
    """The scheduler's internal token must NOT be 403'd at the per-resource handler
    gate under managed roles (it already passed the route gate)."""
    client, _ = client_and_store
    status = _get_run(client, INTERNAL_TOKEN)
    assert status != 403, f"internal service token was denied at the per-resource gate (got {status})"


def test_normal_user_without_role_still_denied(client_and_store):
    """A normal user with no role assignment is STILL denied at the per-resource gate —
    proving the internal-token bypass is strictly internal-only."""
    client, _ = client_and_store
    status = _get_run(client, _user_token("nobody"))
    assert status == 403, f"normal user with no role should be denied at the gate (got {status})"


def test_service_account_pat_passes_the_resource_gate_under_managed_roles(tmp_path):
    """Regression: a PAT must still run agents when a managed-role provider is configured.

    A service account is a first-party machine credential whose PAT scopes ARE its ACL;
    it has no subject or role in the directory. The route gate admits it on scope math,
    but the per-resource gate delegated to the configured provider, which looked up
    ``sa:<name>`` in the role store, found nothing, and 403'd -- so every PAT-gated route
    (and every MCP tool call) broke the moment managed roles were switched on.
    """
    from unittest.mock import AsyncMock, patch

    from agno.db.sqlite import SqliteDb
    from agno.os.middleware import JWTMiddleware

    def _mock_run_output():
        return type("MockRunOutput", (), {"to_dict": lambda self: {"content": "ok", "run_id": "test_run_1"}})()

    db = SqliteDb(db_file=str(tmp_path / "pat_managed_roles.db"))
    agent = Agent(id="research-agent", name="Research Agent", db=db)
    agent.deep_copy = lambda **kwargs: agent

    store = ManagedRoleStore(db_url=f"sqlite:///{tmp_path / 'roles.db'}")
    store.set_role_scopes("viewer", ["agents:*:read"])  # no role mentions the PAT principal
    store.set_role_scopes("os-admin", ["agent_os:admin"])
    store.assign("human-admin", "os-admin")  # the human who mints the PAT is a directory user

    agent_os = AgentOS(id=OS_ID, agents=[agent], db=db)
    app = agent_os.get_app()
    app.state.authorization_provider = store.provider
    app.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256", authorization=True)
    client = TestClient(app)

    admin_jwt = jwt.encode(
        {"sub": "human-admin", "scopes": ["agent_os:admin"], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    minted = client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {admin_jwt}"},
        json={"name": "claude-code", "scopes": [{"scope": "agents:*:run"}, {"scope": "agents:*:read"}]},
    )
    assert minted.status_code == 201, minted.text
    pat = minted.json()["token"]

    with patch.object(agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = _mock_run_output()
        run = client.post(
            "/agents/research-agent/runs",
            headers={"Authorization": f"Bearer {pat}"},
            data={"message": "hello", "stream": "false"},
        )
    assert run.status_code == 200, run.text
    assert mock_arun.call_args.kwargs["user_id"] == "sa:claude-code"


def test_service_account_pat_sees_collections_under_managed_roles(tmp_path):
    """Regression: a PAT must reach LIST endpoints, not just per-resource routes.

    PAT callers are evaluated by scope math because their scopes are their ACL and they
    have no row in a managed store. That exemption was wired into the per-resource gate
    only, so ``GET /agents/{id}`` succeeded while ``GET /agents`` -- which resolves the
    provider separately -- answered 403, or worse returned 200 with an empty list.
    """
    from agno.db.sqlite import SqliteDb
    from agno.os.middleware import JWTMiddleware

    db = SqliteDb(db_file=str(tmp_path / "pat_list.db"))
    agent = Agent(id="research-agent", name="Research Agent", db=db)
    agent.deep_copy = lambda **kwargs: agent

    store = ManagedRoleStore(db_url=f"sqlite:///{tmp_path / 'roles.db'}")
    store.set_role_scopes("os-admin", ["agent_os:admin"])
    store.assign("human-admin", "os-admin")

    agent_os = AgentOS(id=OS_ID, agents=[agent], db=db)
    app = agent_os.get_app()
    app.state.authorization_provider = store.provider
    app.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256", authorization=True)
    client = TestClient(app)

    admin_jwt = jwt.encode(
        {"sub": "human-admin", "scopes": ["agent_os:admin"], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    minted = client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {admin_jwt}"},
        json={"name": "claude-code", "scopes": [{"scope": "agents:*:read"}, {"scope": "agents:*:run"}]},
    )
    assert minted.status_code == 201, minted.text
    headers = {"Authorization": f"Bearer {minted.json()['token']}"}

    assert client.get("/agents/research-agent", headers=headers).status_code == 200
    listing = client.get("/agents", headers=headers)
    assert listing.status_code == 200, listing.text
    assert [a["id"] for a in listing.json()] == ["research-agent"], "PAT saw an empty or filtered listing"


def test_pat_mint_subset_rule_uses_the_provider_not_token_scopes(tmp_path):
    """Escalation regression (PAT-1). Under managed roles the token's `scopes` claim is
    not the caller's authority, so the PAT-mint subset rule must measure the caller
    through the provider (their role), not the claim. A caller whose role grants only
    `service_accounts:write`, but whose token carries an (ignored) `agent_os:admin`,
    must NOT be able to mint a privileged PAT."""
    from agno.db.sqlite import SqliteDb
    from agno.os.middleware import JWTMiddleware

    db = SqliteDb(db_file=str(tmp_path / "pat_subset.db"))
    agent = Agent(id="research-agent", name="Research Agent", db=db)
    store = ManagedRoleStore(db_url=f"sqlite:///{tmp_path / 'roles.db'}")
    store.set_role_scopes("minter", ["service_accounts:write"])  # may create accounts, nothing else
    store.assign("eve", "minter")

    agent_os = AgentOS(id=OS_ID, agents=[agent], db=db)
    app = agent_os.get_app()
    app.state.authorization_provider = store.provider
    app.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256", authorization=True)
    client = TestClient(app)

    # eve's token carries agent_os:admin -- which the managed plane ignores everywhere.
    eve_jwt = jwt.encode(
        {"sub": "eve", "scopes": ["agent_os:admin"], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    # she may reach the mint endpoint (her role grants service_accounts:write) ...
    admin_pat = client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {eve_jwt}"},
        json={"name": "pwn", "scopes": [{"scope": "agent_os:admin"}], "allow_privileged_scopes": True},
    )
    # ... but the subset rule (measured via the provider) refuses scopes she doesn't hold.
    assert admin_pat.status_code == 403, admin_pat.text
    run_pat = client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {eve_jwt}"},
        json={"name": "pwn2", "scopes": [{"scope": "agents:*:run"}]},
    )
    assert run_pat.status_code == 403, run_pat.text


def test_schedule_endpoint_gate_uses_the_provider_not_token_scopes(tmp_path):
    """Confused-deputy regression (PAT-2). The schedule endpoint gate stops
    `schedules:write` from scheduling a run the caller cannot perform (the executor
    fires it with the full-scope internal token). Under managed roles it must decide
    via the provider: a caller with a `schedules:write` role and an ignored
    `agents:*:run` token scope cannot schedule an agent run they are not granted."""
    import pytest as _pytest

    _pytest.importorskip("croniter")
    _pytest.importorskip("pytz")

    from agno.db.sqlite import SqliteDb
    from agno.os.middleware import JWTMiddleware

    db = SqliteDb(db_file=str(tmp_path / "sched.db"))
    agent = Agent(id="research-agent", name="Research Agent", db=db)
    store = ManagedRoleStore(db_url=f"sqlite:///{tmp_path / 'roles.db'}")
    store.set_role_scopes("scheduler", ["schedules:read", "schedules:write"])  # no agents:run
    store.assign("dave", "scheduler")

    agent_os = AgentOS(id=OS_ID, agents=[agent], db=db)
    app = agent_os.get_app()
    app.state.authorization_provider = store.provider
    app.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256", authorization=True)
    client = TestClient(app)

    dave_jwt = jwt.encode(
        {"sub": "dave", "scopes": ["agents:*:run"], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    resp = client.post(
        "/schedules",
        headers={"Authorization": f"Bearer {dave_jwt}"},
        json={
            "name": "sneaky",
            "endpoint": "/agents/research-agent/runs",
            "method": "POST",
            "cron_expr": "0 0 * * *",
            "payload": {"message": "hi"},
        },
    )
    assert resp.status_code == 403, resp.text


def test_admin_pat_can_mint_a_child_under_managed_roles(tmp_path):
    """Issue-1 regression (service-account carve-out). A PAT's scopes ARE its ACL and are
    always scope-enforced, so an admin PAT must still mint a child service account under a
    managed-roles plane -- the subset rule keys off the PAT's own scopes, not the (absent)
    role of its sa: principal."""
    from agno.db.sqlite import SqliteDb
    from agno.os.middleware import JWTMiddleware

    db = SqliteDb(db_file=str(tmp_path / "pat_child.db"))
    agent = Agent(id="research-agent", name="Research Agent", db=db)
    store = ManagedRoleStore(db_url=f"sqlite:///{tmp_path / 'roles.db'}")
    store.set_role_scopes("os-admin", ["agent_os:admin"])
    store.assign("human-admin", "os-admin")

    agent_os = AgentOS(id=OS_ID, agents=[agent], db=db)
    app = agent_os.get_app()
    app.state.authorization_provider = store.provider
    app.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256", authorization=True)
    client = TestClient(app)

    admin_jwt = jwt.encode(
        {"sub": "human-admin", "scopes": ["agent_os:admin"], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    # the human admin mints an admin PAT (its scopes are its ACL)
    admin_pat = client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {admin_jwt}"},
        json={"name": "ci", "scopes": [{"scope": "agent_os:admin"}], "allow_privileged_scopes": True},
    )
    assert admin_pat.status_code == 201, admin_pat.text
    pat_token = admin_pat.json()["token"]

    # that admin PAT must be able to mint a CHILD account -- the sa: carve-out means its
    # own scopes are authoritative, so the subset rule is satisfied (was 403 before the fix)
    child = client.post(
        "/service-accounts",
        headers={"Authorization": f"Bearer {pat_token}"},
        json={"name": "ci-child", "scopes": [{"scope": "agents:*:run"}]},
    )
    assert child.status_code == 201, child.text
