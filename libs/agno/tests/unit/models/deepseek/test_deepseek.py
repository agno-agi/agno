from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.deepseek import DeepSeek


def test_default_config():
    """Default DeepSeek configuration uses deepseek-v4-flash with thinking-friendly defaults."""
    model = DeepSeek()

    assert model.id == "deepseek-v4-flash"
    assert model.name == "DeepSeek"
    assert model.provider == "DeepSeek"
    assert model.base_url == "https://api.deepseek.com"
    # reasoning_effort is opt-in (matches OpenAIChat); the API uses its own default.
    assert model.reasoning_effort is None
    # use_thinking flag defaults to None (use model default).
    assert model.use_thinking is None
    # Structured output support is currently broken upstream.
    assert model.supports_native_structured_outputs is False


def test_requires_api_key():
    """DeepSeek raises an error when no API key is provided."""
    model = DeepSeek()

    with patch.dict("os.environ", {}, clear=True):
        model.api_key = None
        with pytest.raises(ModelAuthenticationError, match="DEEPSEEK_API_KEY not set"):
            model._get_client_params()


def test_thinking_enabled_by_default_for_flash():
    """get_request_params injects thinking mode for the default deepseek-v4-flash."""
    model = DeepSeek(api_key="test")
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_thinking_enabled_by_default_for_pro():
    """get_request_params injects thinking mode for deepseek-v4-pro."""
    model = DeepSeek(id="deepseek-v4-pro", api_key="test")
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_user_extra_body_merged_with_thinking():
    """A user-supplied extra_body is preserved and merged with the thinking flag."""
    model = DeepSeek(api_key="test", extra_body={"custom_key": "custom_value"})
    params = model.get_request_params()

    assert params["extra_body"]["custom_key"] == "custom_value"
    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_explicit_thinking_setting_preserved():
    """An explicit thinking setting in extra_body is never overwritten (raw escape hatch)."""
    model = DeepSeek(api_key="test", extra_body={"thinking": {"type": "disabled"}})
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_use_thinking_false_disables():
    """use_thinking=False turns thinking off on a thinking-capable model."""
    model = DeepSeek(api_key="test", use_thinking=False)
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_use_thinking_false_strips_reasoning_effort():
    """use_thinking=False strips reasoning_effort since it has no effect without thinking."""
    model = DeepSeek(api_key="test", use_thinking=False, reasoning_effort="max")
    params = model.get_request_params()

    assert "reasoning_effort" not in params


def test_use_thinking_true_forces_thinking_on_legacy_chat():
    """use_thinking=True forces thinking on even for the legacy non-thinking deepseek-chat."""
    model = DeepSeek(id="deepseek-chat", api_key="test", use_thinking=True)
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_deepseek_chat_is_non_thinking():
    """The deprecated deepseek-chat maps to non-thinking mode: no thinking flag injected."""
    model = DeepSeek(id="deepseek-chat", api_key="test")
    params = model.get_request_params()

    assert "thinking" not in params.get("extra_body", {})


def test_deepseek_chat_strips_reasoning_effort():
    """reasoning_effort has no effect in non-thinking mode and is stripped for deepseek-chat."""
    model = DeepSeek(id="deepseek-chat", api_key="test", reasoning_effort="max")
    params = model.get_request_params()

    assert "reasoning_effort" not in params


def test_deepseek_reasoner_is_thinking():
    """The deprecated deepseek-reasoner maps to thinking mode, so thinking is injected."""
    model = DeepSeek(id="deepseek-reasoner", api_key="test")
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}
