"""Unit tests for HuggingFace streaming responses.

A single stream chunk may carry more than one tool call; every call in the chunk must survive
parsing instead of only the first one, and arguments split across chunks must still accumulate.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("huggingface_hub")

from agno.models.huggingface import HuggingFace


def _tool_call(index: int, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=f"call_{index}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _stream_delta(tool_calls) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(role="assistant", content=None, tool_calls=tool_calls)
            )
        ],
        usage=None,
    )


def test_stream_chunk_keeps_every_tool_call():
    model = HuggingFace(id="test-model", api_key="test-key")
    delta = _stream_delta(
        [
            _tool_call(0, "get_weather", '{"city":"Paris"}'),
            _tool_call(1, "get_time", '{"zone":"CET"}'),
        ]
    )

    response = model._parse_provider_response_delta(delta)

    assert len(response.tool_calls) == 2
    parsed = model.parse_tool_calls(response.tool_calls)
    assert [call["function"]["name"] for call in parsed] == ["get_weather", "get_time"]
    assert [call["id"] for call in parsed] == ["call_0", "call_1"]
    assert parsed[0]["function"]["arguments"] == '{"city":"Paris"}'
    assert parsed[1]["function"]["arguments"] == '{"zone":"CET"}'


def test_stream_chunks_accumulate_arguments_for_the_same_index():
    model = HuggingFace(id="test-model", api_key="test-key")
    first = model._parse_provider_response_delta(
        _stream_delta([_tool_call(0, "get_weather", '{"ci')])
    )
    second = model._parse_provider_response_delta(
        _stream_delta([_tool_call(0, "get_weather", 'ty":"Paris"}')])
    )

    parsed = model.parse_tool_calls([*first.tool_calls, *second.tool_calls])

    assert len(parsed) == 1
    assert parsed[0]["function"]["arguments"] == '{"city":"Paris"}'


def test_parse_tool_calls_still_accepts_a_nested_group():
    parsed = HuggingFace.parse_tool_calls([[_tool_call(0, "get_weather", "{}")]])

    assert len(parsed) == 1
    assert parsed[0]["function"]["name"] == "get_weather"
