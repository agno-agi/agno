"""An owned schedule is re-decided as its owner every time it fires.

The executor authenticates with the internal token and forwards the owner in a header.
The owner's permission was checked when the schedule was created and never again, so a
user who was disabled, or whose role lost the target, kept running it on a timer. The
internal-token branch now re-checks the owner's directory off switch and, under a
provider that decides from stored grants, the owner's route decision.
"""

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization, UserDirectory  # noqa: E402

SECRET = "schedule-owner-recheck-secret-32-bytes!!"
OS_ID = "schedule-owner-os"
INTERNAL_TOKEN = "internal-service-token-for-the-owner-recheck-test-xxxxxxxxxx"


@pytest.fixture
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "sched.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID, algorithm="HS256")
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("runner", ["agents:*:read", "agents:*:run"])
    authz.define_role("viewer", ["agents:*:read"])
    authz.seed(admin="root")
    authz.assign("alice", "runner")
    directory = UserDirectory(auto_provision=False)
    agent_os = AgentOS(
        id=OS_ID,
        db=db,
        agents=[Agent(id="research", name="R", db=InMemoryDb())],
        internal_service_token=INTERNAL_TOKEN,
        authorization=authz,
        user_directory=directory,
    )
    client = TestClient(agent_os.get_app())
    directory.upsert("alice")
    return client, authz, directory


def _fire(client: TestClient, owner: str = "alice") -> int:
    """What the executor sends: the internal token plus the schedule's owner. The run route
    is gated before the body, so 403 means the owner re-check refused; 400/422 means it passed."""
    resp = client.post(
        "/agents/research/runs",
        data={"message": "tick"},
        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}", SCHEDULE_OWNER_HEADER: owner},
    )
    return resp.status_code


def test_an_authorized_owner_still_fires(harness):
    client, _, _ = harness
    assert _fire(client) != 403


def test_a_disabled_owner_is_refused(harness):
    client, _, directory = harness
    directory.set_disabled("alice", True)
    assert _fire(client) == 403


def test_an_owner_whose_grant_was_revoked_is_refused(harness):
    client, authz, _ = harness
    authz.set_role("alice", "viewer")  # can read agents, can no longer run them
    assert _fire(client) == 403
    authz.set_role("alice", "runner")
    assert _fire(client) != 403


def test_an_unowned_schedule_is_unaffected(harness):
    client, _, _ = harness
    resp = client.post(
        "/agents/research/runs", data={"message": "tick"}, headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"}
    )
    assert resp.status_code != 403
