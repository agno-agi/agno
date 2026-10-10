"""Run-level retries on external framework adapters."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, List

import pytest

from agno.agents.base import BaseExternalAgent, ExternalRunResult, ExternalRunWarningEvent
from agno.exceptions import RunCancelledException
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunOutput,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus


@dataclass
class FlakyAgent(BaseExternalAgent):
    """Fails the first `failures` attempts, after streaming some output, then succeeds."""

    failures: int = 1
    error: type = RuntimeError
    delay_between_retries: int = 0
    attempts: List[dict] = field(default_factory=list)

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        self.attempts.append(kwargs)
        if len(self.attempts) <= self.failures:
            raise self.error(f"attempt {len(self.attempts)} failed")
        return f"answer {len(self.attempts)}"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        attempt = len(self.attempts) + 1
        run_id = kwargs["run_id"]
        tool = ToolExecution(tool_call_id=f"t{attempt}", tool_name="shell", tool_args={"command": "ls"})
        yield RunContentEvent(run_id=run_id, content=f"partial {attempt} ")
        yield ToolCallStartedEvent(run_id=run_id, tool=tool)
        yield ToolCallCompletedEvent(
            run_id=run_id, tool=ToolExecution(tool_call_id=f"t{attempt}", tool_name="shell", result="ok")
        )
        content = await self._arun_adapter(input, **kwargs)
        yield RunContentEvent(run_id=run_id, content=content)


def _stream(agent: BaseExternalAgent, **kwargs: Any) -> List[Any]:
    async def consume():
        return [event async for event in agent._arun_stream("go", yield_run_output=True, **kwargs)]

    return asyncio.run(consume())


def test_no_retries_by_default():
    agent = FlakyAgent(id="flaky")
    assert agent.retries == 0
    out = agent.run("go")
    assert out.status == RunStatus.error
    assert out.content == "attempt 1 failed"
    assert len(agent.attempts) == 1


def test_non_stream_retries_until_success():
    agent = FlakyAgent(id="flaky", retries=2, failures=2)
    out = agent.run("go", session_id="s1")
    assert out.status == RunStatus.completed
    assert out.content == "answer 3"
    assert len(agent.attempts) == 3
    assert {a["run_id"] for a in agent.attempts} == {out.run_id}


def test_non_stream_gives_up_after_retries():
    agent = FlakyAgent(id="flaky", retries=2, failures=5)
    out = agent.run("go")
    assert out.status == RunStatus.error
    assert out.content == "attempt 3 failed"
    assert len(agent.attempts) == 3


def test_stream_retry_keeps_tools_from_every_attempt_and_final_content():
    agent = FlakyAgent(id="flaky", retries=1, failures=1)
    events = _stream(agent)
    run = events[-1]
    assert isinstance(run, RunOutput)
    assert isinstance(events[-2], RunCompletedEvent)
    assert not any(isinstance(e, RunErrorEvent) for e in events)
    assert run.status == RunStatus.completed
    assert run.content == "partial 2 answer 2"
    assert [t.tool_call_id for t in run.tools or []] == ["t1", "t2"]
    assert len(agent.attempts) == 2


def test_stream_gives_up_after_retries():
    agent = FlakyAgent(id="flaky", retries=1, failures=5)
    events = _stream(agent)
    assert isinstance(events[-2], RunErrorEvent)
    assert events[-1].content == "attempt 2 failed"
    assert len(agent.attempts) == 2


@pytest.mark.parametrize("stream", [False, True])
def test_cancelled_attempt_is_not_retried(stream):
    agent = FlakyAgent(id="flaky", retries=3, failures=5, error=RunCancelledException)
    if stream:
        events = _stream(agent)
        assert isinstance(events[-2], RunCancelledEvent)
        status = events[-1].status
    else:
        status = agent.run("go").status
    assert status == RunStatus.cancelled
    assert len(agent.attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_cancel_during_backoff_stops_retrying(stream):
    agent = FlakyAgent(id="flaky", retries=3, failures=5, delay_between_retries=30)

    async def run() -> RunOutput:
        if not stream:
            return await agent._arun_non_stream("go", run_id="r1")
        events = [e async for e in agent._arun_stream("go", run_id="r1", yield_run_output=True)]
        return events[-1]

    task = asyncio.create_task(run())
    while not agent.attempts:
        await asyncio.sleep(0.01)
    await agent.acancel_run("r1")
    out = await asyncio.wait_for(task, 3)
    assert out.status == RunStatus.cancelled
    assert len(agent.attempts) == 1


def test_retry_delay_backoff():
    agent = FlakyAgent(id="flaky", delay_between_retries=2)
    assert [agent._retry_delay(a) for a in range(3)] == [2, 2, 2]
    agent.exponential_backoff = True
    assert [agent._retry_delay(a) for a in range(3)] == [2, 4, 8]


@dataclass
class PickyAgent(FlakyAgent):
    def _is_retryable_error(self, error: Exception) -> bool:
        return "permanent" not in str(error)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "agent_cls, error, retried",
    [
        (PickyAgent, ValueError("permanent failure"), False),
        (PickyAgent, ValueError("transient failure"), True),
        (FlakyAgent, ImportError("sdk missing"), False),
    ],
    ids=["adapter_permanent", "adapter_transient", "import_error"],
)
def test_non_retryable_errors_stop_retrying(agent_cls, error, retried, stream):
    agent = agent_cls(id="flaky", retries=2, failures=5)

    async def adapter(input: Any, **kwargs: Any) -> str:
        agent.attempts.append(kwargs)
        raise error

    agent._arun_adapter = adapter  # type: ignore[method-assign]
    status = _stream(agent)[-1].status if stream else agent.run("go").status
    assert status == RunStatus.error
    assert len(agent.attempts) == (3 if retried else 1)


@dataclass
class ToolyAgent(FlakyAgent):
    """Runs a tool on every attempt and, like the real adapters, leaves it in run_state when the attempt fails."""

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> Any:
        attempt = len(self.attempts) + 1
        tool = ToolExecution(tool_call_id=f"t{attempt}", tool_name="shell", tool_args={"command": "ls"}, result="ok")
        kwargs["run_state"]["tools"] = {tool.tool_call_id: tool}
        content = await super()._arun_adapter(input, **kwargs)
        # On success the adapter returns its tools; on failure they are only in run_state.
        return ExternalRunResult(content, tools=[tool])

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        # Like a real adapter: tool events are streamed as the tool completes, before the
        # attempt can still fail; the base keeps them from the events.
        attempt = len(self.attempts) + 1
        run_id = kwargs["run_id"]
        tool = ToolExecution(tool_call_id=f"t{attempt}", tool_name="shell", tool_args={"command": "ls"})
        yield ToolCallStartedEvent(run_id=run_id, tool=tool)
        yield ToolCallCompletedEvent(
            run_id=run_id, tool=ToolExecution(tool_call_id=f"t{attempt}", tool_name="shell", result="ok")
        )
        result = await self._arun_adapter(input, **kwargs)
        yield RunContentEvent(run_id=run_id, content=result.content)


def test_non_stream_retry_keeps_tools_from_the_failed_attempt():
    agent = ToolyAgent(id="tooly", retries=1, failures=1)
    out = agent.run("go", session_id="s1")
    assert out.status == RunStatus.completed and out.content == "answer 2"
    assert [t.tool_call_id for t in out.tools or []] == ["t1", "t2"]
    assert [m.role for m in out.messages or []].count("tool") == 2


def test_non_stream_gives_up_with_tools_from_every_attempt():
    agent = ToolyAgent(id="tooly", retries=1, failures=5)
    out = agent.run("go")
    assert out.status == RunStatus.error
    assert [t.tool_call_id for t in out.tools or []] == ["t1", "t2"]


def test_stream_retry_announces_the_retry_to_the_consumer():
    agent = FlakyAgent(id="flaky", retries=1, failures=1)
    events = _stream(agent)
    retry_events = [
        e for e in events if isinstance(e, ExternalRunWarningEvent) and (e.warning or {}).get("type") == "retry"
    ]
    assert len(retry_events) == 1
    warning = retry_events[0].warning
    assert (warning["attempt"], warning["attempts"], warning["error"]) == (1, 2, "attempt 1 failed")
    # It arrives after the failed attempt's output and before the retry's.
    contents = [e.content for e in events if isinstance(e, RunContentEvent)]
    assert contents == ["partial 1 ", "partial 2 ", "answer 2"]
    position = events.index(retry_events[0])
    assert isinstance(events[position - 1], ToolCallCompletedEvent) and events[position + 1].content == "partial 2 "
    run = events[-1]
    assert run.metadata["warnings"] == [warning]


@dataclass
class PermanentAgent(FlakyAgent):
    """Every failure is classified as one that would repeat."""

    def _is_retryable_error(self, error: Exception) -> bool:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("permanent", [True, False], ids=["permanent", "transient"])
async def test_queue_fails_a_permanent_failure_without_redriving_it(tmp_path, stream, permanent):
    from agno.db.sqlite import SqliteDb
    from ._queue_harness import run_through_queue

    agent_cls = PermanentAgent if permanent else FlakyAgent
    agent = agent_cls(id="flaky", db=SqliteDb(db_file=str(tmp_path / "runs.db")), failures=5)

    job = await run_through_queue(agent, stream=stream, max_attempts=3)

    assert job["status"] == "failed"
    assert job["attempt"] == (1 if permanent else 3), "a permanent failure is not re-driven by the queue"
    assert len(agent.attempts) == job["attempt"]
    run = await agent.aget_run_output(job["id"], "s")
    assert run.status == RunStatus.error
    assert run.metadata["retryable"] is (not permanent)
    assert run.metadata["error_type"]


def test_error_runs_record_retryability():
    permanent = PermanentAgent(id="p", failures=5).run("go")
    assert permanent.status == RunStatus.error and permanent.metadata["retryable"] is False
    transient = FlakyAgent(id="t", failures=5).run("go")
    assert transient.status == RunStatus.error and transient.metadata["retryable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_queued_retry_keeps_tools_from_the_failed_attempt_exactly_once(tmp_path, stream):
    from agno.db.sqlite import SqliteDb

    from ._queue_harness import run_through_queue

    agent = ToolyAgent(id="tooly", db=SqliteDb(db_file=str(tmp_path / "runs.db")), retries=1, failures=1)
    job = await run_through_queue(agent, stream=stream, max_attempts=1)
    assert job["status"] == "completed" and job["attempt"] == 1, "the agent retried inside one queue attempt"
    run = await agent.aget_run_output(job["id"], "s")
    assert run.status == RunStatus.completed
    assert [t.tool_call_id for t in run.tools or []] == ["t1", "t2"]
    assert [m.tool_call_id for m in run.messages or [] if m.role == "tool"] == ["t1", "t2"]
    assert run.metadata["attempts"] == 2


def test_retried_runs_record_the_attempt_count():
    assert FlakyAgent(id="f", retries=2, failures=1).run("go").metadata["attempts"] == 2
    assert "attempts" not in (FlakyAgent(id="f", retries=2, failures=0).run("go").metadata or {})


@pytest.mark.asyncio
async def test_reclaimed_job_honors_a_persisted_non_retryable_run(tmp_path):
    """The worker that classified the failure crashed after writing the run row but before
    settling the ticket. The worker that reclaims the job must read the classification from the
    row and fail the ticket instead of re-executing."""
    from uuid import uuid4

    from agno.db.schemas.jobs import QueuedJob
    from agno.db.sqlite import SqliteDb
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent = PermanentAgent(id="permanent", db=SqliteDb(db_file=str(tmp_path / "runs.db")), failures=5)
    store = InMemoryQueueStore()
    run_id = str(uuid4())
    await store.enqueue_job(
        QueuedJob(
            id=run_id,
            component_type="agent",
            component_id=agent.id,
            session_id="s",
            payload={"input": "go"},
            max_attempts=3,
        ).to_dict()
    )

    async def wait_until(predicate, timeout=5):
        async def poll():
            while not await predicate():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(poll(), timeout)

    # Worker one runs the job and "crashes" before settling the ticket.
    crashing = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="worker-one",
    )

    async def lost_settle(*args, **kwargs):
        return False

    crashing._asettle_ticket = lost_settle  # type: ignore[method-assign]
    crashing._aretry_or_fail_ticket = lost_settle  # type: ignore[method-assign]
    await crashing.start()
    try:

        async def row_is_error():
            run = await agent.aget_run_output(run_id, "s")
            return run is not None and run.status == RunStatus.error

        await wait_until(row_is_error)
    finally:
        await crashing.stop()
    assert len(agent.attempts) == 1
    assert (await store.get_job(run_id))["status"] == "running", "the ticket was never settled"

    # Worker two reclaims the stale ticket. It must not run the agent again.
    # Age the dead worker's lease so the ticket is reclaimable at once.
    store._jobs[run_id]["locked_at"] -= 3600
    reclaiming = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="worker-two",
    )
    await reclaiming.start()
    try:

        async def ticket_settled():
            return (await store.get_job(run_id))["status"] in ("failed", "completed")

        await wait_until(ticket_settled)
    finally:
        await reclaiming.stop()
    job = await store.get_job(run_id)
    assert job["status"] == "failed" and job["attempt"] == 2
    assert len(agent.attempts) == 1, "the permanent failure was not re-executed after the restart"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_cancel_during_backoff_keeps_tools_from_the_failed_attempt(stream):
    """A tool completed, the attempt failed, and the run was cancelled while waiting to retry:
    the cancelled run still records the tool that ran."""
    agent = ToolyAgent(id="tooly", retries=3, failures=5, delay_between_retries=30)

    async def run() -> RunOutput:
        if not stream:
            return await agent._arun_non_stream("go", run_id="r1")
        events = [e async for e in agent._arun_stream("go", run_id="r1", yield_run_output=True)]
        return events[-1]

    task = asyncio.create_task(run())
    while not agent.attempts:
        await asyncio.sleep(0.01)
    await agent.acancel_run("r1")
    out = await asyncio.wait_for(task, 3)
    assert out.status == RunStatus.cancelled and len(agent.attempts) == 1
    assert [t.tool_call_id for t in out.tools or []] == ["t1"]
    assert [m.tool_call_id for m in out.messages or [] if m.role == "tool"] == ["t1"]


@pytest.mark.asyncio
async def test_reclaim_defers_execution_when_the_classification_cannot_be_read(tmp_path):
    """A read failure on the reclaim must not be taken as 'retryable'. The job waits for a
    reclaim that can read the row, then fails without re-executing."""
    from uuid import uuid4

    from agno.db.schemas.jobs import QueuedJob
    from agno.db.sqlite import SqliteDb
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent = PermanentAgent(id="permanent", db=SqliteDb(db_file=str(tmp_path / "runs.db")), failures=5)
    store = InMemoryQueueStore()
    run_id = str(uuid4())
    await store.enqueue_job(
        QueuedJob(
            id=run_id,
            component_type="agent",
            component_id=agent.id,
            session_id="s",
            payload={"input": "go"},
            max_attempts=5,
        ).to_dict()
    )

    async def wait_until(predicate, timeout=5):
        async def poll():
            while not await predicate():
                await asyncio.sleep(0.01)

        await asyncio.wait_for(poll(), timeout)

    async def lost_settle(*args, **kwargs):
        return False

    crashing = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="worker-one",
    )
    crashing._asettle_ticket = lost_settle  # type: ignore[method-assign]
    crashing._aretry_or_fail_ticket = lost_settle  # type: ignore[method-assign]
    await crashing.start()
    try:

        async def row_is_error():
            run = await agent.aget_run_output(run_id, "s")
            return run is not None and run.status == RunStatus.error

        await wait_until(row_is_error)
    finally:
        await crashing.stop()
    assert len(agent.attempts) == 1

    # The reclaiming worker's first row read fails.
    real_read = agent.aget_run_output
    reads = {"failed": 0}

    async def flaky_read(*args, **kwargs):
        if reads["failed"] == 0:
            reads["failed"] += 1
            raise RuntimeError("database unavailable")
        return await real_read(*args, **kwargs)

    agent.aget_run_output = flaky_read  # type: ignore[method-assign]
    store._jobs[run_id]["locked_at"] -= 3600
    reclaiming = QueueWorker(
        store=store,
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True, poll_interval=0.01, retry_delay_seconds=0),
        worker_id="worker-two",
    )
    await reclaiming.start()
    try:

        async def deferred():
            job = await store.get_job(run_id)
            return reads["failed"] == 1 and job["status"] == "running" and job["attempt"] == 2

        await wait_until(deferred)
        await asyncio.sleep(0.05)
        assert len(agent.attempts) == 1, "a failed classification read must not execute the agent"
        assert (await store.get_job(run_id))["status"] == "running", "the claim is left to go stale, not settled"

        # The lease goes stale; the next reclaim reads the row and fails the ticket.
        store._jobs[run_id]["locked_at"] -= 3600

        async def ticket_failed():
            return (await store.get_job(run_id))["status"] == "failed"

        await wait_until(ticket_failed)
    finally:
        await reclaiming.stop()
    job = await store.get_job(run_id)
    assert job["attempt"] == 3 and len(agent.attempts) == 1
