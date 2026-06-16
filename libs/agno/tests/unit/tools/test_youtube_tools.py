"""Unit tests for YouTubeTools."""

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch

youtube_transcript_api = ModuleType("youtube_transcript_api")
youtube_transcript_api.YouTubeTranscriptApi = Mock()
sys.modules.setdefault("youtube_transcript_api", youtube_transcript_api)


def create_mock_response(data):
    """Create a mock HTTP response."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(data).encode()
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    return mock_response


def test_init_uses_default_timeout():
    """Test initialization uses a default request timeout."""
    from agno.tools.youtube import YouTubeTools

    tools = YouTubeTools()
    assert tools.timeout == 30


def test_get_youtube_video_data_uses_configured_timeout():
    """Test oEmbed lookup uses the configured timeout."""
    from agno.tools.youtube import YouTubeTools

    response_data = {
        "title": "Test Video",
        "author_name": "Test Author",
        "author_url": "https://www.youtube.com/@test",
        "type": "video",
        "height": 113,
        "width": 200,
        "version": "1.0",
        "provider_name": "YouTube",
        "provider_url": "https://www.youtube.com/",
        "thumbnail_url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg",
    }

    with patch("agno.tools.youtube.urlopen") as mock_urlopen:
        mock_urlopen.return_value = create_mock_response(response_data)
        tools = YouTubeTools(timeout=5)

        result = tools.get_youtube_video_data("https://www.youtube.com/watch?v=abc123")

        result_data = json.loads(result)
        assert result_data["title"] == "Test Video"
        assert mock_urlopen.call_args.kwargs["timeout"] == 5
