"""Tests for OpenRouter image-generation response parsing.

OpenRouter returns generated images under the chat message's model_extra["images"]
as data URLs, both in the buffered response and in streamed deltas. Both parsers
must surface them as Image artifacts on model_response.images (matching the Gemini
image-output pattern).
"""

import base64

from openai.types.chat import ChatCompletion, ChatCompletionChunk, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChunkChoice
from openai.types.chat.chat_completion_chunk import ChoiceDelta

from agno.media import Image
from agno.models.openrouter import OpenRouter

# 1x1 transparent PNG
_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _completion_with_extra(message_extra: dict) -> ChatCompletion:
    message = ChatCompletionMessage.model_validate({"role": "assistant", "content": "", **message_extra})
    choice = Choice(index=0, message=message, finish_reason="stop")
    return ChatCompletion(
        id="test",
        choices=[choice],
        created=0,
        model="google/gemini-2.5-flash-image",
        object="chat.completion",
    )


def _chunk_with_extra(delta_extra: dict) -> ChatCompletionChunk:
    delta = ChoiceDelta.model_validate({"role": "assistant", "content": "", **delta_extra})
    choice = ChunkChoice(index=0, delta=delta, finish_reason=None)
    return ChatCompletionChunk(
        id="test",
        choices=[choice],
        created=0,
        model="google/gemini-2.5-flash-image",
        object="chat.completion.chunk",
    )


def test_generated_image_parsed_from_data_url():
    """A data-URL image is decoded into an Image artifact with content bytes."""
    response = _completion_with_extra(
        {"images": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_B64}"}}]}
    )
    model_response = OpenRouter(api_key="test-key")._parse_provider_response(response)

    assert model_response.images is not None
    assert len(model_response.images) == 1
    image = model_response.images[0]
    assert isinstance(image, Image)
    assert image.content == base64.b64decode(_PNG_B64)
    assert image.mime_type == "image/png"


def test_no_images_when_extra_absent():
    """A normal response without images leaves model_response.images unset."""
    response = _completion_with_extra({})
    model_response = OpenRouter(api_key="test-key")._parse_provider_response(response)
    assert model_response.images is None


def test_non_data_url_skipped():
    """A non-data URL is skipped: OpenRouter only emits data URLs, and fetching a
    provider-supplied remote URL server-side would be an SSRF risk."""
    response = _completion_with_extra(
        {"images": [{"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}}]}
    )
    model_response = OpenRouter(api_key="test-key")._parse_provider_response(response)

    assert model_response.images is None


def test_image_without_type_field_is_parsed():
    """An entry omitting the optional `type` field is still parsed (robustness)."""
    response = _completion_with_extra({"images": [{"image_url": {"url": f"data:image/png;base64,{_PNG_B64}"}}]})
    model_response = OpenRouter(api_key="test-key")._parse_provider_response(response)

    assert model_response.images is not None
    assert model_response.images[0].content == base64.b64decode(_PNG_B64)


def test_generated_image_parsed_from_streaming_delta():
    """A streamed delta image is decoded into an Image artifact (stream=True path)."""
    chunk = _chunk_with_extra(
        {"images": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG_B64}"}}]}
    )
    model_response = OpenRouter(api_key="test-key")._parse_provider_response_delta(chunk)

    assert model_response.images is not None
    assert len(model_response.images) == 1
    image = model_response.images[0]
    assert isinstance(image, Image)
    assert image.content == base64.b64decode(_PNG_B64)
    assert image.mime_type == "image/png"


def test_no_images_when_delta_is_plain_text():
    """A normal text delta leaves model_response.images unset."""
    chunk = _chunk_with_extra({})
    model_response = OpenRouter(api_key="test-key")._parse_provider_response_delta(chunk)
    assert model_response.images is None
