"""Zombie-worker acceptance scenarios, end to end against the fences.

Both scenarios reproduce a worker that stalls past lock_grace (heartbeats
stop, execution does not - the event-loop-starvation mode) and then wakes.
They originally demonstrated the corruption; the assertions now pin the
fenced outcomes. Timings sit at the lock_grace floor (3s).

Scenario 1 (multi-attempt reclaim): a worker stalls past lock_grace, a second
worker reclaims at attempt 2, the first wakes and keeps publishing. Fenced:
the zombie's post-wakeup events and terminal sentinel are refused; the
reclaiming attempt's stream and ticket are untouched.

Scenario 2 (DEFAULT config, the sweep-vs-live race): max_attempts=1, the
stalled worker is falsely swept as dead, then finishes. Fenced intent is
FINISHED-WORK-WINS: the ticket keeps the sweep's failure (at-most-once
bookkeeping, the requeue gate guards re-execution), but the run row and the
stream both end COMPLETED with the real result - the zombie holds the SAME
attempt the sweeper stamped, and same-generation writes pass by design.
"""

import asyncio
import time

import pytest

import agno.os.event_streams as es_mod
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.event_streams import InMemoryEventStream, set_event_stream
from agno.os.job_queue import QueueWorker
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.base import RunStatus
from agno.run.status_persist import RunPersistOutcome


class Ev:
    def __init__(self, name: str, run_id: str):
        self.event = name
        self.run_id = run_id
        self.content = name

    def to_dict(self):
        return {"event": self.event, "content": self.content, "run_id": self.run_id}


class Out:
    def __init__(self, run_id: str):
        self.status = RunStatus.completed
        self.run_id = run_id

    def to_dict(self):
        return {"status": "completed", "run_id": self.run_id}


class FencedFakeDb:
    """In-memory db implementing the fenced primitive's real contract:
    attempt fence (stale writers refused), terminal guard, queue_attempt
    stamping. Enough for the worker's persist paths and the item-4 choke
    point to behave exactly as against Postgres."""

    def __init__(self):
        self.rows: dict = {}

    async def append_run_to_session_if_absent(self, session_id, run_dict, user_id=None):
        rid = run_dict.get("run_id")
        if rid in self.rows:
            return False  # row already landed - the worker's claim-time ensure is satisfied
        self.rows[rid] = dict(run_dict)
        return True

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
        if expected_attempt is not None:
            row["queue_attempt"] = expected_attempt
        if kw.get("content_if_absent") is not None and not row.get("content"):
            row["content"] = kw["content_if_absent"]
        return RunPersistOutcome.UPDATED


def fresh_stream() -> InMemoryEventStream:
    return InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())


def make_ticket(run_id: str, max_attempts: int) -> dict:
    now = int(time.time())
    return {
        "id": run_id,
        "job_type": "run",
        "status": "queued",
        "component_type": "agent",
        "component_id": "comp-1",
        "session_id": "s1",
        "user_id": None,
        "payload": {"stream": True, "input": "hi"},
        "attempt": 0,
        "max_attempts": max_attempts,
        "available_at": now,
        "created_at": now,
        "updated_at": now,
        "idempotency_key": None,
        "deployment_id": None,
    }


class TestZombieReclaimAcceptance:
    """Scenario 1: multi-attempt reclaim. The zombie's stream mutations are
    fenced out; the reclaiming attempt owns every surface."""

    @pytest.mark.asyncio
    async def test_zombie_events_and_sentinel_fenced_after_reclaim(self):
        RUN_ID = "run-zombie-1"
        original = es_mod._event_stream
        stream = fresh_stream()
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()

            class Component:
                db = None
                id = "comp-1"

                def __init__(self):
                    self.calls = 0

                def arun(self, **kwargs):
                    self.calls += 1
                    return self._gen(self.calls)

                async def _gen(self, call_no):
                    if call_no == 1:
                        # Attempt 1: two events, then a stall past lock_grace
                        yield Ev("A-1", RUN_ID)
                        yield Ev("A-2", RUN_ID)
                        await asyncio.sleep(5.0)
                        yield Ev("A-3-after-wakeup", RUN_ID)
                        yield Out(RUN_ID)
                    else:
                        # Attempt 2 (the reclaim): finishes AFTER A wakes, so
                        # the zombie's writes interleave mid-leg
                        for i in range(1, 6):
                            yield Ev(f"B-{i}", RUN_ID)
                            await asyncio.sleep(0.5)
                        yield Out(RUN_ID)

            comp = Component()
            cfg = QueueConfig(durable=True, max_attempts=2, lock_grace_seconds=3, retry_delay_seconds=0)
            worker_a = QueueWorker(
                store=store, resolve_component=lambda t, i: comp, config=cfg, worker_id="A", stop_timeout=0.2
            )
            worker_b = QueueWorker(
                store=store, resolve_component=lambda t, i: comp, config=cfg, worker_id="B", stop_timeout=0.2
            )
            await store.enqueue_job(make_ticket(RUN_ID, max_attempts=2))

            job_a = await store.claim_job("A", cfg.lock_grace_seconds)
            assert job_a is not None and job_a["attempt"] == 1
            task_a = asyncio.create_task(worker_a._execute_claimed(job_a))

            await asyncio.sleep(3.5)  # past lock_grace; A stalled mid-execution
            job_b = await store.claim_job("B", cfg.lock_grace_seconds)
            assert job_b is not None and job_b["attempt"] == 2, f"reclaim failed: {job_b}"
            task_b = asyncio.create_task(worker_b._execute_claimed(job_b))

            # A live tail attaches after the reclaim (a client watching the retry)
            tail_names = []

            async def tail():
                async for _idx, sse in stream.tail(RUN_ID, last_event_index=None):
                    tail_names.append(sse)

            await asyncio.sleep(0.2)
            tail_task = asyncio.create_task(tail())
            await asyncio.gather(task_a, task_b)
            await asyncio.wait_for(tail_task, timeout=10)

            # The zombie's post-wakeup event is NOT in the durable view
            replay_names = [str(getattr(e, "event", e)) for _, e in await stream.replay(RUN_ID)]
            assert not any("A-3" in n for n in replay_names), replay_names
            # The reclaiming attempt's full output is
            assert sum(1 for n in replay_names if n.startswith("B-")) == 5, replay_names

            # The zombie's terminal sentinel did not close B's stream early:
            # the tail saw every B event before the (B-issued) close
            assert sum(1 for s in tail_names if "B-" in s) == 5, tail_names

            # Stream and ticket both belong to attempt 2's outcome
            assert await stream.get_run_status(RUN_ID) == RunStatus.completed
            ticket = await store.get_job(RUN_ID)
            assert ticket["status"] == "completed" and ticket["attempt"] == 2
        finally:
            es_mod._event_stream = original


class TestSweepVsLiveWorkerAcceptance:
    """Scenario 2: DEFAULT config. A falsely swept worker finishes anyway.
    Finished-work-wins: ticket keeps the sweep's failure (the requeue gate
    guards re-execution), but the run row and stream carry the REAL result."""

    @pytest.mark.asyncio
    async def test_finished_work_wins_on_false_sweep(self):
        RUN_ID = "run-swept-1"
        original = es_mod._event_stream
        stream = fresh_stream()
        set_event_stream(stream)
        try:
            store = InMemoryQueueStore()
            db = FencedFakeDb()
            db.rows[RUN_ID] = {"run_id": RUN_ID, "status": "PENDING"}

            class Component:
                id = "comp-1"

                def __init__(self):
                    self.db = db
                    self.finished = False

                def arun(self, **kwargs):
                    return self._gen()

                async def _gen(self):
                    from types import SimpleNamespace

                    from agno.agent._storage import aupsert_run

                    yield Ev("A-1", RUN_ID)
                    await asyncio.sleep(5.0)  # swept as dead in here
                    yield Ev("A-2-after-stall", RUN_ID)
                    self.finished = True
                    # The real agent's own terminal save (the item-4 choke
                    # point): worker ownership is live, so this routes through
                    # the fenced primitive - same attempt, finished-work-wins
                    from agno.run.agent import RunOutput

                    await aupsert_run(
                        SimpleNamespace(db=db),
                        RunOutput(run_id=RUN_ID, session_id="s1", status=RunStatus.completed, content="real output"),
                        session_id="s1",
                    )
                    yield Out(RUN_ID)

            comp = Component()
            cfg = QueueConfig(durable=True, max_attempts=1, lock_grace_seconds=3)
            worker_a = QueueWorker(
                store=store, resolve_component=lambda t, i: comp, config=cfg, worker_id="A", stop_timeout=0.2
            )
            worker_b = QueueWorker(
                store=store, resolve_component=lambda t, i: comp, config=cfg, worker_id="B", stop_timeout=0.2
            )
            await store.enqueue_job(make_ticket(RUN_ID, max_attempts=1))

            job = await store.claim_job("A", cfg.lock_grace_seconds)
            task_a = asyncio.create_task(worker_a._execute_claimed(job))

            await asyncio.sleep(3.5)  # past lock_grace; A is mid-stall
            await worker_b._sweep_exhausted()

            ticket = await store.get_job(RUN_ID)
            assert ticket["status"] == "failed", "the sweep must fail the ticket of a stale worker"
            assert str(db.rows[RUN_ID]["status"]).upper() == "ERROR", "the sweep terminalizes the row"
            assert await stream.get_run_status(RUN_ID) == RunStatus.error

            await task_a  # A wakes and finishes

            # FINISHED-WORK-WINS: the user surfaces carry the real result
            assert comp.finished is True
            row = db.rows[RUN_ID]
            assert str(row["status"]).upper() == "COMPLETED", (
                f"the falsely swept worker's real completion must overwrite the sweep's presumption: {row}"
            )
            assert row["content"] == "real output"
            assert await stream.get_run_status(RUN_ID) == RunStatus.completed, (
                "the same-generation terminal must pass (finished-work-wins)"
            )
            # The ticket keeps the sweep's bookkeeping: at-most-once was
            # honored (no second execution), and the requeue zombie gate
            # (409 without force) guards operators from re-driving it
            ticket = await store.get_job(RUN_ID)
            assert ticket["status"] == "failed"
        finally:
            es_mod._event_stream = original
