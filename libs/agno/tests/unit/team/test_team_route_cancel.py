"""Cancellation contract for route teams (respond_directly=True).

Regression tests for #10474: when a route-team run is cancelled while a member
is executing, the team must stop without a second leader-model call — the
member's response is the direct response, so there is nothing to synthesize.

These tests pin that contract across the cancellation mechanisms and timings a
caller can hit: the global registry cancel, the team cancel (which cascades to
in-flight member runs), and cancelling the run task itself, in both streaming
and non-streaming modes. A second leader-model call after cancellation is the
exact "team synthesizes a response after cancellation" symptom reported there.
"""

import asyncio
import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.cancel import cancel_run, get_cancellation_manager, set_cancellation_manager
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.team import Team

SYNTHESIS = "LEADER-SYNTHESIS"


@pytest.fixture(autouse=True)
def reset_cancellation_manager():
    original_manager = get_cancellation_manager()
    set_cancellation_manager(InMemoryRunCancellationManager())
    try:
        yield
    finally:
        set_cancellation_manager(original_manager)


class LeaderModel(Model):
    """Delegates once; a second call is the bug (leader-side synthesis)."""

    def __init__(self, member_id: str = "worker", task: str = "make the thing"):
        super().__init__(id="leader", name="leader", provider="test")
        self.member_id = member_id
        self.task = task
        self.calls = 0

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": self.member_id, "task": self.task}),
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content=SYNTHESIS, response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class MemberModel(Model):
    """Streams two chunks with a gap wide enough to land a cancel mid-run."""

    def __init__(self, started: asyncio.Event):
        super().__init__(id="member", name="member", provider="test")
        self.started = started

    def _chunk(self, content: str) -> ModelResponse:
        return ModelResponse(role="assistant", content=content, response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.started.set()
        return self._chunk("MEMBER-DIRECT-ANSWER")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.started.set()
        await asyncio.sleep(0.8)
        return self._chunk("MEMBER-DIRECT-ANSWER")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._chunk("part-1 ")
        yield self._chunk("MEMBER-DIRECT-ANSWER")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self.started.set()
        yield self._chunk("part-1 ")
        await asyncio.sleep(0.8)
        yield self._chunk("MEMBER-DIRECT-ANSWER")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _team(tmp_path, leader: LeaderModel, member_model: MemberModel) -> Team:
    member = Agent(name="worker", id="worker", model=member_model)
    return Team(
        name="t",
        id="t",
        members=[member],
        model=leader,
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
        respond_directly=True,
        determine_input_for_members=False,
    )


def _assert_no_synthesis(leader: LeaderModel, events: List[Any]) -> None:
    assert leader.calls == 1, f"leader called {leader.calls} times after cancellation"
    for event in events:
        content = getattr(event, "content", None)
        assert content != SYNTHESIS, "leader synthesized a response after cancellation"


_RUN_ID = "route-cancel-run"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_registry_cancel_during_member_run_stops_the_team(tmp_path, stream: bool):
    """cancel_run() while the member executes: no leader-side synthesis."""
    leader = LeaderModel()
    started = asyncio.Event()
    team = _team(tmp_path, leader, MemberModel(started))

    events: List[Any] = []

    async def consume():
        if stream:
            async for event in team.arun(input="go", stream=True, run_id=_RUN_ID):
                events.append(event)
        else:
            events.append(await team.arun(input="go", stream=False, run_id=_RUN_ID))

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 10)
    await asyncio.sleep(0.2)  # land the cancel mid-member-run
    cancel_run(_RUN_ID)
    await asyncio.wait_for(task, 20)

    _assert_no_synthesis(leader, events)


@pytest.mark.asyncio
async def test_team_cancel_with_cascade_stops_the_team(tmp_path):
    """The team-level cancel (used by AgentOS) also cancels in-flight member runs."""
    from agno.team import _run as team_run

    leader = LeaderModel()
    started = asyncio.Event()
    team = _team(tmp_path, leader, MemberModel(started))

    events: List[Any] = []

    async def consume():
        async for event in team.arun(input="go", stream=True, run_id=_RUN_ID):
            events.append(event)

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 10)
    await asyncio.sleep(0.2)
    team_run.cancel_run(_RUN_ID)
    await asyncio.wait_for(task, 20)

    _assert_no_synthesis(leader, events)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
async def test_cancelling_the_run_task_stops_the_team(tmp_path, stream: bool):
    """Cancelling the run task itself (client disconnect style) must not leave a
    window where the leader synthesizes from the partial member result."""
    leader = LeaderModel()
    started = asyncio.Event()
    team = _team(tmp_path, leader, MemberModel(started))

    events: List[Any] = []

    async def consume():
        if stream:
            async for event in team.arun(input="go", stream=True, run_id=_RUN_ID):
                events.append(event)
        else:
            events.append(await team.arun(input="go", stream=False, run_id=_RUN_ID))

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 10)
    await asyncio.sleep(0.2)  # land the cancel mid-member-run
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 20)

    _assert_no_synthesis(leader, events)
