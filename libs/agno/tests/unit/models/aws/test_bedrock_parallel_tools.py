"""Unit tests for batching toolResult blocks for parallel tool calls in AWS Bedrock."""

from agno.models.aws import AwsBedrock
from agno.models.message import Message
from agno.utils.models.claude import format_messages

# ===========================================================================
# Tests for AwsBedrock._format_messages (raw Bedrock Converse API)
# ===========================================================================


class TestAwsBedrockParallelToolResults:
    """Test that AwsBedrock._format_messages batches consecutive tool results."""

    def test_single_tool_result_unchanged(self):
        """A single tool result should produce one user message."""
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        messages = [
            Message(role="user", content="What is 2+3?"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "tool_1",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"x": 2, "y": 3}'},
                    }
                ],
            ),
            Message(role="tool", content="5", tool_call_id="tool_1"),
        ]
        formatted, _ = model._format_messages(messages)

        # Should have: user, assistant, user(tool_result)
        assert len(formatted) == 3
        assert formatted[2]["role"] == "user"
        assert len(formatted[2]["content"]) == 1
        assert "toolResult" in formatted[2]["content"][0]
        assert formatted[2]["content"][0]["toolResult"]["toolUseId"] == "tool_1"

    def test_parallel_tool_results_batched(self):
        """Multiple consecutive tool results should be batched into one user message."""
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        messages = [
            Message(role="user", content="Add 2+3 and multiply 4*5"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "tool_1",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"x": 2, "y": 3}'},
                    },
                    {
                        "id": "tool_2",
                        "type": "function",
                        "function": {"name": "multiply", "arguments": '{"x": 4, "y": 5}'},
                    },
                ],
            ),
            Message(role="tool", content="5", tool_call_id="tool_1"),
            Message(role="tool", content="20", tool_call_id="tool_2"),
        ]
        formatted, _ = model._format_messages(messages)

        # Should have: user, assistant, user(2 tool_results batched)
        assert len(formatted) == 3
        assert formatted[2]["role"] == "user"
        assert len(formatted[2]["content"]) == 2
        assert formatted[2]["content"][0]["toolResult"]["toolUseId"] == "tool_1"
        assert formatted[2]["content"][1]["toolResult"]["toolUseId"] == "tool_2"

    def test_three_parallel_tool_results_batched(self):
        """Three consecutive tool results should all be batched into one message."""
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        messages = [
            Message(role="user", content="Do three things"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "tool_a",
                        "type": "function",
                        "function": {"name": "func_a", "arguments": "{}"},
                    },
                    {
                        "id": "tool_b",
                        "type": "function",
                        "function": {"name": "func_b", "arguments": "{}"},
                    },
                    {
                        "id": "tool_c",
                        "type": "function",
                        "function": {"name": "func_c", "arguments": "{}"},
                    },
                ],
            ),
            Message(role="tool", content="result_a", tool_call_id="tool_a"),
            Message(role="tool", content="result_b", tool_call_id="tool_b"),
            Message(role="tool", content="result_c", tool_call_id="tool_c"),
        ]
        formatted, _ = model._format_messages(messages)

        assert len(formatted) == 3
        assert formatted[2]["role"] == "user"
        assert len(formatted[2]["content"]) == 3
        assert formatted[2]["content"][0]["toolResult"]["toolUseId"] == "tool_a"
        assert formatted[2]["content"][1]["toolResult"]["toolUseId"] == "tool_b"
        assert formatted[2]["content"][2]["toolResult"]["toolUseId"] == "tool_c"

    def test_sequential_tool_calls_not_batched(self):
        """Tool results from separate rounds should NOT be batched together."""
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        messages = [
            Message(role="user", content="Step 1"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "tool_1",
                        "type": "function",
                        "function": {"name": "step1", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="result_1", tool_call_id="tool_1"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "tool_2",
                        "type": "function",
                        "function": {"name": "step2", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="result_2", tool_call_id="tool_2"),
        ]
        formatted, _ = model._format_messages(messages)

        # Should have: user, assistant, user(tool_1), assistant, user(tool_2)
        assert len(formatted) == 5
        assert formatted[2]["role"] == "user"
        assert len(formatted[2]["content"]) == 1
        assert formatted[2]["content"][0]["toolResult"]["toolUseId"] == "tool_1"
        assert formatted[4]["role"] == "user"
        assert len(formatted[4]["content"]) == 1
        assert formatted[4]["content"][0]["toolResult"]["toolUseId"] == "tool_2"

    def test_tool_result_content_preserved(self):
        """Tool result content should be correctly preserved when batching."""
        model = AwsBedrock(id="anthropic.claude-3-sonnet-20240229-v1:0")
        messages = [
            Message(role="user", content="Get data"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "tool_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                    },
                    {
                        "id": "tool_2",
                        "type": "function",
                        "function": {"name": "get_time", "arguments": '{"tz": "EST"}'},
                    },
                ],
            ),
            Message(role="tool", content="Sunny, 72F", tool_call_id="tool_1"),
            Message(role="tool", content="3:00 PM", tool_call_id="tool_2"),
        ]
        formatted, _ = model._format_messages(messages)

        batched = formatted[2]
        assert batched["content"][0]["toolResult"]["content"] == [{"json": {"result": "Sunny, 72F"}}]
        assert batched["content"][1]["toolResult"]["content"] == [{"json": {"result": "3:00 PM"}}]


# ===========================================================================
# Tests for format_messages (Anthropic SDK / aws.Claude)
# ===========================================================================


class TestClaudeFormatMessagesParallelToolResults:
    """Test that format_messages batches consecutive tool results for Claude."""

    def test_single_tool_result_unchanged(self):
        """A single tool result should produce one user message."""
        messages = [
            Message(role="user", content="What is 2+3?"),
            Message(
                role="assistant",
                content="Let me calculate.",
                tool_calls=[
                    {
                        "id": "toolu_01",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"x": 2, "y": 3}'},
                    }
                ],
            ),
            Message(role="tool", content="5", tool_call_id="toolu_01"),
        ]
        chat_messages, _ = format_messages(messages)

        # user, assistant, user(tool_result)
        assert len(chat_messages) == 3
        assert chat_messages[2]["role"] == "user"
        assert len(chat_messages[2]["content"]) == 1
        assert chat_messages[2]["content"][0]["type"] == "tool_result"
        assert chat_messages[2]["content"][0]["tool_use_id"] == "toolu_01"

    def test_parallel_tool_results_batched(self):
        """Multiple consecutive tool results should be batched into one user message."""
        messages = [
            Message(role="user", content="Add 2+3 and multiply 4*5"),
            Message(
                role="assistant",
                content="I will call both tools.",
                tool_calls=[
                    {
                        "id": "toolu_01",
                        "type": "function",
                        "function": {"name": "add", "arguments": '{"x": 2, "y": 3}'},
                    },
                    {
                        "id": "toolu_02",
                        "type": "function",
                        "function": {"name": "multiply", "arguments": '{"x": 4, "y": 5}'},
                    },
                ],
            ),
            Message(role="tool", content="5", tool_call_id="toolu_01"),
            Message(role="tool", content="20", tool_call_id="toolu_02"),
        ]
        chat_messages, _ = format_messages(messages)

        # user, assistant, user(2 tool_results batched)
        assert len(chat_messages) == 3
        assert chat_messages[2]["role"] == "user"
        assert len(chat_messages[2]["content"]) == 2
        assert chat_messages[2]["content"][0]["type"] == "tool_result"
        assert chat_messages[2]["content"][0]["tool_use_id"] == "toolu_01"
        assert chat_messages[2]["content"][1]["type"] == "tool_result"
        assert chat_messages[2]["content"][1]["tool_use_id"] == "toolu_02"

    def test_three_parallel_tool_results_batched(self):
        """Three consecutive tool results should all be batched into one message."""
        messages = [
            Message(role="user", content="Do three things"),
            Message(
                role="assistant",
                content="Calling three tools.",
                tool_calls=[
                    {
                        "id": "toolu_a",
                        "type": "function",
                        "function": {"name": "func_a", "arguments": "{}"},
                    },
                    {
                        "id": "toolu_b",
                        "type": "function",
                        "function": {"name": "func_b", "arguments": "{}"},
                    },
                    {
                        "id": "toolu_c",
                        "type": "function",
                        "function": {"name": "func_c", "arguments": "{}"},
                    },
                ],
            ),
            Message(role="tool", content="result_a", tool_call_id="toolu_a"),
            Message(role="tool", content="result_b", tool_call_id="toolu_b"),
            Message(role="tool", content="result_c", tool_call_id="toolu_c"),
        ]
        chat_messages, _ = format_messages(messages)

        assert len(chat_messages) == 3
        assert chat_messages[2]["role"] == "user"
        assert len(chat_messages[2]["content"]) == 3
        assert chat_messages[2]["content"][0]["tool_use_id"] == "toolu_a"
        assert chat_messages[2]["content"][1]["tool_use_id"] == "toolu_b"
        assert chat_messages[2]["content"][2]["tool_use_id"] == "toolu_c"

    def test_sequential_tool_calls_not_batched(self):
        """Tool results from separate rounds should NOT be batched together."""
        messages = [
            Message(role="user", content="Step 1"),
            Message(
                role="assistant",
                content="Calling step 1.",
                tool_calls=[
                    {
                        "id": "toolu_01",
                        "type": "function",
                        "function": {"name": "step1", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="result_1", tool_call_id="toolu_01"),
            Message(
                role="assistant",
                content="Now step 2.",
                tool_calls=[
                    {
                        "id": "toolu_02",
                        "type": "function",
                        "function": {"name": "step2", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="result_2", tool_call_id="toolu_02"),
        ]
        chat_messages, _ = format_messages(messages)

        # user, assistant, user(tool_1), assistant, user(tool_2)
        assert len(chat_messages) == 5
        assert chat_messages[2]["role"] == "user"
        assert len(chat_messages[2]["content"]) == 1
        assert chat_messages[2]["content"][0]["tool_use_id"] == "toolu_01"
        assert chat_messages[4]["role"] == "user"
        assert len(chat_messages[4]["content"]) == 1
        assert chat_messages[4]["content"][0]["tool_use_id"] == "toolu_02"

    def test_tool_result_content_preserved(self):
        """Tool result content should be correctly preserved when batching."""
        messages = [
            Message(role="user", content="Get data"),
            Message(
                role="assistant",
                content="Calling tools.",
                tool_calls=[
                    {
                        "id": "toolu_w",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
                    },
                    {
                        "id": "toolu_t",
                        "type": "function",
                        "function": {"name": "get_time", "arguments": '{"tz": "EST"}'},
                    },
                ],
            ),
            Message(role="tool", content="Sunny, 72F", tool_call_id="toolu_w"),
            Message(role="tool", content="3:00 PM", tool_call_id="toolu_t"),
        ]
        chat_messages, _ = format_messages(messages)

        batched = chat_messages[2]
        assert batched["content"][0]["content"] == "Sunny, 72F"
        assert batched["content"][1]["content"] == "3:00 PM"

    def test_compress_tool_results_with_batching(self):
        """Batching should work correctly with compressed tool results."""
        messages = [
            Message(role="user", content="Get data"),
            Message(
                role="assistant",
                content="Calling tools.",
                tool_calls=[
                    {
                        "id": "toolu_1",
                        "type": "function",
                        "function": {"name": "func1", "arguments": "{}"},
                    },
                    {
                        "id": "toolu_2",
                        "type": "function",
                        "function": {"name": "func2", "arguments": "{}"},
                    },
                ],
            ),
            Message(role="tool", content="long result 1", compressed_content="short 1", tool_call_id="toolu_1"),
            Message(role="tool", content="long result 2", compressed_content="short 2", tool_call_id="toolu_2"),
        ]
        chat_messages, _ = format_messages(messages, compress_tool_results=True)

        # Should still batch
        assert len(chat_messages) == 3
        assert len(chat_messages[2]["content"]) == 2
        assert chat_messages[2]["content"][0]["content"] == "short 1"
        assert chat_messages[2]["content"][1]["content"] == "short 2"
