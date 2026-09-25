"""Steering an agent run: input sent while the run executes reaches its model before the next request.

Runs are offline: a scripted model plays fixed turns and records the messages every request
saw. The user's mid-run message is simulated by a tool, or by the model while it "generates" an
answer, calling Agent.steer() on the running run, which is exactly the window a real client hits.
"""

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
from agno.run.agent import RunOutput, RunSteeredEvent
from agno.run.base import RunStatus
from agno.run.steering import STEERING_MESSAGE_TEMPLATE, steering_message
from agno.tools import tool

MODES = ["sync", "async", "stream", "astream"]


class _ScriptedModel(Model):
    """Plays ("tools", [(name, args), ...]) and ("answer", text[, steer_text]) turns and records
    every request. An answer with a steer_text steers the run while that answer is produced.
    """

    def __init__(self, script: List[Tuple]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.requests: List[List[Message]] = []
        self.steer_results: List[bool] = []
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
                self.steer_results.append(Agent.steer(kwargs["run_response"].run_id, turn[2]))
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


async def _run(agent: Agent, mode: str, message: str = "What is the capital of France?"):
    """Run the agent in the given mode; return the final RunOutput and any events."""
    events: List[Any] = []
    if mode == "sync":
        return agent.run(message), events
    if mode == "async":
        return await agent.arun(message), events
    output: Optional[RunOutput] = None
    if mode == "stream":
        for event in agent.run(message, stream=True, stream_events=True, yield_run_output=True):
            (events.append(event) if not isinstance(event, RunOutput) else None)
            output = event if isinstance(event, RunOutput) else output
    else:
        async for event in agent.arun(message, stream=True, stream_events=True, yield_run_output=True):
            (events.append(event) if not isinstance(event, RunOutput) else None)
            output = event if isinstance(event, RunOutput) else output
    assert output is not None
    return output, events


def _user_texts(messages: List[Message]) -> List[str]:
    return [m.content for m in messages if m.role == "user"]  # type: ignore[misc]


def _framed(text: str) -> str:
    """What steered text reads like to the model."""
    return STEERING_MESSAGE_TEMPLATE.format(input=text)


def _agent(model: _ScriptedModel, tools: Optional[list] = None, db: Optional[InMemoryDb] = None) -> Agent:
    return Agent(model=model, tools=tools or [], db=db or InMemoryDb(), telemetry=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_steer_during_a_tool_call_reaches_the_next_request(mode):
    @tool
    def lookup_capital(country: str, run_context: RunContext) -> str:
        """Look up a country's capital."""
        assert Agent.steer(run_context.run_id, "Also tell me its population.") is True
        return "Paris"

    model = _ScriptedModel(
        [
            ("tools", [("lookup_capital", {"country": "France"})]),
            ("answer", "Paris, about 2.1M people."),
        ]
    )
    output, events = await _run(_agent(model, [lookup_capital]), mode)

    assert output.status == RunStatus.completed
    # The second request saw the tool result and then the steered message
    second = model.requests[1]
    assert second[-2].role == "tool"
    assert second[-1].role == "user" and second[-1].content == _framed("Also tell me its population.")
    # The steered message is part of the run's transcript
    assert _user_texts(output.messages or [])[-1] == _framed("Also tell me its population.")
    if mode in ("stream", "astream"):
        steered = [e for e in events if isinstance(e, RunSteeredEvent)]
        assert [e.content for e in steered] == [_framed("Also tell me its population.")]
        assert steered[0].message_id == second[-1].id


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_steer_during_the_final_answer_makes_the_model_answer_it(mode):
    model = _ScriptedModel(
        [
            (
                "answer",
                "The capital of France is Paris.",
                "Actually, what about Spain?",
            ),
            ("answer", "The capital of Spain is Madrid."),
        ]
    )
    output, _ = await _run(_agent(model), mode)

    assert model.steer_results == [True]
    assert len(model.requests) == 2
    assert model.requests[1][-1].content == _framed("Actually, what about Spain?")
    assert "Madrid" in (output.content or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_a_finished_run_refuses_steering(mode):
    model = _ScriptedModel([("answer", "Paris.")])
    output, _ = await _run(_agent(model), mode)

    assert output.status == RunStatus.completed
    assert Agent.steer(output.run_id, "one more thing") is False  # type: ignore[arg-type]
    assert await Agent.asteer(output.run_id, "one more thing") is False  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_steering_overrides_stop_after_tool_call(mode):
    @tool(stop_after_tool_call=True)
    def send_report(run_context: RunContext) -> str:
        """Send the report and end the run."""
        assert Agent.steer(run_context.run_id, "Wait, also cc the finance team.") is True
        return "Report sent."

    model = _ScriptedModel(
        [
            ("tools", [("send_report", {})]),
            ("answer", "Report sent; finance was not cc'd yet."),
        ]
    )
    output, _ = await _run(_agent(model, [send_report]), mode)

    assert len(model.requests) == 2
    assert model.requests[1][-1].content == _framed("Wait, also cc the finance team.")
    assert Agent.steer(output.run_id, "late") is False  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_stop_after_tool_call_without_steering_still_stops(mode):
    @tool(stop_after_tool_call=True)
    def send_report() -> str:
        """Send the report and end the run."""
        return "Report sent."

    model = _ScriptedModel([("tools", [("send_report", {})])])
    output, _ = await _run(_agent(model, [send_report]), mode)

    assert len(model.requests) == 1
    assert Agent.steer(output.run_id, "late") is False  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_input_accepted_before_a_pause_is_delivered_when_the_run_continues(mode):
    """A steer that lands in a batch that pauses for confirmation cannot join the conversation
    yet (a tool call is still unanswered). It waits for the continuation, and the paused run
    refuses further steering: a human decision is pending, so continue_run() is the way in."""

    @tool
    def draft_email(run_context: RunContext) -> str:
        """Draft the email."""
        assert Agent.steer(run_context.run_id, "Make it shorter.") is True
        return "Drafted."

    @tool(requires_confirmation=True)
    def send_email() -> str:
        """Send the email."""
        return "Sent."

    # One batch: draft_email runs (and steers), then send_email pauses the batch
    model = _ScriptedModel(
        [
            ("tools", [("draft_email", {}), ("send_email", {})]),
            ("answer", "Sent a shorter email."),
        ]
    )
    agent = _agent(model, [draft_email, send_email])
    paused = agent.run("Email the client.") if mode == "sync" else await agent.arun("Email the client.")
    assert paused.is_paused
    assert Agent.steer(paused.run_id, "while paused") is False  # type: ignore[arg-type]

    for requirement in paused.active_requirements:
        requirement.confirm()
    if mode == "sync":
        done = agent.continue_run(
            run_id=paused.run_id,
            requirements=paused.requirements,
            session_id=paused.session_id,
        )
    else:
        done = await agent.acontinue_run(
            run_id=paused.run_id,
            requirements=paused.requirements,
            session_id=paused.session_id,
        )

    assert done.status == RunStatus.completed
    resumed = model.requests[-1]
    assert [m.role for m in resumed[-3:]] == ["tool", "tool", "user"]
    assert resumed[-1].content == _framed("Make it shorter.")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stream", "astream"])
async def test_a_message_is_used_verbatim_and_its_id_reported(mode):
    own = Message(role="user", content="<note>Switch to metric units.</note>")
    framed = steering_message("Also add humidity.")

    @tool
    def get_weather(run_context: RunContext) -> str:
        """Get the weather."""
        assert Agent.steer(run_context.run_id, own) is True
        assert Agent.steer(run_context.run_id, framed) is True
        return "64F, sunny"

    model = _ScriptedModel([("tools", [("get_weather", {})]), ("answer", "18C, sunny.")])
    _, events = await _run(_agent(model, [get_weather]), mode)

    injected = model.requests[1][-2:]
    assert injected[0].content == "<note>Switch to metric units.</note>"
    assert injected[1].content == _framed("Also add humidity.")
    steered = [e for e in events if isinstance(e, RunSteeredEvent)]
    assert [e.message_id for e in steered] == [own.id, framed.id]
