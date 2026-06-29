"""Unit tests for YouTubeTools."""

import importlib
import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

youtube_transcript_api = ModuleType("youtube_transcript_api")
youtube_transcript_api.YouTubeTranscriptApi = Mock
sys.modules.setdefault("youtube_transcript_api", youtube_transcript_api)


def create_mock_response(data):
    """Create a mock HTTP response."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(data).encode()
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    return mock_response


def _get_youtube_tools_cls():
    return importlib.import_module("agno.tools.youtube").YouTubeTools


def test_init_with_custom_timeout():
    """Test initialization with a custom timeout."""
    YouTubeTools = _get_youtube_tools_cls()
    tools = YouTubeTools(timeout=15)
    assert tools.timeout == 15


def test_get_youtube_video_data_passes_timeout():
    """Test get_youtube_video_data passes the configured timeout to urlopen."""
    YouTubeTools = _get_youtube_tools_cls()
    tools = YouTubeTools(
        enable_get_video_captions=False,
        enable_get_video_timestamps=False,
        timeout=15,
    )
    mock_response_data = {
        "title": "Test Video",
        "author_name": "Test Author",
        "provider_name": "YouTube",
    }

    with patch("agno.tools.youtube.urlopen", return_value=create_mock_response(mock_response_data)) as mock_urlopen:
        result = tools.get_youtube_video_data("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    result_data = json.loads(result)
    assert result_data["title"] == "Test Video"
    assert mock_urlopen.call_args.kwargs["timeout"] == 15
