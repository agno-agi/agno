"""External agents refuse sessions owned by another user and share sessions without an owner."""

from dataclasses import dataclass
from typing import Any

import pytest

from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.run.agent import RunContentEvent


@dataclass
class EchoAgent(BaseExternalAgent):
    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        return f"echo {input}"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any):
        yield RunContentEvent(run_id=kwargs["run_id"], content=f"echo {input}")


@pytest.fixture(params=[False, True], ids=["sqlite", "async-sqlite"])
def agent(request, tmp_path):
    cls = AsyncSqliteDb if request.param else SqliteDb
    return EchoAgent(id="echo", db=cls(db_file=str(tmp_path / "runs.db")))


async def _run_count(agent: EchoAgent, session_id: str) -> int:
    session = await agent.aget_session(session_id)
    return len(session.runs or []) if session else 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["run", "stream", "background"])
async def test_run_into_another_users_session_is_refused(agent, mode):
    await agent.arun("mine", session_id="s", user_id="alice")
    with pytest.raises(ValueError, match="belongs to another user"):
        if mode == "stream":
            [event async for event in agent.arun("intrude", session_id="s", user_id="bob", stream=True)]
        else:
            await agent.arun("intrude", session_id="s", user_id="bob", background=mode == "background")
    session = await agent.aget_session("s")
    assert session.user_id == "alice"
    assert await _run_count(agent, "s") == 1


@pytest.mark.asyncio
async def test_background_prepare_checks_owner_before_atomic_append(agent, monkeypatch):
    calls = []

    async def atomic_append(*args, **kwargs):
        calls.append(args)
        return True

    await agent.arun("mine", session_id="s", user_id="alice")
    monkeypatch.setattr("agno.os.job_queue._atomic_append_run", atomic_append)
    with pytest.raises(ValueError, match="belongs to another user"):
        await agent._aprepare_pending_run("r", "s", "bob", "intrude")
    assert calls == []


@pytest.mark.asyncio
async def test_reads_hide_another_users_session(agent):
    run = await agent.arun("mine", session_id="s", user_id="alice")
    assert await agent.aget_session("s", user_id="bob") is None
    assert await agent.aget_run_output(run.run_id, "s", user_id="bob") is None
    assert (await agent.aget_run_output(run.run_id, "s", user_id="alice")).content == "echo mine"


@pytest.mark.asyncio
async def test_unowned_session_is_shared_across_users(agent):
    await agent.arun("opened", session_id="team")
    alice = await agent.arun("from alice", session_id="team", user_id="alice")
    bob = await agent.arun("from bob", session_id="team", user_id="bob")
    session = await agent.aget_session("team")
    assert session.user_id is None
    assert [run.user_id for run in session.runs] == [None, "alice", "bob"]
    assert (await agent.aget_run_output(alice.run_id, "team", user_id="bob")).content == "echo from alice"
    assert (await agent.aget_run_output(bob.run_id, "team", user_id="alice")).content == "echo from bob"


@pytest.mark.asyncio
async def test_caller_without_user_id_is_not_restricted(agent):
    await agent.arun("mine", session_id="s", user_id="alice")
    assert (await agent.aread_or_create_session("s")).user_id == "alice"
    assert (await agent.aget_session("s")).user_id == "alice"
