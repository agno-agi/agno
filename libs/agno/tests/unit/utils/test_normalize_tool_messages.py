"""Tests for cross-provider tool message normalization.

When a session is created with one provider (e.g., Gemini) and then continued
with another provider (e.g., OpenAI), the tool result messages stored in the
session history may be in a provider-specific format that the new provider
cannot consume.

This module tests the normalize_tool_messages function that converts
provider-specific combined tool messages into the standard per-tool format.
"""

import json

from agno.models.message import Message
from agno.utils.message import normalize_tool_messages


class TestNormalizeCombinedToolMessages:
    """Test normalization of Gemini-style combined tool messages."""

    def test_gemini_combined_tool_message_is_split(self):
        """A Gemini-style combined tool message should be split into individual messages."""
        combined_msg = Message(
            role="tool",
            content=["result_from_tool_a", "result_from_tool_b"],
            tool_name="tool_a, tool_b",
            tool_calls=[
                {"tool_call_id": "call_1", "tool_name": "tool_a", "content": "result_from_tool_a"},
                {"tool_call_id": "call_2", "tool_name": "tool_b", "content": "result_from_tool_b"},
            ],
        )

        result = normalize_tool_messages([combined_msg])

        assert len(result) == 2

        assert result[0].role == "tool"
        assert result[0].content == "result_from_tool_a"
        assert result[0].tool_call_id == "call_1"
        assert result[0].tool_name == "tool_a"

        assert result[1].role == "tool"
        assert result[1].content == "result_from_tool_b"
        assert result[1].tool_call_id == "call_2"
        assert result[1].tool_name == "tool_b"

    def test_gemini_single_tool_call_combined_message(self):
        """A Gemini-style combined message with a single tool call should also be normalized."""
        combined_msg = Message(
            role="tool",
            content=["search result text"],
            tool_name="search",
            tool_calls=[
                {"tool_call_id": "call_abc", "tool_name": "search", "content": "search result text"},
            ],
        )

        result = normalize_tool_messages([combined_msg])

        assert len(result) == 1
        assert result[0].role == "tool"
        assert result[0].content == "search result text"
        assert result[0].tool_call_id == "call_abc"
        assert result[0].tool_name == "search"

    def test_standard_tool_messages_are_not_modified(self):
        """Standard per-tool messages (OpenAI/Claude style) should pass through unchanged."""
        msg1 = Message(
            role="tool",
            content="result_a",
            tool_call_id="call_1",
            tool_name="tool_a",
        )
        msg2 = Message(
            role="tool",
            content="result_b",
            tool_call_id="call_2",
            tool_name="tool_b",
        )

        result = normalize_tool_messages([msg1, msg2])

        assert len(result) == 2
        assert result[0] is msg1
        assert result[1] is msg2

    def test_non_tool_messages_pass_through(self):
        """User and assistant messages should pass through unchanged."""
        user_msg = Message(role="user", content="Hello")
        assistant_msg = Message(
            role="assistant",
            content="I'll help you.",
            tool_calls=[
                {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "test"}'}},
            ],
        )
        tool_msg = Message(
            role="tool",
            content="search result",
            tool_call_id="call_1",
            tool_name="search",
        )

        result = normalize_tool_messages([user_msg, assistant_msg, tool_msg])

        assert len(result) == 3
        assert result[0] is user_msg
        assert result[1] is assistant_msg
        assert result[2] is tool_msg

    def test_mixed_messages_with_combined_tool(self):
        """A realistic history with user, assistant, and Gemini combined tool messages."""
        messages = [
            Message(role="user", content="What is the weather?"),
            Message(
                role="assistant",
                content="Let me check.",
                tool_calls=[
                    {
                        "id": "call_w1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                    },
                    {
                        "id": "call_w2",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "LA"}'},
                    },
                ],
            ),
            # Gemini-style combined tool result
            Message(
                role="tool",
                content=["NYC: 72F sunny", "LA: 85F clear"],
                tool_name="get_weather, get_weather",
                tool_calls=[
                    {"tool_call_id": "call_w1", "tool_name": "get_weather", "content": "NYC: 72F sunny"},
                    {"tool_call_id": "call_w2", "tool_name": "get_weather", "content": "LA: 85F clear"},
                ],
            ),
            Message(role="assistant", content="NYC is 72F and sunny, LA is 85F and clear."),
        ]

        result = normalize_tool_messages(messages)

        assert len(result) == 5  # user + assistant + 2 tool + assistant

        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[2].role == "tool"
        assert result[2].tool_call_id == "call_w1"
        assert result[2].content == "NYC: 72F sunny"
        assert result[3].role == "tool"
        assert result[3].tool_call_id == "call_w2"
        assert result[3].content == "LA: 85F clear"
        assert result[4].role == "assistant"

    def test_combined_tool_message_with_dict_content(self):
        """Tool content that is a dict should be serialized to JSON string."""
        combined_msg = Message(
            role="tool",
            content=[{"temperature": 72, "condition": "sunny"}],
            tool_name="get_weather",
            tool_calls=[
                {
                    "tool_call_id": "call_1",
                    "tool_name": "get_weather",
                    "content": {"temperature": 72, "condition": "sunny"},
                },
            ],
        )

        result = normalize_tool_messages([combined_msg])

        assert len(result) == 1
        assert result[0].role == "tool"
        assert result[0].tool_call_id == "call_1"
        # Content should be serialized to a JSON string
        parsed = json.loads(result[0].content)
        assert parsed["temperature"] == 72
        assert parsed["condition"] == "sunny"

    def test_combined_tool_message_with_none_content_falls_back_to_list(self):
        """If tool_call content is None, fall back to the content list."""
        combined_msg = Message(
            role="tool",
            content=["fallback result"],
            tool_name="tool_a",
            tool_calls=[
                {"tool_call_id": "call_1", "tool_name": "tool_a", "content": None},
            ],
        )

        result = normalize_tool_messages([combined_msg])

        assert len(result) == 1
        assert result[0].content == "fallback result"
        assert result[0].tool_call_id == "call_1"

    def test_preserves_from_history_flag(self):
        """The from_history flag should be preserved on split messages."""
        combined_msg = Message(
            role="tool",
            content=["result"],
            tool_name="tool_a",
            tool_calls=[
                {"tool_call_id": "call_1", "tool_name": "tool_a", "content": "result"},
            ],
            from_history=True,
        )

        result = normalize_tool_messages([combined_msg])

        assert len(result) == 1
        assert result[0].from_history is True

    def test_empty_messages_list(self):
        """An empty list should return an empty list."""
        result = normalize_tool_messages([])
        assert result == []

    def test_tool_message_with_tool_calls_but_with_tool_call_id_is_not_split(self):
        """A tool message that has tool_call_id set at top level should NOT be split,
        even if it also has tool_calls (this is not the Gemini pattern)."""
        msg = Message(
            role="tool",
            content="result",
            tool_call_id="call_1",
            tool_name="tool_a",
            tool_calls=[{"tool_call_id": "call_1", "tool_name": "tool_a", "content": "result"}],
        )

        result = normalize_tool_messages([msg])

        assert len(result) == 1
        assert result[0] is msg  # Should not be split


class TestCrossProviderSessionCompat:
    """End-to-end test simulating cross-provider session history loading."""

    def test_gemini_session_loaded_by_openai(self):
        """Simulate a Gemini session being loaded for use with OpenAI.

        Gemini stores tool results as combined messages. When OpenAI loads this
        history, the normalize_tool_messages function should expand them so that
        OpenAI's _format_message can process them (expects per-tool messages with
        content=string and tool_call_id at the top level).
        """
        # Simulate session history from Gemini
        gemini_history = [
            Message(role="user", content="Calculate 2+3 and 4*5"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {"id": "call_add", "type": "function", "function": {"name": "add", "arguments": '{"a":2,"b":3}'}},
                    {
                        "id": "call_mul",
                        "type": "function",
                        "function": {"name": "multiply", "arguments": '{"a":4,"b":5}'},
                    },
                ],
            ),
            # Gemini combined tool result
            Message(
                role="tool",
                content=["5", "20"],
                tool_name="add, multiply",
                tool_calls=[
                    {"tool_call_id": "call_add", "tool_name": "add", "content": "5"},
                    {"tool_call_id": "call_mul", "tool_name": "multiply", "content": "20"},
                ],
            ),
            Message(role="assistant", content="2+3=5 and 4*5=20"),
        ]

        # Normalize for OpenAI consumption
        normalized = normalize_tool_messages(gemini_history)

        assert len(normalized) == 5

        # Verify tool messages are now in standard format
        tool_msgs = [m for m in normalized if m.role == "tool"]
        assert len(tool_msgs) == 2

        for tool_msg in tool_msgs:
            # Each tool message must have:
            assert isinstance(tool_msg.content, str), "content must be a string for OpenAI"
            assert tool_msg.tool_call_id is not None, "tool_call_id must be set at top level"
            assert tool_msg.tool_name is not None, "tool_name should be preserved"

    def test_openai_session_loaded_by_gemini_is_unchanged(self):
        """OpenAI-style tool messages should pass through normalization unchanged.

        This ensures that when an OpenAI session is loaded by Gemini (or any other
        provider), the normalization does not modify the standard format.
        """
        openai_history = [
            Message(role="user", content="Calculate 2+3"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {"id": "call_add", "type": "function", "function": {"name": "add", "arguments": '{"a":2,"b":3}'}},
                ],
            ),
            Message(
                role="tool",
                content="5",
                tool_call_id="call_add",
                tool_name="add",
            ),
            Message(role="assistant", content="2+3=5"),
        ]

        normalized = normalize_tool_messages(openai_history)

        assert len(normalized) == 4
        # Tool message should be the same object (not split)
        assert normalized[2] is openai_history[2]
