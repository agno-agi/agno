"""Unit tests for WaveSpeedTools (agno.tools.wavespeed)."""

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("wavespeed")

from agno.tools.function import ToolResult  # noqa: E402
from agno.tools.wavespeed import WaveSpeedTools  # noqa: E402


@pytest.fixture
def tools():
    """Build a WaveSpeedTools instance with a mocked WaveSpeed client."""
    with patch("agno.tools.wavespeed.WaveSpeedClient") as mock_client_cls:
        toolkit = WaveSpeedTools(api_key="test-key")
        toolkit.client = mock_client_cls.return_value
        yield toolkit


def test_init_registers_tools():
    with patch("agno.tools.wavespeed.WaveSpeedClient"):
        toolkit = WaveSpeedTools(api_key="test-key")
    tool_names = [tool.__name__ for tool in toolkit.tools]
    assert "generate_image" in tool_names
    assert "generate_video" in tool_names


def test_init_reads_api_key_from_env():
    with patch.dict("os.environ", {"WAVESPEED_API_KEY": "env-key"}):
        with patch("agno.tools.wavespeed.WaveSpeedClient") as mock_client_cls:
            toolkit = WaveSpeedTools()
    assert toolkit.api_key == "env-key"
    mock_client_cls.assert_called_once_with(api_key="env-key")


def test_generate_image_success(tools):
    tools.client.run.return_value = {"outputs": ["https://example.com/image.png"]}

    result = tools.generate_image(MagicMock(), prompt="a red apple")

    assert isinstance(result, ToolResult)
    assert "https://example.com/image.png" in result.content
    assert result.images is not None
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/image.png"

    tools.client.run.assert_called_once_with(
        "bytedance/seedream-v5.0-pro",
        {"prompt": "a red apple"},
        timeout=600.0,
        poll_interval=1.0,
    )


def test_generate_image_with_model_override(tools):
    tools.client.run.return_value = {"outputs": ["https://example.com/image.png"]}

    tools.generate_image(MagicMock(), prompt="a red apple", model="wavespeed-ai/flux-dev")

    assert tools.client.run.call_args[0][0] == "wavespeed-ai/flux-dev"


def test_generate_image_multiple_outputs(tools):
    urls = ["https://example.com/1.png", "https://example.com/2.png"]
    tools.client.run.return_value = {"outputs": urls}

    result = tools.generate_image(MagicMock(), prompt="two apples")

    assert result.images is not None
    assert len(result.images) == 2
    assert [image.url for image in result.images] == urls


def test_generate_image_empty_outputs(tools):
    tools.client.run.return_value = {"outputs": []}

    result = tools.generate_image(MagicMock(), prompt="a red apple")

    assert result.content == "No output received from the model."
    assert result.images is None


def test_generate_image_error(tools):
    tools.client.run.side_effect = RuntimeError("Prediction failed")

    result = tools.generate_image(MagicMock(), prompt="a red apple")

    assert result.content.startswith("Error:")
    assert "Prediction failed" in result.content


def test_generate_video_success(tools):
    tools.client.run.return_value = {"outputs": ["https://example.com/video.mp4"]}

    result = tools.generate_video(MagicMock(), prompt="a balloon in the ocean")

    assert isinstance(result, ToolResult)
    assert "https://example.com/video.mp4" in result.content
    assert result.videos is not None
    assert len(result.videos) == 1
    assert result.videos[0].url == "https://example.com/video.mp4"

    tools.client.run.assert_called_once_with(
        "bytedance/seedance-2.5/text-to-video",
        {"prompt": "a balloon in the ocean"},
        timeout=600.0,
        poll_interval=1.0,
    )


def test_generate_video_error(tools):
    tools.client.run.side_effect = TimeoutError("Prediction timed out")

    result = tools.generate_video(MagicMock(), prompt="a balloon in the ocean")

    assert result.content.startswith("Error:")
    assert "Prediction timed out" in result.content
