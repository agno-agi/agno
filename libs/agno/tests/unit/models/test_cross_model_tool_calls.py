"""Tests for cross-model tool call ID reformatting and normalization.

Covers reformat_tool_call_ids, normalize_tool_messages, and parallel tool calls
across OpenAI Chat (call_*), OpenAI Responses (fc_*/call_*), Claude (toolu_*),
and Gemini (UUID-style) ID formats.
"""

from agno.models.message import Message
from agno.utils.message import normalize_tool_messages, reformat_tool_call_ids

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assistant_msg(tool_calls):
    """Create an assistant message with the given tool_calls list."""
    return Message(role="assistant", content="", tool_calls=tool_calls)


def _tool_msg(tool_call_id, tool_name="get_weather", content="Sunny 22C"):
    """Create a canonical tool result message."""
    return Message(role="tool", tool_call_id=tool_call_id, tool_name=tool_name, content=content)


def _make_tool_call(tc_id, name="get_weather", arguments='{"city": "Paris"}', call_id=None):
    """Create a tool_call dict matching the canonical format."""
    tc = {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }
    if call_id is not None:
        tc["call_id"] = call_id
    return tc


# ---------------------------------------------------------------------------
# reformat_tool_call_ids — single tool call
# ---------------------------------------------------------------------------


class TestReformatToolCallIds:
    def test_noop_when_prefix_matches(self):
        """IDs already matching target prefix should not be remapped."""
        tc = _make_tool_call("call_abc123")
        msgs = [_assistant_msg([tc]), _tool_msg("call_abc123")]
        result = reformat_tool_call_ids(msgs, provider="openai_chat")
        assert result[0].tool_calls[0]["id"] == "call_abc123"
        assert result[1].tool_call_id == "call_abc123"

    def test_remap_claude_to_openai_chat(self):
        """Claude toolu_* IDs should be remapped to call_* for OpenAI Chat."""
        tc = _make_tool_call("toolu_01ABC")
        msgs = [_assistant_msg([tc]), _tool_msg("toolu_01ABC")]
        result = reformat_tool_call_ids(msgs, provider="openai_chat")
        assert result[0].tool_calls[0]["id"].startswith("call_")
        assert result[1].tool_call_id == result[0].tool_calls[0]["id"]

    def test_remap_openai_chat_to_responses(self):
        """OpenAI Chat call_* IDs should be remapped to fc_* for Responses API."""
        tc = _make_tool_call("call_xyz789")
        msgs = [_assistant_msg([tc]), _tool_msg("call_xyz789")]
        result = reformat_tool_call_ids(msgs, provider="openai_responses")
        assert result[0].tool_calls[0]["id"].startswith("fc_")
        # Responses API also needs call_id
        assert result[0].tool_calls[0]["call_id"].startswith("call_")
        assert result[1].tool_call_id == result[0].tool_calls[0]["id"]

    def test_remap_gemini_uuid_to_claude(self):
        """Gemini UUID-style IDs should be remapped to toolu_* for Claude."""
        tc = _make_tool_call("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        msgs = [_assistant_msg([tc]), _tool_msg("a1b2c3d4-e5f6-7890-abcd-ef1234567890")]
        result = reformat_tool_call_ids(msgs, provider="claude")
        assert result[0].tool_calls[0]["id"].startswith("toolu_")
        assert result[1].tool_call_id == result[0].tool_calls[0]["id"]

    def test_gemini_provider_is_noop(self):
        """Gemini accepts any ID format, so no reformatting should happen."""
        tc = _make_tool_call("call_abc123")
        msgs = [_assistant_msg([tc]), _tool_msg("call_abc123")]
        result = reformat_tool_call_ids(msgs, provider="gemini")
        assert result[0].tool_calls[0]["id"] == "call_abc123"
        assert result is msgs  # Should return the same list object

    def test_unknown_provider_is_noop(self):
        """Unknown provider should pass through unchanged."""
        tc = _make_tool_call("call_abc123")
        msgs = [_assistant_msg([tc]), _tool_msg("call_abc123")]
        result = reformat_tool_call_ids(msgs, provider="unknown_provider")
        assert result is msgs

    def test_empty_messages(self):
        """Empty message list should return empty."""
        assert reformat_tool_call_ids([], provider="openai_chat") == []

    def test_no_tool_calls(self):
        """Messages without tool calls should pass through unchanged."""
        msgs = [Message(role="user", content="Hello"), Message(role="assistant", content="Hi")]
        result = reformat_tool_call_ids(msgs, provider="openai_chat")
        assert len(result) == 2
        assert result[0].content == "Hello"

    def test_does_not_mutate_original(self):
        """Remapping should not modify the original messages."""
        tc = _make_tool_call("toolu_01ABC")
        msgs = [_assistant_msg([tc]), _tool_msg("toolu_01ABC")]
        reformat_tool_call_ids(msgs, provider="openai_chat")
        assert msgs[0].tool_calls[0]["id"] == "toolu_01ABC"
        assert msgs[1].tool_call_id == "toolu_01ABC"

    def test_max_length_triggers_reformat(self):
        """IDs that match the prefix but exceed max_length should be reformatted."""
        # OpenAI Chat has max_length=40. Create a call_* ID that's too long.
        long_id = "call_" + "a" * 40  # 45 chars, exceeds 40
        tc = _make_tool_call(long_id)
        msgs = [_assistant_msg([tc]), _tool_msg(long_id)]
        result = reformat_tool_call_ids(msgs, provider="openai_chat")
        new_id = result[0].tool_calls[0]["id"]
        assert new_id.startswith("call_")
        assert len(new_id) <= 40
        assert result[1].tool_call_id == new_id


# ---------------------------------------------------------------------------
# reformat_tool_call_ids — parallel tool calls
# ---------------------------------------------------------------------------


class TestReformatParallelToolCalls:
    def test_parallel_tool_calls_all_remapped(self):
        """Multiple tool calls in one assistant message should all be remapped."""
        tcs = [
            _make_tool_call("toolu_001", name="get_weather", arguments='{"city": "Paris"}'),
            _make_tool_call("toolu_002", name="get_weather", arguments='{"city": "London"}'),
            _make_tool_call("toolu_003", name="get_weather", arguments='{"city": "Tokyo"}'),
        ]
        msgs = [
            _assistant_msg(tcs),
            _tool_msg("toolu_001", content="Paris: Sunny"),
            _tool_msg("toolu_002", content="London: Rainy"),
            _tool_msg("toolu_003", content="Tokyo: Cloudy"),
        ]
        result = reformat_tool_call_ids(msgs, provider="openai_chat")

        # All 3 assistant tool_calls should have new call_* IDs
        new_ids = [tc["id"] for tc in result[0].tool_calls]
        assert all(id_.startswith("call_") for id_ in new_ids)
        # All IDs should be unique
        assert len(set(new_ids)) == 3

        # Each tool result should match its corresponding assistant tool_call
        for i in range(3):
            assert result[i + 1].tool_call_id == new_ids[i]

    def test_parallel_tool_calls_to_responses_api(self):
        """Parallel tool calls remapped to fc_* should also get call_id."""
        tcs = [
            _make_tool_call("call_aaa", name="search"),
            _make_tool_call("call_bbb", name="calculate"),
        ]
        msgs = [
            _assistant_msg(tcs),
            _tool_msg("call_aaa", tool_name="search", content="result1"),
            _tool_msg("call_bbb", tool_name="calculate", content="result2"),
        ]
        result = reformat_tool_call_ids(msgs, provider="openai_responses")

        for tc in result[0].tool_calls:
            assert tc["id"].startswith("fc_")
            assert tc["call_id"].startswith("call_")
            assert tc["id"] != tc["call_id"]

    def test_parallel_mixed_providers_in_history(self):
        """History with tool calls from different providers should all be remapped."""
        # Turn 1: OpenAI Chat
        tc1 = _make_tool_call("call_111", name="get_weather", arguments='{"city": "Paris"}')
        # Turn 2: Claude
        tc2 = _make_tool_call("toolu_222", name="get_weather", arguments='{"city": "London"}')
        # Turn 3: Gemini
        tc3 = _make_tool_call("uuid-333-abc", name="get_weather", arguments='{"city": "Tokyo"}')

        msgs = [
            _assistant_msg([tc1]),
            _tool_msg("call_111", content="Paris: Sunny"),
            Message(role="user", content="Now check London"),
            _assistant_msg([tc2]),
            _tool_msg("toolu_222", content="London: Rainy"),
            Message(role="user", content="And Tokyo"),
            _assistant_msg([tc3]),
            _tool_msg("uuid-333-abc", content="Tokyo: Cloudy"),
        ]

        # Remap all to call_* (for OpenAI Chat)
        result = reformat_tool_call_ids(msgs, provider="openai_chat")

        # call_111 should stay (already has prefix and under max_length)
        assert result[0].tool_calls[0]["id"] == "call_111"
        assert result[1].tool_call_id == "call_111"

        # toolu_222 should be remapped
        assert result[3].tool_calls[0]["id"].startswith("call_")
        assert result[3].tool_calls[0]["id"] != "call_111"
        assert result[4].tool_call_id == result[3].tool_calls[0]["id"]

        # uuid-333-abc should be remapped
        assert result[6].tool_calls[0]["id"].startswith("call_")
        assert result[7].tool_call_id == result[6].tool_calls[0]["id"]

        # All new IDs should be unique
        all_ids = [result[0].tool_calls[0]["id"], result[3].tool_calls[0]["id"], result[6].tool_calls[0]["id"]]
        assert len(set(all_ids)) == 3


# ---------------------------------------------------------------------------
# reformat_tool_call_ids — Responses API dual-ID (fc_*/call_*)
# ---------------------------------------------------------------------------


class TestReformatResponsesApiDualId:
    def test_remap_with_existing_call_id(self):
        """When tool_call has both id and call_id, both should be mapped."""
        tc = _make_tool_call("fc_original123", call_id="call_original456")
        msgs = [_assistant_msg([tc]), _tool_msg("call_original456")]

        # Remap to call_* for OpenAI Chat
        result = reformat_tool_call_ids(msgs, provider="openai_chat")
        new_id = result[0].tool_calls[0]["id"]
        assert new_id.startswith("call_")
        # Tool result referenced call_id, should now match new_id
        assert result[1].tool_call_id == new_id

    def test_remap_responses_to_claude(self):
        """Responses API fc_*/call_* should both map to same toolu_* ID."""
        tc = _make_tool_call("fc_abc", call_id="call_def")
        msgs = [
            _assistant_msg([tc]),
            _tool_msg("call_def"),
        ]
        result = reformat_tool_call_ids(msgs, provider="claude")
        new_id = result[0].tool_calls[0]["id"]
        assert new_id.startswith("toolu_")
        # Tool result should match even though it referenced call_id
        assert result[1].tool_call_id == new_id


# ---------------------------------------------------------------------------
# Claude format_messages — tool result merging
# ---------------------------------------------------------------------------


class TestClaudeFormatMessages:
    def test_parallel_tool_results_merged_into_single_user(self):
        """Multiple consecutive tool results should merge into one user message for Claude."""
        from agno.utils.models.claude import format_messages

        tc1 = _make_tool_call("toolu_001", name="get_weather", arguments='{"city": "Paris"}')
        tc2 = _make_tool_call("toolu_002", name="get_weather", arguments='{"city": "London"}')

        msgs = [
            Message(role="user", content="Check weather in Paris and London"),
            _assistant_msg([tc1, tc2]),
            _tool_msg("toolu_001", content="Paris: Sunny"),
            _tool_msg("toolu_002", content="London: Rainy"),
        ]
        formatted, system = format_messages(msgs)

        # Should be: user, assistant, user (merged tool results)
        assert len(formatted) == 3
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "assistant"
        assert formatted[2]["role"] == "user"

        # Merged user message should contain both tool_results
        content = formatted[2]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert all(item["type"] == "tool_result" for item in content)
        tool_use_ids = {item["tool_use_id"] for item in content}
        assert tool_use_ids == {"toolu_001", "toolu_002"}

    def test_cross_provider_ids_passed_through_for_claude(self):
        """Claude should handle tool calls from Responses API (fc_* IDs) directly."""
        from agno.utils.models.claude import format_messages

        tc = _make_tool_call("fc_abc", call_id="call_xyz")
        msgs = [
            Message(role="user", content="Hello"),
            _assistant_msg([tc]),
            # Tool results now store fc_* (matching assistant id), no translation at storage time
            _tool_msg("fc_abc", content="Result"),
        ]
        formatted, system = format_messages(msgs)

        # Tool result should match assistant's id directly
        tool_result = formatted[2]["content"][0]
        assert tool_result["tool_use_id"] == "fc_abc"


# ---------------------------------------------------------------------------
# Gemini format — individual tool messages
# ---------------------------------------------------------------------------


class TestGeminiFormatMessages:
    def test_individual_tool_msg_formatted(self):
        """Gemini should format individual canonical tool messages correctly."""
        from agno.models.google.gemini import Gemini

        gemini = Gemini(id="gemini-2.0-flash")
        tc = _make_tool_call("toolu_001", name="get_weather")

        msgs = [
            Message(role="user", content="Check weather"),
            Message(role="assistant", content="", tool_calls=[tc]),
            _tool_msg("toolu_001", tool_name="get_weather", content="Sunny"),
        ]
        formatted, system = gemini._format_messages(msgs)

        # Tool result should create a Part.from_function_response
        # Find the "user" content that has function response
        tool_content = None
        for msg in formatted:
            if msg.role == "user":
                for part in msg.parts:
                    if hasattr(part, "function_response") and part.function_response is not None:
                        tool_content = part
        assert tool_content is not None

    def test_missing_tool_name_falls_through(self):
        """Tool message without tool_name should not crash Gemini."""
        from agno.models.google.gemini import Gemini

        gemini = Gemini(id="gemini-2.0-flash")
        msgs = [
            Message(role="user", content="Check weather"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    _make_tool_call("toolu_001", name="get_weather"),
                ],
            ),
            Message(role="tool", tool_call_id="toolu_001", tool_name=None, content="Sunny"),
        ]
        # Should not raise
        formatted, system = gemini._format_messages(msgs)
        assert len(formatted) > 0

    def test_missing_arguments_handled(self):
        """Tool call with missing arguments should not crash Gemini."""
        from agno.models.google.gemini import Gemini

        gemini = Gemini(id="gemini-2.0-flash")
        tc = {
            "id": "toolu_001",
            "type": "function",
            "function": {"name": "get_status"},  # No "arguments" key
        }
        msgs = [
            Message(role="user", content="Check status"),
            Message(role="assistant", content="", tool_calls=[tc]),
            _tool_msg("toolu_001", tool_name="get_status", content="OK"),
        ]
        formatted, system = gemini._format_messages(msgs)
        # Should format without crashing
        assert len(formatted) > 0


# ---------------------------------------------------------------------------
# normalize_tool_messages — backwards compat for old Gemini combined format
# ---------------------------------------------------------------------------


class TestNormalizeToolMessages:
    def test_splits_combined_format(self):
        """Old Gemini combined tool message should be split into individual canonical messages."""
        combined = Message(
            role="tool",
            content=["Paris: Sunny", "London: Rainy"],
            tool_calls=[
                {"tool_call_id": "id_001", "tool_name": "get_weather", "content": "Paris: Sunny"},
                {"tool_call_id": "id_002", "tool_name": "get_weather", "content": "London: Rainy"},
            ],
        )
        result = normalize_tool_messages([combined])
        assert len(result) == 2
        assert result[0].role == "tool"
        assert result[0].tool_call_id == "id_001"
        assert result[0].tool_name == "get_weather"
        assert result[0].content == "Paris: Sunny"
        assert result[1].tool_call_id == "id_002"
        assert result[1].content == "London: Rainy"

    def test_passthrough_canonical_messages(self):
        """Canonical individual tool messages should pass through unchanged."""
        msgs = [
            _tool_msg("id_001", content="result1"),
            _tool_msg("id_002", content="result2"),
        ]
        result = normalize_tool_messages(msgs)
        assert len(result) == 2
        assert result[0].tool_call_id == "id_001"
        assert result[1].tool_call_id == "id_002"

    def test_mixed_combined_and_canonical(self):
        """Mix of combined and canonical messages should be handled."""
        combined = Message(
            role="tool",
            content=["result1", "result2"],
            tool_calls=[
                {"tool_call_id": "id_001", "tool_name": "func1", "content": "result1"},
                {"tool_call_id": "id_002", "tool_name": "func2", "content": "result2"},
            ],
        )
        canonical = _tool_msg("id_003", content="result3")
        user_msg = Message(role="user", content="Hello")

        result = normalize_tool_messages([user_msg, combined, canonical])
        assert len(result) == 4  # user + 2 split + 1 canonical
        assert result[0].role == "user"
        assert result[1].tool_call_id == "id_001"
        assert result[2].tool_call_id == "id_002"
        assert result[3].tool_call_id == "id_003"

    def test_preserves_metrics_on_first(self):
        """Metrics from combined message should be preserved on first split message only."""
        from agno.models.metrics import MessageMetrics

        metrics = MessageMetrics(input_tokens=100)
        combined = Message(
            role="tool",
            content=["r1", "r2"],
            tool_calls=[
                {"tool_call_id": "id_001", "tool_name": "f1", "content": "r1"},
                {"tool_call_id": "id_002", "tool_name": "f2", "content": "r2"},
            ],
            metrics=metrics,
        )
        result = normalize_tool_messages([combined])
        assert result[0].metrics is not None
        assert result[0].metrics.input_tokens == 100
        assert result[1].metrics.input_tokens == 0

    def test_empty_list(self):
        """Empty message list should return empty."""
        assert normalize_tool_messages([]) == []
