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
    assert "embed_video" in names


def test_embed_video_disabled_by_default():
    """embed_video is long-running (async polling), so it is opt-in: off by default."""
    tools = TwelveLabsTools(api_key="k")
    names = [func.name for func in tools.functions.values()]
    assert "analyze_video" in names
    assert "embed_text" in names
    assert "embed_video" not in names


def test_init_with_only_embed_video():
    """Test that `embed_video` can be enabled on its own."""
    tools = TwelveLabsTools(
        api_key="k",
        enable_analyze_video=False,
        enable_embed_text=False,
        enable_embed_video=True,
    )
    names = [func.name for func in tools.functions.values()]
    assert names == ["embed_video"]


def test_analyze_video_no_url(twelvelabs_tools):
    assert twelvelabs_tools.analyze_video(video_url="", prompt="What happens?") == "No video_url provided"


def test_analyze_video_no_prompt(twelvelabs_tools):
    assert twelvelabs_tools.analyze_video(video_url="http://x/v.mp4", prompt="") == "No prompt provided"


def test_embed_text_no_text(twelvelabs_tools):
    assert twelvelabs_tools.embed_text(text="") == "No text provided"


def test_embed_video_no_url(twelvelabs_tools):
    assert twelvelabs_tools.embed_video(video_url="") == "No video_url provided"


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


def test_embed_video_success(twelvelabs_tools):
    """embed_video should create a task, wait for it, then return per-segment metadata (no raw vectors)."""
    seg1 = MagicMock(float_=[0.1, 0.2, 0.3], start_offset_sec=0.0, end_offset_sec=6.0, embedding_scope="clip")
    seg2 = MagicMock(float_=[0.4, 0.5, 0.6], start_offset_sec=6.0, end_offset_sec=12.0, embedding_scope="clip")
    retrieve_response = MagicMock()
    retrieve_response.video_embedding.segments = [seg1, seg2]

    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.return_value = MagicMock(status="ready")
    mock_client.embed.tasks.retrieve.return_value = retrieve_response
    twelvelabs_tools._client = mock_client

    result = json.loads(twelvelabs_tools.embed_video(video_url="http://x/v.mp4"))

    assert result["model"] == "marengo3.0"
    assert result["dimensions"] == 3
    assert result["num_segments"] == 2
    # Raw float vectors are intentionally NOT serialized into the result (they would
    # flood the model context and are useless to the model); only the segment metadata is.
    assert "embedding" not in result["segments"][0]
    assert result["segments"][0]["start_offset_sec"] == 0.0
    assert result["segments"][0]["end_offset_sec"] == 6.0
    assert result["segments"][0]["embedding_scope"] == "clip"
    assert result["segments"][1]["end_offset_sec"] == 12.0

    _, create_kwargs = mock_client.embed.tasks.create.call_args
    assert create_kwargs["model_name"] == "marengo3.0"
    assert create_kwargs["video_url"] == "http://x/v.mp4"
    mock_client.embed.tasks.status.assert_called_with("task_123")
    mock_client.embed.tasks.retrieve.assert_called_once_with(task_id="task_123")


def test_embed_video_skips_segments_without_a_vector(twelvelabs_tools):
    """Segments the platform returns without a float vector should be dropped, not crash."""
    good = MagicMock(float_=[0.1, 0.2], start_offset_sec=0.0, end_offset_sec=6.0, embedding_scope="clip")
    empty = MagicMock(float_=None, start_offset_sec=6.0, end_offset_sec=12.0, embedding_scope="clip")
    retrieve_response = MagicMock()
    retrieve_response.video_embedding.segments = [good, empty]

    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.return_value = MagicMock(status="ready")
    mock_client.embed.tasks.retrieve.return_value = retrieve_response
    twelvelabs_tools._client = mock_client

    result = json.loads(twelvelabs_tools.embed_video(video_url="http://x/v.mp4"))
    assert result["num_segments"] == 1
    assert result["dimensions"] == 2


def test_embed_video_polls_until_ready():
    """The tool should keep polling (sleeping between checks) until a terminal status."""
    seg = MagicMock(float_=[0.1, 0.2], start_offset_sec=0.0, end_offset_sec=6.0, embedding_scope="clip")
    retrieve_response = MagicMock()
    retrieve_response.video_embedding.segments = [seg]

    tools = TwelveLabsTools(api_key="k", embed_poll_interval=0.01)
    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.side_effect = [
        MagicMock(status="processing"),
        MagicMock(status="processing"),
        MagicMock(status="ready"),
    ]
    mock_client.embed.tasks.retrieve.return_value = retrieve_response
    tools._client = mock_client

    with patch("agno.tools.twelvelabs.time.sleep") as mock_sleep:
        result = json.loads(tools.embed_video(video_url="http://x/v.mp4"))

    assert result["num_segments"] == 1
    assert mock_client.embed.tasks.status.call_count == 3
    assert mock_sleep.call_count == 2  # slept between the two non-terminal polls
    mock_client.embed.tasks.retrieve.assert_called_once_with(task_id="task_123")


def test_embed_video_no_task_id(twelvelabs_tools):
    """A create response without a task id should short-circuit before polling."""
    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id=None)
    twelvelabs_tools._client = mock_client

    assert twelvelabs_tools.embed_video(video_url="http://x/v.mp4") == "No embedding task id returned"
    mock_client.embed.tasks.status.assert_not_called()


def test_embed_video_all_segments_without_vectors(twelvelabs_tools):
    """If every segment lacks a vector, report no embedding rather than an empty result."""
    retrieve_response = MagicMock()
    retrieve_response.video_embedding.segments = [MagicMock(float_=None), MagicMock(float_=[])]

    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.return_value = MagicMock(status="ready")
    mock_client.embed.tasks.retrieve.return_value = retrieve_response
    twelvelabs_tools._client = mock_client

    assert twelvelabs_tools.embed_video(video_url="http://x/v.mp4") == "No embedding returned"


def test_embed_video_no_video_embedding_object(twelvelabs_tools):
    """A ready task with no video_embedding payload should report no embedding."""
    retrieve_response = MagicMock()
    retrieve_response.video_embedding = None

    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.return_value = MagicMock(status="ready")
    mock_client.embed.tasks.retrieve.return_value = retrieve_response
    twelvelabs_tools._client = mock_client

    assert twelvelabs_tools.embed_video(video_url="http://x/v.mp4") == "No embedding returned"


def test_embed_video_not_ready(twelvelabs_tools):
    """A non-ready terminal status should surface an error and skip retrieval."""
    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.return_value = MagicMock(status="failed")
    twelvelabs_tools._client = mock_client

    result = twelvelabs_tools.embed_video(video_url="http://x/v.mp4")
    assert "did not complete" in result
    assert "failed" in result
    mock_client.embed.tasks.retrieve.assert_not_called()


def test_embed_video_times_out():
    """A task that never reaches a terminal status should time out instead of hanging."""
    tools = TwelveLabsTools(api_key="k", embed_timeout=0.0)
    mock_client = MagicMock()
    mock_client.embed.tasks.create.return_value = MagicMock(id="task_123")
    mock_client.embed.tasks.status.return_value = MagicMock(status="processing")
    tools._client = mock_client

    result = tools.embed_video(video_url="http://x/v.mp4")
    assert "timed out" in result
    mock_client.embed.tasks.retrieve.assert_not_called()


def test_embed_video_error_is_caught(twelvelabs_tools):
    mock_client = MagicMock()
    mock_client.embed.tasks.create.side_effect = RuntimeError("boom")
    twelvelabs_tools._client = mock_client
    assert "Error embedding video" in twelvelabs_tools.embed_video(video_url="http://x/v.mp4")


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


@pytest.mark.skipif(
    not os.getenv("TWELVELABS_API_KEY"),
    reason="TWELVELABS_API_KEY not set; skipping live TwelveLabs API test",
)
def test_embed_video_live():
    """Live test: Marengo embeds the video into 512-dim segments; only metadata is returned."""
    tools = TwelveLabsTools(enable_embed_video=True)
    result = json.loads(
        tools.embed_video(video_url="https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4")
    )
    assert result["dimensions"] == 512
    assert result["num_segments"] >= 1
    assert "embedding" not in result["segments"][0]
    assert "start_offset_sec" in result["segments"][0]
