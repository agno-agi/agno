"""Tests for LiteLLM toolResult/toolUse alignment when routing to Bedrock backends.

Ensures that tool result messages always carry a tool_call_id matching the
corresponding tool call in the preceding assistant message, even when the
original tool_call_id is missing or empty.
"""

from unittest.mock import MagicMock

from agno.models.litellm import LiteLLM
from agno.models.message import Message


def _make_model() -> LiteLLM:
    """Create a LiteLLM model instance with a mock client to skip env validation."""
    mock_client = MagicMock()
    return LiteLLM(id="bedrock/anthropic.claude-3-sonnet", client=mock_client)


# ---------------------------------------------------------------------------
# _format_messages: single tool call
# ---------------------------------------------------------------------------


def test_format_messages_single_tool_call_preserves_id():
    """A single tool result with a valid tool_call_id is preserved as-is."""
    model = _make_model()
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                }
            ],
        ),
        Message(role="tool", tool_call_id="call_abc", content="Sunny", name="get_weather"),
    ]

    formatted = model._format_messages(messages)

    # Assistant tool call id
    assert formatted[1]["tool_calls"][0]["id"] == "call_abc"
    # Tool result id matches
    assert formatted[2]["tool_call_id"] == "call_abc"


def test_format_messages_single_tool_call_missing_id_falls_back():
    """When tool_call_id is missing, it is filled from the assistant message."""
    model = _make_model()
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                }
            ],
        ),
        # tool_call_id deliberately left as None
        Message(role="tool", tool_call_id=None, content="Sunny", name="get_weather"),
    ]

    formatted = model._format_messages(messages)
    assert formatted[2]["tool_call_id"] == "call_abc"


# ---------------------------------------------------------------------------
# _format_messages: parallel tool calls
# ---------------------------------------------------------------------------


def test_format_messages_parallel_tool_calls_ids_match():
    """Multiple tool results match their corresponding tool calls by position."""
    model = _make_model()
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": '{"tz": "EST"}'},
                },
            ],
        ),
        Message(role="tool", tool_call_id="call_1", content="Sunny", name="get_weather"),
        Message(role="tool", tool_call_id="call_2", content="10am", name="get_time"),
    ]

    formatted = model._format_messages(messages)

    assert formatted[1]["tool_calls"][0]["id"] == "call_1"
    assert formatted[1]["tool_calls"][1]["id"] == "call_2"
    assert formatted[2]["tool_call_id"] == "call_1"
    assert formatted[3]["tool_call_id"] == "call_2"


def test_format_messages_parallel_tool_calls_missing_ids_resolved():
    """When tool_call_ids are all missing, positional fallback assigns correct IDs."""
    model = _make_model()
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": '{"tz": "EST"}'},
                },
            ],
        ),
        # Both tool_call_ids are None
        Message(role="tool", tool_call_id=None, content="Sunny", name="get_weather"),
        Message(role="tool", tool_call_id=None, content="10am", name="get_time"),
    ]

    formatted = model._format_messages(messages)

    assert formatted[2]["tool_call_id"] == "call_1"
    assert formatted[3]["tool_call_id"] == "call_2"


# ---------------------------------------------------------------------------
# _format_messages: synthetic IDs when tool_calls have no id
# ---------------------------------------------------------------------------


def test_format_messages_synthetic_ids_when_tool_call_has_no_id():
    """When a tool call dict has no 'id', a synthetic call_N id is created and
    the corresponding tool result receives it via positional fallback."""
    model = _make_model()
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    # No 'id' key at all
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                },
            ],
        ),
        Message(role="tool", tool_call_id=None, content="Sunny", name="get_weather"),
    ]

    formatted = model._format_messages(messages)

    # Synthetic id should be "call_0"
    assert formatted[1]["tool_calls"][0]["id"] == "call_0"
    # Tool result picks up the synthetic id
    assert formatted[2]["tool_call_id"] == "call_0"


# ---------------------------------------------------------------------------
# _format_messages: multiple rounds of tool calls
# ---------------------------------------------------------------------------


def test_format_messages_multiple_rounds():
    """After one round of tool calls, a second round resets tracking correctly."""
    model = _make_model()
    messages = [
        Message(role="user", content="Hi"),
        # First round
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "r1_call_1", "type": "function", "function": {"name": "fn_a", "arguments": "{}"}},
            ],
        ),
        Message(role="tool", tool_call_id="r1_call_1", content="result_a", name="fn_a"),
        # Second round
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {"id": "r2_call_1", "type": "function", "function": {"name": "fn_b", "arguments": "{}"}},
                {"id": "r2_call_2", "type": "function", "function": {"name": "fn_c", "arguments": "{}"}},
            ],
        ),
        Message(role="tool", tool_call_id=None, content="result_b", name="fn_b"),
        Message(role="tool", tool_call_id=None, content="result_c", name="fn_c"),
    ]

    formatted = model._format_messages(messages)

    # First round
    assert formatted[2]["tool_call_id"] == "r1_call_1"
    # Second round — positional fallback from the second assistant message
    assert formatted[4]["tool_call_id"] == "r2_call_1"
    assert formatted[5]["tool_call_id"] == "r2_call_2"


# ---------------------------------------------------------------------------
# format_function_call_results: backfill from tool_ids
# ---------------------------------------------------------------------------


def test_format_function_call_results_backfills_tool_call_id():
    """format_function_call_results fills in missing tool_call_id from tool_ids kwarg."""
    model = _make_model()
    messages: list = []

    fc_results = [
        Message(role="tool", tool_call_id=None, content="result_a", name="fn_a"),
        Message(role="tool", tool_call_id=None, content="result_b", name="fn_b"),
    ]

    model.format_function_call_results(
        messages=messages,
        function_call_results=fc_results,
        tool_ids=["id_aaa", "id_bbb"],
    )

    assert len(messages) == 2
    assert messages[0].tool_call_id == "id_aaa"
    assert messages[1].tool_call_id == "id_bbb"


def test_format_function_call_results_keeps_existing_id():
    """format_function_call_results does not overwrite an existing tool_call_id."""
    model = _make_model()
    messages: list = []

    fc_results = [
        Message(role="tool", tool_call_id="existing_id", content="result_a", name="fn_a"),
    ]

    model.format_function_call_results(
        messages=messages,
        function_call_results=fc_results,
        tool_ids=["different_id"],
    )

    assert messages[0].tool_call_id == "existing_id"


def test_format_function_call_results_no_tool_ids():
    """format_function_call_results works without tool_ids kwarg (base-class compat)."""
    model = _make_model()
    messages: list = []

    fc_results = [
        Message(role="tool", tool_call_id="call_x", content="result", name="fn"),
    ]

    model.format_function_call_results(
        messages=messages,
        function_call_results=fc_results,
    )

    assert len(messages) == 1
    assert messages[0].tool_call_id == "call_x"


# ---------------------------------------------------------------------------
# _parse_provider_response: tool_ids in extra
# ---------------------------------------------------------------------------


def test_parse_provider_response_populates_tool_ids():
    """_parse_provider_response sets extra['tool_ids'] for each tool call."""
    model = _make_model()

    # Build a mock response mimicking LiteLLM's return value
    mock_tool_call_1 = MagicMock()
    mock_tool_call_1.id = "tc_111"
    mock_tool_call_1.function.name = "fn_a"
    mock_tool_call_1.function.arguments = '{"x": 1}'

    mock_tool_call_2 = MagicMock()
    mock_tool_call_2.id = "tc_222"
    mock_tool_call_2.function.name = "fn_b"
    mock_tool_call_2.function.arguments = '{"y": 2}'

    mock_message = MagicMock()
    mock_message.content = None
    mock_message.reasoning_content = None
    mock_message.tool_calls = [mock_tool_call_1, mock_tool_call_2]

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = None

    result = model._parse_provider_response(mock_response)

    assert result.extra is not None
    assert result.extra["tool_ids"] == ["tc_111", "tc_222"]
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["id"] == "tc_111"
    assert result.tool_calls[1]["id"] == "tc_222"


# ---------------------------------------------------------------------------
# _parse_provider_response_delta: tool_ids in extra for streaming
# ---------------------------------------------------------------------------


def test_parse_provider_response_delta_populates_tool_ids():
    """Streaming delta with a tool call id propagates it via extra['tool_ids']."""
    model = _make_model()

    mock_func = MagicMock()
    mock_func.name = "fn_a"
    mock_func.arguments = '{"x": 1}'

    mock_tool_call = MagicMock()
    mock_tool_call.index = 0
    mock_tool_call.id = "tc_stream_1"
    mock_tool_call.function = mock_func

    mock_delta = MagicMock()
    mock_delta.content = None
    mock_delta.reasoning_content = None
    mock_delta.tool_calls = [mock_tool_call]

    mock_choice = MagicMock()
    mock_choice.delta = mock_delta

    mock_chunk = MagicMock()
    mock_chunk.choices = [mock_choice]
    mock_chunk.usage = None

    result = model._parse_provider_response_delta(mock_chunk)

    assert result.extra is not None
    assert result.extra["tool_ids"] == ["tc_stream_1"]


def test_parse_provider_response_delta_no_tool_id_no_extra():
    """Streaming delta without a tool call id does not set extra."""
    model = _make_model()

    mock_func = MagicMock()
    mock_func.name = "fn_a"
    mock_func.arguments = '{"x": 1}'

    mock_tool_call = MagicMock()
    mock_tool_call.index = 0
    mock_tool_call.id = None  # no id in this chunk
    mock_tool_call.function = mock_func

    mock_delta = MagicMock()
    mock_delta.content = None
    mock_delta.reasoning_content = None
    mock_delta.tool_calls = [mock_tool_call]

    mock_choice = MagicMock()
    mock_choice.delta = mock_delta

    mock_chunk = MagicMock()
    mock_chunk.choices = [mock_choice]
    mock_chunk.usage = None

    result = model._parse_provider_response_delta(mock_chunk)

    # No tool id means no extra with tool_ids
    assert result.extra is None or "tool_ids" not in (result.extra or {})
