"""Tests for max_history_tokens truncation logic."""

from agno.models.message import Message
from agno.utils.message import _estimate_message_tokens, truncate_history_by_tokens


class TestEstimateMessageTokens:
    def test_string_content(self):
        msg = Message(role="user", content="Hello world")
        tokens = _estimate_message_tokens(msg)
        # "Hello world" = 11 chars + "user" = 4 chars => (15 + 3) // 4 = 4
        assert tokens == 4

    def test_empty_content(self):
        msg = Message(role="user", content="")
        tokens = _estimate_message_tokens(msg)
        # "" + "user" = 4 chars => (4 + 3) // 4 = 1
        assert tokens == 1

    def test_list_content(self):
        msg = Message(role="user", content=[{"type": "text", "text": "Hello"}])
        tokens = _estimate_message_tokens(msg)
        # json.dumps([{"type": "text", "text": "Hello"}]) = 35 chars + "user" = 4 => (39+3)//4 = 10
        assert tokens == 10

    def test_with_tool_calls(self):
        msg = Message(
            role="assistant",
            content="result",
            tool_calls=[{"id": "tc1", "function": {"name": "foo", "arguments": "{}"}}],
        )
        tokens_with = _estimate_message_tokens(msg)
        msg_without = Message(role="assistant", content="result")
        tokens_without = _estimate_message_tokens(msg_without)
        assert tokens_with > tokens_without
        # tool_calls JSON adds significant chars, so the difference should be meaningful
        assert tokens_with - tokens_without >= 5

    def test_none_content(self):
        """None content should be skipped, not passed to json.dumps."""
        msg = Message(role="user", content=None)
        tokens = _estimate_message_tokens(msg)
        # Only "user" role = 4 chars => (4 + 3) // 4 = 1
        assert tokens == 1

    def test_non_serializable_content(self):
        """Ensure non-JSON-serializable content does not raise."""

        class Custom:
            pass

        msg = Message(role="user", content=[Custom()])  # type: ignore[list-item]
        tokens = _estimate_message_tokens(msg)
        # Fallback path uses str(); result should be modest but above minimum
        assert 2 <= tokens <= 50


class TestTruncateHistoryByTokens:
    def _make_messages(self, contents: list[str]) -> list[Message]:
        return [Message(role="user", content=c) for c in contents]

    def test_no_truncation_when_under_budget(self):
        msgs = self._make_messages(["hi", "there"])
        original_len = len(msgs)
        truncate_history_by_tokens(msgs, max_tokens=10000)
        assert len(msgs) == original_len

    def test_truncation_drops_oldest(self):
        # Each message ~100 chars => ~25 tokens per message
        msgs = self._make_messages(["x" * 100] * 10)
        # Budget for ~2 messages worth
        truncate_history_by_tokens(msgs, max_tokens=55)
        # Should keep only the most recent messages that fit
        assert len(msgs) < 10
        # Budget fits at most 2 messages (each ~25 tokens), so upper bound is 2
        assert 1 <= len(msgs) <= 2

    def test_empty_messages(self):
        msgs: list[Message] = []
        truncate_history_by_tokens(msgs, max_tokens=100)
        assert msgs == []

    def test_zero_budget_clears_all(self):
        msgs = self._make_messages(["hello", "world"])
        truncate_history_by_tokens(msgs, max_tokens=0)
        assert msgs == []

    def test_keeps_most_recent(self):
        msgs = [
            Message(role="user", content="oldest " + "x" * 200),
            Message(role="assistant", content="old " + "x" * 200),
            Message(role="user", content="recent " + "x" * 200),
            Message(role="assistant", content="newest " + "x" * 200),
        ]
        # Budget for ~2 messages (each ~200 chars = ~50 tokens, so ~100 token budget)
        truncate_history_by_tokens(msgs, max_tokens=110)
        assert len(msgs) <= 3
        # The newest message should always be kept
        assert msgs[-1].content is not None
        assert "newest" in str(msgs[-1].content)

    def test_single_message_over_budget(self):
        msgs = self._make_messages(["x" * 10000])
        truncate_history_by_tokens(msgs, max_tokens=5)
        # Single message exceeds budget, nothing fits
        assert msgs == []

    def test_preserves_message_order(self):
        msgs = self._make_messages(["a", "b", "c", "d", "e"])
        truncate_history_by_tokens(msgs, max_tokens=10000)
        contents = [m.content for m in msgs]
        assert contents == ["a", "b", "c", "d", "e"]

    def test_drops_leading_tool_messages(self):
        """After truncation, leading tool messages should be removed."""
        msgs = [
            Message(role="user", content="x" * 200),
            Message(role="assistant", content="call", tool_calls=[{"id": "t1", "function": {"name": "f", "arguments": "{}"}}]),
            Message(role="tool", content="result", tool_call_id="t1"),
            Message(role="user", content="recent " + "x" * 50),
            Message(role="assistant", content="newest " + "x" * 50),
        ]
        # Budget tight enough to drop the first 2-3 messages, possibly leaving tool at front
        truncate_history_by_tokens(msgs, max_tokens=40)
        # After truncation, history must not start with a tool message
        if msgs:
            assert msgs[0].role != "tool"


class TestAgentMaxHistoryTokensParam:
    def test_agent_accepts_max_history_tokens(self):
        from agno.agent.agent import Agent

        agent = Agent(max_history_tokens=1000)
        assert agent.max_history_tokens == 1000

    def test_agent_default_none(self):
        from agno.agent.agent import Agent

        agent = Agent()
        assert agent.max_history_tokens is None

    def test_max_history_tokens_round_trip(self):
        """max_history_tokens should survive serialization round-trip via _storage."""
        from agno.agent._storage import from_dict, to_dict
        from agno.agent.agent import Agent

        agent = Agent(max_history_tokens=2048)
        data = to_dict(agent)
        assert data.get("max_history_tokens") == 2048
        restored = from_dict(Agent, data)
        assert restored.max_history_tokens == 2048
