from unittest.mock import MagicMock, patch

from agno.models.message import Message
from agno.run.messages import RunMessages


def _make_run_messages(messages):
    rm = RunMessages()
    rm.messages = messages
    return rm


_LEARNING_ROLES = ("user", "assistant", "model")


def _filter(run_messages):
    """Mirrors the filter logic in agent/_managers.py process_learnings."""
    if not run_messages:
        return []
    return [m for m in (run_messages.messages or []) if m.role in _LEARNING_ROLES]


class TestLearningMessageFiltering:
    def test_keeps_user_messages(self):
        rm = _make_run_messages([Message(role="user", content="Hello")])
        result = _filter(rm)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_keeps_assistant_messages(self):
        rm = _make_run_messages([Message(role="assistant", content="Hi there")])
        result = _filter(rm)
        assert len(result) == 1

    def test_keeps_model_role(self):
        rm = _make_run_messages([Message(role="model", content="Gemini response")])
        result = _filter(rm)
        assert len(result) == 1

    def test_filters_system_messages(self):
        rm = _make_run_messages(
            [
                Message(role="system", content="You are a helpful assistant"),
                Message(role="user", content="Hello"),
            ]
        )
        result = _filter(rm)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_filters_tool_messages(self):
        rm = _make_run_messages(
            [
                Message(role="user", content="Search for X"),
                Message(role="tool", content='{"result": "found"}', tool_call_id="call_1"),
            ]
        )
        result = _filter(rm)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_filters_developer_role(self):
        rm = _make_run_messages(
            [
                Message(role="developer", content="System instructions via developer role"),
                Message(role="user", content="Hello"),
            ]
        )
        result = _filter(rm)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_keeps_assistant_with_tool_calls(self):
        rm = _make_run_messages(
            [
                Message(
                    role="assistant",
                    content="Let me search",
                    tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
                ),
            ]
        )
        result = _filter(rm)
        assert len(result) == 1

    def test_keeps_assistant_tool_call_only(self):
        # Role filter keeps it — stores handle via text conversion (no content = empty text)
        rm = _make_run_messages(
            [
                Message(
                    role="assistant",
                    tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
                ),
            ]
        )
        result = _filter(rm)
        assert len(result) == 1

    def test_empty_messages(self):
        rm = _make_run_messages([])
        assert _filter(rm) == []

    def test_none_run_messages(self):
        assert _filter(None) == []

    def test_full_conversation_with_tool_calls(self):
        rm = _make_run_messages(
            [
                Message(role="system", content="You are a helpful assistant with search tools"),
                Message(role="user", content="What is the weather in NYC?"),
                Message(
                    role="assistant",
                    tool_calls=[{"id": "call_1", "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'}}],
                ),
                Message(role="tool", content='{"temp": 72, "condition": "sunny"}', tool_call_id="call_1"),
                Message(role="assistant", content="The weather in NYC is 72F and sunny"),
            ]
        )
        result = _filter(rm)
        # system and tool filtered out, both assistant messages kept
        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[2].role == "assistant"
        assert result[2].content == "The weather in NYC is 72F and sunny"
