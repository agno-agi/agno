"""RunStatus.unverified across the OS-layer surfaces.

Each test pins one surface that enumerates, filters, or maps run statuses:
the event-stream terminal sets (complete_run must not rewrite UNVERIFIED to
COMPLETED), the events-buffer reap list, the reopen tuples a continue relies
on, the WebSocket/SSE resume tuples, the job-queue ticket vocabulary and the
sweep's reconciliation, the scheduler poller's terminal set, the RunSchema
projections, the MCP trimmed and history projections, the A2A streaming
terminal state, and the component walk over the Verify workflow step.
"""

import asyncio
import inspect
import json
from time import time

import pytest

from agno.run.base import RunStatus
from agno.verifiers.types import Verification

# --- event streams: terminal sets -------------------------------------------


def test_in_memory_terminal_statuses_include_unverified():
    from agno.os.event_streams.in_memory import _TERMINAL_STATUSES

    assert RunStatus.unverified in _TERMINAL_STATUSES


def test_redis_terminal_statuses_include_unverified():
    # The redis backend has no top-level redis import, so the module's
    # terminal set is importable without the optional dependency.
    from agno.os.event_streams.redis import _TERMINAL_STATUSES

    assert RunStatus.unverified in _TERMINAL_STATUSES


# --- event streams: complete_run must not coerce UNVERIFIED -----------------


def _fresh_in_memory_stream():
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    return InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())


def test_in_memory_complete_run_keeps_unverified():
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-1", RunStatus.running)
        await stream.complete_run("run-1", RunStatus.unverified)
        return await stream.get_run_status("run-1")

    assert asyncio.run(scenario()) == RunStatus.unverified


def test_in_memory_complete_run_still_coerces_non_terminal():
    # The mark-terminal contract survives: a genuinely non-terminal argument
    # (a producer racing mid-transition) still coerces to COMPLETED.
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-2", RunStatus.running)
        await stream.complete_run("run-2", RunStatus.running)
        return await stream.get_run_status("run-2")

    assert asyncio.run(scenario()) == RunStatus.completed


def test_in_memory_tail_ends_on_unverified_run():
    # A tail attached to an already-unverified run must replay and end, not
    # idle against the live queue as if the run were still active.
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-3", RunStatus.running)
        await stream.complete_run("run-3", RunStatus.unverified)
        events = []
        async for item in stream.tail("run-3"):
            events.append(item)
        return events

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=5.0)) == []


# --- event streams: reopen accepts UNVERIFIED (continue-in-place) -----------


def test_in_memory_reopen_accepts_unverified():
    # Continuing an unverified run restarts its verification budget on the
    # SAME stream, so the reopen must invalidate the unverified sentinel the
    # way it invalidates a pause's; declining left the continue's tail closing
    # empty against the stale terminal.
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("r-unv", RunStatus.pending)
        await stream.complete_run("r-unv", RunStatus.unverified)
        reopened = await stream.reopen_run("r-unv")
        return reopened, await stream.get_run_status("r-unv")

    reopened, status = asyncio.run(scenario())
    assert reopened is True
    assert status == RunStatus.pending


def test_in_memory_reopen_still_declines_completed():
    # The guard still protects true terminals a continue may not resurrect.
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("r-done", RunStatus.pending)
        await stream.complete_run("r-done", RunStatus.completed)
        reopened = await stream.reopen_run("r-done")
        return reopened, await stream.get_run_status("r-done")

    reopened, status = asyncio.run(scenario())
    assert reopened is False
    assert status == RunStatus.completed


def test_base_default_reopen_accepts_unverified():
    from agno.os.event_streams.base import BaseEventStream

    class _FakeStream:
        def __init__(self):
            self.status = RunStatus.unverified

        async def get_run_status(self, run_id):
            return self.status

        async def set_run_status(self, run_id, status):
            self.status = status

    fake = _FakeStream()
    assert asyncio.run(BaseEventStream.reopen_run(fake, "r-unv")) is True  # type: ignore[arg-type]
    assert fake.status == RunStatus.pending


def test_redis_reopen_accepts_unverified():
    # The redis reopenable tuple is built from .value strings inside a CAS
    # transaction; drive the real CAS against fakeredis.
    fakeredis = pytest.importorskip("fakeredis", reason="fakeredis not installed")
    from agno.os.event_streams.redis import RedisEventStream

    async def scenario():
        stream = RedisEventStream(fakeredis.FakeAsyncRedis(), block_ms=100)
        try:
            await stream.register_run("r-unv", RunStatus.running)
            await stream.complete_run("r-unv", RunStatus.unverified)
            reopened = await stream.reopen_run("r-unv")
            return reopened, await stream.get_run_status("r-unv")
        finally:
            await stream.aclose()

    reopened, status = asyncio.run(scenario())
    assert reopened is True
    assert status == RunStatus.pending


def test_amark_continue_stream_running_reopens_unverified_stream(monkeypatch):
    # End to end through the continue seam's stream sync: an unverified run's
    # stream must come back RUNNING for the continuation leg, not stay parked
    # on the terminal (which made every attached tail close immediately).
    import agno.os.event_streams as es_mod
    from agno.os.utils import amark_continue_stream_running

    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("r-unv", RunStatus.pending)
        await stream.complete_run("r-unv", RunStatus.unverified)
        monkeypatch.setattr(es_mod, "get_event_stream", lambda: stream)
        await amark_continue_stream_running("r-unv")
        return await stream.get_run_status("r-unv")

    assert asyncio.run(scenario()) == RunStatus.running


# --- managers: EventsBuffer cleanup reaps unverified runs -------------------


def test_events_buffer_cleanup_reaps_unverified():
    from agno.os.managers import EventsBuffer

    buffer = EventsBuffer()
    buffer.register_run("run-unverified", RunStatus.running)
    buffer.set_run_completed("run-unverified", RunStatus.unverified)
    # Age the completion past the retention window, then reap.
    buffer.run_metadata["run-unverified"]["completed_at"] = time() - buffer.cleanup_interval - 1
    buffer.cleanup_runs()
    assert "run-unverified" not in buffer.run_metadata
    assert "run-unverified" not in buffer.events


def test_events_buffer_cleanup_preserves_unverified_index():
    # UNVERIFIED is continuable on the same stream: after the buffer reaps a
    # settled unverified run, a continuation's events must keep ascending
    # past every index a resuming client has already seen. A counter reset
    # to 0 makes the client's last_event_index dedup discard the whole
    # continuation - the same guarantee paused runs already have.
    from agno.os.managers import EventsBuffer

    buffer = EventsBuffer()
    buffer.register_run("run-unv", RunStatus.running)
    for _ in range(3):
        buffer.add_event("run-unv", object())  # type: ignore[arg-type]
    buffer.set_run_completed("run-unv", RunStatus.unverified)
    buffer.cleanup_run("run-unv")
    assert "run-unv" not in buffer.run_metadata
    # Continue-in-place reopens under the same id: monotonic, no restart at 0.
    assert buffer.add_event("run-unv", object()) == 3  # type: ignore[arg-type]


def test_events_buffer_cleanup_keeps_running_runs():
    from agno.os.managers import EventsBuffer

    buffer = EventsBuffer()
    buffer.register_run("run-live", RunStatus.running)
    buffer.run_metadata["run-live"]["last_updated"] = time() - buffer.cleanup_interval - 1
    buffer.cleanup_runs()
    assert "run-live" in buffer.run_metadata


# --- routers: WebSocket/SSE resume tuples -----------------------------------


@pytest.mark.parametrize(
    "module_path, function_name",
    [
        ("agno.os.routers.agents.router", "_resume_stream_generator"),
        ("agno.os.routers.teams.router", "_resume_stream_generator"),
        ("agno.os.routers.workflows.router", "_resume_stream_generator"),
        ("agno.os.routers.workflows.router", "handle_workflow_subscription"),
    ],
)
def test_resume_paths_treat_unverified_as_terminal(module_path, function_name):
    # The terminal tuples live inline in the resume generators; without
    # unverified in them, a finished-but-unverified run falls through to the
    # live-tail path and the client hangs on a run that will produce nothing.
    module = __import__(module_path, fromlist=[function_name])
    source = inspect.getsource(getattr(module, function_name))
    assert "RunStatus.unverified" in source


# --- job queue: ticket vocabulary and status coercion -----------------------


def test_ticket_status_to_api_maps_unverified():
    from agno.os.job_queue import ticket_status_to_api

    assert ticket_status_to_api("unverified") == "UNVERIFIED"


def test_run_status_round_trips_unverified_string():
    # The queue executor coerces a DB-read plain-str status back through the
    # enum before publishing the terminal sentinel; the member existing is
    # what keeps UNVERIFIED from being coerced to ERROR there.
    assert RunStatus("UNVERIFIED") is RunStatus.unverified
    assert RunStatus.unverified == "UNVERIFIED"


# --- job queue: sweep reconciliation and inline-continue settlement ---------


class _RecordingQueueStore:
    def __init__(self):
        self.swept = []
        self.paused_settled = []

    async def settle_swept_job(self, job_id, worker_id, status, error=None):
        self.swept.append((job_id, status, error))
        return True

    async def settle_paused_job(self, run_id, status, error=None):
        self.paused_settled.append((run_id, status, error))
        return True


def _worker_with(store, component):
    from agno.job_queue.config import QueueConfig
    from agno.os.job_queue import QueueWorker

    return QueueWorker(
        store=store,
        resolve_component=lambda component_type, component_id: component,
        config=QueueConfig(),
        worker_id="w-test",
    )


class _SweepQueueStore:
    """Job store fake for a FULL _sweep_exhausted pass over one stale job."""

    def __init__(self, job, settle_result=True, settle_raises=False):
        self.job = job
        self.settle_result = settle_result
        self.settle_raises = settle_raises
        self.swept = []

    async def sweep_exhausted_jobs(self, lock_grace_seconds):
        return [dict(self.job)]

    async def acquire_sweep(self, job_id, worker_id, lock_grace_seconds):
        return True

    async def settle_swept_job(self, job_id, worker_id, status, error=None):
        if self.settle_raises:
            raise RuntimeError("ticket store write failed")
        self.swept.append((job_id, status, error))
        return self.settle_result


class _RowComponent:
    """Component whose run row is ONE mutable dict, exposing the fenceless
    update primitive an older third-party store would: no unverified-vs-error
    guard, so the queue layer alone must protect the row."""

    def __init__(self, row):
        self.row = row
        self.db = _RowComponent._Db(row)

    async def aget_run_output(self, run_id, session_id, user_id=None):
        from agno.run.agent import RunOutput

        return RunOutput(run_id=run_id, session_id=session_id, status=RunStatus(self.row["status"]))

    class _Db:
        def __init__(self, row):
            self.row = row

        async def update_run_in_session(
            self, session_id, run_id, fields, expected_attempt=None, user_id=None, content_if_absent=None
        ):
            from agno.run.status_persist import RunPersistOutcome

            self.row.update({k: v for k, v in fields.items() if v is not None})
            return RunPersistOutcome.UPDATED


def _swept_job():
    return {
        "id": "run-unv",
        "session_id": "s1",
        "user_id": None,
        "component_type": "agent",
        "component_id": "a1",
        "payload": {"stream": True},
        "attempt": 1,
        "max_attempts": 1,
    }


def test_sweep_reconciles_unverified_run_instead_of_defacing_it(monkeypatch):
    # A crash after the run row committed UNVERIFIED but before the ticket
    # write must reconcile like COMPLETED does: ticket settles completed and
    # the stream carries the UNVERIFIED terminal. Driven through the WHOLE
    # sweep pass: without the arm, the sweep fell through to the honest-
    # failure path and rewrote the settled UNVERIFIED row to ERROR - the
    # row's final status is the assertion, not just the reconcile's return.
    import agno.os.event_streams as es_mod

    row = {"status": "UNVERIFIED"}
    store = _SweepQueueStore(_swept_job())
    worker = _worker_with(store, _RowComponent(row))
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-unv", RunStatus.running)
        monkeypatch.setattr(es_mod, "get_event_stream", lambda: stream)
        await worker._sweep_exhausted()
        return await stream.get_run_status("run-unv")

    stream_status = asyncio.run(scenario())
    assert store.swept == [("run-unv", "completed", None)]
    assert row["status"] == "UNVERIFIED"
    # The stream sentinel keeps the true terminal status, never COMPLETED.
    assert stream_status == RunStatus.unverified


@pytest.mark.parametrize("settle_kwargs", [{"settle_result": False}, {"settle_raises": True}])
def test_sweep_ticket_settle_failure_never_defaces_reconciled_row(monkeypatch, settle_kwargs):
    # A transient ticket-store failure AFTER the stream sentinel landed used
    # to make the reconcile report False, sending the caller down the honest-
    # failure path against a row that is settled. The ticket may stay open
    # for the next sweep; the row must survive as UNVERIFIED.
    import agno.os.event_streams as es_mod

    row = {"status": "UNVERIFIED"}
    store = _SweepQueueStore(_swept_job(), **settle_kwargs)
    worker = _worker_with(store, _RowComponent(row))
    stream = _fresh_in_memory_stream()

    async def scenario():
        await stream.register_run("run-unv", RunStatus.running)
        monkeypatch.setattr(es_mod, "get_event_stream", lambda: stream)
        await worker._sweep_exhausted()
        return await stream.get_run_status("run-unv")

    stream_status = asyncio.run(scenario())
    assert row["status"] == "UNVERIFIED"
    assert stream_status == RunStatus.unverified


class _TicketStore:
    def __init__(self):
        self.completed = []

    async def complete_job(self, job_id, worker_id, attempt, status, error=None):
        self.completed.append((job_id, attempt, status, error))
        return True


class _SettledUnverifiedComponent:
    """No .db on purpose: the reclaim guard must not depend on the prepare or
    stamp writes landing - only on the row read."""

    def __init__(self):
        self.arun_calls = 0

    async def aget_run_output(self, run_id, session_id, user_id=None):
        from agno.run.agent import RunOutput

        return RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.unverified)

    def arun(self, **kwargs):
        self.arun_calls += 1
        raise AssertionError("a settled UNVERIFIED row must never re-execute")


def test_reclaimed_job_over_settled_unverified_row_does_not_reexecute(monkeypatch):
    # Crash window: the run row committed UNVERIFIED but the worker died
    # before the ticket write, so the stale claim is reclaimed (attempt 2).
    # Re-executing repeats the run's side effects; the claim seam must honor
    # the settled row instead - ticket completed, stream sentinel UNVERIFIED.
    import agno.os.event_streams as es_mod

    store = _TicketStore()
    component = _SettledUnverifiedComponent()
    worker = _worker_with(store, component)
    stream = _fresh_in_memory_stream()
    job = {
        "id": "run-unv",
        "session_id": "s1",
        "user_id": None,
        "component_type": "agent",
        "component_id": "a1",
        "payload": {"stream": True},
        "attempt": 2,
        "max_attempts": 3,
    }

    async def scenario():
        await stream.register_run("run-unv", RunStatus.running)
        monkeypatch.setattr(es_mod, "get_event_stream", lambda: stream)
        await worker._execute_claimed_inner(job)
        return await stream.get_run_status("run-unv")

    stream_status = asyncio.run(scenario())
    assert component.arun_calls == 0
    assert store.completed == [("run-unv", 2, "completed", None)]
    assert stream_status == RunStatus.unverified


def test_reclaimed_continuation_of_unverified_run_still_executes():
    # A queued CONTINUE of an unverified run is the product's
    # continue-in-place: the reclaim guard must not short-circuit it.
    from agno.run.agent import RunOutput

    class _ContinuableComponent:
        def __init__(self):
            self.continue_calls = 0

        async def aget_run_output(self, run_id, session_id, user_id=None):
            return RunOutput(run_id=run_id, session_id=session_id, status=RunStatus.unverified)

        async def acontinue_run(self, **kwargs):
            self.continue_calls += 1
            return RunOutput(
                run_id=kwargs.get("run_id"), session_id=kwargs.get("session_id"), status=RunStatus.completed
            )

    store = _TicketStore()
    component = _ContinuableComponent()
    worker = _worker_with(store, component)
    job = {
        "id": "run-unv",
        "session_id": "s1",
        "user_id": None,
        "component_type": "agent",
        "component_id": "a1",
        "payload": {"stream": False, "continue": {"stream_events": False}},
        "attempt": 2,
        "max_attempts": 3,
    }

    asyncio.run(worker._execute_claimed_inner(job))
    assert component.continue_calls == 1
    assert store.completed == [("run-unv", 2, "completed", None)]


def test_asettle_paused_ticket_maps_unverified_to_completed():
    from agno.os.job_queue import asettle_paused_ticket

    store = _RecordingQueueStore()
    worker = _worker_with(store, None)
    asyncio.run(asettle_paused_ticket(worker, "run-unv", RunStatus.unverified))
    assert store.paused_settled == [("run-unv", "completed", None)]


def test_asettle_paused_ticket_still_leaves_paused_alone():
    from agno.os.job_queue import asettle_paused_ticket

    store = _RecordingQueueStore()
    worker = _worker_with(store, None)
    asyncio.run(asettle_paused_ticket(worker, "run-still-paused", RunStatus.paused))
    assert store.paused_settled == []


# --- scheduler: poller terminal set -----------------------------------------


def test_scheduler_terminal_statuses_include_unverified():
    # String literals by design: the poller compares statuses read off HTTP
    # responses, so the enum member alone does not cover this file.
    from agno.scheduler.executor import _TERMINAL_STATUSES

    assert "UNVERIFIED" in _TERMINAL_STATUSES


def test_scheduler_poll_maps_unverified_to_failed():
    from agno.scheduler.executor import ScheduleExecutor

    source = inspect.getsource(ScheduleExecutor)
    assert '"UNVERIFIED"' in source


# --- os/schema.py: run projections carry verification -----------------------


def test_run_schema_from_dict_carries_verification():
    from agno.os.schema import RunSchema

    record = {"status": "unverified", "stop_reason": "exhausted", "attempts": []}
    schema = RunSchema.from_dict({"run_id": "r1", "status": "UNVERIFIED", "verification": record})
    assert schema.verification == record
    assert schema.status == "UNVERIFIED"


def test_run_schema_from_dict_verification_defaults_to_none():
    from agno.os.schema import RunSchema

    assert RunSchema.from_dict({"run_id": "r1"}).verification is None


def test_team_run_schema_from_dict_carries_verification():
    from agno.os.schema import TeamRunSchema

    record = {"status": "verified", "stop_reason": "passed", "attempts": []}
    schema = TeamRunSchema.from_dict({"run_id": "r1", "verification": record})
    assert schema.verification == record


# --- os/mcp_results.py: trimmed projections ---------------------------------


def _run_output_with_verification(verification):
    from agno.run.agent import RunOutput

    return RunOutput(
        run_id="r1",
        session_id="s1",
        content="the answer",
        status=RunStatus.unverified,
        verification=verification,
    )


def test_trimmed_structured_content_carries_verification_summary():
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trimmed_structured_content

    verification = Verification(status="unverified", stop_reason="exhausted")
    structured = trimmed_structured_content(_run_output_with_verification(verification))
    assert structured["status"] == "UNVERIFIED"
    assert structured["verification"] == {"status": "unverified", "stop_reason": "exhausted"}
    # The compact summary only: attempts/verdicts stay out of the trimmed view.
    assert "attempts" not in structured["verification"]


def test_trimmed_structured_content_accepts_dict_verification():
    # After a DB round-trip the record arrives as a plain dict.
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trimmed_structured_content

    run_output = _run_output_with_verification(None)
    run_output.verification = {"status": "verified", "stop_reason": "passed", "attempts": []}
    structured = trimmed_structured_content(run_output)
    assert structured["verification"] == {"status": "verified", "stop_reason": "passed"}


def test_trimmed_structured_content_omits_verification_when_absent():
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trimmed_structured_content

    structured = trimmed_structured_content(_run_output_with_verification(None))
    assert "verification" not in structured


def test_session_run_history_fields_include_verification():
    pytest.importorskip("mcp")
    from agno.os.mcp_results import SESSION_RUN_HISTORY_FIELDS, trim_session_run

    assert "verification" in SESSION_RUN_HISTORY_FIELDS
    record = {"status": "unverified", "stop_reason": "exhausted"}
    trimmed = trim_session_run({"run_id": "r1", "content": "answer", "verification": record, "messages": ["kept-out"]})
    assert trimmed["verification"] == {"status": "unverified", "stop_reason": "exhausted", "attempts": 0}
    assert "messages" not in trimmed


def test_session_run_history_summarizes_fat_verification_record():
    # The raw record carries every attempt's verdicts and reports (measured
    # 11-76KB per run); the history view must ship only the outcome summary
    # with the attempt COUNT. The full record stays reachable via
    # get_session_runs(run_id=...).
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trim_session_run

    fat_record = {
        "status": "unverified",
        "stop_reason": "exhausted",
        "attempts": [
            {"index": 0, "verdicts": [{"name": "check", "passed": False, "report": "line\n" * 500}]},
            {"index": 1, "verdicts": [{"name": "check", "passed": False, "report": "line\n" * 500}]},
        ],
        "baseline_fingerprint": "abc",
        "budget_baseline": 0,
    }
    trimmed = trim_session_run({"run_id": "r1", "content": "answer", "verification": fat_record})
    assert trimmed["verification"] == {"status": "unverified", "stop_reason": "exhausted", "attempts": 2}
    assert len(json.dumps(trimmed)) < 500


def test_session_run_history_summarizes_dataclass_verification_record():
    # A fresh (not-yet-persisted) run hands the record over as a dataclass.
    pytest.importorskip("mcp")
    from agno.os.mcp_results import trim_session_run
    from agno.verifiers.types import VerificationAttempt

    record = Verification(status="verified", stop_reason="passed", attempts=[VerificationAttempt(index=0)])
    trimmed = trim_session_run({"run_id": "r1", "content": "answer", "verification": record})
    assert trimmed["verification"] == {"status": "verified", "stop_reason": "passed", "attempts": 1}


# --- A2A: streaming terminal state and verification forwarding --------------


def _parse_a2a_chunks(chunks):
    parsed = []
    for chunk in chunks:
        for line in chunk.split("\n"):
            if line.startswith("data: "):
                parsed.append(json.loads(line[len("data: ") :]))
    return parsed


def _collect_a2a_stream(events):
    from agno.os.interfaces.a2a.utils import stream_a2a_response

    async def _source():
        for event in events:
            yield event

    async def _collect():
        return [chunk async for chunk in stream_a2a_response(_source(), request_id="req-1")]

    return _parse_a2a_chunks(asyncio.run(_collect()))


def _unverified_agent_events():
    from agno.run.agent import RunCompletedEvent, RunStartedEvent, VerificationCompletedEvent

    return [
        RunStartedEvent(run_id="run-1", session_id="sess-1"),
        VerificationCompletedEvent(
            run_id="run-1",
            session_id="sess-1",
            attempt=3,
            max_attempts=3,
            passed=False,
            stop_reason="exhausted",
            verdicts=[{"name": "check", "passed": False, "summary": "still failing"}],
        ),
        RunCompletedEvent(run_id="run-1", session_id="sess-1", content="claimed done"),
    ]


def test_a2a_stream_unverified_run_ends_failed():
    # The non-stream Task mapping already reports UNVERIFIED as failed; the
    # streaming path must agree, or a consuming agent reads an unverified
    # answer as a verified completed one.
    pytest.importorskip("a2a")
    parsed = _collect_a2a_stream(_unverified_agent_events())

    finals = [
        p["result"] for p in parsed if p["result"].get("kind") == "status-update" and p["result"].get("final") is True
    ]
    assert len(finals) == 1
    assert finals[0]["status"]["state"] == "failed"
    assert finals[0]["metadata"]["agno_event_type"] == "run_unverified"
    assert finals[0]["metadata"]["stop_reason"] == "exhausted"

    tasks = [p["result"] for p in parsed if p["result"].get("kind") == "task"]
    assert len(tasks) == 1
    assert tasks[0]["status"]["state"] == "failed"


def test_a2a_stream_verified_run_still_ends_completed():
    pytest.importorskip("a2a")
    from agno.run.agent import RunCompletedEvent, RunStartedEvent, VerificationCompletedEvent

    parsed = _collect_a2a_stream(
        [
            RunStartedEvent(run_id="run-1", session_id="sess-1"),
            VerificationCompletedEvent(
                run_id="run-1", session_id="sess-1", attempt=1, max_attempts=3, passed=True, stop_reason="passed"
            ),
            RunCompletedEvent(run_id="run-1", session_id="sess-1", content="done"),
        ]
    )
    finals = [
        p["result"] for p in parsed if p["result"].get("kind") == "status-update" and p["result"].get("final") is True
    ]
    assert finals[0]["status"]["state"] == "completed"
    tasks = [p["result"] for p in parsed if p["result"].get("kind") == "task"]
    assert tasks[0]["status"]["state"] == "completed"


def test_a2a_stream_forwards_verification_events_as_working_updates():
    # Verification started/completed used to be silently dropped by the elif
    # chain; they must ride as non-final working status-updates like the
    # other secondary events.
    pytest.importorskip("a2a")
    from agno.run.agent import RunCompletedEvent, RunStartedEvent, VerificationCompletedEvent, VerificationStartedEvent

    events = [
        RunStartedEvent(run_id="run-1", session_id="sess-1"),
        VerificationStartedEvent(run_id="run-1", session_id="sess-1", attempt=1, max_attempts=3),
        VerificationCompletedEvent(
            run_id="run-1", session_id="sess-1", attempt=1, max_attempts=3, passed=True, stop_reason="passed"
        ),
        RunCompletedEvent(run_id="run-1", session_id="sess-1", content="done"),
    ]
    parsed = _collect_a2a_stream(events)
    working = [
        p["result"] for p in parsed if p["result"].get("kind") == "status-update" and p["result"].get("final") is False
    ]
    event_types = [(w.get("metadata") or {}).get("agno_event_type") for w in working]
    assert "verification_started" in event_types
    assert "verification_completed" in event_types
    completed_update = next(
        w for w in working if (w.get("metadata") or {}).get("agno_event_type") == "verification_completed"
    )
    assert completed_update["metadata"]["passed"] is True
    assert completed_update["metadata"]["attempt"] == 1
    assert completed_update["metadata"]["max_attempts"] == 3


def test_a2a_stream_team_unverified_run_ends_failed():
    pytest.importorskip("a2a")
    from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
    from agno.run.team import RunStartedEvent as TeamRunStartedEvent
    from agno.run.team import TeamVerificationCompletedEvent

    parsed = _collect_a2a_stream(
        [
            TeamRunStartedEvent(run_id="run-1", session_id="sess-1"),
            TeamVerificationCompletedEvent(
                run_id="run-1", session_id="sess-1", attempt=2, max_attempts=2, passed=False, stop_reason="noop"
            ),
            TeamRunCompletedEvent(run_id="run-1", session_id="sess-1", content="claimed"),
        ]
    )
    finals = [
        p["result"] for p in parsed if p["result"].get("kind") == "status-update" and p["result"].get("final") is True
    ]
    assert finals[0]["status"]["state"] == "failed"
    assert finals[0]["metadata"]["stop_reason"] == "noop"


def _team_with_failed_member_events():
    from agno.run.agent import RunStartedEvent, VerificationCompletedEvent
    from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
    from agno.run.team import RunStartedEvent as TeamRunStartedEvent

    return [
        TeamRunStartedEvent(run_id="team-1", session_id="sess-1"),
        RunStartedEvent(run_id="member-1", parent_run_id="team-1", session_id="sess-1"),
        VerificationCompletedEvent(
            run_id="member-1",
            parent_run_id="team-1",
            session_id="sess-1",
            attempt=2,
            max_attempts=2,
            passed=False,
            stop_reason="exhausted",
        ),
        TeamRunCompletedEvent(run_id="team-1", session_id="sess-1", content="team answer"),
    ]


def _task_id_of(result):
    # The a2a models serialize with field names by default but may carry
    # camelCase aliases; accept either so the assertion pins the value.
    return result.get("taskId", result.get("task_id"))


def test_a2a_stream_failed_member_does_not_fail_completed_team_run():
    # The task's lifecycle is scoped to the ROOT run: a member's failed
    # verification must not mark the completed TEAM run failed, and the
    # member's RunStarted must not replace the task identity.
    pytest.importorskip("a2a")
    parsed = _collect_a2a_stream(_team_with_failed_member_events())

    finals = [
        p["result"] for p in parsed if p["result"].get("kind") == "status-update" and p["result"].get("final") is True
    ]
    assert len(finals) == 1
    assert finals[0]["status"]["state"] == "completed"
    assert _task_id_of(finals[0]) == "team-1"

    tasks = [p["result"] for p in parsed if p["result"].get("kind") == "task"]
    assert len(tasks) == 1
    assert tasks[0]["status"]["state"] == "completed"
    assert tasks[0]["id"] == "team-1"

    # Every status-update stays on the team's task: the member's RunStarted
    # never re-pointed the stream at the nested run.
    updates = [p["result"] for p in parsed if p["result"].get("kind") == "status-update"]
    assert all(_task_id_of(u) == "team-1" for u in updates)


def test_a2a_stream_nested_verification_still_flows_as_working_update():
    # Member verification outcomes keep flowing as NON-final working updates,
    # marked with their origin run so consumers can attribute them.
    pytest.importorskip("a2a")
    parsed = _collect_a2a_stream(_team_with_failed_member_events())

    working = [
        p["result"] for p in parsed if p["result"].get("kind") == "status-update" and p["result"].get("final") is False
    ]
    nested = [w for w in working if (w.get("metadata") or {}).get("agno_event_type") == "verification_completed"]
    assert len(nested) == 1
    assert nested[0]["metadata"]["passed"] is False
    assert nested[0]["metadata"]["origin_run_id"] == "member-1"


# --- os/utils: the component walk reaches inside a Verify step --------------


def _walk_workflow():
    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.workflow.step import Step
    from agno.workflow.verify import Verify
    from agno.workflow.workflow import Workflow

    def named_check(run_output):
        return True

    model = OpenAIResponses(id="gpt-5.5", api_key="test")
    agent = Agent(id="draft-agent", name="Draft Agent", model=model)
    workflow = Workflow(
        id="wf-verify",
        name="WF Verify",
        steps=[Step(name="draft", agent=agent), Verify([named_check], name="gate")],
    )
    workflow._prepare_steps()
    return workflow, model, named_check


def test_component_walk_reaches_verify_absorbed_segment_and_checks():
    # After _prepare_steps the Verify has absorbed its loop-back segment, so
    # the top-level steps list holds only the Verify: the walk must recurse
    # into it (or the absorbed agent is lost to the registry) and register
    # each check under the name to_dict emits (or rehydration degrades every
    # check to the fail-closed placeholder).
    from agno.os.utils import collect_components_from_workflow
    from agno.registry import Registry

    workflow, model, named_check = _walk_workflow()
    registry = Registry(name="walk-test")
    collect_components_from_workflow(workflow, registry, set())

    assert registry.get_function("named_check") is named_check
    assert model in registry.models


def test_component_walk_registers_renamed_check_under_emitted_name():
    # check(fn, name=...) emits the custom name in to_dict; the registered
    # callable must resolve under that name, not the function's own __name__.
    from agno.os.utils import collect_components_from_workflow
    from agno.registry import Registry
    from agno.verifiers import check
    from agno.workflow.verify import Verify
    from agno.workflow.workflow import Workflow

    def raw_fn(run_output):
        return True

    workflow = Workflow(
        id="wf-renamed",
        name="WF Renamed",
        steps=[Verify([check(raw_fn, name="custom-gate")], on_fail=None)],
    )
    workflow._prepare_steps()
    registry = Registry(name="walk-renamed")
    collect_components_from_workflow(workflow, registry, set())

    registered = registry.get_function("custom-gate")
    assert registered is not None
    assert registered(None) is True


def test_mcp_tool_walk_reaches_verify_absorbed_segment():
    from agno.os.utils import collect_mcp_tools_from_workflow_step

    class MCPTools:
        # The walk matches by class name across the MRO, so this stands in
        # for the real toolkit without the optional dependency.
        pass

    from agno.agent import Agent
    from agno.models.openai import OpenAIResponses
    from agno.workflow.step import Step
    from agno.workflow.verify import Verify
    from agno.workflow.workflow import Workflow

    tool = MCPTools()
    agent = Agent(id="mcp-agent", name="MCP Agent", model=OpenAIResponses(id="gpt-5.5", api_key="test"), tools=[tool])
    workflow = Workflow(
        id="wf-mcp",
        name="WF MCP",
        steps=[Step(name="draft", agent=agent), Verify([lambda run_output: True], name="gate")],
    )
    workflow._prepare_steps()

    found = []
    for step in workflow.steps:
        collect_mcp_tools_from_workflow_step(step, found)
    assert tool in found
