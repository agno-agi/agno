from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import pytest

from agno.agent._tools import run_tool
from agno.agent.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import CustomEvent, RunOutput, ToolCallCompletedEvent
from agno.run.messages import RunMessages
from agno.tools.function import Function, FunctionCall


class _TestModel(Model):
    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content="test")

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content="test")

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield ModelResponse(content="test")

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield ModelResponse(content="test")

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return ModelResponse(content="test")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse(content="test")


@dataclass
class StockProgressEvent(CustomEvent):
    event_data: Optional[Dict[str, str]] = None


EVENT_PAYLOAD = "EVENT_PAYLOAD_SHOULD_NOT_BE_MODEL_VISIBLE"
SUMMARY = "Filtered stock list total: 2"


def _completed_tool_result(events: List[Any]) -> str:
    completed_events = [
        event
        for event in events
        if isinstance(event, ModelResponse) and event.event == ModelResponseEvent.tool_call_completed.value
    ]
    assert len(completed_events) == 1
    completed_event = completed_events[0]
    assert completed_event.tool_executions is not None
    assert completed_event.tool_executions[0].result is not None
    return completed_event.tool_executions[0].result


def test_sync_generator_custom_event_is_not_in_tool_result():
    def screen_stocks() -> Iterator[object]:
        yield StockProgressEvent(event_data={"stocks": EVENT_PAYLOAD})
        yield SUMMARY

    model = _TestModel()
    function = Function.from_callable(screen_stocks)
    function_call = FunctionCall(function=function, arguments={}, call_id="call_sync")
    function_call_results: List[Message] = []

    events = list(model.run_function_call(function_call, function_call_results))

    custom_events = [event for event in events if isinstance(event, StockProgressEvent)]
    assert len(custom_events) == 1
    assert custom_events[0].tool_call_id == "call_sync"
    assert custom_events[0].event_data == {"stocks": EVENT_PAYLOAD}

    assert len(function_call_results) == 1
    assert function_call_results[0].content == SUMMARY
    assert _completed_tool_result(events) == SUMMARY


def test_custom_event_only_generator_has_empty_tool_result():
    def screen_stocks() -> Iterator[object]:
        yield StockProgressEvent(event_data={"stocks": EVENT_PAYLOAD})

    model = _TestModel()
    function = Function.from_callable(screen_stocks)
    function_call = FunctionCall(function=function, arguments={}, call_id="call_event_only")
    function_call_results: List[Message] = []

    events = list(model.run_function_call(function_call, function_call_results))

    custom_events = [event for event in events if isinstance(event, StockProgressEvent)]
    assert len(custom_events) == 1
    assert custom_events[0].tool_call_id == "call_event_only"
    assert custom_events[0].event_data == {"stocks": EVENT_PAYLOAD}

    assert len(function_call_results) == 1
    assert function_call_results[0].content == ""
    assert _completed_tool_result(events) == ""


def test_run_tool_streams_custom_event_without_tool_result_leak():
    def screen_stocks() -> Iterator[object]:
        yield StockProgressEvent(event_data={"stocks": EVENT_PAYLOAD})
        yield SUMMARY

    model = _TestModel()
    agent = Agent(model=model, telemetry=False)
    function = Function.from_callable(screen_stocks)
    tool_execution = ToolExecution(tool_call_id="call_wrapper", tool_name=function.name, tool_args={})
    run_output = RunOutput(run_id="run_wrapper", agent_id="agent_wrapper", agent_name="Agent")
    run_messages = RunMessages()

    events = list(
        run_tool(
            agent=agent,
            run_response=run_output,
            run_messages=run_messages,
            tool=tool_execution,
            functions={function.name: function},
            stream_events=True,
        )
    )

    custom_events = [event for event in events if isinstance(event, StockProgressEvent)]
    assert len(custom_events) == 1
    assert custom_events[0].tool_call_id == "call_wrapper"
    assert custom_events[0].event_data == {"stocks": EVENT_PAYLOAD}

    completed_events = [event for event in events if isinstance(event, ToolCallCompletedEvent)]
    assert len(completed_events) == 1
    assert completed_events[0].tool is not None
    assert completed_events[0].tool.result == SUMMARY
    assert len(run_messages.messages) == 1
    assert run_messages.messages[0].content == SUMMARY


@pytest.mark.asyncio
async def test_async_generator_custom_event_is_not_in_tool_result():
    async def screen_stocks() -> AsyncIterator[object]:
        yield StockProgressEvent(event_data={"stocks": EVENT_PAYLOAD})
        yield SUMMARY

    model = _TestModel()
    function = Function.from_callable(screen_stocks)
    function_call = FunctionCall(function=function, arguments={}, call_id="call_async")
    function_call_results: List[Message] = []

    events = [
        event
        async for event in model.arun_function_calls(
            [function_call],
            function_call_results=function_call_results,
            skip_pause_check=True,
        )
    ]

    custom_events = [event for event in events if isinstance(event, StockProgressEvent)]
    assert len(custom_events) == 1
    assert custom_events[0].tool_call_id == "call_async"
    assert custom_events[0].event_data == {"stocks": EVENT_PAYLOAD}

    assert len(function_call_results) == 1
    assert function_call_results[0].content == SUMMARY
    assert _completed_tool_result(events) == SUMMARY


@pytest.mark.asyncio
async def test_sync_generator_custom_event_is_not_in_async_tool_result():
    def screen_stocks() -> Iterator[object]:
        yield StockProgressEvent(event_data={"stocks": EVENT_PAYLOAD})
        yield SUMMARY

    model = _TestModel()
    function = Function.from_callable(screen_stocks)
    function_call = FunctionCall(function=function, arguments={}, call_id="call_async_sync_generator")
    function_call_results: List[Message] = []

    events = [
        event
        async for event in model.arun_function_calls(
            [function_call],
            function_call_results=function_call_results,
            skip_pause_check=True,
        )
    ]

    custom_events = [event for event in events if isinstance(event, StockProgressEvent)]
    assert len(custom_events) == 1
    assert custom_events[0].tool_call_id == "call_async_sync_generator"
    assert custom_events[0].event_data == {"stocks": EVENT_PAYLOAD}

    assert len(function_call_results) == 1
    assert function_call_results[0].content == SUMMARY
    assert _completed_tool_result(events) == SUMMARY
