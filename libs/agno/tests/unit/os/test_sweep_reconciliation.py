"""The reconciling sweep: a stale lease proves heartbeats stopped, not that
the leg failed.

Before this, the sweeper blind-stamped ERROR on all three planes. A crash in
the window between the run row committing and the ticket settling produced
row=COMPLETED / ticket=failed / stream=ERROR - three surfaces, three answers
(the external review's headline P1 repro). Worse, a swept PAUSE - a valid
HITL continuation waiting for approval - was overwritten with ERROR, and the
failed ticket then obstructed the recovery path built for exactly that.

Now the sweeper pre-reads the run row and reconciles: settled rows get a
matching ticket settle and (for terminals) the winning stream sentinel;
paused rows park the ticket back to paused; only genuinely-unsettled rows
get the honest failure treatment, byte-for-byte as before. The fenced
persist's typed outcome arbitrates the pre-read/write race.
"""

import time
from types import SimpleNamespace

import pytest

import agno.os.event_streams as es_mod
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.event_streams import InMemoryEventStream, set_event_stream
from agno.os.job_queue import QueueWorker
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.base import RunStatus
from agno.run.status_persist import RunPersistOutcome

RUN_ID = "r-sweep"


class FencedFakeDb:
    """Implements update_run_in_session's real contract (attempt fence,
    terminal guard) over a dict - the same fake the zombie acceptance tests
    trust."""

    def __init__(self):
        self.rows: dict = {}

    async def update_run_in_session(self, session_id, run_id, fields, expected_attempt=None, user_id=None, **kw):
        row = self.rows.get(run_id)
        if row is None:
            return RunPersistOutcome.MISSING
        stored_attempt = row.get("queue_attempt")
        if expected_attempt is not None and stored_attempt is not None and stored_attempt > expected_attempt:
            return RunPersistOutcome.STALE_ATTEMPT
        stored_status = str(row.get("status") or "").lower()
        incoming = str(fields.get("status") or "").lower()
        if stored_status in ("completed", "cancelled") and incoming and incoming != stored_status:
            return RunPersistOutcome.TERMINAL_REFUSED
        row.update(fields)
        if kw.get("content_if_absent") is not None and not row.get("content"):
            row["content"] = kw["content_if_absent"]
        return RunPersistOutcome.UPDATED


class FakeComponent:
    """Just enough component for the sweep: a db with the fenced primitive
    and a run-row read the reconcile pre-read consults."""

    id = "comp-1"

    def __init__(self, row: dict):
        self.db = FencedFakeDb()
        self.db.rows[RUN_ID] = row

    async def aget_run_output(self, run_id, session_id, user_id=None):
        row = self.db.rows.get(run_id)
        return SimpleNamespace(**row) if row is not None else None


def make_stale_ticket(stream: bool = True) -> dict:
    now = int(time.time())
    return {
        "id": RUN_ID,
        "job_type": "run",
        "status": "queued",
        "component_type": "agent",
        "component_id": "comp-1",
        "session_id": "s1",
        "user_id": None,
        "payload": {"input": "hi", "stream": stream},
        "attempt": 0,
        "max_attempts": 1,
        "available_at": now,
        "created_at": now,
        "updated_at": now,
        "idempotency_key": None,
        "deployment_id": None,
    }


async def sweep_once(component: FakeComponent, store: InMemoryQueueStore) -> QueueWorker:
    worker = QueueWorker(
        store=store,
        resolve_component=lambda t, i: component,
        config=QueueConfig(durable=True, lock_grace_seconds=3),
        worker_id="sweeper",
        stop_timeout=0.2,
    )
    await worker._sweep_exhausted()
    return worker


@pytest.fixture()
def stream_harness():
    original = es_mod._event_stream
    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    set_event_stream(stream)
    yield stream
    es_mod._event_stream = original


async def seed_stale_running(store: InMemoryQueueStore) -> None:
    await store.enqueue_job(make_stale_ticket())
    await store.claim_job("dead-worker")
    store._jobs[RUN_ID]["locked_at"] -= 1000


class TestSweepReconciliation:
    @pytest.mark.asyncio
    async def test_completed_row_reconciles_all_three_planes(self, stream_harness):
        """The headline repro: crash between the row commit and the ticket
        settle. The old sweep answered COMPLETED / failed / ERROR."""
        component = FakeComponent({"run_id": RUN_ID, "status": "COMPLETED", "content": "real", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        await sweep_once(component, store)

        assert component.db.rows[RUN_ID]["status"] == "COMPLETED", "the settled row must not be touched"
        assert component.db.rows[RUN_ID]["content"] == "real"
        assert (await store.get_job(RUN_ID))["status"] == "completed", "the ticket must MATCH the row"
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.completed, "the stream carries the winner"

    @pytest.mark.asyncio
    async def test_cancelled_row_reconciles_to_cancelled(self, stream_harness):
        component = FakeComponent({"run_id": RUN_ID, "status": "CANCELLED", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        await sweep_once(component, store)

        assert (await store.get_job(RUN_ID))["status"] == "cancelled"
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.cancelled

    @pytest.mark.asyncio
    async def test_paused_row_parks_ticket_and_touches_nothing_else(self, stream_harness):
        """A swept pause is SETTLED-for-the-leg: park the ticket, leave the
        row alone, keep the stream showing paused - and prove recovery is
        unobstructed by driving a durable continue afterwards."""
        component = FakeComponent({"run_id": RUN_ID, "status": "PAUSED", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.paused)

        await sweep_once(component, store)

        assert component.db.rows[RUN_ID]["status"] == "PAUSED", "the sweep must not deface a valid pause"
        assert (await store.get_job(RUN_ID))["status"] == "paused"
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.paused, "no ERROR sentinel on a pause"
        # The recovery path the failed ticket used to obstruct:
        assert (await store.continue_job(RUN_ID, {"kwargs": {}}))["outcome"] == "queued"

    @pytest.mark.asyncio
    async def test_paused_row_with_unsentineled_stream_gets_the_pause_repaired(self, stream_harness):
        """The crash window between the row committing PAUSED and the
        executor's finally writing the stream's paused sentinel: the stream
        still says RUNNING, so attached tails would idle forever. The
        reconcile must repair the stream view to paused, not assume the
        sentinel already stands."""
        component = FakeComponent({"run_id": RUN_ID, "status": "PAUSED", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        # The crash left the stream mid-leg: status RUNNING, no sentinel
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        await sweep_once(component, store)

        assert component.db.rows[RUN_ID]["status"] == "PAUSED"
        assert (await store.get_job(RUN_ID))["status"] == "paused"
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.paused, (
            "tails must observe the pause - a RUNNING stream over a parked ticket idles forever"
        )

    @pytest.mark.asyncio
    async def test_race_flip_between_preread_and_write_reconciles(self, stream_harness):
        """Pre-read says RUNNING, the leg completes in the gap, the fenced
        write comes back TERMINAL_REFUSED: the sweeper must re-read and
        reconcile, never fail over a terminal row."""
        component = FakeComponent({"run_id": RUN_ID, "status": "RUNNING", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        real_update = component.db.update_run_in_session

        async def flip_then_refuse(session_id, run_id, fields, **kw):
            component.db.rows[RUN_ID].update(status="COMPLETED", content="landed in the gap")
            return await real_update(session_id, run_id, fields, **kw)

        component.db.update_run_in_session = flip_then_refuse  # type: ignore[method-assign]
        await sweep_once(component, store)

        assert component.db.rows[RUN_ID]["status"] == "COMPLETED"
        assert (await store.get_job(RUN_ID))["status"] == "completed", "the race must land in the reconcile branch"
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.completed

    @pytest.mark.asyncio
    async def test_genuinely_dead_running_row_keeps_the_honest_failure(self, stream_harness):
        """The fix must not soften the truth-telling path: an unsettled row
        still gets ERROR / failed / ERROR."""
        component = FakeComponent({"run_id": RUN_ID, "status": "RUNNING", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        await sweep_once(component, store)

        assert str(component.db.rows[RUN_ID]["status"]).upper() == "ERROR"
        job = await store.get_job(RUN_ID)
        assert job["status"] == "failed" and "worker lost" in job["error"].lower()
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.error

    @pytest.mark.asyncio
    async def test_stale_attempt_row_settles_ticket_without_touching_row_or_stream(self, stream_harness):
        """A row stamped by a NEWER attempt than the swept ticket: the row
        and stream are that writer's; only the ticket bookkeeping settles."""
        component = FakeComponent({"run_id": RUN_ID, "status": "RUNNING", "queue_attempt": 5})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        await sweep_once(component, store)

        assert component.db.rows[RUN_ID]["status"] == "RUNNING", "a newer attempt's row is not ours"
        assert component.db.rows[RUN_ID]["queue_attempt"] == 5
        assert (await store.get_job(RUN_ID))["status"] == "failed"
        assert await stream_harness.get_run_status(RUN_ID) == RunStatus.running, "no sentinel on their stream"

    @pytest.mark.asyncio
    async def test_resweep_after_reconcile_is_a_noop(self, stream_harness):
        component = FakeComponent({"run_id": RUN_ID, "status": "COMPLETED", "queue_attempt": 1})
        store = InMemoryQueueStore()
        await seed_stale_running(store)
        await stream_harness.register_run(RUN_ID, RunStatus.running)

        worker = await sweep_once(component, store)
        first = dict(await store.get_job(RUN_ID))
        await worker._sweep_exhausted()
        assert (await store.get_job(RUN_ID))["status"] == first["status"] == "completed"
