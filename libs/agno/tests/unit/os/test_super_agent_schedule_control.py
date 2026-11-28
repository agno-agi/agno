"""Super Agent pauses, resumes and deletes schedules in chat by the API's rules, and says why when it cannot."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company.routines import _ensure_automation_schedule
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, Schedule
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.manager.schedule_control import AUTOMATION_PAUSED_EFFECT, ScheduleControlTools
from agno.tools.scheduler import SchedulerTools
from tests.unit.os.test_company_decision_tools import SECRET, automated_callers, context, headers

ADMIN = ["agent_os:admin"]
MEMBER = ["schedules:read", "schedules:write", "schedules:delete", "agents:run", "routines:read", "goals:read"]
ROUTINE_WRITER = [*MEMBER, "routines:write"]


class System:
    def __init__(self, tmp_path, isolation=False, authorization=True):
        self.db = SqliteDb(db_file=str(tmp_path / "schedule-control.db"))
        options = {"user_isolation": isolation}
        if authorization:
            options["authorization"] = Authorization(verification_keys=[SECRET], algorithm="HS256")
        self.os = AgentOS(
            id="company-decision-tools",
            db=self.db,
            agents=[Agent(id="reader", db=self.db, telemetry=False)],
            company=CompanyConfig(),
            telemetry=False,
            **options,
        )
        app = self.os.get_app()
        self.os._company_app = self.os._manager_app = app
        self.client = TestClient(app)
        asyncio.run(_ensure_automation_schedule(self.db))

    def call(self, tool, run_context, **arguments):
        method = getattr(ScheduleControlTools(self.os), "a" + tool)
        return asyncio.run(method(**arguments, _agno_run_context=run_context))

    def routine(self, name="review", cron="0 9 * * *", goal="Docs"):
        admin = headers(ADMIN, user="ada")
        goal_id = self.client.post("/company/goals", json={"name": goal}, headers=admin).json()["id"]
        body = dict(goal_id=goal_id, name=name, executor_type="agent", executor_id="reader", instructions="Review")
        created = self.client.post("/company/routines", json={**body, "cron_expr": cron}, headers=admin)
        assert created.status_code == 201, created.text
        return goal_id, created.json()["id"]

    def persons_schedule(self, user="sam", name="nightly"):
        body = dict(name=name, cron_expr="0 2 * * *", endpoint="/agents/reader/runs", payload={"message": "Run"})
        created = self.client.post("/schedules", json=body, headers=headers(MEMBER, user=user))
        assert created.status_code == 201, created.text
        return created.json()["id"]

    def orphan(self):
        row = Schedule(
            id="orphan",
            name="this-agentos.agentos-maintenance",
            cron_expr="0 9 * * *",
            endpoint="/agents/company-manager-internal/runs",
            managed_by="company",
            payload={"message": "Maintain"},
            next_run_at=1,
        )
        self.db.create_schedule(row.to_dict())
        return "orphan"

    def enabled(self, schedule_id):
        row = self.db.get_schedule(schedule_id)
        return None if row is None else row["enabled"]


@pytest.fixture
def system(tmp_path):
    built = System(tmp_path)
    yield built
    built.db.close()


@pytest.fixture
def isolated(tmp_path):
    built = System(tmp_path, isolation=True)
    yield built
    built.db.close()


admin = lambda: context(ADMIN, user="ada")  # noqa: E731
member = lambda user="sam": context(MEMBER, user=user)  # noqa: E731


def test_an_administrator_pauses_resumes_and_deletes_a_routine_by_name(system):
    goal_id, routine_id = system.routine()

    paused = system.call("pause_schedule", admin(), schedule="review")
    assert paused.startswith("Paused Routine 'review' of Goal 'Docs'") and routine_id in paused, paused
    assert system.enabled(routine_id) is False
    resumed = system.call("resume_schedule", admin(), schedule=routine_id)
    assert resumed.startswith("Resumed Routine 'review' of Goal 'Docs'") and "next run" in resumed, resumed
    assert system.enabled(routine_id) is True

    wrong = system.call("delete_schedule", admin(), schedule_id=routine_id, name="nightly")
    assert wrong.startswith("Not done") and "is named 'review'" in wrong and system.enabled(routine_id) is True
    deleted = system.call("delete_schedule", admin(), schedule_id=routine_id, name="review")
    assert deleted.startswith("Deleted Routine 'review' of Goal 'Docs'"), deleted
    assert system.db.get_schedule(routine_id) is None
    assert routine_id not in (system.db.get_goal(goal_id)["metadata"].get("routine_ids") or [])


def test_a_routine_is_paused_by_a_person_with_the_routine_permissions_and_deleted_only_by_an_administrator(system):
    _, routine_id = system.routine()

    refused = system.call("pause_schedule", member(), schedule=routine_id)
    assert refused.startswith("Not done") and "routines:write" in refused and "administrator" in refused, refused
    assert system.enabled(routine_id) is True

    writer = context(ROUTINE_WRITER, user="sam")
    assert system.call("pause_schedule", writer, schedule=routine_id).startswith("Paused")
    assert system.enabled(routine_id) is False
    refused = system.call("delete_schedule", writer, schedule_id=routine_id, name="review")
    assert refused.startswith("Not done") and "Only an administrator can delete it" in refused, refused
    assert "You can pause it with pause_schedule" in refused
    assert system.db.get_schedule(routine_id) is not None


def test_a_routine_of_an_archived_goal_is_paused_and_deleted_and_not_resumed(system):
    goal_id, routine_id = system.routine()
    assert system.client.delete("/company/goals/" + goal_id, headers=headers(ADMIN, user="ada")).status_code == 204

    paused = system.call("pause_schedule", admin(), schedule=routine_id)
    assert paused.startswith("Paused Routine 'review' of Goal 'Docs', which is archived"), paused
    refused = system.call("resume_schedule", admin(), schedule=routine_id)
    assert refused.startswith("Not done") and system.enabled(routine_id) is False, refused
    assert system.call("delete_schedule", admin(), schedule_id=routine_id, name="review").startswith("Deleted")


def test_company_automation_is_paused_and_resumed_by_an_administrator_only(system):
    refused = system.call("pause_schedule", member(), schedule="Company automation")
    assert refused.startswith("Not done") and "Only an administrator can pause it" in refused, refused
    assert system.enabled(COMPANY_AUTOMATION_SCHEDULE_ID) is True

    paused = system.call("pause_schedule", admin(), schedule=COMPANY_AUTOMATION_SCHEDULE_ID)
    assert paused.startswith("Paused Company automation") and AUTOMATION_PAUSED_EFFECT in paused, paused
    assert system.enabled(COMPANY_AUTOMATION_SCHEDULE_ID) is False
    refused = system.call(
        "delete_schedule", admin(), schedule_id=COMPANY_AUTOMATION_SCHEDULE_ID, name="Company automation"
    )
    assert refused.startswith("Not done: Company automation cannot be deleted"), refused
    assert system.call("resume_schedule", admin(), schedule="company automation").startswith("Resumed")
    assert system.enabled(COMPANY_AUTOMATION_SCHEDULE_ID) is True


def test_a_company_schedule_with_no_goal_is_stopped_by_an_administrator(system):
    system.orphan()

    refused = system.call("pause_schedule", member(), schedule="orphan")
    assert refused.startswith("Not done") and "Only an administrator can pause it" in refused, refused
    assert system.enabled("orphan") is True
    assert system.call("pause_schedule", admin(), schedule="orphan").startswith("Paused Company schedule")
    assert system.enabled("orphan") is False
    assert "cannot run" in system.call("resume_schedule", admin(), schedule="orphan")
    name = "this-agentos.agentos-maintenance"
    assert system.call("delete_schedule", admin(), schedule_id="orphan", name=name).startswith("Deleted")
    assert system.db.get_schedule("orphan") is None


def test_another_persons_schedule_is_not_reported_missing(isolated):
    schedule_id = isolated.persons_schedule(user="sam")

    refused = isolated.call("pause_schedule", member("lee"), schedule=schedule_id)
    assert refused.startswith("Not done") and "belongs to user sam" in refused and "not yours" in refused, refused
    assert "administrator" in refused and isolated.enabled(schedule_id) is True
    # A name is looked up only among the schedules the person may see.
    assert "no schedule has the ID or the name" in isolated.call("pause_schedule", member("lee"), schedule="nightly")

    assert isolated.call("pause_schedule", member("sam"), schedule="nightly").startswith("Paused schedule 'nightly'")
    assert isolated.call("resume_schedule", admin(), schedule=schedule_id).startswith("Resumed")
    assert isolated.call("delete_schedule", admin(), schedule_id=schedule_id, name="nightly").startswith("Deleted")


def test_the_listing_says_who_manages_each_schedule_and_what_an_administrator_can_do(system):
    from agno.tools.agentos import AgentOSTools

    _, routine_id = system.routine()
    schedule_id = system.persons_schedule(user="sam")
    system.orphan()

    rows = {row["id"]: row for row in json.loads(AgentOSTools(db=system.db).list_schedules())["schedules"]}

    routine = rows[routine_id]
    assert (routine["managed_by"], routine["routine"], routine["owner"]) == ("company_routine", "review", "ada")
    assert routine["goal_id"] and routine["an_administrator_can"] == ["pause", "resume", "delete"]
    automation = rows[COMPANY_AUTOMATION_SCHEDULE_ID]
    assert (automation["managed_by"], automation["an_administrator_can"]) == ("company_automation", ["pause", "resume"])
    assert (rows["orphan"]["managed_by"], rows["orphan"]["an_administrator_can"]) == ("company", ["pause", "delete"])
    assert (rows[schedule_id]["managed_by"], rows[schedule_id]["owner"]) == ("person", "sam")


def test_two_schedules_with_one_name_are_told_apart(system):
    _, first = system.routine(name="agentos-maintenance", goal="This AgentOS")
    _, second = system.routine(name="agentos-maintenance", goal="Maintenance")

    asked = system.call("pause_schedule", admin(), schedule="agentos-maintenance")

    assert asked.startswith("Not done: 2 schedules are named 'agentos-maintenance'"), asked
    assert first in asked and second in asked and "Goal 'This AgentOS'" in asked and "Goal 'Maintenance'" in asked
    assert system.enabled(first) is True and system.enabled(second) is True


@pytest.mark.parametrize("caller", ["routine-run", "task-run", "service-account", "scheduler"])
def test_only_a_person_changes_a_schedule(system, caller):
    schedule_id = system.persons_schedule(user="alice")
    run_context = automated_callers()[caller]

    answer = system.call("pause_schedule", run_context, schedule=schedule_id)

    assert answer.startswith("Not done") and system.enabled(schedule_id) is True, answer


def test_delete_pauses_for_confirmation_and_the_sync_tools_change_nothing(system):
    schedule_id = system.persons_schedule(user="sam")
    tools = ScheduleControlTools(system.os)
    functions = tools.get_async_functions()
    assert functions["delete_schedule"].requires_confirmation is True
    assert not functions["pause_schedule"].requires_confirmation

    assert "asynchronous run" in tools.pause_schedule(schedule_id, _agno_run_context=admin())
    assert "asynchronous run" in tools.delete_schedule(schedule_id, "nightly", _agno_run_context=admin())
    assert system.enabled(schedule_id) is True


def test_without_authorization_every_person_can_stop_every_schedule(tmp_path):
    from agno.run import RunContext

    built = System(tmp_path, authorization=False)
    try:
        nobody = RunContext(run_id="r", session_id="s", user_id="sam", authorization=None)
        assert built.call("pause_schedule", nobody, schedule=COMPANY_AUTOMATION_SCHEDULE_ID).startswith("Paused")
        assert built.enabled(COMPANY_AUTOMATION_SCHEDULE_ID) is False
    finally:
        built.db.close()


# ------------------------------------------------------------------ Platform Builder's schedule tools


@pytest.mark.parametrize("tool", ["get_schedule", "disable_schedule", "enable_schedule", "delete_schedule"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_platform_builder_says_a_schedule_is_another_users_and_not_missing(system, tool, asynchronous):
    schedule_id = system.persons_schedule(user="sam")
    tools = SchedulerTools(db=system.db)
    lee = context(MEMBER, user="lee")

    def answer(identifier):
        if asynchronous:
            return json.loads(asyncio.run(getattr(tools, "a" + tool)(identifier, run_context=lee)))
        return json.loads(getattr(tools, tool)(identifier, run_context=lee))

    theirs = answer(schedule_id)
    assert theirs["error_type"] == "not_owner" and "belongs to user sam" in theirs["error"], theirs
    assert system.db.get_schedule(schedule_id)["enabled"] is True
    assert "not found" in answer("no-such-schedule")["error"]
