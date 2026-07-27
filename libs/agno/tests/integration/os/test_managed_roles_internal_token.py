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
