"""Unit tests for TwelveLabsTools class."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.twelvelabs import TwelveLabsTools


@pytest.fixture
def twelvelabs_tools():
    """Create TwelveLabsTools instance with a dummy API key."""
    with patch.dict("os.environ", {"TWELVELABS_API_KEY": "test_key"}):
        return TwelveLabsTools()


def test_init_with_api_key():
    """Test initialization with a provided API key."""
    tools = TwelveLabsTools(api_key="my_key")
    assert tools.api_key == "my_key"


def test_init_reads_env(twelvelabs_tools):
    """Test initialization reads the API key from the environment."""
    assert twelvelabs_tools.api_key == "test_key"


def test_init_with_selective_tools():
    """Test that only selected tools are registered."""
    tools = TwelveLabsTools(api_key="k", enable_analyze_video=True, enable_embed_text=False)
    names = [func.name for func in tools.functions.values()]
    assert "analyze_video" in names
    assert "embed_text" not in names


def test_init_all_tools():
    """Test that `all=True` registers every tool."""
    tools = TwelveLabsTools(api_key="k", all=True)
    names = [func.name for func in tools.functions.values()]
    assert "analyze_video" in names
    assert "embed_text" in names


def test_analyze_video_no_url(twelvelabs_tools):
    assert twelvelabs_tools.analyze_video(video_url="", prompt="What happens?") == "No video_url provided"


def test_analyze_video_no_prompt(twelvelabs_tools):
    assert twelvelabs_tools.analyze_video(video_url="http://x/v.mp4", prompt="") == "No prompt provided"


def test_embed_text_no_text(twelvelabs_tools):
    assert twelvelabs_tools.embed_text(text="") == "No text provided"


def test_analyze_video_success(twelvelabs_tools):
    """analyze_video should return the model's text answer."""
    mock_client = MagicMock()
    mock_client.analyze.return_value = MagicMock(data="A cat plays piano.")
    twelvelabs_tools._client = mock_client

    result = twelvelabs_tools.analyze_video(video_url="http://x/v.mp4", prompt="What happens?")

    assert result == "A cat plays piano."
    _, kwargs = mock_client.analyze.call_args
    assert kwargs["model_name"] == "pegasus1.5"
    assert kwargs["prompt"] == "What happens?"
    assert kwargs["max_tokens"] == 2048


def test_embed_text_success(twelvelabs_tools):
    """embed_text should return JSON with the embedding vector and its dimensions."""
    segment = MagicMock()
    segment.float_ = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.text_embedding.segments = [segment]

    mock_client = MagicMock()
    mock_client.embed.create.return_value = mock_response
    twelvelabs_tools._client = mock_client

    result = json.loads(twelvelabs_tools.embed_text(text="a cat playing piano"))

    assert result["model"] == "marengo3.0"
    assert result["dimensions"] == 3
    assert result["embedding"] == [0.1, 0.2, 0.3]
    _, kwargs = mock_client.embed.create.call_args
    assert kwargs["model_name"] == "marengo3.0"


def test_analyze_video_error_is_caught(twelvelabs_tools):
    mock_client = MagicMock()
    mock_client.analyze.side_effect = RuntimeError("boom")
    twelvelabs_tools._client = mock_client
    assert "Error analyzing video" in twelvelabs_tools.analyze_video(video_url="http://x/v.mp4", prompt="?")


@pytest.mark.skipif(
    not os.getenv("TWELVELABS_API_KEY"),
    reason="TWELVELABS_API_KEY not set; skipping live TwelveLabs API test",
)
def test_embed_text_live():
    """Live test: Marengo returns a 512-dim text embedding."""
    tools = TwelveLabsTools()
    result = json.loads(tools.embed_text(text="a cat playing piano"))
    assert result["dimensions"] == 512
    assert len(result["embedding"]) == 512
