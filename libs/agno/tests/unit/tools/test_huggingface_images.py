"""Unit tests for HuggingFaceImageTools class."""

from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image as PILImage

from agno.tools.huggingface_images import HuggingFaceImageTools


def _make_test_image(width=64, height=64):
    """Create a minimal test image."""
    return PILImage.new("RGB", (width, height), color="red")


@pytest.fixture
def tools():
    """Create a HuggingFaceImageTools instance with a test API key."""
    return HuggingFaceImageTools(api_key="test-key")


def test_default_model(tools):
    assert tools.model == "black-forest-labs/FLUX.1-schnell"


def test_custom_model():
    t = HuggingFaceImageTools(model="stabilityai/stable-diffusion-xl-base-1.0", api_key="test-key")
    assert t.model == "stabilityai/stable-diffusion-xl-base-1.0"


def test_default_provider(tools):
    assert tools.provider == "hf-inference"


def test_api_key_from_param():
    t = HuggingFaceImageTools(api_key="my-key")
    assert t.api_key == "my-key"


@patch.dict("os.environ", {"HF_TOKEN": "env-key"})
def test_api_key_from_env():
    t = HuggingFaceImageTools()
    assert t.api_key == "env-key"


def test_tool_registered(tools):
    assert "create_image" in tools.functions


def test_tool_disabled():
    t = HuggingFaceImageTools(api_key="test-key", enable_create_image=False)
    assert "create_image" not in t.functions


def test_toolkit_name(tools):
    assert tools.name == "huggingface_images"


@patch("agno.tools.huggingface_images.InferenceClient")
def test_create_image_returns_image(mock_client_cls, tools):
    mock_client_cls.return_value.text_to_image.return_value = _make_test_image()

    result = tools.create_image("a red circle")

    assert result.images is not None
    assert len(result.images) == 1
    assert result.images[0].content is not None
    assert result.images[0].original_prompt == "a red circle"
    assert "successfully" in result.content.lower()


@patch("agno.tools.huggingface_images.InferenceClient")
def test_create_image_passes_model(mock_client_cls):
    mock_client_cls.return_value.text_to_image.return_value = _make_test_image()

    t = HuggingFaceImageTools(model="custom/model", api_key="test-key")
    t.create_image("test prompt")

    mock_client_cls.return_value.text_to_image.assert_called_once_with("test prompt", model="custom/model")


@patch("agno.tools.huggingface_images.InferenceClient")
def test_create_image_passes_provider(mock_client_cls):
    mock_client_cls.return_value.text_to_image.return_value = _make_test_image()

    t = HuggingFaceImageTools(provider="fal-ai", api_key="test-key")
    t.create_image("test")

    mock_client_cls.assert_called_once_with(provider="fal-ai", api_key="test-key")


@patch("agno.tools.huggingface_images.InferenceClient")
def test_create_image_error(mock_client_cls, tools):
    mock_client_cls.return_value.text_to_image.side_effect = Exception("API down")

    result = tools.create_image("test")

    assert result.images is None
    assert "error" in result.content.lower()
    assert "API down" in result.content


def test_create_image_no_api_key():
    t = HuggingFaceImageTools(api_key=None)
    t.api_key = None
    result = t.create_image("test")

    assert result.images is None
    assert "HF_TOKEN" in result.content


@patch("agno.tools.huggingface_images.InferenceClient")
def test_image_has_unique_id(mock_client_cls, tools):
    mock_client_cls.return_value.text_to_image.return_value = _make_test_image()

    r1 = tools.create_image("test 1")
    r2 = tools.create_image("test 2")

    assert r1.images[0].id != r2.images[0].id


@patch("agno.tools.huggingface_images.InferenceClient")
def test_image_format(mock_client_cls, tools):
    mock_client_cls.return_value.text_to_image.return_value = _make_test_image()

    result = tools.create_image("test")

    assert result.images[0].format == "png"


@patch("agno.tools.huggingface_images.InferenceClient")
def test_image_content_is_valid(mock_client_cls, tools):
    mock_client_cls.return_value.text_to_image.return_value = _make_test_image()

    result = tools.create_image("test")

    img = PILImage.open(BytesIO(result.images[0].content))
    assert img.size == (64, 64)
