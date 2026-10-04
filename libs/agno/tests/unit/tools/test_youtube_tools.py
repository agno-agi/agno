import io
import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from agno.tools.youtube import YouTubeTools, _is_youtube_host


class TestIsYouTubeHost:
    @pytest.mark.parametrize(
        "hostname,expected",
        [
            ("youtube.com", True),
            ("www.youtube.com", True),
            ("m.youtube.com", True),
            ("music.youtube.com", True),
            ("youtube-nocookie.com", True),
            ("www.youtube-nocookie.com", True),
            ("youtube.com.br", True),
            ("www.youtube.co.uk", True),
            ("youtube.fr", True),
            ("google.com", False),
            ("notyoutube.com", False),
            ("fakeyoutube.com", False),
            ("", False),
            (None, False),
        ],
    )
    def test_is_youtube_host(self, hostname, expected):
        assert _is_youtube_host(hostname) is expected


class TestGetYouTubeVideoId:
    @pytest.fixture
    def tools(self):
        return YouTubeTools()

    @pytest.mark.parametrize(
        "url,expected_id",
        [
            # Standard watch URLs
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&feature=shared", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?feature=shared&v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # Short URLs (youtu.be)
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?t=10", "dQw4w9WgXcQ"),
            ("youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # YouTube Shorts
            ("https://www.youtube.com/shorts/BGQWPY4IigY", "BGQWPY4IigY"),
            ("https://www.youtube.com/shorts/BGQWPY4IigY/", "BGQWPY4IigY"),
            ("https://www.youtube.com/shorts/BGQWPY4IigY?feature=share", "BGQWPY4IigY"),
            ("https://youtube.com/shorts/BGQWPY4IigY", "BGQWPY4IigY"),
            ("youtube.com/shorts/BGQWPY4IigY", "BGQWPY4IigY"),
            ("https://m.youtube.com/shorts/BGQWPY4IigY", "BGQWPY4IigY"),
            # Live streams
            ("https://www.youtube.com/live/jfKfPfyJRdk", "jfKfPfyJRdk"),
            ("https://www.youtube.com/live/jfKfPfyJRdk/", "jfKfPfyJRdk"),
            ("https://www.youtube.com/live/jfKfPfyJRdk?si=abcdef123", "jfKfPfyJRdk"),
            ("https://youtube.com/live/jfKfPfyJRdk", "jfKfPfyJRdk"),
            # Embeds and /v/
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ/", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # Subdomains & privacy-enhanced
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube-nocookie.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # ccTLDs
            ("https://www.youtube.com.br/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.co.uk/shorts/BGQWPY4IigY", "BGQWPY4IigY"),
            # Whitespace handling
            ("   https://www.youtube.com/watch?v=dQw4w9WgXcQ \n  ", "dQw4w9WgXcQ"),
        ],
    )
    def test_valid_youtube_urls(self, tools, url, expected_id):
        assert tools.get_youtube_video_id(url) == expected_id

    @pytest.mark.parametrize(
        "invalid_url",
        [
            None,
            "",
            "   ",
            123,
            [],
            "https://google.com/watch?v=dQw4w9WgXcQ",
            "https://notyoutube.com/shorts/BGQWPY4IigY",
            "https://fake-youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com",
            "https://www.youtube.com/",
            "https://www.youtube.com/feed/subscriptions",
            "https://www.youtube.com/watch",
            "https://www.youtube.com/watch?v=",
            "https://www.youtube.com/shorts/",
            "https://www.youtube.com/live/",
            "https://youtu.be/",
        ],
    )
    def test_invalid_youtube_urls(self, tools, invalid_url):
        assert tools.get_youtube_video_id(invalid_url) is None


class TestGetYouTubeVideoData:
    @pytest.fixture
    def tools(self):
        return YouTubeTools()

    def test_empty_url(self, tools):
        assert tools.get_youtube_video_data("") == "No URL provided"
        assert tools.get_youtube_video_data(None) == "No URL provided"

    def test_url_with_no_video_id(self, tools):
        with patch("agno.tools.youtube.urlopen") as mock_urlopen:
            result = tools.get_youtube_video_data("https://www.youtube.com/feed/subscriptions")
            assert result == "No video ID found"
            mock_urlopen.assert_not_called()

    def test_valid_watch_url(self, tools):
        mock_response_data = {
            "title": "Never Gonna Give You Up",
            "author_name": "Rick Astley",
            "author_url": "https://www.youtube.com/@RickAstleyYT",
            "type": "video",
            "height": 113,
            "width": 200,
            "version": "1.0",
            "provider_name": "YouTube",
            "provider_url": "https://www.youtube.com/",
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        }
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = io.BytesIO(json.dumps(mock_response_data).encode("utf-8"))
        mock_cm.__exit__.return_value = None

        with patch("agno.tools.youtube.urlopen", return_value=mock_cm) as mock_urlopen:
            result = tools.get_youtube_video_data("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            data = json.loads(result)
            assert data["title"] == "Never Gonna Give You Up"
            assert data["author_name"] == "Rick Astley"
            assert data["thumbnail_url"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"

            # Check that urlopen was called with oEmbed URL for the resolved video id
            called_url = mock_urlopen.call_args[0][0]
            assert "https://www.youtube.com/oembed?" in called_url
            assert "dQw4w9WgXcQ" in called_url

    def test_shorts_url_fetches_via_canonical_watch_url(self, tools):
        mock_response_data = {
            "title": "Sample Short",
            "author_name": "Creator",
            "author_url": "https://www.youtube.com/@Creator",
            "type": "video",
            "height": 113,
            "width": 200,
            "version": "1.0",
            "provider_name": "YouTube",
            "provider_url": "https://www.youtube.com/",
            "thumbnail_url": "https://i.ytimg.com/vi/BGQWPY4IigY/hqdefault.jpg",
        }
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = io.BytesIO(json.dumps(mock_response_data).encode("utf-8"))
        mock_cm.__exit__.return_value = None

        with patch("agno.tools.youtube.urlopen", return_value=mock_cm) as mock_urlopen:
            result = tools.get_youtube_video_data("https://www.youtube.com/shorts/BGQWPY4IigY")
            data = json.loads(result)
            assert data["title"] == "Sample Short"

            called_url = mock_urlopen.call_args[0][0]
            assert "https://www.youtube.com/oembed?" in called_url
            assert "BGQWPY4IigY" in called_url

    def test_network_error_handling(self, tools):
        with patch("agno.tools.youtube.urlopen", side_effect=URLError("Connection refused")):
            result = tools.get_youtube_video_data("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            assert result.startswith("Error getting video data:")


class TestGetYouTubeVideoCaptions:
    @pytest.fixture
    def tools(self):
        return YouTubeTools()

    def test_empty_url(self, tools):
        assert tools.get_youtube_video_captions("") == "No URL provided"
        assert tools.get_youtube_video_captions(None) == "No URL provided"

    def test_invalid_url(self, tools):
        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api:
            result = tools.get_youtube_video_captions("https://www.youtube.com/feed/subscriptions")
            assert result == "No video ID found"
            mock_api.assert_not_called()

    def test_valid_url(self, tools):
        mock_line1 = MagicMock(text="Hello world")
        mock_line2 = MagicMock(text="Welcome back")

        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api_class:
            mock_api_instance = MagicMock()
            mock_api_class.return_value = mock_api_instance
            mock_api_instance.fetch.return_value = [mock_line1, mock_line2]

            result = tools.get_youtube_video_captions("https://www.youtube.com/shorts/BGQWPY4IigY")
            assert result == "Hello world Welcome back"
            mock_api_instance.fetch.assert_called_once_with("BGQWPY4IigY")

    def test_valid_url_no_captions(self, tools):
        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api_class:
            mock_api_instance = MagicMock()
            mock_api_class.return_value = mock_api_instance
            mock_api_instance.fetch.return_value = []

            result = tools.get_youtube_video_captions("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            assert result == "No captions found for video"

    def test_languages_and_proxies(self):
        tools = YouTubeTools(languages=["pt", "en"], proxies={"https": "http://proxy:8080"})
        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api_class:
            mock_api_instance = MagicMock()
            mock_api_class.return_value = mock_api_instance
            mock_api_instance.fetch.return_value = [MagicMock(text="Olá mundo")]

            result = tools.get_youtube_video_captions("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            assert result == "Olá mundo"
            mock_api_instance.fetch.assert_called_once_with(
                "dQw4w9WgXcQ",
                languages=["pt", "en"],
                proxies={"https": "http://proxy:8080"},
            )

    def test_exception_handling(self, tools):
        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api_class:
            mock_api_instance = MagicMock()
            mock_api_class.return_value = mock_api_instance
            mock_api_instance.fetch.side_effect = Exception("TranscriptsDisabled")

            result = tools.get_youtube_video_captions("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            assert result == "Error getting captions for video: TranscriptsDisabled"


class TestGetVideoTimestamps:
    @pytest.fixture
    def tools(self):
        return YouTubeTools()

    def test_empty_url(self, tools):
        assert tools.get_video_timestamps("") == "No URL provided"
        assert tools.get_video_timestamps(None) == "No URL provided"

    def test_invalid_url(self, tools):
        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api:
            result = tools.get_video_timestamps("https://www.youtube.com/feed/subscriptions")
            assert result == "No video ID found"
            mock_api.assert_not_called()

    def test_valid_url(self, tools):
        mock_line1 = MagicMock(text="Introduction", start=0.0)
        mock_line2 = MagicMock(text="Deep dive", start=65.0)
        mock_line3 = MagicMock(text="Conclusion", start=125.0)

        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api_class:
            mock_api_instance = MagicMock()
            mock_api_class.return_value = mock_api_instance
            mock_api_instance.fetch.return_value = [mock_line1, mock_line2, mock_line3]

            result = tools.get_video_timestamps("https://www.youtube.com/live/jfKfPfyJRdk")
            expected = "0:00 - Introduction\n1:05 - Deep dive\n2:05 - Conclusion"
            assert result == expected
            mock_api_instance.fetch.assert_called_once_with("jfKfPfyJRdk")

    def test_exception_handling(self, tools):
        with patch("agno.tools.youtube.YouTubeTranscriptApi") as mock_api_class:
            mock_api_instance = MagicMock()
            mock_api_class.return_value = mock_api_instance
            mock_api_instance.fetch.side_effect = Exception("Could not retrieve transcript")

            result = tools.get_video_timestamps("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            assert result == "Error generating timestamps: Could not retrieve transcript"


class TestYouTubeToolsInit:
    def test_default_tools_registration(self):
        tools = YouTubeTools()
        tool_names = [tool.__name__ for tool in tools.tools]
        assert "get_youtube_video_captions" in tool_names
        assert "get_youtube_video_data" in tool_names
        assert "get_video_timestamps" in tool_names

    def test_selective_tools_registration(self):
        tools = YouTubeTools(
            enable_get_video_captions=True,
            enable_get_video_data=False,
            enable_get_video_timestamps=False,
        )
        tool_names = [tool.__name__ for tool in tools.tools]
        assert tool_names == ["get_youtube_video_captions"]

    def test_all_flag(self):
        tools = YouTubeTools(
            all=True,
            enable_get_video_captions=False,
            enable_get_video_data=False,
            enable_get_video_timestamps=False,
        )
        tool_names = [tool.__name__ for tool in tools.tools]
        assert len(tool_names) == 3
