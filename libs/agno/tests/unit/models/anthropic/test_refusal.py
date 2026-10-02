from types import SimpleNamespace
from typing import Optional

import pytest
from anthropic.lib.streaming import MessageStopEvent
from anthropic.types import Message as AnthropicMessage
from anthropic.types import RefusalStopDetails, TextBlock, Usage

from agno.agent import Agent
from agno.exceptions import ModelRefusalError
from agno.models.anthropic import Claude
from agno.models.fallback import FallbackConfig, get_fallback_models
from agno.models.message import Message
from agno.run.base import RunStatus


def _response(stop_reason: str, text: Optional[str] = None, category: Optional[str] = None) -> AnthropicMessage:
    stop_details = RefusalStopDetails(type="refusal", category=category) if stop_reason == "refusal" else None
    return AnthropicMessage(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-test",
        content=[TextBlock(type="text", text=text)] if text else [],
        stop_reason=stop_reason,
        stop_sequence=None,
        stop_details=stop_details,
        usage=Usage(input_tokens=10, output_tokens=0 if stop_reason == "refusal" else 2),
    )


class _Messages:
    def __init__(self, response: AnthropicMessage) -> None:
        self.response = response
        self.calls = 0

    def create(self, **kwargs) -> AnthropicMessage:
        self.calls += 1
        return self.response


def _claude(response: AnthropicMessage, **kwargs) -> Claude:
    """A Claude whose client is a stub. A subclass rather than an instance attribute, so the copies
    agno makes of a model (fallback models, for one) keep the stub and never reach the network."""
    messages = _Messages(response)

    class _StubClaude(Claude):
        def get_client(self):
            return SimpleNamespace(messages=messages)

    return _StubClaude(id="claude-test", api_key="offline", **kwargs)


def _call_kwargs() -> dict:
    return {"messages": [Message(role="user", content="hi")], "assistant_message": Message(role="assistant")}


def test_a_refusal_raises_a_refusal_error():
    model = _claude(_response("refusal", category="cyber"))

    with pytest.raises(ModelRefusalError) as exc_info:
        model.invoke(**_call_kwargs())

    assert exc_info.value.status_code == 200
    assert exc_info.value.category == "cyber"
    assert "refusal" in exc_info.value.message


def test_a_refusal_after_partial_text_still_raises():
    model = _claude(_response("refusal", text="Here is how you", category="general_harms"))

    with pytest.raises(ModelRefusalError):
        model.invoke(**_call_kwargs())


def test_a_refusal_without_a_category_raises():
    with pytest.raises(ModelRefusalError) as exc_info:
        _claude(_response("refusal")).invoke(**_call_kwargs())

    assert exc_info.value.category is None


def test_a_refusal_is_not_retried_on_the_same_model():
    model = _claude(_response("refusal", category="cyber"), retries=3, delay_between_retries=0)

    with pytest.raises(ModelRefusalError):
        model._invoke_with_retry(**_call_kwargs())

    assert model.get_client().messages.calls == 1


def test_general_fallback_models_apply_to_a_refusal():
    other = Claude(id="claude-other", api_key="offline")
    config = FallbackConfig(on_error=[other])

    assert get_fallback_models(config, ModelRefusalError("declined")) == [other]


def test_a_refused_stream_raises_at_message_stop():
    model = Claude(id="claude-test", api_key="offline")
    event = MessageStopEvent(type="message_stop", message=_response("refusal", category="cyber"))

    with pytest.raises(ModelRefusalError):
        model._parse_provider_response_delta(event)


def test_an_agent_run_ends_in_error_on_a_refusal():
    agent = Agent(model=_claude(_response("refusal", category="cyber")))

    run = agent.run("hi")

    assert run.status == RunStatus.error


def test_an_agent_answers_from_its_fallback_model_after_a_refusal():
    agent = Agent(
        model=_claude(_response("refusal", category="cyber")),
        fallback_models=[_claude(_response("end_turn", text="answered by the fallback"))],
    )

    run = agent.run("hi")

    assert run.status == RunStatus.completed
    assert run.content == "answered by the fallback"


def test_an_end_turn_response_is_unchanged():
    response = _claude(_response("end_turn", text="ok")).invoke(**_call_kwargs())

    assert response.content == "ok"
