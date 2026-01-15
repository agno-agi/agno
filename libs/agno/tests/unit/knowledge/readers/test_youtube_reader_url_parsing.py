"""
Tests for YouTube Reader URL parsing.

Bug Report: KNOWLEDGE-003 (FIXED)
- YouTubeReader now handles both youtube.com and youtu.be URL formats
- Invalid URLs raise ValueError instead of silently failing
"""

import pytest

from agno.knowledge.reader.youtube_reader import YouTubeReader


class TestYouTubeVideoIdExtraction:
    """Test that YouTube video IDs are correctly extracted from various URL formats."""

    @pytest.fixture
    def reader(self):
        """Create a YouTubeReader instance."""
        return YouTubeReader()

    # Standard youtube.com URLs
    def test_standard_youtube_url(self, reader):
        """Standard youtube.com URL should extract correct video ID."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        video_id = reader._extract_video_id(url)
        assert video_id == "dQw4w9WgXcQ"

    def test_youtube_url_with_extra_params(self, reader):
        """YouTube URL with additional parameters should extract correct ID."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        video_id = reader._extract_video_id(url)
        assert video_id == "dQw4w9WgXcQ"

    def test_youtube_url_with_feature_param(self, reader):
        """YouTube URL with feature parameter should extract correct ID."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=youtu.be"
        video_id = reader._extract_video_id(url)
        assert video_id == "dQw4w9WgXcQ"

    # youtu.be short URLs (Bug KNOWLEDGE-003 fix)
    def test_youtu_be_short_url(self, reader):
        """Short youtu.be URL should extract video ID."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        video_id = reader._extract_video_id(url)
        assert video_id == "dQw4w9WgXcQ"

    def test_youtu_be_with_timestamp(self, reader):
        """Short youtu.be URL with timestamp should extract video ID."""
        url = "https://youtu.be/dQw4w9WgXcQ?t=42"
        video_id = reader._extract_video_id(url)
        assert video_id == "dQw4w9WgXcQ"

    def test_youtu_be_with_start_param(self, reader):
        """Short youtu.be URL with start parameter should extract video ID."""
        url = "https://youtu.be/dQw4w9WgXcQ?start=120"
        video_id = reader._extract_video_id(url)
        assert video_id == "dQw4w9WgXcQ"

    # Invalid URLs should raise ValueError
    def test_invalid_url_channel(self, reader):
        """Channel URL should raise ValueError."""
        url = "https://www.youtube.com/channel/UCq-Fj5jknLsUf-MWSy4_brA"
        with pytest.raises(ValueError, match="Could not extract video ID"):
            reader._extract_video_id(url)

    def test_invalid_url_not_youtube(self, reader):
        """Non-YouTube URL should raise ValueError."""
        url = "https://example.com/not-youtube"
        with pytest.raises(ValueError, match="Could not extract video ID"):
            reader._extract_video_id(url)

    def test_invalid_video_id_too_short(self, reader):
        """URL with invalid video ID (too short) should raise ValueError."""
        url = "https://www.youtube.com/watch?v=abc"
        with pytest.raises(ValueError, match="must be 11 characters"):
            reader._extract_video_id(url)

    def test_invalid_video_id_too_long(self, reader):
        """URL with invalid video ID (too long) should raise ValueError."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQextra"
        with pytest.raises(ValueError, match="must be 11 characters"):
            reader._extract_video_id(url)


class TestYouTubeReaderURLFormats:
    """Test that all common YouTube URL formats are supported."""

    @pytest.fixture
    def reader(self):
        return YouTubeReader()

    @pytest.mark.parametrize(
        "url,expected_id",
        [
            # Standard formats
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            # With extra parameters
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=60", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "dQw4w9WgXcQ"),
            # Short URL formats
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ?t=1m30s", "dQw4w9WgXcQ"),
        ],
    )
    def test_url_formats(self, reader, url, expected_id):
        """Various YouTube URL formats should extract correct video ID."""
        video_id = reader._extract_video_id(url)
        assert video_id == expected_id
