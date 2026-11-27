"""What is asked again about a schedule's owner each time the schedule fires.

Schedules are fired by the real executor against the app. One kind is saved through the API, so it
carries the authority of the request that saved it. The other is created in code with an owner and
no saved authority, as schedules made before saved authority existed are stored.
"""

import time

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.os.authz import Authorization, Role, UserDirectory
from agno.run.authorization import AUTHORIZATION_KEY
from agno.scheduler import ScheduleExecutor, ScheduleManager

SECRET = "schedule-owner-firing-secret-at-least-256-bits-long"
OS_ID = "schedule-owner-firing-os"
INTERNAL_TOKEN = "internal-service-token-for-the-schedule-owner-firing-tests"
ENDPOINT = "/agents/research/runs"


class _FixtureModel(Model):
    def __init__(self):
        super().__init__(id="fixture", provider="test")

    def invoke(self, messages, **kwargs):
        return ModelResponse(role="assistant", content="answer", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def _auth(sub, scopes=None):
    payload = {"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600}
    if scopes is not None:
        payload["scopes"] = scopes
    return {"Authorization": "Bearer " + jwt.encode(payload, SECRET, algorithm="HS256")}


class _System:
    """One AgentOS with a runner role and a viewer role, and the executor that fires its schedules."""

    def __init__(self, tmp_path, **authorization):
        self.db = SqliteDb(db_file=str(tmp_path / "os.db"))
        self.authz = Authorization(
            verification_keys=[SECRET],
            algorithm="HS256",
            roles=[
                Role("runner", scopes=["agents:read", "agents:run", "schedules:read", "schedules:write"]),
                Role("viewer", scopes=["agents:read"]),
            ],
            **authorization,
        )
        self.directory = UserDirectory()
        self.os = AgentOS(
            id=OS_ID,
            db=self.db,
            agents=[Agent(id="research", name="Research", model=_FixtureModel())],
            authorization=self.authz,
            user_directory=self.directory,
            internal_service_token=INTERNAL_TOKEN,
            telemetry=False,
        )
        self.app = self.os.get_app()
        self.client = TestClient(self.app)

    def saved_through_the_api(self, name, headers):
        """A schedule a person saves: it carries their authority as it is at that moment."""
        body = {"name": name, "cron_expr": "0 9 * * *", "endpoint": ENDPOINT, "payload": {"message": "tick"}}
        response = self.client.post("/schedules", json=body, headers=headers)
        assert response.status_code == 201, response.text
        row = self.db.get_schedule(response.json()["id"])
        assert AUTHORIZATION_KEY in row["payload"]
        return row

    def with_no_saved_authority(self, name, owner):
        """A schedule with an owner and no saved authority, as code and older releases store one."""
        schedule = ScheduleManager(self.db).create(
            name=name, cron="0 9 * * *", endpoint=ENDPOINT, payload={"message": "tick"}, user_id=owner
        )
        row = self.db.get_schedule(schedule.id)
        assert row["user_id"] == owner and AUTHORIZATION_KEY not in (row["payload"] or {})
        return row

    async def fire(self, row):
        """Fire a schedule as the scheduler does. Returns "fired" or the refusal it got."""
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test") as client:
            executor = ScheduleExecutor(
                base_url="http://test", internal_service_token=INTERNAL_TOKEN, timeout=10, poll_interval=0.01
            )
            executor._client = client
            result = await executor.execute(self.db.get_schedule(row["id"]), self.db, release_schedule=False)
        if result["status"] == "success":
            return "fired"
        return result.get("error") or result["status"]


# ----------------------------------------------------------------- a disabled user's schedules stop


@pytest.mark.asyncio
@pytest.mark.parametrize("trust", [None, False])
@pytest.mark.parametrize("saved_authority", [True, False])
async def test_a_disabled_users_schedule_stops_firing(tmp_path, trust, saved_authority):
    system = _System(tmp_path, **({} if trust is None else {"trust_token_scopes": trust}))
    system.authz.assign("alice@example.com", "runner")
    if saved_authority:
        row = system.saved_through_the_api("daily", _auth("alice@example.com"))
    else:
        system.directory.upsert("alice@example.com")
        row = system.with_no_saved_authority("daily", "alice@example.com")
    assert await system.fire(row) == "fired"

    system.directory.set_disabled("alice@example.com", True)
    assert "Schedule owner is disabled" in await system.fire(row)
    system.directory.set_disabled("alice@example.com", False)
    assert await system.fire(row) == "fired"


@pytest.mark.asyncio
async def test_a_disabled_user_with_scopes_on_their_token_is_stopped_too(tmp_path):
    # The owner never held a role: the schedule was saved on the scopes of their token
    system = _System(tmp_path)
    # The scheduler starts the run and then reads its status, so the owner needs read as well as run
    scopes = ["agents:read", "agents:run", "schedules:write"]
    row = system.saved_through_the_api("daily", _auth("operator@example.com", scopes))
    assert await system.fire(row) == "fired"
    system.directory.set_disabled("operator@example.com", True)
    assert "Schedule owner is disabled" in await system.fire(row)


# ----------------------------------------------------------------- a downgraded owner's stored role is asked again


@pytest.mark.asyncio
@pytest.mark.parametrize("trust", [None, False])
@pytest.mark.parametrize("saved_authority", [True, False])
async def test_an_owner_moved_to_a_lesser_role_stops_firing(tmp_path, trust, saved_authority):
    system = _System(tmp_path, **({} if trust is None else {"trust_token_scopes": trust}))
    system.authz.assign("alice@example.com", "runner")
    if saved_authority:
        row = system.saved_through_the_api("daily", _auth("alice@example.com"))
    else:
        system.directory.upsert("alice@example.com")
        row = system.with_no_saved_authority("daily", "alice@example.com")
    assert await system.fire(row) == "fired"

    system.authz.set_role("alice@example.com", "viewer")  # can read agents, can no longer run them
    refusal = await system.fire(row)
    assert "Insufficient permissions for scheduled target" in refusal or "not authorized to run this target" in refusal
    system.authz.set_role("alice@example.com", "runner")
    assert await system.fire(row) == "fired"


@pytest.mark.asyncio
async def test_an_owner_with_no_stored_role_and_no_saved_authority_keeps_firing(tmp_path):
    # Their access was on a token this OS no longer sees, so the check made when it was saved stands
    system = _System(tmp_path)
    system.directory.upsert("operator@example.com")
    row = system.with_no_saved_authority("daily", "operator@example.com")
    assert system.authz.roles_of("operator@example.com") == []
    assert await system.fire(row) == "fired"


@pytest.mark.asyncio
async def test_scopes_saved_from_the_owners_token_still_count(tmp_path):
    # A limit, on main as well: the scopes are kept as they were when the schedule was saved, so a
    # later change to the owner's stored role does not stop a schedule those scopes cover
    system = _System(tmp_path)
    system.authz.assign("alice@example.com", "runner")
    row = system.saved_through_the_api("daily", _auth("alice@example.com", ["agents:read", "agents:run"]))
    system.authz.set_role("alice@example.com", "viewer")
    assert await system.fire(row) == "fired"


@pytest.mark.asyncio
async def test_a_schedule_with_no_owner_is_not_asked(tmp_path):
    system = _System(tmp_path)
    schedule = ScheduleManager(system.db).create(
        name="system", cron="0 9 * * *", endpoint=ENDPOINT, payload={"message": "tick"}
    )
    assert await system.fire(system.db.get_schedule(schedule.id)) == "fired"
