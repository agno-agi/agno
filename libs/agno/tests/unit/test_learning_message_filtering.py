from agno.models.message import Message
from agno.run.messages import RunMessages
from agno.utils.message import get_conversation_text

# ---------------------------------------------------------------------------
# Caller-level filter (mirrors _managers.py logic)
# ---------------------------------------------------------------------------

_LEARNING_ROLES = ("user", "assistant", "model")


def _make_run_messages(messages):
    rm = RunMessages()
    rm.messages = messages
    return rm


def _filter(run_messages):
    if not run_messages:
        return []
    return [m for m in (run_messages.messages or []) if m.role in _LEARNING_ROLES]


class TestCallerLevelFilter:
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
        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[2].role == "assistant"
        assert result[2].content == "The weather in NYC is 72F and sunny"


# ---------------------------------------------------------------------------
# Shared text conversion (get_conversation_text)
# ---------------------------------------------------------------------------


class TestMessagesToLearningText:
    def test_user_message(self):
        result = get_conversation_text([Message(role="user", content="Hello")])
        assert result == "User: Hello"

    def test_assistant_message(self):
        result = get_conversation_text([Message(role="assistant", content="Hi there")])
        assert result == "Assistant: Hi there"

    def test_model_role_normalized_to_assistant(self):
        result = get_conversation_text([Message(role="model", content="Gemini says hi")])
        assert result == "Assistant: Gemini says hi"

    def test_filters_system_role(self):
        result = get_conversation_text(
            [
                Message(role="system", content="You are helpful"),
                Message(role="user", content="Hello"),
            ]
        )
        assert result == "User: Hello"

    def test_filters_tool_role(self):
        result = get_conversation_text(
            [
                Message(role="user", content="Search"),
                Message(role="tool", content='{"result": "data"}', tool_call_id="c1"),
            ]
        )
        assert result == "User: Search"

    def test_filters_developer_role(self):
        result = get_conversation_text(
            [
                Message(role="developer", content="Instructions"),
                Message(role="user", content="Hello"),
            ]
        )
        assert result == "User: Hello"

    def test_strips_tool_calls_from_assistant(self):
        # Assistant with content + tool_calls — only content appears in text
        result = get_conversation_text(
            [
                Message(
                    role="assistant",
                    content="Let me search for that",
                    tool_calls=[{"id": "c1", "function": {"name": "search", "arguments": "{}"}}],
                ),
            ]
        )
        assert result == "Assistant: Let me search for that"
        assert "search" not in result or "Let me search" in result

    def test_skips_assistant_with_no_content(self):
        # Assistant with only tool_calls, no content — skipped
        result = get_conversation_text(
            [
                Message(
                    role="assistant",
                    tool_calls=[{"id": "c1", "function": {"name": "search", "arguments": "{}"}}],
                ),
                Message(role="user", content="Thanks"),
            ]
        )
        assert result == "User: Thanks"

    def test_skips_whitespace_only_content(self):
        result = get_conversation_text([Message(role="user", content="   ")])
        assert result == ""

    def test_empty_list(self):
        assert get_conversation_text([]) == ""

    def test_full_conversation(self):
        result = get_conversation_text(
            [
                Message(role="system", content="You are a helpful assistant"),
                Message(role="user", content="What is the weather?"),
                Message(
                    role="assistant",
                    tool_calls=[{"id": "c1", "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'}}],
                ),
                Message(role="tool", content='{"temp": 72}', tool_call_id="c1"),
                Message(role="assistant", content="It is 72F in NYC"),
            ]
        )
        assert result == "User: What is the weather?\nAssistant: It is 72F in NYC"

    def test_multi_turn_conversation(self):
        result = get_conversation_text(
            [
                Message(role="user", content="My name is Sarah"),
                Message(role="assistant", content="Nice to meet you, Sarah!"),
                Message(role="user", content="I study neuroscience"),
                Message(role="assistant", content="That is a fascinating field."),
            ]
        )
        lines = result.split("\n")
        assert len(lines) == 4
        assert lines[0] == "User: My name is Sarah"
        assert lines[3] == "Assistant: That is a fascinating field."
