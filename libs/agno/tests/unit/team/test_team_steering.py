"""Steering a team run: input sent while the leader works reaches the leader's next model request."""

import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.run.steering import STEERING_MESSAGE_TEMPLATE
from agno.run.team import RunSteeredEvent as TeamRunSteeredEvent
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.tools import tool

MODES = ["sync", "async", "stream", "astream"]


class _ScriptedModel(Model):
    """Plays ("tools", [(name, args), ...]) and ("answer", text[, steer_text]) turns; records requests."""

    def __init__(self, script: List[Tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.requests: List[List[Message]] = []
        self._calls = 0

    def _next(self, kwargs: Dict[str, Any]) -> ModelResponse:
        self.requests.append(list(kwargs["messages"]))
        turn = self.script.pop(0)
        if turn[0] == "tools":
            response = ModelResponse(role="assistant")
            for name, args in turn[1]:
                self._calls += 1
                response.tool_calls.append(
                    {
                        "id": f"call_{self._calls}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                )
        else:
            if len(turn) == 3:
                assert Team.steer(kwargs["run_response"].run_id, turn[2]) is True
            response = ModelResponse(role="assistant", content=turn[1])
        response.response_usage = MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2)
        return response

    def invoke(self, *args, **kwargs):
        return self._next(kwargs)

    async def ainvoke(self, *args, **kwargs):
        return self._next(kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self._next(kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._next(kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _team(model: _ScriptedModel, tools: Optional[list] = None) -> Team:
    member = Agent(name="Researcher", model=_ScriptedModel([]), telemetry=False)
    return Team(
        name="Desk",
        model=model,
        members=[member],
        tools=tools or [],
        db=InMemoryDb(),
        telemetry=False,
    )


async def _run(team: Team, mode: str, message: str = "Brief me on France."):
    events: List[Any] = []
    if mode == "sync":
        return team.run(message), events
    if mode == "async":
        return await team.arun(message), events
    output: Optional[TeamRunOutput] = None
    stream = team.run(message, stream=True, stream_events=True, yield_run_output=True)
    if mode == "stream":
        for event in stream:  # type: ignore[union-attr]
            if isinstance(event, TeamRunOutput):
                output = event
            else:
                events.append(event)
    else:
        async for event in team.arun(message, stream=True, stream_events=True, yield_run_output=True):  # type: ignore[union-attr]
            if isinstance(event, TeamRunOutput):
                output = event
            else:
                events.append(event)
    assert output is not None
    return output, events


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_steer_during_a_leader_tool_call_reaches_the_leaders_next_request(mode):
    @tool
    def lookup_capital(run_context: RunContext) -> str:
        """Look up the capital."""
        assert Team.steer(run_context.run_id, "Keep it to one line.") is True
        return "Paris"

    model = _ScriptedModel([("tools", [("lookup_capital", {})]), ("answer", "France: capital Paris.")])
    output, events = await _run(_team(model, [lookup_capital]), mode)

    assert output.status == RunStatus.completed
    assert model.requests[1][-1].role == "user"
    framed = STEERING_MESSAGE_TEMPLATE.format(input="Keep it to one line.")
    assert model.requests[1][-1].content == framed
    if mode in ("stream", "astream"):
        assert [e.content for e in events if isinstance(e, TeamRunSteeredEvent)] == [framed]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_steer_during_the_leaders_final_answer_is_answered_and_then_refused(mode):
    model = _ScriptedModel(
        [
            ("answer", "France: capital Paris.", "And Spain?"),
            ("answer", "Spain: capital Madrid."),
        ]
    )
    output, _ = await _run(_team(model), mode)

    assert len(model.requests) == 2
    assert "Madrid" in (output.content or "")
    assert Team.steer(output.run_id, "late") is False  # type: ignore[arg-type]
