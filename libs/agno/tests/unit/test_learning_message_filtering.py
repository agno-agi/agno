from agno.models.message import Message
from agno.utils.message import get_conversation_text

# ---------------------------------------------------------------------------
# get_conversation_text — shared text conversion for learning stores
# ---------------------------------------------------------------------------


class TestGetConversationText:
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

    def test_skips_assistant_with_no_content(self):
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

    def test_full_conversation_with_tool_calls(self):
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
