from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.media import Image
from agno.models.aimlapi import AIMLAPI
from agno.models.message import Message


def test_default_config():
    """Default AIMLAPI configuration."""
    model = AIMLAPI(api_key="test")

    assert model.id == "gpt-4o-mini"
    assert model.name == "AIMLAPI"
    assert model.provider == "AIMLAPI"
    assert model.base_url == "https://api.aimlapi.com/v1"
    assert model.max_tokens == 4096


def test_requires_api_key():
    """AIMLAPI raises an error when no API key is provided."""
    model = AIMLAPI()

    with patch.dict("os.environ", {}, clear=True):
        model.api_key = None
        with pytest.raises(ModelAuthenticationError, match="AIMLAPI_API_KEY not set"):
            model._get_client_params()


def test_format_message_replaces_none_content_with_empty_string():
    """AIMLAPI._format_message replaces a None content with an empty string."""
    model = AIMLAPI(api_key="test")

    message = Message(role="assistant", content=None)
    formatted = model._format_message(message)

    assert formatted["content"] == ""


def test_format_message_accepts_compress_tool_results_positional_arg():
    """Regression test for #9034.

    ``OpenAIChat._format_all_messages`` calls ``self._format_message(m, compress_tool_results)``
    positionally. AIMLAPI's override previously only accepted ``(self, message)``, which raised
    ``AIMLAPI._format_message() takes 2 positional arguments but 3 were given`` for any request,
    including ones that included an image (multimodal messages).
    """
    model = AIMLAPI(id="meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo", api_key="test")

    message = Message(
        role="user",
        content="Tell me about this image",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    # Calling with compress_tool_results positionally must not raise a TypeError.
    formatted = model._format_message(message, False)
    assert formatted["role"] == "user"

    formatted_kwarg = model._format_message(message, compress_tool_results=True)
    assert formatted_kwarg["role"] == "user"


def test_format_all_messages_with_images_does_not_raise():
    """Regression test for #9034: the real internal call path used by agent runs."""
    model = AIMLAPI(id="meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo", api_key="test")

    messages = [
        Message(
            role="user",
            content="Tell me about this image",
            images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
        ),
        Message(role="assistant", content=None),
    ]

    formatted = model._format_all_messages(messages)

    assert len(formatted) == 2
    assert formatted[-1]["content"] == ""
