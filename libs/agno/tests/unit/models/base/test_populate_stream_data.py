"""
Regression test for #9490.

`ModelResponse.tool_calls` defaults to an empty list (field(default_factory=list)),
never None. `_populate_stream_data` guarded it with `is not None`, which is always
true, so `should_yield` was flipped to True on empty metadata chunks (e.g.
content_block_start), yielding zero-payload events up the stack.
"""

from agno.models.base import MessageData, Model
from agno.models.response import ModelResponse


def _drain(delta: ModelResponse):
    """Call the unbound method (it only uses self as a bound handle) and return yielded deltas."""
    stream_data = MessageData()
    return list(Model._populate_stream_data(object(), stream_data, delta)), stream_data


def test_empty_delta_does_not_yield():
    # An empty metadata chunk: no content, no tool calls (tool_calls defaults to []).
    yielded, _ = _drain(ModelResponse())
    assert yielded == [], "empty delta must not yield a zero-payload event"


def test_delta_with_empty_tool_calls_list_does_not_yield():
    delta = ModelResponse(tool_calls=[])
    yielded, stream_data = _drain(delta)
    assert yielded == [], "an empty tool_calls list must not trigger a yield"
    # Nothing was accumulated (stays at the default empty list).
    assert stream_data.response_tool_calls == []


def test_delta_with_real_tool_call_yields():
    delta = ModelResponse(tool_calls=[{"id": "1", "function": {"name": "f", "arguments": "{}"}}])
    yielded, stream_data = _drain(delta)
    assert len(yielded) == 1, "a non-empty tool_calls delta must yield"
    assert stream_data.response_tool_calls == delta.tool_calls


def test_delta_with_content_yields():
    delta = ModelResponse(content="hello")
    yielded, stream_data = _drain(delta)
    assert len(yielded) == 1
    assert stream_data.response_content == "hello"
