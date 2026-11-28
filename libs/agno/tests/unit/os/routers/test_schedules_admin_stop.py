"""An administrator can stop every schedule through the Scheduler API, and no one else gains anything."""

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company.routines import _ensure_automation_schedule
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, Schedule
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig

SECRET = "schedules-admin-stop-secret-0123456789"
AUTOMATION = "/schedules/" + COMPANY_AUTOMATION_SCHEDULE_ID
ROUTINES_ONLY = "Company-managed schedules must be changed through /company/routines"


def _headers(user, scopes):
    claims = {"sub": user, "aud": "admin-stop", "scopes": scopes}
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


ADMIN = _headers("ada", ["agent_os:admin"])
OTHER_ADMIN = _headers("grace", ["agent_os:admin"])
MEMBER = _headers("sam", ["schedules:read", "schedules:write", "schedules:delete", "agents:run"])


def _os(db, authorization=True, company=True, isolation=False):
    return AgentOS(
        id="admin-stop",
        db=db,
        agents=[Agent(id="reader", db=db, telemetry=False)],
        company=CompanyConfig() if company else None,
        telemetry=False,
        authorization=authorization,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET], algorithm="HS256", user_isolation=isolation
        )
        if authorization
        else None,
    )


@pytest.fixture
def db(tmp_path):
    database = SqliteDb(db_file=str(tmp_path / "admin-stop.db"))
    yield database
    database.close()


def _routine(client, headers=ADMIN, cron="0 9 * * *"):
    goal = client.post("/company/goals", json={"name": "Docs"}, headers=headers).json()
    body = dict(goal_id=goal["id"], name="review", executor_type="agent", executor_id="reader", instructions="Review")
    created = client.post("/company/routines", json={**body, "cron_expr": cron}, headers=headers)
    assert created.status_code == 201, created.text
    return goal["id"], created.json()["id"]


async def _automation(db, **kwargs):
    return await _ensure_automation_schedule(db, **kwargs)


def test_an_administrator_pauses_resumes_and_deletes_a_routine_another_person_created(db):
    with TestClient(_os(db).get_app()) as client:
        goal_id, routine_id = _routine(client)
        path = "/schedules/" + routine_id

        for refused in (
            client.post(path + "/disable", headers=MEMBER),
            client.post(path + "/enable", headers=MEMBER),
            client.delete(path, headers=MEMBER),
        ):
            assert refused.status_code == 409 and refused.json()["detail"] == ROUTINES_ONLY
        assert db.get_schedule(routine_id)["enabled"] is True

        paused = client.post(path + "/disable", headers=OTHER_ADMIN)
        assert paused.status_code == 200, paused.text
        assert paused.json()["enabled"] is False and db.get_schedule(routine_id)["enabled"] is False
        resumed = client.post(path + "/enable", headers=OTHER_ADMIN)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["enabled"] is True and db.get_schedule(routine_id)["enabled"] is True
        # Editing and running a Routine stay with the Routine API, for an administrator too.
        assert (
            client.patch(path, json={"cron_expr": "0 8 * * *"}, headers=OTHER_ADMIN).json()["detail"] == ROUTINES_ONLY
        )
        assert client.post(path + "/trigger", headers=OTHER_ADMIN).json()["detail"] == ROUTINES_ONLY

        assert client.delete(path, headers=OTHER_ADMIN).status_code == 204
        assert db.get_schedule(routine_id) is None
        assert routine_id not in (db.get_goal(goal_id)["metadata"].get("routine_ids") or [])


def test_enabling_a_routine_keeps_the_rules_of_the_routine_api(db):
    with TestClient(_os(db).get_app()) as client:
        goal_id, routine_id = _routine(client)
        assert client.post(f"/schedules/{routine_id}/disable", headers=ADMIN).status_code == 200
        assert client.delete("/company/goals/" + goal_id, headers=ADMIN).status_code == 204

        refused = client.post(f"/schedules/{routine_id}/enable", headers=ADMIN)

        # A Routine of an archived Goal cannot run, whoever asks.
        assert refused.status_code == 404, refused.text
        assert db.get_schedule(routine_id)["enabled"] is False
        assert client.delete("/schedules/" + routine_id, headers=ADMIN).status_code == 204


def test_an_administrator_stops_a_company_schedule_that_names_no_goal_and_no_owner(db):
    with TestClient(_os(db, isolation=True).get_app()) as client:
        orphan = Schedule(
            id="orphan",
            name="this-agentos.agentos-maintenance",
            cron_expr="0 9 * * *",
            endpoint="/agents/company-manager-internal/runs",
            managed_by="company",
            payload={"message": "Maintain"},
            next_run_at=1,
        )
        db.create_schedule(orphan.to_dict())

        assert client.post("/schedules/orphan/disable", headers=MEMBER).status_code == 404
        assert db.get_schedule("orphan")["enabled"] is True
        assert client.post("/schedules/orphan/disable", headers=ADMIN).json()["enabled"] is False
        assert client.post("/schedules/orphan/enable", headers=ADMIN).status_code == 409
        assert client.delete("/schedules/orphan", headers=ADMIN).status_code == 204
        assert db.get_schedule("orphan") is None


def test_an_administrator_stops_another_persons_schedule_under_user_isolation(db):
    with TestClient(_os(db, isolation=True).get_app()) as client:
        body = dict(name="nightly", cron_expr="0 2 * * *", endpoint="/agents/reader/runs", payload={"message": "Run"})
        schedule_id = client.post("/schedules", json=body, headers=MEMBER).json()["id"]
        stranger = _headers("lee", ["schedules:read", "schedules:write", "schedules:delete", "agents:run"])

        assert client.post(f"/schedules/{schedule_id}/disable", headers=stranger).status_code == 404
        assert client.post(f"/schedules/{schedule_id}/disable", headers=ADMIN).json()["enabled"] is False
        assert client.post(f"/schedules/{schedule_id}/enable", headers=ADMIN).json()["enabled"] is True
        assert client.delete(f"/schedules/{schedule_id}", headers=ADMIN).status_code == 204


@pytest.mark.asyncio
async def test_an_administrator_pauses_company_automation_and_a_restart_keeps_it_paused(db):
    await _automation(db)
    with TestClient(_os(db).get_app()) as client:
        refused = client.post(AUTOMATION + "/disable", headers=MEMBER)
        assert refused.status_code == 403, refused.text
        assert client.post(AUTOMATION + "/enable", headers=MEMBER).status_code == 403
        assert db.get_schedule(COMPANY_AUTOMATION_SCHEDULE_ID)["enabled"] is True

        paused = client.post(AUTOMATION + "/disable", headers=ADMIN)
        assert paused.status_code == 200, paused.text
        assert paused.json()["enabled"] is False

        # Only pause and resume: the schedule is never deleted, edited or run by hand.
        for response in (
            client.delete(AUTOMATION, headers=ADMIN),
            client.patch(AUTOMATION, json={"cron_expr": "*/5 * * * *"}, headers=ADMIN),
            client.post(AUTOMATION + "/trigger", headers=ADMIN),
        ):
            assert response.status_code == 409 and "only be paused and resumed" in response.json()["detail"]

    # What every start does before the poller runs: the pause is kept, with Company on or off.
    for company_on in (True, False, True):
        await _automation(db, enabled=company_on)
        stored = db.get_schedule(COMPANY_AUTOMATION_SCHEDULE_ID)
        assert stored["enabled"] is False and stored["disabled_reason"] is None
    # A paused schedule is not due, so the poller never claims it.
    assert db.claim_due_schedule("worker") is None

    with TestClient(_os(db).get_app()) as client:
        resumed = client.post(AUTOMATION + "/enable", headers=ADMIN)
        assert resumed.status_code == 200, resumed.text
        assert db.get_schedule(COMPANY_AUTOMATION_SCHEDULE_ID)["enabled"] is True


@pytest.mark.asyncio
async def test_company_off_still_turns_automation_back_on_when_company_returns(db):
    await _automation(db)
    await _automation(db, enabled=False)
    assert db.get_schedule(COMPANY_AUTOMATION_SCHEDULE_ID)["disabled_reason"] == "company_off"
    with TestClient(_os(db, company=False).get_app()) as client:
        # With Company off nothing serves the schedule, so it cannot be turned on.
        assert client.post(AUTOMATION + "/enable", headers=ADMIN).status_code == 409
    await _automation(db, enabled=True)
    assert db.get_schedule(COMPANY_AUTOMATION_SCHEDULE_ID)["enabled"] is True


@pytest.mark.asyncio
async def test_a_pause_while_company_is_off_is_kept_when_company_returns(db):
    await _automation(db)
    await _automation(db, enabled=False)
    with TestClient(_os(db, company=False).get_app()) as client:
        assert client.post(AUTOMATION + "/disable", headers=ADMIN).status_code == 200
    await _automation(db, enabled=True)
    assert db.get_schedule(COMPANY_AUTOMATION_SCHEDULE_ID)["enabled"] is False


@pytest.mark.asyncio
async def test_without_authorization_every_caller_can_stop_a_company_schedule(db):
    await _automation(db)
    with TestClient(_os(db, authorization=False).get_app()) as client:
        _, routine_id = _routine(client, headers={})
        assert client.post(f"/schedules/{routine_id}/disable").json()["enabled"] is False
        assert client.post(AUTOMATION + "/disable").json()["enabled"] is False
        assert client.post(AUTOMATION + "/enable").json()["enabled"] is True
        assert client.delete("/schedules/" + routine_id).status_code == 204
