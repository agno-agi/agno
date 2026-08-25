"""External agent adapters must persist runs to the runs table (v3 storage).

upsert_session writes only the session row after denormalization; runs live
in their own table. Appending to session.runs and calling upsert_session
alone silently loses all history.
"""

import asyncio
import tempfile
from dataclasses import dataclass
from typing import Any, AsyncIterator

import pytest

from agno.agents.base import BaseExternalAgent
from agno.db.sqlite import SqliteDb
from agno.run.agent import RunContentEvent, RunOutputEvent


@dataclass
class EchoAgent(BaseExternalAgent):
    framework: str = "test-framework"
    last_history: Any = None

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        self.last_history = kwargs.get("history")
        return f"echo: {input}"

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        self.last_history = kwargs.get("history")
        yield RunContentEvent(run_id=kwargs.get("run_id", ""), content=f"echo: {input}")


@pytest.fixture
def agent():
    tmp = tempfile.mkdtemp()
    db = SqliteDb(db_file=f"{tmp}/ext.db")
    return EchoAgent(name="Echo", id="echo-agent", db=db)


def test_run_persisted_to_runs_table(agent):
    out = asyncio.run(agent._arun_non_stream("hello", session_id="s1", user_id="u1"))
    runs = agent.db.get_runs(session_id="s1")
    assert len(runs) == 1
    assert runs[0].run_id == out.run_id


def test_history_flows_across_turns(agent):
    asyncio.run(agent._arun_non_stream("hello", session_id="s1", user_id="u1"))
    asyncio.run(agent._arun_non_stream("again", session_id="s1", user_id="u1"))
    assert agent.last_history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "echo: hello"},
    ]


def test_streaming_run_persisted(agent):
    async def consume():
        async for _ in agent._arun_stream("hello", session_id="s1", user_id="u1"):
            pass

    asyncio.run(consume())
    assert len(agent.db.get_runs(session_id="s1")) == 1


def test_session_read_returns_runs(agent):
    out = asyncio.run(agent._arun_non_stream("hello", session_id="s1", user_id="u1"))
    session = agent.db.get_session(session_id="s1", session_type=None)
    assert len(session.runs or []) == 1
    # AgentOS run inspection path
    assert agent.get_run_output(out.run_id, session_id="s1") is not None


def test_get_run_output_returns_an_isolated_copy(agent):
    out = asyncio.run(agent._arun_non_stream("hello", session_id="s1", user_id="u1"))
    fetched = agent.get_run_output(out.run_id, session_id="s1")
    assert fetched is not None

    fetched.content = "mutated by caller"

    retrieved = agent.db.get_session(session_id="s1", session_type=None)
    assert retrieved.runs[0].content == "echo: hello"


def test_run_indexes_are_sequential(agent):
    for text in ("one", "two", "three"):
        asyncio.run(agent._arun_non_stream(text, session_id="s1", user_id="u1"))
    rows, _ = agent.db.get_runs(session_id="s1", deserialize=False)
    assert sorted(r["run_index"] for r in rows) == [0, 1, 2]
