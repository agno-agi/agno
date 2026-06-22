"""Unit tests for ScavioTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.scavio import ScavioTools


@pytest.fixture
def mock_scavio_client():
    """Create a mock ScavioClient instance."""
    with patch("agno.tools.scavio.ScavioClient") as mock_client_cls:
        mock_client = Mock()
        mock_client.google = Mock()
        mock_client.youtube = Mock()
        mock_client.amazon = Mock()
        mock_client.walmart = Mock()
        mock_client.reddit = Mock()
        mock_client.tiktok = Mock()
        mock_client.instagram = Mock()
        mock_client_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def scavio_tools(mock_scavio_client):
    """Create a ScavioTools instance with mocked dependencies."""
    tools = ScavioTools(api_key="test_key", all=True)
    tools.client = mock_scavio_client
    return tools


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_api_key():
    """Test initialization with explicit API key."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="my_key")
        assert tools.api_key == "my_key"
        assert tools.max_results == 5


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch("agno.tools.scavio.ScavioClient"):
        with patch.dict("os.environ", {"SCAVIO_API_KEY": "env_key"}):
            tools = ScavioTools()
            assert tools.api_key == "env_key"


def test_init_missing_api_key():
    """Test initialization fails without API key."""
    with patch("agno.tools.scavio.ScavioClient"):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No Scavio API key"):
                ScavioTools()


def test_init_default_tools():
    """Test default initialization enables only Google search."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="test_key")
        tool_names = [t.__name__ for t in tools.tools]
        assert "google_search" in tool_names
        assert "youtube_search" not in tool_names
        assert "amazon_search" not in tool_names


def test_init_all_flag():
    """Test initialization with all=True enables all tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="test_key", all=True)
        tool_names = [t.__name__ for t in tools.tools]
        assert "google_search" in tool_names
        assert "youtube_search" in tool_names
        assert "amazon_search" in tool_names
        assert "walmart_search" in tool_names
        assert "reddit_search" in tool_names
        assert "tiktok_search" in tool_names
        assert "instagram_search" in tool_names


def test_init_selective_tools():
    """Test initialization with selective tool flags."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="test_key", enable_google=False, enable_youtube=True, enable_reddit=True)
        tool_names = [t.__name__ for t in tools.tools]
        assert "google_search" not in tool_names
        assert "youtube_search" in tool_names
        assert "reddit_search" in tool_names
        assert "amazon_search" not in tool_names


def test_init_custom_max_results():
    """Test initialization with custom max_results."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="test_key", max_results=10)
        assert tools.max_results == 10


# ============================================================================
# GOOGLE SEARCH TESTS
# ============================================================================


def test_google_search(scavio_tools, mock_scavio_client):
    """Test google_search method."""
    mock_scavio_client.google.search.return_value = {
        "organic_results": [
            {"title": "Result 1", "link": "https://example.com", "snippet": "Test snippet"},
            {"title": "Result 2", "link": "https://example2.com", "snippet": "Another snippet"},
        ]
    }

    result = scavio_tools.google_search("test query")

    assert "Result 1" in result
    assert "https://example.com" in result
    assert "Test snippet" in result
    mock_scavio_client.google.search.assert_called_once_with("test query", country_code=None, language=None)


def test_google_search_with_params(scavio_tools, mock_scavio_client):
    """Test google_search with optional parameters."""
    mock_scavio_client.google.search.return_value = {"organic_results": []}

    scavio_tools.google_search("test", country_code="us", language="en")

    mock_scavio_client.google.search.assert_called_once_with("test", country_code="us", language="en")


def test_google_search_with_answer_box(scavio_tools, mock_scavio_client):
    """Test google_search includes answer_box when present."""
    mock_scavio_client.google.search.return_value = {
        "answer_box": {"answer": "42", "title": "The answer"},
        "organic_results": [{"title": "Result", "link": "https://ex.com", "snippet": "snip"}],
    }

    result = scavio_tools.google_search("meaning of life")

    assert "42" in result
    assert "The answer" in result


def test_google_search_respects_max_results(scavio_tools, mock_scavio_client):
    """Test google_search limits results."""
    mock_scavio_client.google.search.return_value = {
        "organic_results": [
            {"title": f"Result {i}", "link": f"https://ex{i}.com", "snippet": f"Snippet {i}"} for i in range(10)
        ]
    }

    result = scavio_tools.google_search("test", max_results=2)

    assert "Result 0" in result
    assert "Result 1" in result
    assert "Result 2" not in result


def test_google_search_error_handling(scavio_tools, mock_scavio_client):
    """Test google_search handles errors gracefully."""
    mock_scavio_client.google.search.side_effect = Exception("API timeout")

    result = scavio_tools.google_search("test")

    assert "Error" in result
    assert "API timeout" in result


# ============================================================================
# YOUTUBE SEARCH TESTS
# ============================================================================


def test_youtube_search(scavio_tools, mock_scavio_client):
    """Test youtube_search method."""
    mock_scavio_client.youtube.search.return_value = {
        "video_results": [
            {
                "title": "Video 1",
                "link": "https://youtube.com/watch?v=abc",
                "channel": {"name": "Channel 1"},
                "views": "1M",
                "published_date": "2 days ago",
            }
        ]
    }

    result = scavio_tools.youtube_search("python tutorial")

    assert "Video 1" in result
    assert "Channel 1" in result
    mock_scavio_client.youtube.search.assert_called_once_with("python tutorial", sort_by=None)


def test_youtube_search_with_sort(scavio_tools, mock_scavio_client):
    """Test youtube_search with sort parameter."""
    mock_scavio_client.youtube.search.return_value = {"video_results": []}

    scavio_tools.youtube_search("test", sort_by="date")

    mock_scavio_client.youtube.search.assert_called_once_with("test", sort_by="date")


def test_youtube_search_error(scavio_tools, mock_scavio_client):
    """Test youtube_search handles errors."""
    mock_scavio_client.youtube.search.side_effect = Exception("Rate limit")

    result = scavio_tools.youtube_search("test")

    assert "Error" in result


# ============================================================================
# AMAZON SEARCH TESTS
# ============================================================================


def test_amazon_search(scavio_tools, mock_scavio_client):
    """Test amazon_search method."""
    mock_scavio_client.amazon.search.return_value = {
        "results": [{"title": "Product 1", "price": "$29.99", "url": "https://amazon.com/dp/123"}]
    }

    result = scavio_tools.amazon_search("headphones")

    assert "Product 1" in result
    mock_scavio_client.amazon.search.assert_called_once_with("headphones", domain=None, sort_by=None)


def test_amazon_search_with_domain(scavio_tools, mock_scavio_client):
    """Test amazon_search with domain parameter."""
    mock_scavio_client.amazon.search.return_value = {"results": []}

    scavio_tools.amazon_search("laptop", domain="co.uk")

    mock_scavio_client.amazon.search.assert_called_once_with("laptop", domain="co.uk", sort_by=None)


# ============================================================================
# WALMART SEARCH TESTS
# ============================================================================


def test_walmart_search(scavio_tools, mock_scavio_client):
    """Test walmart_search method."""
    mock_scavio_client.walmart.search.return_value = {"results": [{"title": "Item 1", "price": "$19.99"}]}

    result = scavio_tools.walmart_search("tv")

    assert "Item 1" in result
    mock_scavio_client.walmart.search.assert_called_once_with("tv", sort_by=None)


# ============================================================================
# REDDIT SEARCH TESTS
# ============================================================================


def test_reddit_search(scavio_tools, mock_scavio_client):
    """Test reddit_search method."""
    mock_scavio_client.reddit.search.return_value = {
        "posts": [{"title": "Post 1", "subreddit": "python", "url": "https://reddit.com/r/python/123"}]
    }

    result = scavio_tools.reddit_search("asyncio")

    assert "Post 1" in result
    mock_scavio_client.reddit.search.assert_called_once_with("asyncio", sort=None)


def test_reddit_search_with_sort(scavio_tools, mock_scavio_client):
    """Test reddit_search with sort parameter."""
    mock_scavio_client.reddit.search.return_value = {"posts": []}

    scavio_tools.reddit_search("test", sort="top")

    mock_scavio_client.reddit.search.assert_called_once_with("test", sort="top")


# ============================================================================
# TIKTOK SEARCH TESTS
# ============================================================================


def test_tiktok_search(scavio_tools, mock_scavio_client):
    """Test tiktok_search method."""
    mock_scavio_client.tiktok.search_videos.return_value = {
        "videos": [{"title": "TikTok 1", "author": "user1", "views": 50000}]
    }

    result = scavio_tools.tiktok_search("cooking")

    assert "TikTok 1" in result
    mock_scavio_client.tiktok.search_videos.assert_called_once_with("cooking", sort_type=None)


# ============================================================================
# INSTAGRAM SEARCH TESTS
# ============================================================================


def test_instagram_search(scavio_tools, mock_scavio_client):
    """Test instagram_search method."""
    mock_scavio_client.instagram.search_users.return_value = {
        "users": [{"username": "testuser", "full_name": "Test User", "followers": 1000}]
    }

    result = scavio_tools.instagram_search("photography")

    assert "testuser" in result
    mock_scavio_client.instagram.search_users.assert_called_once_with("photography")


# ============================================================================
# FORMAT HELPER TESTS
# ============================================================================


def test_format_google_results_with_answer_box():
    """Test _format_google_results includes answer box."""
    response = {
        "answer_box": {"answer": "Paris"},
        "organic_results": [{"title": "France", "link": "https://ex.com", "snippet": "Capital"}],
    }

    result = ScavioTools._format_google_results(response, max_results=5)

    assert "Paris" in result
    assert "France" in result


def test_format_google_results_limits_output():
    """Test _format_google_results respects max_results."""
    response = {
        "organic_results": [{"title": f"R{i}", "link": f"https://ex{i}.com", "snippet": f"S{i}"} for i in range(10)]
    }

    result = ScavioTools._format_google_results(response, max_results=3)

    assert "R0" in result
    assert "R2" in result
    assert "R3" not in result


def test_format_youtube_results():
    """Test _format_youtube_results formats correctly."""
    response = {
        "video_results": [
            {
                "title": "Vid",
                "link": "https://yt.com/v",
                "channel": {"name": "Ch"},
                "views": "1K",
                "published_date": "1d",
            }
        ]
    }

    result = ScavioTools._format_youtube_results(response, max_results=5)

    assert "Vid" in result
    assert "Ch" in result


def test_format_results_generic_list():
    """Test _format_results handles raw list response."""
    response = [{"title": "Item 1"}, {"title": "Item 2"}, {"title": "Item 3"}]

    result = ScavioTools._format_results(response, max_results=2)

    assert "Item 1" in result
    assert "Item 2" in result
    assert "Item 3" not in result


def test_format_results_dict_with_results_key():
    """Test _format_results handles dict with 'results' key."""
    response = {"results": [{"name": "A"}, {"name": "B"}]}

    result = ScavioTools._format_results(response, max_results=5)

    assert "A" in result
    assert "B" in result


def test_format_results_dict_without_known_keys():
    """Test _format_results falls back to full JSON dump."""
    response = {"custom_key": "custom_value", "count": 42}

    result = ScavioTools._format_results(response, max_results=5)

    assert "custom_value" in result
    assert "42" in result
