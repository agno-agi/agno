"""Member-HITL continuation contract for route teams (respond_directly=True).

When a member agent's own tool pauses for confirmation (human-in-the-loop),
the team run pauses with it. Once that confirmation is resolved through
continue_run — accepted or rejected — the member's response is still the direct
response: the leader must not be called again to synthesize. Regression tests
for the follow-up of #10474, reported with a member tool requiring confirmation
where the team synthesized a leader response afterwards.

Pinned across all four continuation paths (sync/async × streaming/non-streaming),
since the delegate tool's stop_after_tool_call contract holds on each of them.
"""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools import tool

SYNTHESIS = "LEADER-SYNTHESIS"
MEMBER_ANSWER = "MEMBER-DIRECT-ANSWER"


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
    """First call issues the confirmable tool; second call is the member's final answer."""

    def __init__(self):
        super().__init__(id="member", name="member", provider="test")
        self.calls = 0

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-m-1",
                        "type": "function",
                        "function": {"name": "risky_action", "arguments": json.dumps({"action": "delete"})},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content=MEMBER_ANSWER, response_usage=MessageMetrics())

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


@tool(requires_confirmation=True)
def risky_action(action: str) -> str:
    return f"performed {action}"


def _team(tmp_path, leader: LeaderModel, member_model: MemberModel) -> Team:
    member = Agent(name="worker", id="worker", model=member_model, tools=[risky_action])
    return Team(
        name="t",
        id="t",
        members=[member],
        model=leader,
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
        respond_directly=True,
        determine_input_for_members=False,
    )


def _assert_paused(run: Any) -> None:
    assert run.status == RunStatus.paused, f"expected a paused run, got {run.status}"
    assert run.requirements, "expected the member pause to propagate to the team run"


async def _run_to_pause_async(tmp_path, leader: LeaderModel, member_model: MemberModel):
    team = _team(tmp_path, leader, member_model)
    run = await team.arun(input="go", stream=False, run_id="route-hitl-run")
    _assert_paused(run)
    return team, run


def _run_to_pause_sync(tmp_path, leader: LeaderModel, member_model: MemberModel):
    team = _team(tmp_path, leader, member_model)
    run = team.run(input="go", stream=False, run_id="route-hitl-run")
    _assert_paused(run)
    return team, run


def _resolve(requirement: Any, resolve: str) -> None:
    if resolve == "reject":
        requirement.reject()
    else:
        requirement.confirm()


def _assert_no_synthesis(leader: LeaderModel, outputs: List[Any]) -> None:
    assert leader.calls == 1, f"leader called {leader.calls} times after member-HITL resolution"
    for output in outputs:
        content = getattr(output, "content", None)
        assert content != SYNTHESIS, "leader synthesized a response after member-HITL resolution"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("resolve", ["reject", "confirm"])
async def test_async_continue_returns_member_response_directly(tmp_path, resolve: str, stream: bool):
    """Async continuation: the member's response is final, no leader synthesis."""
    leader = LeaderModel()
    team, run = await _run_to_pause_async(tmp_path, leader, MemberModel())

    requirement = run.requirements[0]
    _resolve(requirement, resolve)

    if stream:
        events: List[Any] = []
        async for event in team.acontinue_run(
            run_response=run, requirements=[requirement], stream=True, yield_run_output=True
        ):
            events.append(event)
        final = next((e for e in reversed(events) if isinstance(e, TeamRunOutput)), None)
        _assert_no_synthesis(leader, events)
    else:
        final = await team.acontinue_run(run_response=run, requirements=[requirement])
        _assert_no_synthesis(leader, [final])

    assert final is not None, "continuation did not produce a final run output"
    assert final.status == RunStatus.completed
    assert final.content == MEMBER_ANSWER


@pytest.mark.parametrize("stream", [True, False])
@pytest.mark.parametrize("resolve", ["reject", "confirm"])
def test_sync_continue_returns_member_response_directly(tmp_path, resolve: str, stream: bool):
    """Sync continuation: the member's response is final, no leader synthesis."""
    leader = LeaderModel()
    team, run = _run_to_pause_sync(tmp_path, leader, MemberModel())

    requirement = run.requirements[0]
    _resolve(requirement, resolve)

    if stream:
        events: List[Any] = []
        for event in team.continue_run(
            run_response=run, requirements=[requirement], stream=True, yield_run_output=True
        ):
            events.append(event)
        final = next((e for e in reversed(events) if isinstance(e, TeamRunOutput)), None)
        _assert_no_synthesis(leader, events)
    else:
        final = team.continue_run(run_response=run, requirements=[requirement])
        _assert_no_synthesis(leader, [final])

    assert final is not None, "continuation did not produce a final run output"
    assert final.status == RunStatus.completed
    assert final.content == MEMBER_ANSWER
