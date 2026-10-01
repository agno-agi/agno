"""Unit tests for YouTubeTools."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agno.tools.youtube import YouTubeTools


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=BGQWPY4IigY",
        "https://youtu.be/BGQWPY4IigY?si=abc",
        "https://www.youtube.com/embed/BGQWPY4IigY",
        "https://www.youtube.com/shorts/BGQWPY4IigY",
        "https://youtube.com/shorts/BGQWPY4IigY?feature=share",
        "https://www.youtube.com/live/BGQWPY4IigY",
        "https://m.youtube.com/watch?v=BGQWPY4IigY",
        "https://music.youtube.com/watch?v=BGQWPY4IigY",
        "https://www.youtube-nocookie.com/embed/BGQWPY4IigY",
    ],
)
def test_get_youtube_video_captions_accepts_url_forms(url):
    with patch("agno.tools.youtube.YouTubeTranscriptApi") as transcript_api:
        fetch = transcript_api.return_value.fetch
        fetch.return_value = [SimpleNamespace(text="hello"), SimpleNamespace(text="world")]

        result = YouTubeTools().get_youtube_video_captions(url)

    fetch.assert_called_once_with("BGQWPY4IigY")
    assert result == "hello world"


def test_get_youtube_video_data_without_video_id_skips_request():
    with patch("agno.tools.youtube.urlopen") as urlopen:
        result = YouTubeTools().get_youtube_video_data("https://vimeo.com/123")

    assert result == "No video ID found"
    urlopen.assert_not_called()
