"""Failure and continuation boundaries for native approval delivery; no model calls."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from agno.agents._approval import db_call, sync_events, tail_stored
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.response import ToolExecution
from agno.run.agent import RunContinuedEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.session import AgentSession
from tests.unit.agents.test_human_approval import Harness


@pytest.mark.asyncio
@pytest.mark.parametrize("database", [SqliteDb, AsyncSqliteDb])
@pytest.mark.parametrize("decision", ["pending", "approved", "rejected"])
async def test_orphaned_native_pause_can_be_cancelled(tmp_path, database, decision):
    db = database(db_file=str(tmp_path / "orphan.db"))
    agent = Harness(id="agent", db=db)
    run = RunOutput(
        run_id="orphan",
        session_id="session",
        agent_id="agent",
        status=RunStatus.paused,
        requirements=[
            RunRequirement(
                tool_execution=ToolExecution(tool_call_id="tool", approval_id="approval", requires_confirmation=True)
            )
        ],
        metadata={"native_approval": {"owner": "dead", "approval_ids": ["approval"]}},
    )
    await db_call(db, "upsert_session", AgentSession(session_id="session", agent_id="agent", runs=[run]))
    await db_call(db, "upsert_run", run, session_id="session", run_index=0)
    await db_call(
        db,
        "create_approval",
        {
            "id": "approval",
            "run_id": "orphan",
            "session_id": "session",
            "agent_id": "agent",
            "status": decision,
            "run_status": "PAUSED",
            "source_type": "agent",
            "approval_type": "required",
            "pause_type": "confirmation",
            "context": {"native_approval": {"owner": "dead"}},
            "expires_at": int(time.time()) + 60,
        },
    )
    await agent.acancel_run("orphan")
    await agent.acancel_run("orphan")
    stored = await agent.aget_run_output("orphan", "session")
    assert stored.status == RunStatus.cancelled
    assert not stored.requirements
    assert stored.metadata["native_approval"]["approval_ids"] == []
    assert (await db_call(db, "get_approval", "approval"))["status"] == "cancelled"
    session = await agent.aget_session("session")
    agent._claim_session(session, "session", "next")
    agent._release_session("session", "next")


@pytest.mark.asyncio
async def test_stored_tail_detects_new_approval_without_stored_events():
    run = RunOutput(
        run_id="run",
        session_id="session",
        status=RunStatus.paused,
        metadata={"native_approval": {"approval_ids": ["first"]}},
    )
    reads = 0

    async def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads > 1:
            run.metadata["native_approval"]["approval_ids"] = ["second"]
        return run

    agent = SimpleNamespace(approval_timeout=0.25, aget_run_output=read)
    items = [item async for item in tail_stored(agent, "run", "session", None, 0)]
    assert items[-1].metadata["native_approval"]["approval_ids"] == ["second"]
    assert any(getattr(item, "event", None) == "RunPaused" for item in items)


@pytest.mark.asyncio
async def test_budget_read_failure_does_not_cancel_native_execution():
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    async def read(*args, **kwargs):
        raise RuntimeError("transient database outage")

    agent = SimpleNamespace(_uses_native_approvals=True, approval_timeout=1, aget_run_output=read)
    worker = QueueWorker(
        store=InMemoryQueueStore(),
        resolve_component=lambda *_: agent,
        config=QueueConfig(timeout_seconds=1),
        worker_id="test",
    )
    result = await worker._await_with_timeout(
        asyncio.sleep(0.05, result="done"), None, agent, {"id": "run", "session_id": "session"}
    )
    assert result == "done"


@pytest.mark.asyncio
async def test_budget_poll_retains_human_wait_during_database_outage(monkeypatch):
    from agno.agents import _approval
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    reads = 0

    async def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 1:
            return RunOutput(metadata={"native_approval": {"approval_ids": ["pending"]}})
        raise RuntimeError("transient database outage")

    # Exercise the real timer: an outage during a human wait must not spend
    # the short execution budget or cause a burst of database retries.
    monkeypatch.setattr(_approval, "read_approval_run", read)
    agent = SimpleNamespace(_uses_native_approvals=True, approval_timeout=3)
    worker = QueueWorker(
        store=InMemoryQueueStore(),
        resolve_component=lambda *_: agent,
        config=QueueConfig(timeout_seconds=0.5),
        worker_id="test",
    )
    assert (
        await worker._await_with_timeout(
            asyncio.sleep(1.3, result="done"), None, agent, {"id": "run", "session_id": "session"}
        )
        == "done"
    )
    assert reads == 2


@pytest.mark.asyncio
async def test_approval_run_read_is_scoped_without_loading_session_history(tmp_path, monkeypatch):
    from agno.agents._approval import read_approval_run

    db = SqliteDb(db_file=str(tmp_path / "scope.db"))
    agent = Harness(id="agent", db=db)
    run = RunOutput(run_id="run", session_id="session", agent_id="agent", user_id="user")
    db.upsert_session(AgentSession(session_id="session", agent_id="agent", user_id="user", runs=[run]))
    db.upsert_run(run, session_id="session")

    def reject_full_session(*args, **kwargs):
        pytest.fail("Approval polling must not load session history")

    monkeypatch.setattr(db, "get_session", reject_full_session)
    assert (await read_approval_run(agent, "run", "session", "user")).run_id == "run"
    assert await read_approval_run(agent, "run", "session", "other") is None
    assert await read_approval_run(agent, "run", "other", "user") is None
    agent.id = "other"
    assert await read_approval_run(agent, "run", "session", "user") is None


@pytest.mark.asyncio
async def test_sync_postgres_approval_calls_leave_event_loop_free():
    import threading

    from agno.agents._approval import db_call

    owner = threading.get_ident()
    db = SimpleNamespace(
        db_engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")), get_run=lambda _: threading.get_ident()
    )
    assert await db_call(db, "get_run", "run") != owner


@pytest.mark.asyncio
async def test_successive_approvals_with_lifecycle_events_excluded(tmp_path, monkeypatch):
    from agno.agents._approval import current_bridge
    from agno.run.agent import RunContentEvent, RunEvent
    from tests.unit.agents.test_human_approval import pending

    agent = Harness(
        id="agent",
        db=SqliteDb(db_file=str(tmp_path / "events.db")),
        approval_timeout=5,
        events_to_skip=[RunEvent.run_paused, RunEvent.run_continued],
    )

    async def source(input, **kwargs):
        await current_bridge().request("Bash", {"command": "first"}, {})
        await current_bridge().request("Bash", {"command": "second"}, {})
        yield RunContentEvent(content="done")

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        first = await pending(agent)
        first_id = first.requirements[0].tool_execution.approval_id
        agent.db.update_approval(first_id, status="approved")
        second = await asyncio.wait_for(agent.acontinue_run(run_id="run", session_id="session"), 3)
        assert second.status == RunStatus.paused
        assert second.requirements[0].tool_execution.tool_args == {"command": "second"}
        assert not any(event.event in ("RunPaused", "RunContinued") for event in second.events or [])
        agent.db.update_approval(second.requirements[0].tool_execution.approval_id, status="rejected")
        completed = await asyncio.wait_for(agent.acontinue_run(run_id="run", session_id="session"), 3)
        assert completed.status == RunStatus.completed
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_sync_continuation_iterator_inside_running_loop():
    async def source():
        yield RunContinuedEvent(run_id="run")

    assert [item.event for item in sync_events(source())] == ["RunContinued"]


@pytest.mark.asyncio
async def test_parallel_acknowledgement_is_not_a_new_permission_pause():
    pending = RunOutput(
        run_id="run",
        session_id="session",
        status=RunStatus.paused,
        events=[RunContinuedEvent(approval_id="first")],
        metadata={"native_approval": {"approval_ids": ["second"]}},
    )
    completed = RunOutput(run_id="run", session_id="session", status=RunStatus.completed, content="done")
    states = iter([pending, completed])

    async def read(*args, **kwargs):
        return next(states)

    agent = SimpleNamespace(approval_timeout=0.25, aget_run_output=read)
    items = [item async for item in tail_stored(agent, "run", "session", None, 0, {"first", "second"})]
    assert items[-1].status == RunStatus.completed


@pytest.mark.asyncio
async def test_codex_closed_transport_does_not_leak_a_callback_exception(monkeypatch):
    from agno.agents.codex._approval import human_client

    async def request(*args):
        return True

    client = human_client(None, SimpleNamespace(request=request))._client._sync
    errors = []

    def closed(payload):
        raise BrokenPipeError("closed")

    monkeypatch.setattr(client, "_write_message", closed)
    monkeypatch.setattr(client._router, "fail_all", errors.append)
    await client.decide(
        {
            "id": 1,
            "method": "item/commandExecution/requestApproval",
            "params": {"command": "echo test", "itemId": "tool"},
        }
    )
    assert len(errors) == 1
    assert isinstance(errors[0], BrokenPipeError)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.pending, RunStatus.completed, RunStatus.cancelled])
async def test_never_started_or_terminal_native_job_is_not_failed_on_reclaim(tmp_path, status):
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent = Harness(id="agent", db=SqliteDb(db_file=str(tmp_path / "pending.db")))
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        status=status,
        queue_attempt=1,
        metadata={"native_approval": {"owner": "old", "approval_ids": []}} if status != RunStatus.pending else None,
    )
    agent.db.upsert_session(AgentSession(session_id="session", agent_id="agent", runs=[run]))
    agent.db.upsert_run(run, session_id="session")
    worker = QueueWorker(
        store=InMemoryQueueStore(),
        resolve_component=lambda *_: agent,
        config=QueueConfig(durable=True),
        worker_id="successor",
    )
    assert not await worker._ahonor_non_retryable_row(
        agent, {"id": "run", "session_id": "session", "attempt": 2, "component_type": "agent", "component_id": "agent"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.completed, RunStatus.cancelled])
async def test_reclaimed_terminal_native_run_settles_ticket_without_execution(tmp_path, status):
    from agno.db.schemas.jobs import QueuedJob
    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import QueueWorker

    agent = Harness(id="agent", db=SqliteDb(db_file=str(tmp_path / "terminal.db")))
    run = RunOutput(
        run_id="run",
        session_id="session",
        agent_id="agent",
        status=status,
        queue_attempt=1,
        metadata={"native_approval": {"owner": "old", "approval_ids": []}},
    )
    agent.db.upsert_session(AgentSession(session_id="session", agent_id="agent", runs=[run]))
    agent.db.upsert_run(run, session_id="session")
    store = InMemoryQueueStore()
    await store.enqueue_job(
        QueuedJob(
            id="run",
            component_type="agent",
            component_id="agent",
            session_id="session",
            payload={"input": "work", "kwargs": {}},
            max_attempts=3,
        ).to_dict()
    )
    await store.claim_job("old")
    job = await store.claim_job("successor", lock_grace_seconds=0)
    assert job["attempt"] == 2
    worker = QueueWorker(
        store=store, resolve_component=lambda *_: agent, config=QueueConfig(durable=True), worker_id="successor"
    )
    await worker._execute_claimed_inner(job)
    assert (await store.get_job("run"))["status"] == status.value.lower()
    assert agent.calls == 0
    assert (await agent.aget_run_output("run", "session")).status == status


@pytest.mark.asyncio
async def test_delivered_decision_is_preserved_after_a_later_failure(tmp_path, monkeypatch):
    from agno.agents._approval import current_bridge, submit_decisions
    from tests.unit.agents.test_human_approval import pending

    agent = Harness(id="agent", db=SqliteDb(db_file=str(tmp_path / "audit.db")), approval_timeout=5)

    async def source(input, **kwargs):
        assert await current_bridge().request("Bash", {"command": "echo test"}, {})
        raise RuntimeError("failure after delivery")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "_arun_adapter_stream", source)
    task = asyncio.create_task(agent.arun("work", session_id="session", run_id="run"))
    try:
        run = await pending(agent)
        approval_id = run.requirements[0].tool_execution.approval_id
        agent.db.update_approval(approval_id, status="approved")
        await submit_decisions(agent, "run", "session", None)
        result = await asyncio.wait_for(task, 3)
        assert result.status == RunStatus.error
        assert agent.db.get_approval(approval_id)["status"] == "approved"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
