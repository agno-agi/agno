"""Text from consecutive model turns must not run together.

A model that writes text, calls a tool, then writes more text produces two
assistant messages. The run's content is their concatenation, and without a
separator "Let me check." + "It is sunny." renders as "Let me check.It is sunny."
"""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.metrics import MessageMetrics
from agno.models.base import Model, _content_segment_separator
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_weather(city: str) -> str:
    """Get the weather for a city."""
    return "Sunny 22C"


def _tool_call(call_id: str = "call_1") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}


class ScriptedModel(Model):
    """Offline model that plays back one canned ModelResponse per turn.

    Streaming splits each turn's content into two chunks and sends the tool
    calls in a trailing chunk, mirroring how providers deliver deltas.
    """

    def __init__(self, turns: List[ModelResponse]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self._turns = list(turns)
        self.captured_messages: List[List[Message]] = []

    def _next_turn(self, messages: List[Message]) -> ModelResponse:
        self.captured_messages.append(list(messages))
        turn = self._turns.pop(0)
        return ModelResponse(
            content=turn.content, tool_calls=turn.tool_calls, role="assistant", response_usage=MessageMetrics()
        )

    def _turn_deltas(self, messages: List[Message]) -> List[ModelResponse]:
        turn = self._next_turn(messages)
        deltas: List[ModelResponse] = []
        content = turn.content or ""
        if content:
            split = max(1, len(content) // 2)
            deltas.append(ModelResponse(content=content[:split], role="assistant"))
            deltas.append(ModelResponse(content=content[split:]))
        if turn.tool_calls:
            deltas.append(ModelResponse(tool_calls=turn.tool_calls))
        deltas.append(ModelResponse(response_usage=MessageMetrics()))
        return deltas

    def invoke(self, messages: List[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_turn(messages)

    async def ainvoke(self, messages: List[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_turn(messages)

    def invoke_stream(self, messages: List[Message], *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield from self._turn_deltas(messages)

    async def ainvoke_stream(self, messages: List[Message], *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for delta in self._turn_deltas(messages):
            yield delta

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _two_turn_model(first: str = "Let me check.", second: str = "It is sunny.") -> ScriptedModel:
    return ScriptedModel(
        [
            ModelResponse(content=first, tool_calls=[_tool_call()]),
            ModelResponse(content=second),
        ]
    )


def _tools(show_result: bool = False) -> List[Function]:
    function = Function.from_callable(get_weather)
    function.show_result = show_result
    return [function]


def _stream_content(events: List[Any]) -> List[str]:
    return [
        event.content
        for event in events
        if isinstance(event, ModelResponse)
        and event.event == ModelResponseEvent.assistant_response.value
        and isinstance(event.content, str)
        and event.content
    ]


async def _collect(aiterator: AsyncIterator[Any]) -> List[Any]:
    return [item async for item in aiterator]


# ---------------------------------------------------------------------------
# Separator helper
# ---------------------------------------------------------------------------


class TestContentSegmentSeparator:
    def test_separates_two_sentences(self):
        assert _content_segment_separator("Let me check.", "It is sunny.") == "\n\n"

    def test_no_separator_when_previous_ends_with_whitespace(self):
        assert _content_segment_separator("Let me check.\n", "It is sunny.") == ""

    def test_no_separator_when_new_starts_with_whitespace(self):
        assert _content_segment_separator("Let me check.", " It is sunny.") == ""

    def test_no_separator_around_empty_segments(self):
        assert _content_segment_separator("", "It is sunny.") == ""
        assert _content_segment_separator(None, "It is sunny.") == ""
        assert _content_segment_separator("Let me check.", "") == ""

    def test_no_separator_for_non_text(self):
        assert _content_segment_separator("Let me check.", {"a": 1}) == ""


# ---------------------------------------------------------------------------
# Model.response / aresponse
# ---------------------------------------------------------------------------


class TestNonStreamingResponse:
    def test_text_around_tool_call_is_separated(self):
        model = _two_turn_model()
        messages = [Message(role="user", content="Weather in Paris?")]
        response = model.response(messages=messages, tools=_tools())
        assert response.content == "Let me check.\n\nIt is sunny."

    def test_assistant_messages_keep_their_own_text(self):
        model = _two_turn_model()
        messages = [Message(role="user", content="Weather in Paris?")]
        model.response(messages=messages, tools=_tools())
        assistant_contents = [m.content for m in messages if m.role == "assistant"]
        assert assistant_contents == ["Let me check.", "It is sunny."]

    def test_existing_whitespace_at_seam_is_kept_as_is(self):
        model = _two_turn_model(first="Let me check.\n")
        response = model.response(messages=[Message(role="user", content="hi")], tools=_tools())
        assert response.content == "Let me check.\nIt is sunny."

    def test_tool_only_first_turn_adds_no_leading_separator(self):
        model = _two_turn_model(first="")
        response = model.response(messages=[Message(role="user", content="hi")], tools=_tools())
        assert response.content == "It is sunny."

    def test_shown_tool_result_is_its_own_segment(self):
        model = _two_turn_model()
        response = model.response(messages=[Message(role="user", content="hi")], tools=_tools(show_result=True))
        assert response.content == "Let me check.\n\nSunny 22C\n\nIt is sunny."

    @pytest.mark.asyncio
    async def test_async_text_around_tool_call_is_separated(self):
        model = _two_turn_model()
        messages = [Message(role="user", content="Weather in Paris?")]
        response = await model.aresponse(messages=messages, tools=_tools())
        assert response.content == "Let me check.\n\nIt is sunny."
        assert [m.content for m in messages if m.role == "assistant"] == ["Let me check.", "It is sunny."]

    @pytest.mark.asyncio
    async def test_async_shown_tool_result_is_its_own_segment(self):
        model = _two_turn_model()
        response = await model.aresponse(messages=[Message(role="user", content="hi")], tools=_tools(show_result=True))
        assert response.content == "Let me check.\n\nSunny 22C\n\nIt is sunny."


# ---------------------------------------------------------------------------
# Model.response_stream / aresponse_stream
# ---------------------------------------------------------------------------


class TestStreamingResponse:
    def test_second_turn_first_chunk_carries_the_separator(self):
        model = _two_turn_model()
        messages = [Message(role="user", content="Weather in Paris?")]
        chunks = _stream_content(list(model.response_stream(messages=messages, tools=_tools())))
        assert "".join(chunks) == "Let me check.\n\nIt is sunny."
        assert chunks == ["Let me", " check.", "\n\nIt is ", "sunny."]

    def test_streamed_assistant_messages_keep_their_own_text(self):
        model = _two_turn_model()
        messages = [Message(role="user", content="Weather in Paris?")]
        list(model.response_stream(messages=messages, tools=_tools()))
        assert [m.content for m in messages if m.role == "assistant"] == ["Let me check.", "It is sunny."]

    def test_streamed_shown_tool_result_is_its_own_segment(self):
        model = _two_turn_model()
        chunks = _stream_content(
            list(model.response_stream(messages=[Message(role="user", content="hi")], tools=_tools(show_result=True)))
        )
        assert "".join(chunks) == "Let me check.\n\nSunny 22C\n\nIt is sunny."

    def test_no_separator_when_first_turn_is_tool_only(self):
        model = _two_turn_model(first="")
        chunks = _stream_content(
            list(model.response_stream(messages=[Message(role="user", content="hi")], tools=_tools()))
        )
        assert "".join(chunks) == "It is sunny."

    def test_non_streamed_turns_inside_stream_are_separated(self):
        model = _two_turn_model()
        chunks = _stream_content(
            list(
                model.response_stream(
                    messages=[Message(role="user", content="hi")], tools=_tools(), stream_model_response=False
                )
            )
        )
        assert "".join(chunks) == "Let me check.\n\nIt is sunny."

    @pytest.mark.asyncio
    async def test_async_second_turn_first_chunk_carries_the_separator(self):
        model = _two_turn_model()
        messages = [Message(role="user", content="Weather in Paris?")]
        chunks = _stream_content(await _collect(model.aresponse_stream(messages=messages, tools=_tools())))
        assert chunks == ["Let me", " check.", "\n\nIt is ", "sunny."]
        assert [m.content for m in messages if m.role == "assistant"] == ["Let me check.", "It is sunny."]

    @pytest.mark.asyncio
    async def test_async_streamed_shown_tool_result_is_its_own_segment(self):
        model = _two_turn_model()
        chunks = _stream_content(
            await _collect(
                model.aresponse_stream(messages=[Message(role="user", content="hi")], tools=_tools(show_result=True))
            )
        )
        assert "".join(chunks) == "Let me check.\n\nSunny 22C\n\nIt is sunny."

    @pytest.mark.asyncio
    async def test_async_non_streamed_turns_inside_stream_are_separated(self):
        model = _two_turn_model()
        chunks = _stream_content(
            await _collect(
                model.aresponse_stream(
                    messages=[Message(role="user", content="hi")], tools=_tools(), stream_model_response=False
                )
            )
        )
        assert "".join(chunks) == "Let me check.\n\nIt is sunny."


# ---------------------------------------------------------------------------
# Agent.run / arun (the path AgentOS drives)
# ---------------------------------------------------------------------------


def _agent() -> Agent:
    return Agent(model=_two_turn_model(), tools=[get_weather], telemetry=False)


class TestAgentRun:
    def test_run_content_is_separated(self):
        run = _agent().run("Weather in Paris?")
        assert run.content == "Let me check.\n\nIt is sunny."

    def test_streamed_run_content_is_separated(self):
        agent = _agent()
        events = list(agent.run("Weather in Paris?", stream=True, stream_events=True))
        streamed = "".join(e.content for e in events if e.event == "RunContent" and isinstance(e.content, str))
        assert streamed == "Let me check.\n\nIt is sunny."
        completed = [e for e in events if e.event == "RunCompleted"]
        assert completed[-1].content == "Let me check.\n\nIt is sunny."

    @pytest.mark.asyncio
    async def test_arun_content_is_separated(self):
        run = await _agent().arun("Weather in Paris?")
        assert run.content == "Let me check.\n\nIt is sunny."

    @pytest.mark.asyncio
    async def test_streamed_arun_content_is_separated(self):
        agent = _agent()
        events = await _collect(agent.arun("Weather in Paris?", stream=True, stream_events=True))
        streamed = "".join(e.content for e in events if e.event == "RunContent" and isinstance(e.content, str))
        assert streamed == "Let me check.\n\nIt is sunny."
        completed = [e for e in events if e.event == "RunCompleted"]
        assert completed[-1].content == "Let me check.\n\nIt is sunny."
