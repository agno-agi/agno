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

    def test_tool_result_followed_by_user_message_merged(self):
        """A tool result (mapped to user) followed by a user message should merge into one."""
        from agno.utils.models.claude import format_messages

        tc = _make_tool_call("toolu_001", name="get_weather")
        msgs = [
            Message(role="user", content="Check weather"),
            _assistant_msg([tc]),
            _tool_msg("toolu_001", content="Sunny"),
            Message(role="user", content="Thanks, now check London"),
        ]
        formatted, system = format_messages(msgs)

        # Should be: user, assistant, user (merged tool result + follow-up)
        assert len(formatted) == 3
        assert formatted[2]["role"] == "user"
        content = formatted[2]["content"]
        assert isinstance(content, list)
        # Should contain tool_result + text
        types = [item.get("type") if isinstance(item, dict) else None for item in content]
        assert "tool_result" in types
        assert "text" in types

    def test_three_consecutive_tool_results_merged(self):
        """Three parallel tool results should all merge into a single user message."""
        from agno.utils.models.claude import format_messages

        tc1 = _make_tool_call("toolu_001", name="search", arguments='{"q": "a"}')
        tc2 = _make_tool_call("toolu_002", name="search", arguments='{"q": "b"}')
        tc3 = _make_tool_call("toolu_003", name="search", arguments='{"q": "c"}')

        msgs = [
            Message(role="user", content="Search for a, b, c"),
            _assistant_msg([tc1, tc2, tc3]),
            _tool_msg("toolu_001", content="Result A"),
            _tool_msg("toolu_002", content="Result B"),
            _tool_msg("toolu_003", content="Result C"),
        ]
        formatted, system = format_messages(msgs)

        assert len(formatted) == 3
        content = formatted[2]["content"]
        assert isinstance(content, list)
        assert len(content) == 3
        assert all(item["type"] == "tool_result" for item in content)

    def test_alternating_roles_no_merge_needed(self):
        """When roles already alternate, no merging should happen."""
        from agno.utils.models.claude import format_messages

        msgs = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
            Message(role="user", content="How are you?"),
        ]
        formatted, system = format_messages(msgs)

        assert len(formatted) == 3
        assert formatted[0]["role"] == "user"
        assert formatted[1]["role"] == "assistant"
        assert formatted[2]["role"] == "user"


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


# ---------------------------------------------------------------------------
# Parallel tool calls — provider-specific formatting
# ---------------------------------------------------------------------------


class TestParallelToolCallsGeminiFormat:
    """Parallel tool results should be formatted correctly for Gemini."""

    def test_parallel_tool_results_merged_for_gemini(self):
        """Multiple consecutive tool results should merge into one Gemini user turn."""
        from agno.models.google.gemini import Gemini

        gemini = Gemini(id="gemini-2.0-flash")
        tc1 = _make_tool_call("toolu_001", name="get_weather", arguments='{"city": "Paris"}')
        tc2 = _make_tool_call("toolu_002", name="get_weather", arguments='{"city": "London"}')
        tc3 = _make_tool_call("toolu_003", name="get_weather", arguments='{"city": "Tokyo"}')

        msgs = [
            Message(role="user", content="Check weather in Paris, London, and Tokyo"),
            _assistant_msg([tc1, tc2, tc3]),
            _tool_msg("toolu_001", tool_name="get_weather", content="Paris: Sunny"),
            _tool_msg("toolu_002", tool_name="get_weather", content="London: Rainy"),
            _tool_msg("toolu_003", tool_name="get_weather", content="Tokyo: Cloudy"),
        ]
        formatted, system = gemini._format_messages(msgs)

        # Should be: user, model, user (merged tool results)
        assert len(formatted) == 3
        assert formatted[0].role == "user"
        assert formatted[1].role == "model"
        assert formatted[2].role == "user"

        # Merged user message should contain all 3 function_response parts
        fn_responses = [
            p for p in formatted[2].parts if hasattr(p, "function_response") and p.function_response is not None
        ]
        assert len(fn_responses) == 3

    def test_cross_provider_parallel_to_gemini(self):
        """Claude-style tool IDs in parallel should format correctly for Gemini."""
        from agno.models.google.gemini import Gemini

        gemini = Gemini(id="gemini-2.0-flash")
        tc1 = _make_tool_call("toolu_aaa", name="search", arguments='{"q": "a"}')
        tc2 = _make_tool_call("toolu_bbb", name="search", arguments='{"q": "b"}')

        msgs = [
            Message(role="user", content="Search for a and b"),
            _assistant_msg([tc1, tc2]),
            _tool_msg("toolu_aaa", tool_name="search", content="Result A"),
            _tool_msg("toolu_bbb", tool_name="search", content="Result B"),
        ]
        formatted, system = gemini._format_messages(msgs)

        # Gemini accepts any ID format, so these should format fine
        fn_responses = []
        for msg in formatted:
            if msg.role == "user":
                for part in msg.parts:
                    if hasattr(part, "function_response") and part.function_response is not None:
                        fn_responses.append(part)
        assert len(fn_responses) == 2


class TestParallelToolCallsClaudeFormat:
    """Parallel tool calls from various providers formatted for Claude."""

    def test_parallel_from_openai_chat_for_claude(self):
        """OpenAI Chat call_* IDs in parallel should format correctly for Claude."""
        from agno.utils.models.claude import format_messages

        tc1 = _make_tool_call("call_abc123", name="get_weather", arguments='{"city": "Paris"}')
        tc2 = _make_tool_call("call_def456", name="get_weather", arguments='{"city": "London"}')

        msgs = [
            Message(role="user", content="Check weather in Paris and London"),
            _assistant_msg([tc1, tc2]),
            _tool_msg("call_abc123", content="Paris: Sunny"),
            _tool_msg("call_def456", content="London: Rainy"),
        ]
        formatted, system = format_messages(msgs)

        # Should be: user, assistant (with tool_use blocks), user (merged tool_results)
        assert len(formatted) == 3
        assert formatted[2]["role"] == "user"
        content = formatted[2]["content"]
        assert len(content) == 2
        assert all(item["type"] == "tool_result" for item in content)

    def test_parallel_from_gemini_for_claude(self):
        """Gemini UUID-style IDs in parallel should format correctly for Claude."""
        from agno.utils.models.claude import format_messages

        tc1 = _make_tool_call("uuid-111-aaa", name="search", arguments='{"q": "a"}')
        tc2 = _make_tool_call("uuid-222-bbb", name="search", arguments='{"q": "b"}')

        msgs = [
            Message(role="user", content="Search for a and b"),
            _assistant_msg([tc1, tc2]),
            _tool_msg("uuid-111-aaa", tool_name="search", content="Result A"),
            _tool_msg("uuid-222-bbb", tool_name="search", content="Result B"),
        ]
        formatted, system = format_messages(msgs)

        assert len(formatted) == 3
        content = formatted[2]["content"]
        assert len(content) == 2
        tool_use_ids = {item["tool_use_id"] for item in content}
        assert tool_use_ids == {"uuid-111-aaa", "uuid-222-bbb"}


class TestParallelToolCallsReformat:
    """Parallel tool calls remapped across all provider combinations."""

    def test_claude_parallel_to_gemini_noop(self):
        """Gemini accepts any ID — parallel Claude IDs should pass through."""
        tcs = [
            _make_tool_call("toolu_001", name="search"),
            _make_tool_call("toolu_002", name="calculate"),
        ]
        msgs = [
            _assistant_msg(tcs),
            _tool_msg("toolu_001", content="r1"),
            _tool_msg("toolu_002", content="r2"),
        ]
        result = reformat_tool_call_ids(msgs, provider="gemini")
        # Gemini has prefix=None, so no reformatting
        assert result[0].tool_calls[0]["id"] == "toolu_001"
        assert result[0].tool_calls[1]["id"] == "toolu_002"
        assert result[1].tool_call_id == "toolu_001"
        assert result[2].tool_call_id == "toolu_002"

    def test_gemini_parallel_to_responses_api(self):
        """Gemini UUID-style parallel calls should get fc_* + call_* for Responses API."""
        tcs = [
            _make_tool_call("uuid-aaa-111", name="search"),
            _make_tool_call("uuid-bbb-222", name="calculate"),
            _make_tool_call("uuid-ccc-333", name="lookup"),
        ]
        msgs = [
            _assistant_msg(tcs),
            _tool_msg("uuid-aaa-111", content="r1"),
            _tool_msg("uuid-bbb-222", content="r2"),
            _tool_msg("uuid-ccc-333", content="r3"),
        ]
        result = reformat_tool_call_ids(msgs, provider="openai_responses")

        for tc in result[0].tool_calls:
            assert tc["id"].startswith("fc_")
            assert "call_id" in tc
            assert tc["call_id"].startswith("call_")

        # Tool results should match the new fc_* IDs
        for i in range(3):
            assert result[i + 1].tool_call_id == result[0].tool_calls[i]["id"]

        # All IDs unique
        fc_ids = [tc["id"] for tc in result[0].tool_calls]
        assert len(set(fc_ids)) == 3

    def test_responses_parallel_to_openai_chat(self):
        """Responses API fc_* parallel calls should become call_* for Chat."""
        tcs = [
            _make_tool_call("fc_001", name="search", call_id="call_s1"),
            _make_tool_call("fc_002", name="calculate", call_id="call_c1"),
        ]
        msgs = [
            _assistant_msg(tcs),
            _tool_msg("fc_001", content="r1"),
            _tool_msg("fc_002", content="r2"),
        ]
        result = reformat_tool_call_ids(msgs, provider="openai_chat")

        for tc in result[0].tool_calls:
            assert tc["id"].startswith("call_")

        assert result[1].tool_call_id == result[0].tool_calls[0]["id"]
        assert result[2].tool_call_id == result[0].tool_calls[1]["id"]


# ---------------------------------------------------------------------------
# reformat_tool_call_ids — Mistral (alphanumeric, length 9)
# ---------------------------------------------------------------------------


class TestMistralReformat:
    """Mistral requires alphanumeric-only IDs with exactly 9 characters."""

    def test_claude_to_mistral(self):
        """Claude toolu_* IDs should become 9-char alphanumeric."""
        tc = _make_tool_call("toolu_abc123def456")
        msgs = [_assistant_msg([tc]), _tool_msg("toolu_abc123def456")]
        result = reformat_tool_call_ids(msgs, provider="mistral")
        new_id = result[0].tool_calls[0]["id"]
        assert len(new_id) == 9
        assert new_id.isalnum()
        assert result[1].tool_call_id == new_id

    def test_openai_chat_to_mistral(self):
        """OpenAI Chat call_* IDs should become 9-char alphanumeric."""
        tc = _make_tool_call("call_abc123456789")
        msgs = [_assistant_msg([tc]), _tool_msg("call_abc123456789")]
        result = reformat_tool_call_ids(msgs, provider="mistral")
        new_id = result[0].tool_calls[0]["id"]
        assert len(new_id) == 9
        assert new_id.isalnum()
        assert result[1].tool_call_id == new_id

    def test_responses_to_mistral(self):
        """Responses API fc_* IDs should become 9-char alphanumeric."""
        tc = _make_tool_call("fc_abc123456789", call_id="call_xyz")
        msgs = [_assistant_msg([tc]), _tool_msg("fc_abc123456789")]
        result = reformat_tool_call_ids(msgs, provider="mistral")
        new_id = result[0].tool_calls[0]["id"]
        assert len(new_id) == 9
        assert new_id.isalnum()
        assert result[1].tool_call_id == new_id

    def test_gemini_uuid_to_mistral(self):
        """Gemini UUID-style IDs (with hyphens) should be reformatted."""
        tc = _make_tool_call("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        msgs = [_assistant_msg([tc]), _tool_msg("a1b2c3d4-e5f6-7890-abcd-ef1234567890")]
        result = reformat_tool_call_ids(msgs, provider="mistral")
        new_id = result[0].tool_calls[0]["id"]
        assert len(new_id) == 9
        assert new_id.isalnum()
        assert result[1].tool_call_id == new_id

    def test_native_mistral_noop(self):
        """Native 9-char alphanumeric IDs should pass through unchanged."""
        tc = _make_tool_call("abc123def")
        msgs = [_assistant_msg([tc]), _tool_msg("abc123def")]
        result = reformat_tool_call_ids(msgs, provider="mistral")
        assert result[0].tool_calls[0]["id"] == "abc123def"
        assert result[1].tool_call_id == "abc123def"

    def test_parallel_to_mistral(self):
        """Parallel tool calls from Claude should all get unique 9-char IDs."""
        tcs = [
            _make_tool_call("toolu_aaa111", name="get_weather", arguments='{"city":"NYC"}'),
            _make_tool_call("toolu_bbb222", name="get_weather", arguments='{"city":"LA"}'),
            _make_tool_call("toolu_ccc333", name="get_weather", arguments='{"city":"SF"}'),
        ]
        msgs = [
            _assistant_msg(tcs),
            _tool_msg("toolu_aaa111", content="cold"),
            _tool_msg("toolu_bbb222", content="warm"),
            _tool_msg("toolu_ccc333", content="foggy"),
        ]
        result = reformat_tool_call_ids(msgs, provider="mistral")

        ids = [tc["id"] for tc in result[0].tool_calls]
        assert len(set(ids)) == 3, "all IDs should be unique"
        for new_id in ids:
            assert len(new_id) == 9
            assert new_id.isalnum()

        # Tool results match
        for i in range(3):
            assert result[i + 1].tool_call_id == result[0].tool_calls[i]["id"]
