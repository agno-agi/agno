"""Run-level retries on external framework adapters."""

import asyncio
from dataclasses import dataclass, field
from typing import Any, List

import pytest

from agno.agents.base import BaseExternalAgent
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
