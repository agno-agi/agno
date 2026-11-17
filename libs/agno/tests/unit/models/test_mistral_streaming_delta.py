"""Regression tests for agno#11608: list-shaped stream deltas are discarded."""

from types import SimpleNamespace

from agno.models.mistral.mistral import MistralChat


def _delta(content):
    choice = SimpleNamespace(delta=SimpleNamespace(role="assistant", content=content, tool_calls=None))
    return SimpleNamespace(data=SimpleNamespace(choices=[choice], usage=None))


def _model():
    return MistralChat(id="mistral-small-2603", api_key="synthetic")


def test_string_delta_is_content():
    assert _model()._parse_provider_response_delta(_delta("91")).content == "91"


def test_thinking_delta_is_reasoning():
    thinking = {"type": "thinking", "thinking": [{"type": "text", "text": "17 * 23 = 391."}]}
    out = _model()._parse_provider_response_delta(_delta([thinking]))
    assert out.reasoning_content and "391" in out.reasoning_content
    assert out.content in (None, "")


def test_mixed_closing_delta_keeps_text_chunk():
    closing = {"type": "thinking", "thinking": [], "closed": True}
    text = {"type": "text", "text": "3"}
    out = _model()._parse_provider_response_delta(_delta([closing, text]))
    assert out.content == "3"
