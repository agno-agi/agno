"""Tests for handling mixed external_execution and regular tools in OpenAI models.

When an agent has a mix of tools where some use external_execution=True and others
don't, format_function_call_results must correctly map tool_call_ids to function call
results. Previously, index-based mapping caused misalignment when external tool calls
were present but not executed (paused), leading to OpenAI API errors like
'No tool output found for function call call_XXX'.
"""

from typing import Dict, List

from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


def _make_assistant_message_with_tool_calls(tool_calls: List[Dict]) -> Message:
    """Helper to create an assistant message with tool_calls."""
    return Message(role="assistant", tool_calls=tool_calls)


class TestFormatFunctionCallResultsMixedTools:
    """Tests for OpenAIResponses.format_function_call_results with mixed tool types."""

    def test_single_regular_tool_call_id_preserved(self):
        """A single regular tool result should keep its fc_* id (translation happens at runtime)."""
        model = OpenAIResponses(id="gpt-4o")

        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_regular",
                    "call_id": "call_regular",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="hello"),
            assistant_msg,
        ]

        # Result message uses fc_id (as set by create_function_call_result)
        result = Message(role="tool", tool_call_id="fc_regular", content="August 1st, 2024")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[result],
            tool_call_ids=["call_regular"],
        )

        # fc_* id should be preserved — translation to call_* happens at runtime in _format_messages
        assert result.tool_call_id == "fc_regular"
        assert messages[-1] is result

    def test_mixed_external_and_regular_tool_correct_mapping(self):
        """When both external and regular tool calls exist, regular results get correct call_ids.

        This is the core bug fix: previously, index-based mapping would assign the
        external tool's call_id to the regular tool's result when the external tool
        appeared first in the tool_call_ids list.
        """
        model = OpenAIResponses(id="gpt-4o")

        # Assistant message has two tool calls: one external (first) and one regular (second)
        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_external",
                    "call_id": "call_external",
                    "type": "function",
                    "function": {"name": "get_user_location", "arguments": '{"reason": "weather"}'},
                },
                {
                    "id": "fc_regular",
                    "call_id": "call_regular",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="What is the weather?"),
            assistant_msg,
        ]

        # Only the regular tool was executed (external was paused)
        regular_result = Message(role="tool", tool_call_id="fc_regular", content="August 1st, 2024")

        # tool_call_ids from the full response includes BOTH tools
        model.format_function_call_results(
            messages=messages,
            function_call_results=[regular_result],
            tool_call_ids=["call_external", "call_regular"],
        )

        # fc_* id should be preserved — translation to call_* happens at runtime in _format_messages
        assert regular_result.tool_call_id == "fc_regular"

    def test_mixed_tools_reverse_order(self):
        """Regular tool first, external tool second - fc_* ids preserved."""
        model = OpenAIResponses(id="gpt-4o")

        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_regular",
                    "call_id": "call_regular",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
                {
                    "id": "fc_external",
                    "call_id": "call_external",
                    "type": "function",
                    "function": {"name": "get_user_location", "arguments": '{"reason": "weather"}'},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="What is the weather?"),
            assistant_msg,
        ]

        regular_result = Message(role="tool", tool_call_id="fc_regular", content="August 1st, 2024")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[regular_result],
            tool_call_ids=["call_regular", "call_external"],
        )

        assert regular_result.tool_call_id == "fc_regular"

    def test_multiple_regular_tools_with_external(self):
        """Multiple regular tools plus one external tool - fc_* ids preserved."""
        model = OpenAIResponses(id="gpt-4o")

        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_external",
                    "call_id": "call_external",
                    "type": "function",
                    "function": {"name": "get_user_location", "arguments": "{}"},
                },
                {
                    "id": "fc_date",
                    "call_id": "call_date",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
                {
                    "id": "fc_time",
                    "call_id": "call_time",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="What time is it?"),
            assistant_msg,
        ]

        date_result = Message(role="tool", tool_call_id="fc_date", content="August 1st, 2024")
        time_result = Message(role="tool", tool_call_id="fc_time", content="14:30 UTC")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[date_result, time_result],
            tool_call_ids=["call_external", "call_date", "call_time"],
        )

        assert date_result.tool_call_id == "fc_date"
        assert time_result.tool_call_id == "fc_time"

    def test_all_regular_tools_no_regression(self):
        """All regular tools (no external) - fc_* ids preserved."""
        model = OpenAIResponses(id="gpt-4o")

        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_date",
                    "call_id": "call_date",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
                {
                    "id": "fc_time",
                    "call_id": "call_time",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="What time is it?"),
            assistant_msg,
        ]

        date_result = Message(role="tool", tool_call_id="fc_date", content="August 1st, 2024")
        time_result = Message(role="tool", tool_call_id="fc_time", content="14:30 UTC")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[date_result, time_result],
            tool_call_ids=["call_date", "call_time"],
        )

        assert date_result.tool_call_id == "fc_date"
        assert time_result.tool_call_id == "fc_time"

    def test_result_with_call_id_already_set(self):
        """If a result already has a call_id (not fc_id), it should not be corrupted."""
        model = OpenAIResponses(id="gpt-4o")

        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_abc",
                    "call_id": "call_abc",
                    "type": "function",
                    "function": {"name": "my_tool", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="test"),
            assistant_msg,
        ]

        # Result already has call_id format (not in fc_id_to_call_id mapping)
        result = Message(role="tool", tool_call_id="call_abc", content="done")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[result],
            tool_call_ids=["call_abc"],
        )

        # Should remain unchanged
        assert result.tool_call_id == "call_abc"

    def test_empty_function_call_results(self):
        """No results (all tools paused) should not crash."""
        model = OpenAIResponses(id="gpt-4o")

        messages: List[Message] = [
            Message(role="user", content="test"),
        ]
        initial_len = len(messages)

        model.format_function_call_results(
            messages=messages,
            function_call_results=[],
            tool_call_ids=["call_external"],
        )

        # No messages should have been added
        assert len(messages) == initial_len

    def test_format_messages_produces_correct_output_after_fix(self):
        """End-to-end: after format_function_call_results, _format_messages should produce
        correct function_call_output items with the right call_ids.
        """
        model = OpenAIResponses(id="gpt-4o")

        assistant_msg = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_external",
                    "call_id": "call_external",
                    "type": "function",
                    "function": {"name": "get_user_location", "arguments": '{"reason": "weather"}'},
                },
                {
                    "id": "fc_regular",
                    "call_id": "call_regular",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="What is the weather?"),
            assistant_msg,
        ]

        regular_result = Message(role="tool", tool_call_id="fc_regular", content="August 1st, 2024")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[regular_result],
            tool_call_ids=["call_external", "call_regular"],
        )

        formatted = model._format_messages(messages)

        # Find the function_call_output items
        outputs = [item for item in formatted if isinstance(item, dict) and item.get("type") == "function_call_output"]

        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_regular"
        assert outputs[0]["output"] == "August 1st, 2024"

    def test_multi_turn_conversation_maps_correctly(self):
        """In a multi-turn conversation, tool_call_id mapping should use the correct
        assistant message's tool_calls without collisions across turns.
        """
        model = OpenAIResponses(id="gpt-4o")

        # Turn 1: assistant called get_date
        turn1_assistant = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_turn1_date",
                    "call_id": "call_turn1_date",
                    "type": "function",
                    "function": {"name": "get_date", "arguments": "{}"},
                },
            ]
        )
        turn1_result = Message(role="tool", tool_call_id="call_turn1_date", content="August 1st, 2024")

        # Turn 2: assistant calls both external + regular
        turn2_assistant = _make_assistant_message_with_tool_calls(
            [
                {
                    "id": "fc_external",
                    "call_id": "call_external",
                    "type": "function",
                    "function": {"name": "get_user_location", "arguments": "{}"},
                },
                {
                    "id": "fc_regular",
                    "call_id": "call_regular",
                    "type": "function",
                    "function": {"name": "get_time", "arguments": "{}"},
                },
            ]
        )

        messages: List[Message] = [
            Message(role="user", content="What date is it?"),
            turn1_assistant,
            turn1_result,
            Message(role="assistant", content="Today is August 1st, 2024."),
            Message(role="user", content="What time is it in my location?"),
            turn2_assistant,
        ]

        # Only the regular tool from turn 2 was executed
        regular_result = Message(role="tool", tool_call_id="fc_regular", content="14:30 UTC")

        model.format_function_call_results(
            messages=messages,
            function_call_results=[regular_result],
            tool_call_ids=["call_external", "call_regular"],
        )

        # fc_* id should be preserved — translation to call_* happens at runtime in _format_messages
        assert regular_result.tool_call_id == "fc_regular"


class TestBuildFcIdToCallIdMap:
    """Tests for the _build_fc_id_to_call_id_map helper method."""

    def test_builds_mapping_from_assistant_tool_calls(self):
        """Should extract fc_id -> call_id pairs from assistant messages."""
        model = OpenAIResponses(id="gpt-4o")

        messages = [
            Message(role="user", content="test"),
            _make_assistant_message_with_tool_calls(
                [
                    {
                        "id": "fc_abc",
                        "call_id": "call_abc",
                        "type": "function",
                        "function": {"name": "t", "arguments": "{}"},
                    },
                    {
                        "id": "fc_def",
                        "call_id": "call_def",
                        "type": "function",
                        "function": {"name": "t", "arguments": "{}"},
                    },
                ]
            ),
        ]

        mapping = model._build_fc_id_to_call_id_map(messages)

        assert mapping == {"fc_abc": "call_abc", "fc_def": "call_def"}

    def test_empty_messages_returns_empty_map(self):
        """No messages should produce an empty mapping."""
        model = OpenAIResponses(id="gpt-4o")
        assert model._build_fc_id_to_call_id_map([]) == {}

    def test_messages_without_tool_calls_returns_empty_map(self):
        """Messages with no tool_calls should produce an empty mapping."""
        model = OpenAIResponses(id="gpt-4o")
        messages = [Message(role="user", content="hello"), Message(role="assistant", content="hi")]
        assert model._build_fc_id_to_call_id_map(messages) == {}

    def test_falls_back_to_fc_id_when_no_call_id(self):
        """When call_id is missing, fc_id should map to itself."""
        model = OpenAIResponses(id="gpt-4o")

        messages = [
            _make_assistant_message_with_tool_calls(
                [{"id": "fc_abc", "type": "function", "function": {"name": "t", "arguments": "{}"}}]
            ),
        ]

        mapping = model._build_fc_id_to_call_id_map(messages)
        assert mapping == {"fc_abc": "fc_abc"}
