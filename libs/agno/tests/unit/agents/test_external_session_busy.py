"""One turn per session for external agents: a second turn is refused with SessionBusyError."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, List

import pytest

from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import SqliteDb
from agno.exceptions import SessionBusyError
from agno.run.agent import RunContentEvent, RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


@dataclass
class SlowAgent(BaseExternalAgent):
    """Waits on a gate inside the adapter so a turn can be held in flight."""

    gate: Any = field(default=None, repr=False)
    calls: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.gate = asyncio.Event()

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        self.calls.append(kwargs["session_id"])
        await self.gate.wait()
        return "done"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        yield RunContentEvent(run_id=kwargs["run_id"], content=await self._arun_adapter(input, **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_second_turn_on_a_busy_session_is_refused_before_the_adapter(stream):
    agent = SlowAgent(id="slow")

    async def turn(session_id: str):
        if stream:
            return [e async for e in agent._arun_stream("go", session_id=session_id)]
        return await agent._arun_non_stream("go", session_id=session_id)

    first = asyncio.create_task(turn("s"))
    while not agent.calls:
        await asyncio.sleep(0.01)
    with pytest.raises(SessionBusyError) as info:
        await turn("s")
    assert info.value.status_code == 409 and info.value.type == "session_busy"
    assert "already has run" in str(info.value)
    assert agent.calls == ["s"], "the refused turn never reached the adapter"

    agent.gate.set()
    await first
    assert await turn("other") is not None
    assert agent.calls == ["s", "other"]
    agent.gate.clear()
    agent.gate.set()
    await turn("s")
    assert agent.calls == ["s", "other", "s"], "the session is free again once the turn finished"


@pytest.mark.asyncio
async def test_a_failed_turn_releases_the_session():
    @dataclass
    class Failing(BaseExternalAgent):
        async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
            raise RuntimeError("boom")

    agent = Failing(id="failing")
    out = await agent._arun_non_stream("go", session_id="s")
    assert out.status == RunStatus.error
    assert agent._sessions_in_flight == {}


@pytest.mark.asyncio
async def test_unfinished_run_row_from_another_replica_blocks_the_session(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = SlowAgent(id="slow", db=db)
    agent.gate.set()
    db.upsert_session(AgentSession(session_id="s", agent_id="slow"))
    db.upsert_run(
        run=RunOutput(run_id="r-other", session_id="s", agent_id="slow", status=RunStatus.pending), session_id="s"
    )

    with pytest.raises(SessionBusyError) as info:
        await agent._arun_non_stream("go", session_id="s")
    assert info.value.run_id == "r-other"
    with pytest.raises(SessionBusyError):
        await agent.arun("go", session_id="s", background=True)
    assert agent.calls == [] and len(db.get_session("s", session_type="agent").runs) == 1, "no pending row written"

    db.upsert_run(
        run=RunOutput(run_id="r-other", session_id="s", agent_id="slow", status=RunStatus.cancelled), session_id="s"
    )
    out = await agent._arun_non_stream("go", session_id="s")
    assert out.status == RunStatus.completed, "cancelling the stuck run frees the session"


def test_agentos_answers_409_and_a_typed_run_error_event(tmp_path):
    import json

    from fastapi.testclient import TestClient

    from agno.os import AgentOS

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = SlowAgent(id="slow", db=db)
    agent.gate.set()
    db.upsert_session(AgentSession(session_id="s", agent_id="slow"))
    db.upsert_run(
        run=RunOutput(run_id="r-other", session_id="s", agent_id="slow", status=RunStatus.running), session_id="s"
    )
    client = TestClient(AgentOS(agents=[agent], db=db).get_app(), raise_server_exceptions=False)

    resp = client.post("/agents/slow/runs", data={"message": "go", "session_id": "s", "stream": "false"})
    assert resp.status_code == 409, resp.text
    assert "r-other" in resp.json()["detail"]

    resp = client.post(
        "/agents/slow/runs", data={"message": "go", "session_id": "s", "stream": "false", "background": "true"}
    )
    assert resp.status_code == 409, resp.text

    resp = client.post("/agents/slow/runs", data={"message": "go", "session_id": "s", "stream": "true"})
    assert resp.status_code == 200
    events = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert [e["event"] for e in events] == ["RunError"]
    assert events[0]["error_type"] == "session_busy" and "r-other" in events[0]["content"]
    assert agent.calls == []


@pytest.mark.asyncio
async def test_queued_turns_on_one_session_run_in_acceptance_order(tmp_path):
    agent = SlowAgent(id="slow", db=SqliteDb(db_file=str(tmp_path / "runs.db")))
    agent.gate.set()
    await agent._aprepare_pending_run("first", "s", None, "one")
    await agent._aprepare_pending_run("second", "s", None, "two")

    with pytest.raises(SessionBusyError) as info:
        await agent.arun("two", run_id="second", session_id="s")
    assert info.value.run_id == "first", "a turn waits for the pending turn accepted before it"

    assert (await agent.arun("one", run_id="first", session_id="s")).status == RunStatus.completed
    assert (await agent.arun("two", run_id="second", session_id="s")).status == RunStatus.completed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RunStatus.pending, RunStatus.running])
@pytest.mark.parametrize("sync_cancel", [False, True])
async def test_cancelling_an_unowned_run_row_frees_its_session(tmp_path, status, sync_cancel):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = SlowAgent(id="slow", db=db)
    agent.gate.set()
    db.upsert_session(AgentSession(session_id="s", agent_id="slow"))
    db.upsert_run(run=RunOutput(run_id="crashed", session_id="s", agent_id="slow", status=status), session_id="s")
    with pytest.raises(SessionBusyError):
        await agent._arun_non_stream("go", session_id="s")

    if sync_cancel:
        agent.cancel_run("crashed")
    else:
        await agent.acancel_run("crashed")

    row = agent.get_run_output("crashed", "s")
    assert row.status == RunStatus.cancelled and row.content == "Run cancelled"
    assert (await agent._arun_non_stream("go", session_id="s")).status == RunStatus.completed


@pytest.mark.asyncio
async def test_cancelling_a_row_still_registered_by_a_dead_process_frees_its_session(tmp_path):
    """A shared cancellation manager keeps a crashed process's registration until its TTL, so
    'registered' does not mean live. With no handle in this process the row is still cancelled."""
    from agno.run.cancel import aregister_run

    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = SlowAgent(id="slow", db=db)
    agent.gate.set()
    db.upsert_session(AgentSession(session_id="s", agent_id="slow"))
    db.upsert_run(
        run=RunOutput(run_id="crashed", session_id="s", agent_id="slow", status=RunStatus.running), session_id="s"
    )
    await aregister_run("crashed")  # the dead process's registration outlives it

    assert await agent.acancel_run("crashed") is True, "the manager still reports it registered"
    assert agent.get_run_output("crashed", "s").status == RunStatus.cancelled
    assert (await agent._arun_non_stream("go", session_id="s")).status == RunStatus.completed


@pytest.mark.asyncio
async def test_cancel_leaves_finished_and_other_agents_rows_alone(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    agent = SlowAgent(id="slow", db=db)
    db.upsert_session(AgentSession(session_id="s", agent_id="slow"))
    db.upsert_run(
        run=RunOutput(run_id="done", session_id="s", agent_id="slow", status=RunStatus.completed, content="ok"),
        session_id="s",
    )
    db.upsert_session(AgentSession(session_id="t", agent_id="other"))
    db.upsert_run(
        run=RunOutput(run_id="theirs", session_id="t", agent_id="other", status=RunStatus.running), session_id="t"
    )

    await agent.acancel_run("done")
    await agent.acancel_run("theirs")
    assert db.get_run("done").status == RunStatus.completed
    assert db.get_run("theirs").status == RunStatus.running


@pytest.mark.asyncio
async def test_rewriting_a_queued_runs_row_goes_through_the_attempt_fence(monkeypatch):
    from unittest.mock import MagicMock

    from agno.run import status_persist
    from agno.run.concurrency import worker_managed_execution

    db = MagicMock(spec=SqliteDb)
    agent = SlowAgent(id="slow", db=db)
    session = AgentSession(session_id="s", agent_id="slow")
    run = RunOutput(run_id="r", session_id="s", agent_id="slow", status=RunStatus.completed)
    fenced: List[str] = []

    async def refuse(db: Any, run: Any, *args: Any, **kwargs: Any) -> bool:
        fenced.append(run.run_id)
        return True  # a newer attempt owns the row: the save was handled by being dropped

    monkeypatch.setattr(status_persist, "apersist_worker_owned_run", refuse)
    with worker_managed_execution("r", "worker-1", attempt=1):
        await agent._arewrite_run_row(session, run)
    assert fenced == ["r"]
    db.upsert_run.assert_not_called()
