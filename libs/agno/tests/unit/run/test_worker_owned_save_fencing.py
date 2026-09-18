"""A run's OWN saves are fenced while it executes under the queue
worker.

The per-run save helpers (agent/team/workflow, sync and async) consult the
worker-ownership registry before writing. A registered run saves through
``update_run_in_session`` with ``expected_attempt`` - so a zombie attempt's
write (late terminal save or mid-run flush after a newer attempt claimed
the row) is refused by the primitive and DROPPED, never retried through the
bare ``upsert_run`` clobber path. Unregistered runs and adapters without
the primitive keep the exact legacy behavior.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.db.base import AsyncBaseDb, BaseDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.concurrency import mark_worker_managed, unmark_worker_managed
from agno.run.status_persist import RunPersistOutcome

RUN_ID = "r-fence"
SESSION_ID = "s-fence"


@pytest.fixture(autouse=True)
def clean_registry():
    yield
    unmark_worker_managed(RUN_ID)


def make_run() -> RunOutput:
    return RunOutput(run_id=RUN_ID, session_id=SESSION_ID, status=RunStatus.completed, content="done")


def make_sync_db(outcome=RunPersistOutcome.UPDATED):
    db = MagicMock(spec=BaseDb, name="sync_db")
    db.update_run_in_session = MagicMock(return_value=outcome)
    db.upsert_run = MagicMock()
    # A bare MagicMock answers every attribute, so it would otherwise
    # advertise the strict create/scoped update pair it does not implement
    db.supports_atomic_run_creation = False
    return db


def make_async_db(outcome=RunPersistOutcome.UPDATED):
    # spec'd to AsyncBaseDb because the save helpers pick their sync/async
    # branch with isinstance: a bare MagicMock is not an async adapter, so
    # the async upsert_run fallback would never be reached and its coroutine
    # would be created and dropped unawaited instead of exercised
    db = MagicMock(spec=AsyncBaseDb, name="async_db")
    db.update_run_in_session = AsyncMock(return_value=outcome)
    db.upsert_run = AsyncMock()
    # A bare MagicMock answers every attribute, so it would otherwise
    # advertise the strict create/scoped update pair it does not implement
    db.supports_atomic_run_creation = False
    return db


def assert_saved_through_fence(db, attempt: int, calls: int = 1) -> None:
    """The save reached the attempt-fenced primitive for this run.

    Asserting only that bare ``upsert_run`` went uncalled passes even when
    the fenced helper raises, because every choke point swallows exceptions.
    """
    assert db.update_run_in_session.call_count == calls
    fenced = db.update_run_in_session.call_args.kwargs
    assert fenced["run_id"] == RUN_ID
    assert fenced["expected_attempt"] == attempt
    db.upsert_run.assert_not_called()


class TestFenceHelperCore:
    @pytest.mark.asyncio
    async def test_unmanaged_run_falls_through(self):
        from agno.run.status_persist import apersist_worker_owned_run

        db = make_async_db()
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False
        db.update_run_in_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_managed_run_saves_fenced(self):
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=3)
        db = make_async_db(RunPersistOutcome.UPDATED)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True
        call = db.update_run_in_session.call_args.kwargs
        assert call["expected_attempt"] == 3
        assert call["run_id"] == RUN_ID
        assert call["fields"]["status"] == "COMPLETED"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("outcome", [RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED])
    async def test_fence_refusal_is_dropped_not_retried(self, outcome):
        """The refusal is FINAL: handled=True so no caller falls through to
        the unfenced upsert_run - that retry is exactly the clobber."""
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="zombie", attempt=1)
        db = make_async_db(outcome)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True

    @pytest.mark.asyncio
    async def test_adapter_without_primitive_falls_through(self):
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = SimpleNamespace()  # no update_run_in_session at all
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False

    def test_sync_twin_fences_managed_run(self):
        from agno.run.status_persist import persist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=4)
        db = make_sync_db(RunPersistOutcome.UPDATED)
        assert persist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True
        assert db.update_run_in_session.call_args.kwargs["expected_attempt"] == 4

    def test_sync_twin_skips_async_only_adapter(self):
        from agno.run.status_persist import persist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=4)
        db = MagicMock()
        db.update_run_in_session = AsyncMock()
        assert persist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False


class TestMissingRowAppendPath:
    """MISSING means the row is not there yet: the fenced save appends it,
    and every answer the append can give has to be routed."""

    @pytest.mark.asyncio
    async def test_append_stamps_the_attempt(self):
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.MISSING)
        db.append_run_to_session_if_absent = AsyncMock(return_value=True)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True
        appended = db.append_run_to_session_if_absent.call_args.kwargs
        assert appended["run_dict"]["queue_attempt"] == 2, (
            "a fresh row without the attempt stamp lets the next fence compare pass vacuously"
        )

    @pytest.mark.asyncio
    async def test_append_returning_none_falls_through(self):
        """No session row to append to: the legacy path decides, so the
        caller must NOT be told the save was handled."""
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.MISSING)
        db.append_run_to_session_if_absent = AsyncMock(return_value=None)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False

    @pytest.mark.asyncio
    async def test_append_returning_false_redrives_the_fence(self):
        """A concurrent writer landed the row between check and append, so
        the fenced update is re-driven against it rather than skipped."""
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db()
        db.update_run_in_session = AsyncMock(
            side_effect=[RunPersistOutcome.MISSING, RunPersistOutcome.UPDATED],
        )
        db.append_run_to_session_if_absent = AsyncMock(return_value=False)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True
        assert db.update_run_in_session.call_count == 2
        assert db.update_run_in_session.call_args.kwargs["expected_attempt"] == 2

    @pytest.mark.asyncio
    async def test_append_returning_false_with_row_still_gone_falls_through(self):
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.MISSING)
        db.append_run_to_session_if_absent = AsyncMock(return_value=False)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False
        assert db.update_run_in_session.call_count == 2

    @pytest.mark.asyncio
    async def test_adapter_without_append_falls_through(self):
        from agno.run.status_persist import apersist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.MISSING)
        assert await apersist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False

    def test_sync_append_stamps_the_attempt(self):
        from agno.run.status_persist import persist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=5)
        db = make_sync_db(RunPersistOutcome.MISSING)
        db.append_run_to_session_if_absent = MagicMock(return_value=True)
        assert persist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True
        appended = db.append_run_to_session_if_absent.call_args.kwargs
        assert appended["run_dict"]["queue_attempt"] == 5

    def test_sync_append_returning_none_falls_through(self):
        from agno.run.status_persist import persist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=5)
        db = make_sync_db(RunPersistOutcome.MISSING)
        db.append_run_to_session_if_absent = MagicMock(return_value=None)
        assert persist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False

    def test_sync_append_returning_false_redrives_the_fence(self):
        from agno.run.status_persist import persist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=5)
        db = make_sync_db()
        db.update_run_in_session = MagicMock(
            side_effect=[RunPersistOutcome.MISSING, RunPersistOutcome.UPDATED],
        )
        db.append_run_to_session_if_absent = MagicMock(return_value=False)
        assert persist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is True
        assert db.update_run_in_session.call_count == 2

    def test_sync_twin_skips_async_only_append(self):
        from agno.run.status_persist import persist_worker_owned_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=5)
        db = make_sync_db(RunPersistOutcome.MISSING)
        db.append_run_to_session_if_absent = AsyncMock(return_value=True)
        assert persist_worker_owned_run(db, make_run(), session_id=SESSION_ID) is False


class TestChokePointWiring:
    """The three components' save helpers actually consult the fence: a
    managed run's save goes through the attempt-fenced primitive and never
    reaches bare upsert_run."""

    @pytest.mark.asyncio
    async def test_agent_async_save_is_fenced(self):
        from agno.agent._storage import aupsert_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.STALE_ATTEMPT)
        agent = SimpleNamespace(db=db)
        await aupsert_run(agent, make_run(), session_id=SESSION_ID)
        assert_saved_through_fence(db, attempt=2)

    @pytest.mark.asyncio
    async def test_agent_async_save_unmanaged_uses_upsert(self):
        from agno.agent._storage import aupsert_run

        db = make_async_db()
        agent = SimpleNamespace(db=db)
        await aupsert_run(agent, make_run(), session_id=SESSION_ID)
        db.upsert_run.assert_awaited_once()
        db.update_run_in_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_team_async_save_is_fenced(self):
        from agno.run.team import TeamRunOutput
        from agno.team._storage import _aupsert_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.STALE_ATTEMPT)
        team = SimpleNamespace(db=db)
        run = TeamRunOutput(run_id=RUN_ID, session_id=SESSION_ID, status=RunStatus.completed)
        await _aupsert_run(team, run, session_id=SESSION_ID)
        assert_saved_through_fence(db, attempt=2)

    @pytest.mark.asyncio
    async def test_workflow_async_save_is_fenced(self):
        from agno.run.workflow import WorkflowRunOutput
        from agno.workflow.workflow import Workflow

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_async_db(RunPersistOutcome.STALE_ATTEMPT)
        workflow = Workflow(id="wf-fence", name="WF", db=db, steps=[], telemetry=False)
        run = WorkflowRunOutput(run_id=RUN_ID, session_id=SESSION_ID, status=RunStatus.completed)
        await workflow.asave_run(run=run, session_id=SESSION_ID)
        assert_saved_through_fence(db, attempt=2)

    def test_agent_sync_save_is_fenced(self):
        from agno.agent._storage import upsert_run as sync_upsert_run

        mark_worker_managed(RUN_ID, worker_id="w1", attempt=2)
        db = make_sync_db(RunPersistOutcome.STALE_ATTEMPT)
        agent = SimpleNamespace(db=db)
        sync_upsert_run(agent, make_run(), session_id=SESSION_ID)
        assert_saved_through_fence(db, attempt=2)
