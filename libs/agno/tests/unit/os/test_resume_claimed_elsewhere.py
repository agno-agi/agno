"""A replica-local event stream only carries the runs this replica executes.

The replica that accepts a durable-queue streaming submission registers the run PENDING in
its own stream. When another replica's worker claims the job, that entry never advances, so a
live tail of it would heartbeat forever. /resume must answer from the run row instead, and a
tail that is already open must end once another replica claims the job.
"""

import asyncio
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest

from agno.db.schemas.jobs import QueuedJob
from agno.job_queue.store import InMemoryQueueStore
from agno.run.agent import RunContentEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput

OUTPUTS = {"agents": RunOutput, "teams": TeamRunOutput, "workflows": WorkflowRunOutput}


@pytest.fixture()
def replica(monkeypatch):
    import agno.os.event_streams as streams
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.job_queue import set_active_queue_worker
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    stream = InMemoryEventStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(streams, "_event_stream", stream)
    monkeypatch.setattr("agno.os.event_streams.in_memory._TAIL_IDLE_RECHECK_SECONDS", 0.05)
    monkeypatch.setattr("agno.os.utils._TAIL_CLAIM_RECHECK_SECONDS", 0.05, raising=False)
    store = InMemoryQueueStore()
    set_active_queue_worker(SimpleNamespace(store=store, worker_id="worker-here"))
    yield SimpleNamespace(stream=stream, store=store)
    set_active_queue_worker(None)


def seed_ticket(store, run_id, status, locked_by=None):
    store._jobs[run_id] = QueuedJob(
        id=run_id,
        component_type="agent",
        component_id="qa-agent",
        session_id="s1",
        payload={"input": "hi", "stream": True},
        status=status,
        attempt=0 if status == "queued" else 1,
        locked_by=locked_by,
    ).to_dict()


def claim(store, run_id, worker_id):
    store._jobs[run_id].update(status="running", locked_by=worker_id, attempt=1)


class StoredRun:
    """A component whose database holds ``run``."""

    def __init__(self, run):
        self.run = run

    async def aget_run_output(self, run_id, session_id, user_id=None):
        return self.run


def resume(kind, component, last_event_index=None):
    module = importlib.import_module(f"agno.os.routers.{kind}.router")
    return module._resume_stream_generator(component, "r1", last_event_index, "s1")


async def collect(frames, timeout=5):
    async def drain():
        return [frame async for frame in frames]

    return await asyncio.wait_for(drain(), timeout)


def payloads(frames):
    return [json.loads(frame.split("data: ", 1)[1]) for frame in frames if "data: " in frame]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agents", "teams", "workflows"])
async def test_resume_answers_from_the_row_while_another_replica_runs_the_job(replica, kind):
    await replica.stream.register_run("r1", RunStatus.pending)
    seed_ticket(replica.store, "r1", "running", locked_by="worker-there")
    run = OUTPUTS[kind](run_id="r1", session_id="s1", status=RunStatus.running)
    (meta,) = payloads(await collect(resume(kind, StoredRun(run))))
    assert meta["event"] == "replay" and meta["status"] == "RUNNING"
    assert "another replica" in meta["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agents", "teams", "workflows"])
async def test_resume_replays_stored_events_once_another_replica_finished_the_job(replica, kind):
    await replica.stream.register_run("r1", RunStatus.pending)
    seed_ticket(replica.store, "r1", "completed")
    events = []
    for index in range(3):
        event = RunContentEvent(content=f"c{index}", run_id="r1")
        event.event_index = index
        events.append(event)
    run = OUTPUTS[kind](run_id="r1", session_id="s1", status=RunStatus.completed, events=events)
    meta, *replayed = payloads(await collect(resume(kind, StoredRun(run), last_event_index=0)))
    assert meta["event"] == "replay" and meta["status"] == "COMPLETED"
    assert [event["event_index"] for event in replayed] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agents", "teams", "workflows"])
async def test_an_open_resume_tail_ends_when_another_replica_claims_the_job(replica, kind):
    await replica.stream.register_run("r1", RunStatus.pending)
    seed_ticket(replica.store, "r1", "queued")
    frames = []

    async def consume():
        async for frame in resume(kind, StoredRun(None)):
            frames.append(frame)
            if frame.startswith("event: subscribed"):
                claim(replica.store, "r1", "worker-there")

    await asyncio.wait_for(consume(), 5)
    assert frames[0].startswith("event: subscribed")
    assert frames[-1].startswith("event: stream_expired")
    assert payloads(frames[-1:])[0]["status"] == "RUNNING"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agents", "teams", "workflows"])
async def test_resume_tails_a_job_this_replica_runs(replica, kind):
    await replica.stream.register_run("r1", RunStatus.running)
    seed_ticket(replica.store, "r1", "running", locked_by="worker-here")
    frames = []

    async def consume():
        async for frame in resume(kind, StoredRun(None)):
            frames.append(frame)
            if frame.startswith("event: subscribed"):
                await replica.stream.add_event("r1", RunContentEvent(content="live", run_id="r1"))
                await replica.stream.complete_run("r1", RunStatus.completed)

    await asyncio.wait_for(consume(), 5)
    assert any('"content":"live"' in frame for frame in frames)
    assert not any(frame.startswith("event: stream_expired") for frame in frames)


@pytest.mark.asyncio
async def test_a_shared_stream_tails_a_job_another_replica_runs(replica, monkeypatch):
    import agno.os.event_streams as streams
    from agno.os.event_streams.in_memory import InMemoryEventStream
    from agno.os.managers import EventsBuffer, SSESubscriberManager

    class SharedStream(InMemoryEventStream):
        shared = True

    stream = SharedStream(events_buffer=EventsBuffer(), subscriber_manager=SSESubscriberManager())
    monkeypatch.setattr(streams, "_event_stream", stream)
    await stream.register_run("r1", RunStatus.running)
    seed_ticket(replica.store, "r1", "running", locked_by="worker-there")
    frames = []

    async def consume():
        async for frame in resume("agents", StoredRun(None)):
            frames.append(frame)
            if frame.startswith("event: subscribed"):
                await stream.add_event("r1", RunContentEvent(content="live", run_id="r1"))
                await stream.complete_run("r1", RunStatus.completed)

    await asyncio.wait_for(consume(), 5)
    assert any('"content":"live"' in frame for frame in frames)


@pytest.mark.asyncio
async def test_the_submitters_own_stream_ends_as_soon_as_another_replica_claims_the_job(replica):
    from agno.os.utils import queued_run_tail_streamer

    await replica.stream.register_run("r1", RunStatus.pending)
    seed_ticket(replica.store, "r1", "running", locked_by="worker-there")
    frames = await collect(queued_run_tail_streamer("r1"), timeout=3)
    assert frames[-1].startswith("event: stream_expired")
    meta = payloads(frames[-1:])[0]
    assert meta["status"] == "RUNNING" and "another replica" in meta["message"]


def test_only_the_redis_stream_is_shared():
    from agno.os.event_streams import InMemoryEventStream, RedisEventStream

    assert InMemoryEventStream().shared is False
    fakeredis = pytest.importorskip("fakeredis")
    assert RedisEventStream(fakeredis.FakeAsyncRedis()).shared is True


@pytest.mark.asyncio
async def test_resume_over_http_on_the_submitting_replica_returns_the_row(replica, tmp_path):
    """A plain (non-sandbox) agent's queued streaming run, through the real endpoint."""
    import time

    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS
    from agno.session import AgentSession

    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    db.upsert_session(AgentSession(session_id="s1", agent_id="qa-agent", created_at=int(time.time())))
    db.upsert_run(
        run=RunOutput(run_id="r1", session_id="s1", agent_id="qa-agent", status=RunStatus.running), session_id="s1"
    )
    await replica.stream.register_run("r1", RunStatus.pending)
    seed_ticket(replica.store, "r1", "running", locked_by="worker-there")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await asyncio.wait_for(
            client.post("/agents/qa-agent/runs/r1/resume", data={"session_id": "s1"}), timeout=5
        )
    assert response.status_code == 200
    (meta,) = payloads(response.text.split("\n\n"))
    assert meta["event"] == "replay" and meta["status"] == "RUNNING"
