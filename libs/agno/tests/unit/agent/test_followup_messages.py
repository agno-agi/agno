"""Tests for followup message construction.

Regression tests for https://github.com/agno-agi/agno/issues/8355:
json_object-only providers (e.g. DeepSeek) require the word "json" in the
prompt when response_format={"type": "json_object"} is used. The followup
system prompt must satisfy this and describe the expected JSON shape.
"""

from agno.agent._response import _build_followup_messages, _get_followups_response_format
from agno.run.agent import Followups


class _FakeModel:
    """Minimal stand-in exposing the capability flags read by _get_followups_response_format."""

    def __init__(self, native: bool = False, json_schema: bool = False):
        self.supports_native_structured_outputs = native
        self.supports_json_schema_outputs = json_schema


def test_followup_messages_default_structure():
    """Without json_object mode, messages keep the original system/user structure."""
    messages = _build_followup_messages("Paris is the capital of France.", 3, user_message="Capital of France?")

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "Capital of France?" in messages[1].content
    assert "Generate exactly 3 follow-up suggestions." in messages[1].content


def test_followup_messages_json_object_mode_contains_json():
    """json_object mode must include the word "json" and the expected fields in the prompt.

    DeepSeek (and OpenAI JSON mode) reject requests with response_format
    {"type": "json_object"} unless the prompt contains the word "json".
    """
    messages = _build_followup_messages(
        "Paris is the capital of France.",
        3,
        user_message="Capital of France?",
        response_format={"type": "json_object"},
    )

    system_content = messages[0].content
    assert "json" in system_content.lower()
    # The prompt should also describe the expected shape so the model emits
    # {"suggestions": [...]} that _parse_followups_response can validate.
    assert "suggestions" in system_content


def test_followup_messages_structured_output_mode_unchanged():
    """Schema-aware response formats do not need the JSON instructions appended."""
    for response_format in (
        Followups,
        {"type": "json_schema", "json_schema": {"name": "Followups", "schema": Followups.model_json_schema()}},
    ):
        messages = _build_followup_messages(
            "Paris is the capital of France.",
            3,
            response_format=response_format,
        )
        assert "<json_fields>" not in messages[0].content


def test_get_followups_response_format_fallback_to_json_object():
    """Models without structured/json-schema output support fall back to json_object."""
    assert _get_followups_response_format(_FakeModel()) == {"type": "json_object"}
    assert _get_followups_response_format(_FakeModel(native=True)) is Followups
    assert _get_followups_response_format(_FakeModel(json_schema=True))["type"] == "json_schema"
