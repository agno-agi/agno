"""Unit tests for DalleTools request parameters and response handling."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.dalle import DalleTools


def _image_data(url=None, b64_json=None, revised_prompt=None):
    data = MagicMock()
    data.url = url
    data.b64_json = b64_json
    data.revised_prompt = revised_prompt
    return data


def _generate(tools, data, output_format=None):
    client = MagicMock()
    response = MagicMock()
    response.data = data
    response.output_format = output_format
    client.images.generate.return_value = response
    with patch("agno.tools.dalle.OpenAI", return_value=client):
        result = tools.create_image("a cat")
    return result, client.images.generate.call_args.kwargs


def test_default_gpt_image_request_uses_supported_quality():
    tools = DalleTools(api_key="test-key")

    _, request = _generate(tools, [_image_data(b64_json=base64.b64encode(b"png").decode())])

    assert request["model"] == "gpt-image-2"
    assert request["quality"] == "auto"


@pytest.mark.parametrize("quality", ["auto", "low", "medium", "high"])
def test_gpt_image_accepts_gpt_image_qualities(quality):
    assert DalleTools(api_key="test-key", quality=quality).quality == quality


@pytest.mark.parametrize("quality", ["standard", "hd"])
def test_gpt_image_rejects_dalle_qualities(quality):
    with pytest.raises(ValueError, match="Invalid quality for gpt-image-2"):
        DalleTools(api_key="test-key", quality=quality)


@pytest.mark.parametrize("model", ["gpt-image-2", "gpt-image-1.5", "gpt-image-1-mini"])
def test_accepts_supported_models(model):
    assert DalleTools(api_key="test-key", model=model).model == model


@pytest.mark.parametrize("model", ["dall-e-3", "dall-e-2", "gpt-image-1"])
def test_rejects_retired_models(model):
    with pytest.raises(ValueError, match="Invalid model"):
        DalleTools(api_key="test-key", model=model)


def test_rejects_unknown_model_and_lists_valid_ones():
    with pytest.raises(ValueError, match="gpt-image-2"):
        DalleTools(api_key="test-key", model="dall-e-4")


@pytest.mark.parametrize("size", ["auto", "1024x1024", "1536x1024", "1024x1536", "1792x1024", "2048x1152"])
def test_gpt_image_2_accepts_fixed_and_custom_sizes(size):
    assert DalleTools(api_key="test-key", size=size).size == size


@pytest.mark.parametrize("size", ["256x256", "512x512", "1792x1024", "1024x1792"])
def test_older_gpt_image_models_reject_sizes_outside_fixed_list(size):
    with pytest.raises(ValueError, match="Invalid size for gpt-image-1.5"):
        DalleTools(api_key="test-key", model="gpt-image-1.5", size=size)


def test_b64_response_is_decoded_into_image_content():
    tools = DalleTools(api_key="test-key")

    result, _ = _generate(tools, [_image_data(b64_json=base64.b64encode(b"image-bytes").decode())], "webp")

    assert result.images is not None and len(result.images) == 1
    image = result.images[0]
    assert image.content == b"image-bytes"
    assert image.mime_type == "image/webp"
    assert image.url is None
    assert result.content == "Image has been generated\n"


def test_b64_response_defaults_to_png_mime_type():
    tools = DalleTools(api_key="test-key")

    result, _ = _generate(tools, [_image_data(b64_json=base64.b64encode(b"image-bytes").decode())])

    assert result.images[0].mime_type == "image/png"


def test_url_response_is_still_attached():
    tools = DalleTools(api_key="test-key")

    result, _ = _generate(tools, [_image_data(url="https://example.com/cat.png", revised_prompt="a fluffy cat")])

    assert result.images[0].url == "https://example.com/cat.png"
    assert result.images[0].revised_prompt == "a fluffy cat"
    assert "https://example.com/cat.png" in result.content


def test_style_is_not_sent_and_logs_deprecation():
    with patch("agno.tools.dalle.log_warning") as log_warning:
        tools = DalleTools(api_key="test-key", style="vivid")

    _, request = _generate(tools, [_image_data(b64_json=base64.b64encode(b"png").decode())])

    assert "style" not in request
    assert any("style option is deprecated" in call.args[0] for call in log_warning.call_args_list)


def test_b64_response_has_no_revised_prompt():
    tools = DalleTools(api_key="test-key")

    result, _ = _generate(tools, [_image_data(b64_json=base64.b64encode(b"png").decode(), revised_prompt="ignored")])

    assert result.images[0].revised_prompt is None


def test_init_logs_deprecation_pointing_to_openai_tools():
    with patch("agno.tools.dalle.log_warning") as log_warning:
        DalleTools(api_key="test-key")

    message = log_warning.call_args.args[0]
    assert "DalleTools is deprecated" in message
    assert "OpenAITools" in message
