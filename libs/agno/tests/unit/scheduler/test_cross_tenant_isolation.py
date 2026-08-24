"""Cross-tenant isolation regression tests for the scheduler.

Pins the fix for the scheduler hijack: ``get_schedule_by_name`` is
bucket-exact (``user_id=None`` addresses only unowned schedules), and
``SchedulerTools`` acts as the run's user via the injected ``run_context``,
so one user's agent can neither rewrite nor even see another user's
same-named schedule.
"""

import json

import pytest

pytest.importorskip("croniter", reason="croniter not installed")
pytest.importorskip("pytz", reason="pytz not installed")

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.run import RunContext  # noqa: E402
from agno.scheduler.manager import ScheduleManager  # noqa: E402
from agno.tools.scheduler import SchedulerTools  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "scheduler.db"))


@pytest.fixture
def mgr(db):
    return ScheduleManager(db)


def _rc(user_id):
    return RunContext(run_id="run-1", session_id="session-1", user_id=user_id)


class TestBucketExactNameLookup:
    def test_unowned_lookup_never_matches_owned_schedule(self, db, mgr):
        mgr.create(name="report", cron="0 9 * * *", endpoint="/bob", user_id="bob")

        assert db.get_schedule_by_name("report", user_id=None) is None
        assert db.get_schedule_by_name("report", user_id="alice") is None
        found = db.get_schedule_by_name("report", user_id="bob")
        assert found is not None and found["user_id"] == "bob"

    def test_unowned_lookup_matches_unowned_schedule(self, db, mgr):
        unowned = mgr.create(name="report", cron="0 9 * * *", endpoint="/shared")

        found = db.get_schedule_by_name("report", user_id=None)
        assert found is not None and found["id"] == unowned.id and found["user_id"] is None

    def test_scoped_lookup_never_matches_unowned_schedule(self, db, mgr):
        mgr.create(name="report", cron="0 9 * * *", endpoint="/shared")

        assert db.get_schedule_by_name("report", user_id="alice") is None


class TestCreateUpdateCannotHijack:
    def test_unowned_create_update_does_not_touch_owned_schedule(self, mgr):
        bobs = mgr.create(name="report", cron="0 9 * * *", endpoint="/bob", user_id="bob")

        created = mgr.create(name="report", cron="0 6 * * *", endpoint="/other", if_exists="update")

        assert created.id != bobs.id
        assert created.user_id is None
        untouched = mgr.get(bobs.id, user_id="bob")
        assert untouched.endpoint == "/bob"
        assert untouched.cron_expr == "0 9 * * *"

    def test_scoped_create_update_does_not_touch_other_owner(self, mgr):
        bobs = mgr.create(name="report", cron="0 9 * * *", endpoint="/bob", user_id="bob")

        created = mgr.create(name="report", cron="0 6 * * *", endpoint="/alice", if_exists="update", user_id="alice")

        assert created.id != bobs.id
        assert created.user_id == "alice"
        assert mgr.get(bobs.id, user_id="bob").endpoint == "/bob"

    def test_create_update_still_updates_within_own_bucket(self, mgr):
        first = mgr.create(name="report", cron="0 9 * * *", endpoint="/v1", user_id="alice")

        updated = mgr.create(name="report", cron="0 6 * * *", endpoint="/v2", if_exists="update", user_id="alice")

        assert updated.id == first.id
        assert updated.endpoint == "/v2"
        assert updated.user_id == "alice"

    @pytest.mark.asyncio
    async def test_async_unowned_create_update_does_not_touch_owned_schedule(self, mgr):
        bobs = await mgr.acreate(name="report", cron="0 9 * * *", endpoint="/bob", user_id="bob")

        created = await mgr.acreate(name="report", cron="0 6 * * *", endpoint="/other", if_exists="update")

        assert created.id != bobs.id
        assert created.user_id is None
        untouched = await mgr.aget(bobs.id, user_id="bob")
        assert untouched.endpoint == "/bob"


class TestSchedulerToolsActAsRunUser:
    def test_create_schedule_is_owned_by_run_user(self, db):
        tools = SchedulerTools(db=db, default_endpoint="/agents/a/runs", default_payload={"message": "go"})

        result = json.loads(tools.create_schedule(name="daily", cron="0 9 * * *", run_context=_rc("alice")))

        assert result["status"] == "created"
        row = db.get_schedule(result["id"])
        assert row["user_id"] == "alice"

    def test_agent_cannot_rewrite_other_users_schedule(self, db):
        tools = SchedulerTools(db=db, default_endpoint="/agents/a/runs", default_payload={"message": "go"})
        bobs = json.loads(tools.create_schedule(name="daily", cron="0 9 * * *", run_context=_rc("bob")))

        alices = json.loads(tools.create_schedule(name="daily", cron="0 6 * * *", run_context=_rc("alice")))

        assert alices["status"] == "created"
        assert alices["id"] != bobs["id"]
        assert db.get_schedule(bobs["id"])["cron_expr"] == "0 9 * * *"

    def test_list_is_scoped_to_run_user(self, db):
        tools = SchedulerTools(db=db, default_endpoint="/agents/a/runs", default_payload={"message": "go"})
        tools.create_schedule(name="bobs-task", cron="0 9 * * *", run_context=_rc("bob"))
        tools.create_schedule(name="alices-task", cron="0 9 * * *", run_context=_rc("alice"))

        listed = json.loads(tools.list_schedules(run_context=_rc("alice")))

        names = {s["name"] for s in listed["schedules"]}
        assert names == {"alices-task"}

    def test_get_delete_disable_are_scoped_to_run_user(self, db):
        tools = SchedulerTools(db=db, default_endpoint="/agents/a/runs", default_payload={"message": "go"})
        bobs = json.loads(tools.create_schedule(name="daily", cron="0 9 * * *", run_context=_rc("bob")))

        assert "error" in json.loads(tools.get_schedule(bobs["id"], run_context=_rc("alice")))
        assert "error" in json.loads(tools.delete_schedule(bobs["id"], run_context=_rc("alice")))
        assert "error" in json.loads(tools.disable_schedule(bobs["id"], run_context=_rc("alice")))
        assert db.get_schedule(bobs["id"])["enabled"] is True

    def test_fixed_toolkit_user_id_wins_over_run_context(self, db):
        tools = SchedulerTools(
            db=db, default_endpoint="/agents/a/runs", default_payload={"message": "go"}, user_id="service-account"
        )

        result = json.loads(tools.create_schedule(name="daily", cron="0 9 * * *", run_context=_rc("alice")))

        assert db.get_schedule(result["id"])["user_id"] == "service-account"

    @pytest.mark.asyncio
    async def test_async_tools_are_scoped_to_run_user(self, db):
        tools = SchedulerTools(db=db, default_endpoint="/agents/a/runs", default_payload={"message": "go"})
        bobs = json.loads(await tools.acreate_schedule(name="daily", cron="0 9 * * *", run_context=_rc("bob")))

        assert db.get_schedule(bobs["id"])["user_id"] == "bob"
        listed = json.loads(await tools.alist_schedules(run_context=_rc("alice")))
        assert listed["count"] == 0
        assert "error" in json.loads(await tools.adelete_schedule(bobs["id"], run_context=_rc("alice")))
