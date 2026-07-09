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
