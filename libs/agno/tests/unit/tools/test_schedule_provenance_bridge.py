"""Provenance is written through the manager's bridge, not at the adapter.

ScheduleManager already bridges sync and async adapters for every schedule
call. The provenance stamp reached past it, straight to the adapter, and
caught NotImplementedError -- which an async adapter never raises. It
returns a coroutine instead: nobody awaits it, the write never happens, and
the tool reports success.
"""

import asyncio
import json
import warnings

import pytest

from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.registry import Registry
from agno.run.base import RunContext
from agno.scheduler.manager import ScheduleManager
from agno.tools.studio import StudioTools

ACTOR = RunContext(run_id="run-1", session_id="sess-1")


@pytest.fixture
def async_db(tmp_path):
    return AsyncSqliteDb(id="prov-async", db_file=str(tmp_path / "prov.db"))


@pytest.fixture
def armed(async_db):
    manager = ScheduleManager(db=async_db)
    manager.create(name="nightly", cron="0 10 * * *", endpoint="/agents/a1/runs")
    return manager, manager.list()[0].id


class TestUpdateScheduleOnAnAsyncDatabase:
    def test_the_adapter_method_really_is_async(self, async_db):
        """The premise: if this stops being true the bug cannot recur."""
        assert asyncio.iscoroutinefunction(async_db.stamp_schedule_provenance)

    def test_the_stamp_lands(self, async_db, armed):
        manager, schedule_id = armed
        studio = StudioTools(registry=Registry(name="r"), db=async_db, schedules=True)

        out = json.loads(studio.update_schedule(schedule_id, cron="0 11 * * *", _agno_run_context=ACTOR))
        assert out.get("ok") is True, out

        row = manager.get(schedule_id)
        assert row.updated_by_run_id == "run-1"
        assert row.updated_by_session_id == "sess-1"

    def test_no_coroutine_is_dropped(self, async_db, armed):
        manager, schedule_id = armed
        studio = StudioTools(registry=Registry(name="r"), db=async_db, schedules=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            studio.update_schedule(schedule_id, cron="0 12 * * *", _agno_run_context=ACTOR)

        assert [str(w.message) for w in caught if "never awaited" in str(w.message)] == []

    def test_the_update_itself_still_commits(self, async_db, armed):
        manager, schedule_id = armed
        studio = StudioTools(registry=Registry(name="r"), db=async_db, schedules=True)
        studio.update_schedule(schedule_id, cron="0 13 * * *", _agno_run_context=ACTOR)
        assert manager.get(schedule_id).cron_expr == "0 13 * * *"


class TestTheBridgeHelper:
    def test_an_adapter_without_the_method_answers_false(self, tmp_path):
        class NoProvenance:
            pass

        manager = ScheduleManager(db=NoProvenance())
        assert manager.stamp_provenance("whatever", updated_by_run_id="r") is False


class TestAStampFailureDoesNotFailACommittedUpdate:
    """The stamp is written after manager.update has committed, so it cannot
    decide whether the update happened. A stamp that blows up loses only the
    record of who made the change; answering a hard error for a cadence the
    caller can see take effect does not -- the caller retries or reports a
    failure that never was.
    """

    @pytest.fixture
    def studio(self, async_db):
        return StudioTools(registry=Registry(name="r"), db=async_db, schedules=True)

    @pytest.fixture
    def exploding_stamp(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("stamp write exploded")

        monkeypatch.setattr(ScheduleManager, "stamp_provenance", boom)

    def test_the_update_is_still_reported_as_made(self, armed, studio, exploding_stamp):
        manager, schedule_id = armed

        out = json.loads(studio.update_schedule(schedule_id, cron="0 14 * * *", _agno_run_context=ACTOR))

        assert out.get("ok") is True, out
        assert manager.get(schedule_id).cron_expr == "0 14 * * *"
        assert any("could not stamp provenance" in w for w in out["warnings"]), out

    def test_the_async_twin_inherits_the_same_answer(self, armed, studio, exploding_stamp):
        """aupdate_schedule delegates to update_schedule, so the rule holds for
        it without a second implementation."""
        manager, schedule_id = armed

        out = json.loads(asyncio.run(studio.aupdate_schedule(schedule_id, cron="0 15 * * *", _agno_run_context=ACTOR)))

        assert out.get("ok") is True, out
        assert manager.get(schedule_id).cron_expr == "0 15 * * *"

    def test_an_update_that_itself_fails_is_still_an_error(self, armed, studio, monkeypatch):
        """Only the stamp is best-effort. The write that changes the schedule
        is the operation itself, and its failure is still reported."""
        _, schedule_id = armed

        def boom(*args, **kwargs):
            raise RuntimeError("update write exploded")

        monkeypatch.setattr(ScheduleManager, "update", boom)
        out = json.loads(studio.update_schedule(schedule_id, cron="0 16 * * *", _agno_run_context=ACTOR))
        assert out.get("ok") is False, out
