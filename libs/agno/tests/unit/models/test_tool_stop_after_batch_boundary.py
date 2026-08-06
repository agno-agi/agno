from __future__ import annotations

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.tools.function import Function


class _BatchModel(Model):
    def __init__(self, tool_names: list[str]) -> None:
        super().__init__(
            id="tool-stop-boundary-test",
            name="tool-stop-boundary-test",
            provider="test",
        )
        self.tool_names = tool_names
        self.calls = 0

    def _next_response(self) -> ModelResponse:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("provider was called after a stop-after boundary")
        return ModelResponse(
            tool_calls=[
                {
                    "id": f"{name}-call",
                    "type": "function",
                    "function": {"name": name, "arguments": "{}"},
                }
                for name in self.tool_names
            ]
        )

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next_response()

    async def ainvoke_stream(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[ModelResponse]:
        yield self._next_response()

    def _parse_provider_response(
        self,
        response: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class _ContinuationOrderingModel(_BatchModel):
    def __init__(self) -> None:
        super().__init__([])

    def _ordered_response(self, messages: list[Message]) -> ModelResponse:
        self.calls += 1
        tool_call_ids = [message.tool_call_id for message in messages if message.role == "tool"]
        assert tool_call_ids[-2:] == ["present-call", "edit-call"]
        return ModelResponse(content="ordered")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._ordered_response(kwargs["messages"])

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._ordered_response(kwargs["messages"])

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._ordered_response(kwargs["messages"])

    async def ainvoke_stream(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[ModelResponse]:
        yield self._ordered_response(kwargs["messages"])


def _functions(executions: list[str]) -> list[Function]:
    def present() -> str:
        executions.append("present")
        return "presented"

    def edit() -> str:
        executions.append("edit")
        return "edited"

    present_function = Function.from_callable(present)
    present_function.requires_confirmation = True
    present_function.stop_after_tool_call = True
    edit_function = Function.from_callable(edit)
    edit_function.stop_after_tool_call = True
    return [present_function, edit_function]


def _confirmation_functions(executions: list[str]) -> list[Function]:
    def confirm_a() -> str:
        executions.append("confirm_a")
        return "a"

    def confirm_b() -> str:
        executions.append("confirm_b")
        return "b"

    functions = [
        Function.from_callable(confirm_a),
        Function.from_callable(confirm_b),
    ]
    for function in functions:
        function.requires_confirmation = True
    return functions


def _paused_boundary_run() -> RunOutput:
    execution = ToolExecution(
        tool_call_id="present-call",
        tool_name="present",
        tool_args={},
        requires_confirmation=True,
        confirmed=True,
        stop_after_tool_call=True,
    )
    run = RunOutput(
        run_id="ordered-boundary-run",
        session_id="ordered-boundary-session",
        status=RunStatus.paused,
        tools=[execution],
        requirements=[RunRequirement(tool_execution=execution)],
        messages=[
            Message(role="user", content="Present, then edit."),
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": "present-call",
                        "type": "function",
                        "function": {"name": "present", "arguments": "{}"},
                    },
                    {
                        "id": "edit-call",
                        "type": "function",
                        "function": {"name": "edit", "arguments": "{}"},
                    },
                ],
            ),
            Message(
                role="tool",
                tool_call_id="edit-call",
                tool_name="edit",
                content="Skipped because present is a stop-after boundary.",
                tool_call_error=True,
            ),
        ],
    )
    return RunOutput.from_dict(run.to_dict())


def _assert_boundary_result(
    *,
    model: _BatchModel,
    messages: list[Message],
    executions: list[str],
    first_tool: str,
) -> None:
    assert model.calls == 1
    expected_executions = [] if first_tool == "present" else ["edit"]
    assert executions == expected_executions

    tool_messages = [message for message in messages if message.role == "tool"]
    deferred_name = "edit" if first_tool == "present" else "present"
    deferred = next(message for message in tool_messages if message.tool_name == deferred_name)
    assert deferred.tool_call_id == f"{deferred_name}-call"
    assert deferred.tool_call_error is True
    assert deferred.stop_after_tool_call is False
    assert f"{first_tool} is a stop-after boundary" in str(deferred.content)

    if first_tool == "present":
        assert not any(message.tool_name == "present" for message in tool_messages)
    else:
        edit_result = next(message for message in tool_messages if message.tool_name == "edit")
        assert edit_result.content == "edited"
        assert edit_result.stop_after_tool_call is True


@pytest.mark.parametrize("first_tool", ["present", "edit"])
@pytest.mark.parametrize("stream", [False, True])
def test_sync_later_calls_do_not_cross_stop_after_boundary(
    first_tool: str,
    stream: bool,
) -> None:
    later_tool = "edit" if first_tool == "present" else "present"
    model = _BatchModel([first_tool, later_tool])
    executions: list[str] = []
    messages = [Message(role="user", content="Review and update the artifact.")]
    kwargs = {
        "messages": messages,
        "tools": _functions(executions),
        "tool_call_limit": 8,
    }

    if stream:
        list(model.response_stream(**kwargs))
    else:
        model.response(**kwargs)

    _assert_boundary_result(
        model=model,
        messages=messages,
        executions=executions,
        first_tool=first_tool,
    )


@pytest.mark.parametrize("first_tool", ["present", "edit"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_async_later_calls_do_not_cross_stop_after_boundary(
    first_tool: str,
    stream: bool,
) -> None:
    later_tool = "edit" if first_tool == "present" else "present"
    model = _BatchModel([first_tool, later_tool])
    executions: list[str] = []
    messages = [Message(role="user", content="Review and update the artifact.")]
    kwargs = {
        "messages": messages,
        "tools": _functions(executions),
        "tool_call_limit": 8,
    }

    if stream:
        async for _ in model.aresponse_stream(**kwargs):
            pass
    else:
        await model.aresponse(**kwargs)

    _assert_boundary_result(
        model=model,
        messages=messages,
        executions=executions,
        first_tool=first_tool,
    )


@pytest.mark.parametrize("stream", [False, True])
def test_sync_multiple_confirmation_proposals_remain_pending(stream: bool) -> None:
    model = _BatchModel(["confirm_a", "confirm_b"])
    executions: list[str] = []
    messages = [Message(role="user", content="Propose both actions.")]
    kwargs = {
        "messages": messages,
        "tools": _confirmation_functions(executions),
    }

    if stream:
        events = list(model.response_stream(**kwargs))
        paused_names = [
            execution.tool_name
            for event in events
            for execution in (getattr(event, "tool_executions", None) or [])
            if execution.requires_confirmation
        ]
    else:
        response = model.response(**kwargs)
        paused_names = [
            execution.tool_name for execution in (response.tool_executions or []) if execution.requires_confirmation
        ]

    assert model.calls == 1
    assert executions == []
    assert paused_names == ["confirm_a", "confirm_b"]
    assert not any(message.role == "tool" for message in messages)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_async_multiple_confirmation_proposals_remain_pending(
    stream: bool,
) -> None:
    model = _BatchModel(["confirm_a", "confirm_b"])
    executions: list[str] = []
    messages = [Message(role="user", content="Propose both actions.")]
    kwargs = {
        "messages": messages,
        "tools": _confirmation_functions(executions),
    }

    if stream:
        events = [event async for event in model.aresponse_stream(**kwargs)]
        paused_names = [
            execution.tool_name
            for event in events
            for execution in (getattr(event, "tool_executions", None) or [])
            if execution.requires_confirmation
        ]
    else:
        response = await model.aresponse(**kwargs)
        paused_names = [
            execution.tool_name for execution in (response.tool_executions or []) if execution.requires_confirmation
        ]

    assert model.calls == 1
    assert executions == []
    assert paused_names == ["confirm_a", "confirm_b"]
    assert not any(message.role == "tool" for message in messages)


@pytest.mark.parametrize("stream", [False, True])
def test_sync_resumed_boundary_result_precedes_deferred_sibling(stream: bool) -> None:
    model = _ContinuationOrderingModel()
    executions: list[str] = []
    agent = Agent(model=model, tools=_functions(executions), telemetry=False)
    paused = _paused_boundary_run()

    if stream:
        events = list(agent.continue_run(paused, stream=True, yield_run_output=True))
        result = next(event for event in events if isinstance(event, RunOutput))
    else:
        result = agent.continue_run(paused)

    assert result.status == RunStatus.completed
    assert model.calls == 1
    assert executions == ["present"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_async_resumed_boundary_result_precedes_deferred_sibling(stream: bool) -> None:
    model = _ContinuationOrderingModel()
    executions: list[str] = []
    agent = Agent(model=model, tools=_functions(executions), telemetry=False)
    paused = _paused_boundary_run()

    if stream:
        events = [event async for event in agent.acontinue_run(paused, stream=True, yield_run_output=True)]
        result = next(event for event in events if isinstance(event, RunOutput))
    else:
        result = await agent.acontinue_run(paused)

    assert result.status == RunStatus.completed
    assert model.calls == 1
    assert executions == ["present"]
