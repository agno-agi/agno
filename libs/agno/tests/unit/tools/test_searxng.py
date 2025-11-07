"""Unit tests for Searxng class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.searxng import Searxng


@pytest.fixture
def searxng_instance():
    """Create a Searxng instance."""
    return Searxng(host="http://localhost:53153")


@pytest.fixture
def searxng_with_engines():
    """Create a Searxng instance with engines."""
    return Searxng(host="http://localhost:53153", engines=["google", "bing"])


@pytest.fixture
def searxng_with_fixed_results():
    """Create a Searxng instance with fixed max results."""
    return Searxng(host="http://localhost:53153", fixed_max_results=3)


def test_searxng_search(searxng_instance):
    """Test the search method of Searxng."""
    mock_response_payload = {
        "results": [
            {"title": "Result 1", "url": "http://example.com/1"},
            {"title": "Result 2", "url": "http://example.com/2"},
            {"title": "Result 3", "url": "http://example.com/3"},
        ]
    }

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        result = searxng_instance.search_web("test query", max_results=2)

        # Parse the JSON result since the method returns JSON string
        result_data = json.loads(result)

        # Check that only 2 results are returned (respecting max_results)
        assert len(result_data["results"]) == 2
        assert result_data["results"][0]["title"] == "Result 1"
        assert result_data["results"][1]["title"] == "Result 2"

        mock_get.assert_called_once_with("http://localhost:53153/search?format=json&q=test%20query")


def test_searxng_search_with_engines(searxng_with_engines):
    """Test search with specific engines configured."""
    mock_response_payload = {"results": [{"title": "Test", "url": "http://test.com"}]}

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        searxng_with_engines.search_web("test query")

        expected_url = "http://localhost:53153/search?format=json&q=test%20query&engines=google,bing"
        mock_get.assert_called_once_with(expected_url)


def test_searxng_search_with_fixed_max_results(searxng_with_fixed_results):
    """Test search with fixed max results override."""
    mock_response_payload = {
        "results": [{"title": f"Result {i}", "url": f"http://example.com/{i}"} for i in range(1, 6)]
    }

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        result = searxng_with_fixed_results.search_web("test query", max_results=10)
        result_data = json.loads(result)

        # Should respect fixed_max_results (3) instead of max_results (10)
        assert len(result_data["results"]) == 3


def test_searxng_image_search(searxng_instance):
    """Test the image_search method."""
    mock_response_payload = {"results": [{"title": "Image 1", "url": "http://example.com/img1"}]}

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        # Need to create instance with images=True to register the tool
        searxng_images = Searxng(host="http://localhost:53153")
        result = searxng_images.image_search("test image")

        expected_url = "http://localhost:53153/search?format=json&q=test%20image&categories=images"
        mock_get.assert_called_once_with(expected_url)

        result_data = json.loads(result)
        assert result_data["results"][0]["title"] == "Image 1"


def test_searxng_news_search():
    """Test the news_search method."""
    mock_response_payload = {"results": [{"title": "News 1", "url": "http://example.com/news1"}]}

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        searxng_news = Searxng(host="http://localhost:53153")
        searxng_news.news_search("breaking news")

        expected_url = "http://localhost:53153/search?format=json&q=breaking%20news&categories=news"
        mock_get.assert_called_once_with(expected_url)


def test_searxng_search_error_handling(searxng_instance):
    """Test error handling in search method."""
    with patch("httpx.get") as mock_get:
        mock_get.side_effect = Exception("Network error")

        result = searxng_instance.search_web("test query")

        assert "Error fetching results from searxng: Network error" in result


def test_searxng_query_encoding(searxng_instance):
    """Test that queries are properly URL encoded."""
    mock_response_payload = {"results": []}

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        searxng_instance.search_web("test query with spaces & symbols")

        expected_url = "http://localhost:53153/search?format=json&q=test%20query%20with%20spaces%20%26%20symbols"
        mock_get.assert_called_once_with(expected_url)


def test_searxng_initialization():
    """Test Searxng initialization with various parameters."""
    searxng = Searxng(host="http://test.com", engines=["google"], fixed_max_results=10)

    assert searxng.host == "http://test.com"
    assert searxng.engines == ["google"]
    assert searxng.fixed_max_results == 10
    assert (
        len(searxng.tools) == 8
    )  # All 8 tools: search, image_search, it_search, map_search, music_search, news_search, science_search, video_search


@pytest.mark.parametrize(
    "category,method_name",
    [
        ("it", "it_search"),
        ("map", "map_search"),
        ("music", "music_search"),
        ("science", "science_search"),
        ("videos", "video_search"),
    ],
)
def test_category_searches(category, method_name):
    """Test all category-specific search methods."""
    mock_response_payload = {"results": [{"title": "Test", "url": "http://test.com"}]}

    with patch("httpx.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_response_payload
        mock_get.return_value = mock_response

        # Create instance with only the specific method included
        searxng = Searxng(host="http://localhost:53153", include_tools=[method_name])

        # Call the method
        method = getattr(searxng, method_name)
        result = method("test query")

        expected_url = f"http://localhost:53153/search?format=json&q=test%20query&categories={category}"
        mock_get.assert_called_once_with(expected_url)

        result_data = json.loads(result)
        assert result_data["results"][0]["title"] == "Test"
