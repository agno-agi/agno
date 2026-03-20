"""
Tests for _strip_trailing_assistant_for_output_format.

Verifies that when output_format is active (i.e. response_format is set
on a model that supports structured outputs), trailing assistant messages
are stripped to avoid Anthropic's "pre-filling not supported" error.

See: https://github.com/agno-agi/agno/issues/5582
"""

from pydantic import BaseModel

from agno.models.anthropic.claude import Claude


class _DummySchema(BaseModel):
    answer: str
    confidence: float


def _make_model(model_id: str = "claude-sonnet-4-5-20250929") -> Claude:
    """Create a Claude instance without needing an API key."""
    return Claude(id=model_id, api_key="test-key")


# ── output_schema alone (no trailing assistant) ────────────────────────
class TestOutputSchemaWithoutTrailingAssistant:
    """output_schema should work fine when the last message is a user message."""

    def test_user_last_message_unchanged(self):
        model = _make_model()
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages, response_format=_DummySchema
        )
        assert result == messages

    def test_tool_result_last_message_unchanged(self):
        """Tool results map to role 'user' in Anthropic API, should be kept."""
        model = _make_model()
        messages = [
            {"role": "user", "content": "Search for X"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "input": {}, "name": "search"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result"}]},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages, response_format=_DummySchema
        )
        assert result == messages


# ── reasoning alone (no output_schema) ─────────────────────────────────
class TestReasoningWithoutOutputSchema:
    """Trailing assistant messages should be kept when output_schema is not set."""

    def test_trailing_assistant_kept_when_no_response_format(self):
        model = _make_model()
        messages = [
            {"role": "user", "content": "Think about this"},
            {"role": "assistant", "content": "I'm thinking..."},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages, response_format=None
        )
        assert result == messages
        assert len(result) == 2


# ── both output_schema + reasoning (the bug scenario) ─────────────────
class TestOutputSchemaWithReasoning:
    """When both are active, trailing assistant must be stripped."""

    def test_trailing_assistant_stripped(self):
        model = _make_model()
        messages = [
            {"role": "user", "content": "Research this topic"},
            {"role": "assistant", "content": "Here are my findings from the tools..."},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages, response_format=_DummySchema
        )
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_multi_turn_trailing_assistant_stripped(self):
        """Simulates a full tool-call cycle ending with assistant."""
        model = _make_model()
        messages = [
            {"role": "user", "content": "Search for X"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "input": {}, "name": "search"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result"}]},
            {"role": "assistant", "content": "Based on the search results..."},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages, response_format=_DummySchema
        )
        assert len(result) == 3
        assert result[-1]["role"] == "user"

    def test_empty_messages_unchanged(self):
        model = _make_model()
        result = model._strip_trailing_assistant_for_output_format(
            [], response_format=_DummySchema
        )
        assert result == []


# ── non-structured-output models ───────────────────────────────────────
class TestNonStructuredOutputModel:
    """Models that don't support structured outputs should not strip."""

    def test_unsupported_model_keeps_trailing_assistant(self):
        model = _make_model(model_id="claude-3-haiku-20240307")
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Thinking..."},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages, response_format=_DummySchema
        )
        assert len(result) == 2
        assert result[-1]["role"] == "assistant"


# ── dict response_format ───────────────────────────────────────────────
class TestDictResponseFormat:
    """Ensure dict-based response_format also triggers stripping."""

    def test_dict_response_format_strips_trailing_assistant(self):
        model = _make_model()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "response"},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages,
            response_format={"type": "json_schema", "schema": {"type": "object"}},
        )
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_json_object_response_format_keeps_trailing_assistant(self):
        """json_object response_format should not trigger stripping.

        _build_output_format() returns None for {"type": "json_object"},
        so trailing assistant messages must be preserved.
        """
        model = _make_model()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "response"},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages,
            response_format={"type": "json_object"},
        )
        assert result == messages
        assert len(result) == 2
        assert result[-1]["role"] == "assistant"


# ── json_object response_format (no stripping) ────────────────────────
class TestJsonObjectResponseFormat:
    """json_object format does not produce output_format — should not strip."""

    def test_json_object_format_keeps_trailing_assistant(self):
        model = _make_model()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "response"},
        ]
        result = model._strip_trailing_assistant_for_output_format(
            messages,
            response_format={"type": "json_object"},
        )
        assert len(result) == 2
        assert result[-1]["role"] == "assistant"
