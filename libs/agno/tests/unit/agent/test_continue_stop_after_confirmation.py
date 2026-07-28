from __future__ import annotations

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ToolExecution
from agno.run.agent import (
    RunCompletedEvent,
    RunOutput,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.tools.decorator import tool


class _CountingModel(Model):
    def __init__(self) -> None:
        super().__init__(id="counting-model", name="counting-model", provider="test")
        self.calls = 0

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        return ModelResponse(content="model follow-up")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        return ModelResponse(content="model follow-up")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        self.calls += 1
        yield ModelResponse(content="model follow-up")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self.calls += 1
        yield ModelResponse(content="model follow-up")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class _ProposalModel(_CountingModel):
    def _proposal(self) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            tool_calls=[
                {
                    "id": "proposal-1",
                    "type": "function",
                    "function": {"name": "present", "arguments": "{}"},
                }
            ]
        )

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._proposal()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._proposal()


def _paused_response(
    tool_name: str,
    *,
    confirmed: bool,
    stop_after_tool_call: bool,
    run_id: str,
    session_id: str,
) -> RunOutput:
    execution = ToolExecution(
        tool_call_id=f"{run_id}-tool",
        tool_name=tool_name,
        tool_args={},
        stop_after_tool_call=stop_after_tool_call,
        requires_confirmation=True,
        confirmed=confirmed,
    )
    paused = RunOutput(
        run_id=run_id,
        session_id=session_id,
        status=RunStatus.paused,
        tools=[execution],
        requirements=[RunRequirement(tool_execution=execution)],
        messages=[
            Message(role="user", content="Finish the action."),
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": execution.tool_call_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": "{}"},
                    }
                ],
            ),
        ],
    )
    return RunOutput.from_dict(paused.to_dict())


def _agent(
    *,
    stop_after_tool_call: bool,
    model: _CountingModel | None = None,
) -> tuple[Agent, _CountingModel, list[str]]:
    executions: list[str] = []

    @tool(
        requires_confirmation=True,
        stop_after_tool_call=stop_after_tool_call,
    )
    def present() -> str:
        executions.append("present")
        return "approved"

    selected_model = model or _CountingModel()
    return Agent(model=selected_model, tools=[present], telemetry=False), selected_model, executions


def test_pause_persists_stop_after_contract_sync() -> None:
    agent, _, _ = _agent(stop_after_tool_call=True, model=_ProposalModel())

    paused = agent.run("Present the artifact.")
    restored = RunOutput.from_dict(paused.to_dict())

    assert restored.status == RunStatus.paused
    assert restored.tools and restored.tools[0].stop_after_tool_call is True


@pytest.mark.asyncio
async def test_pause_persists_stop_after_contract_async() -> None:
    agent, _, _ = _agent(stop_after_tool_call=True, model=_ProposalModel())

    paused = await agent.arun("Present the artifact.")
    restored = RunOutput.from_dict(paused.to_dict())

    assert restored.status == RunStatus.paused
    assert restored.tools and restored.tools[0].stop_after_tool_call is True


def test_confirmed_stop_after_tool_completes_without_sync_model_follow_up() -> None:
    agent, model, executions = _agent(stop_after_tool_call=True)
    paused = _paused_response(
        "present",
        confirmed=True,
        stop_after_tool_call=True,
        run_id="sync-stop-after",
        session_id="sync-stop-after-session",
    )

    result = agent.continue_run(paused)

    assert result.status == RunStatus.completed
    assert result.content == "approved"
    assert result.is_paused is False
    assert executions == ["present"]
    assert model.calls == 0
    assert result.tools and result.tools[0].stop_after_tool_call is True


@pytest.mark.asyncio
async def test_confirmed_stop_after_tool_completes_without_async_model_follow_up() -> None:
    agent, model, executions = _agent(stop_after_tool_call=True)
    paused = _paused_response(
        "present",
        confirmed=True,
        stop_after_tool_call=True,
        run_id="async-stop-after",
        session_id="async-stop-after-session",
    )

    result = await agent.acontinue_run(paused)

    assert result.status == RunStatus.completed
    assert result.content == "approved"
    assert result.is_paused is False
    assert executions == ["present"]
    assert model.calls == 0
    assert result.tools and result.tools[0].stop_after_tool_call is True


def test_confirmed_stop_after_tool_streams_events_without_sync_model_follow_up() -> None:
    agent, model, executions = _agent(stop_after_tool_call=True)
    paused = _paused_response(
        "present",
        confirmed=True,
        stop_after_tool_call=True,
        run_id="sync-stream-stop-after",
        session_id="sync-stream-stop-after-session",
    )

    events = list(
        agent.continue_run(
            paused,
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    )
    result = next(event for event in events if isinstance(event, RunOutput))

    assert result.status == RunStatus.completed
    assert result.content == "approved"
    assert executions == ["present"]
    assert model.calls == 0
    assert result.tools and result.tools[0].stop_after_tool_call is True
    assert sum(isinstance(event, ToolCallStartedEvent) for event in events) == 1
    assert sum(isinstance(event, ToolCallCompletedEvent) for event in events) == 1
    assert sum(isinstance(event, RunCompletedEvent) for event in events) == 1
    tool_message = next(message for message in result.messages or [] if message.role == "tool")
    assert tool_message.tool_call_id == paused.tools[0].tool_call_id
    assert tool_message.content == "approved"


@pytest.mark.asyncio
async def test_confirmed_stop_after_tool_streams_events_without_async_model_follow_up() -> None:
    agent, model, executions = _agent(stop_after_tool_call=True)
    paused = _paused_response(
        "present",
        confirmed=True,
        stop_after_tool_call=True,
        run_id="async-stream-stop-after",
        session_id="async-stream-stop-after-session",
    )

    events = [
        event
        async for event in agent.acontinue_run(
            paused,
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    ]
    result = next(event for event in events if isinstance(event, RunOutput))

    assert result.status == RunStatus.completed
    assert result.content == "approved"
    assert executions == ["present"]
    assert model.calls == 0
    assert result.tools and result.tools[0].stop_after_tool_call is True
    assert sum(isinstance(event, ToolCallStartedEvent) for event in events) == 1
    assert sum(isinstance(event, ToolCallCompletedEvent) for event in events) == 1
    assert sum(isinstance(event, RunCompletedEvent) for event in events) == 1
    tool_message = next(message for message in result.messages or [] if message.role == "tool")
    assert tool_message.tool_call_id == paused.tools[0].tool_call_id
    assert tool_message.content == "approved"


@pytest.mark.parametrize(
    ("confirmed", "expected_executions"),
    [
        (True, ["present"]),
        (False, []),
    ],
)
def test_confirmation_without_stop_after_still_gets_model_follow_up(
    confirmed: bool,
    expected_executions: list[str],
) -> None:
    agent, model, executions = _agent(stop_after_tool_call=False)
    paused = _paused_response(
        "present",
        confirmed=confirmed,
        stop_after_tool_call=False,
        run_id=f"sync-follow-up-{confirmed}",
        session_id=f"sync-follow-up-{confirmed}-session",
    )

    result = agent.continue_run(paused)

    assert result.status == RunStatus.completed
    assert result.content == "model follow-up"
    assert executions == expected_executions
    assert model.calls == 1
