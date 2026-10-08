import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agno.agents.sandbox import SandboxAgent
from agno.db.sqlite import SqliteDb
from agno.sandbox.base import ExecResult, SandboxHandle, SandboxProvider


@dataclass
class FakeProvider(SandboxProvider):
    name: str = "fake"
    handles: dict = field(default_factory=dict)
    destroyed: list = field(default_factory=list)

    async def acreate(self, spec):
        handle = SandboxHandle(spec.name, "http://runtime", "running")
        self.handles[spec.name] = handle
        return handle

    async def aget(self, ref):
        return self.handles.get(ref)

    async def adestroy(self, handle):
        self.destroyed.append(handle.provider_ref)
        self.handles.pop(handle.provider_ref, None)

    async def aexec(self, handle, cmd, timeout=60):
        return ExecResult(0, "", "")


@pytest.mark.asyncio
async def test_concurrent_resolution_creates_once_and_rejects_other_owner(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "registry.db"))
    provider = FakeProvider()
    a = SandboxAgent(id="coder", db=db, provider=provider, token_secret="x" * 32)
    b = SandboxAgent(
        id="coder", db=SqliteDb(db_file=str(tmp_path / "registry.db")), provider=provider, token_secret="x" * 32
    )
    creates = []

    async def create(self, row, worker):
        creates.append(row["sandbox_id"])
        await asyncio.sleep(0.05)
        handle = SandboxHandle(row["provider_ref"], "http://runtime", "running")
        provider.handles[handle.provider_ref] = handle
        assert await self._registry.replace(row, status="ready", url=handle.url)

    monkeypatch.setattr(SandboxAgent, "_create", create)
    await a._registry.list("coder")
    await b._registry.list("coder")
    worker = SimpleNamespace(config=SimpleNamespace(lock_grace_seconds=3))
    job = dict(id="run", session_id="s", user_id="owner", attempt=1)
    first, second = await asyncio.gather(a._resolve(job, worker), b._resolve(job, worker))
    assert first["sandbox_id"] == second["sandbox_id"]
    assert len(creates) == 1
    with pytest.raises(PermissionError):
        await b._resolve({**job, "user_id": "other"}, worker)
    # A newly claimed attempt destroys the prior environment before recreation.
    replacement = await b._resolve({**job, "attempt": 2}, worker)
    assert replacement["generation"] == 2
    assert provider.destroyed == [first["provider_ref"]]
    assert a._token(first) != a._token(replacement)
    db.db_engine.dispose()
    b.db.db_engine.dispose()


@pytest.mark.asyncio
async def test_idle_destroy_loses_to_run_reservation(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "registry.db"))
    provider = FakeProvider()
    agent = SandboxAgent(id="coder", db=db, provider=provider)
    sid = str(uuid4())
    assert db.upsert_sandbox(
        dict(
            sandbox_id=sid,
            session_id="s",
            agent_id="coder",
            user_id="owner",
            provider="fake",
            status="ready",
            generation=1,
            provider_ref="container",
            metadata={},
        )
    )
    row = db.get_sandbox(sandbox_id=sid)
    assert db.upsert_sandbox({**row, "active_run_id": "new-run", "active_attempt": 1}, row["revision"])
    with pytest.raises(ValueError):
        await agent.adestroy_sandbox(sid, expected_revision=row["revision"])
    assert not provider.destroyed
    assert not await agent.adestroy_sandbox(sid, user_id="other")
    db.db_engine.dispose()


def test_sync_run_delegates_to_submission_not_a_local_adapter(tmp_path, monkeypatch):
    from agno.run.agent import RunContentEvent, RunOutput

    agent = SandboxAgent(id="coder", provider=FakeProvider())
    calls = []

    async def submit(self, input, session_id, user_id, background, stream, kwargs):
        calls.append((input, session_id, user_id))
        return RunOutput(content="remote result")

    async def stream(self, input, session_id, user_id, background, kwargs):
        calls.append((input, session_id, user_id))
        yield RunContentEvent(content="remote stream")

    monkeypatch.setattr(SandboxAgent, "_submit", submit)
    monkeypatch.setattr(SandboxAgent, "_submit_stream", stream)
    assert agent.run("hello", session_id="s", user_id="owner").content == "remote result"
    assert list(agent.run("hello", stream=True, session_id="s", user_id="owner"))[0].content == "remote stream"
    assert calls == [("hello", "s", "owner")] * 2


@pytest.mark.asyncio
async def test_busy_session_wait_is_not_a_startup_timeout_and_can_be_cancelled(tmp_path, monkeypatch):
    import agno.agents.sandbox as module
    from agno.exceptions import RunCancelledException
    from agno.run.cancel import acancel_run, acleanup_run

    db = SqliteDb(db_file=str(tmp_path / "busy.db"))
    provider = FakeProvider()
    agent = SandboxAgent(id="coder", db=db, provider=provider, startup_timeout=1)
    job_id = str(uuid4())
    row = dict(
        sandbox_id=str(uuid4()),
        session_id="busy",
        agent_id="coder",
        user_id="owner",
        provider="fake",
        status="ready",
        generation=1,
        provider_ref="container",
        active_run_id="first-run",
        active_attempt=1,
        metadata={},
    )
    db.upsert_sandbox(row)
    provider.handles["container"] = SandboxHandle("container", "http://runtime", "running")
    elapsed = 0

    def advancing_clock():
        nonlocal elapsed
        elapsed += 0.3
        return elapsed

    monkeypatch.setattr(module, "monotonic", advancing_clock)
    task = asyncio.create_task(
        agent._resolve(
            dict(id=job_id, session_id="busy", user_id="owner", attempt=1),
            SimpleNamespace(config=SimpleNamespace(lock_grace_seconds=0)),
        )
    )
    await asyncio.sleep(0.8)
    assert elapsed > 1 and not task.done()
    await acancel_run(job_id)
    with pytest.raises(RunCancelledException):
        await asyncio.wait_for(task, 1)
    assert db.get_sandbox(session_id="busy")["active_run_id"] == "first-run"
    await acleanup_run(job_id)
    db.db_engine.dispose()


@pytest.mark.asyncio
async def test_startup_rejects_a_different_queue_database():
    from agno.db.postgres import PostgresDb
    from agno.job_queue import QueueConfig
    from agno.os.job_queue import _SyncStoreAdapter

    db = PostgresDb(db_url="postgresql+psycopg://localhost/not-connected")
    other = PostgresDb(db_url="postgresql+psycopg://localhost/another-not-connected")
    agent = SandboxAgent(id="coder", db=db, provider=FakeProvider())
    worker = SimpleNamespace(store=_SyncStoreAdapter(other), config=QueueConfig())
    with pytest.raises(ValueError, match="same database instance"):
        await agent._astart(worker)
    db.db_engine.dispose()
    other.db_engine.dispose()


@pytest.mark.asyncio
async def test_foreground_stream_preserves_runtime_warnings_and_expiry(monkeypatch):
    import json

    import agno.os.utils as utils
    from agno.run.agent import RunOutput

    agent = SandboxAgent(id="coder", provider=FakeProvider())
    frames = [
        {"event": "CustomEvent", "run_id": "r", "event_index": 2, "warning": {"code": "mirror_error"}},
        {"event": "stream_expired", "run_id": "r", "status": "RUNNING", "message": "Reconnect"},
    ]

    async def submit(*args, **kwargs):
        return RunOutput(run_id="r")

    async def tail(*args, **kwargs):
        for frame in frames:
            yield "data: " + json.dumps(frame) + "\n\n"

    monkeypatch.setattr(SandboxAgent, "_submit", submit)
    monkeypatch.setattr(utils, "queued_run_tail_streamer", tail)
    result = [event.to_dict() async for event in agent.arun("hi", stream=True)]
    assert result == frames
