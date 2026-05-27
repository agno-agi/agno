"""Unit tests for ParallelTools"""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.parallel import ParallelTools


@pytest.fixture
def mock_parallel_client():
    """Mock Parallel client."""
    with patch("agno.tools.parallel.ParallelClient") as mock_client:
        yield mock_client


@pytest.fixture
def parallel_tools(mock_parallel_client):
    """Create ParallelTools instance with mocked client."""
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key")


def test_parallel_search(parallel_tools):
    """Test parallel_search function."""
    # Setup mock data
    mock_result = Mock()
    mock_result.model_dump = Mock(
        return_value={
            "search_id": "test-search-id",
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "publish_date": "2025-01-01",
                    "excerpt": "Test excerpt content",
                }
            ],
        }
    )

    parallel_tools.parallel_client.beta.search = Mock(return_value=mock_result)

    # Execute test
    result = parallel_tools.parallel_search(objective="Test objective")
    result_dict = json.loads(result)

    # Verify the result
    assert result_dict["search_id"] == "test-search-id"
    assert len(result_dict["results"]) == 1
    assert result_dict["results"][0]["title"] == "Test Title"


def test_parallel_search_with_queries(parallel_tools):
    """Test parallel_search with search queries."""
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "test-id", "results": []})

    parallel_tools.parallel_client.beta.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="Test", search_queries=["query1", "query2"])

    # Verify search_queries was passed
    call_args = parallel_tools.parallel_client.beta.search.call_args
    assert call_args[1]["search_queries"] == ["query1", "query2"]


def test_parallel_search_error(parallel_tools):
    """Test parallel_search error handling."""
    parallel_tools.parallel_client.beta.search = Mock(side_effect=Exception("API Error"))

    result = parallel_tools.parallel_search(objective="Test")
    result_dict = json.loads(result)

    assert "error" in result_dict
    assert "Search failed" in result_dict["error"]


def test_parallel_extract(parallel_tools):
    """Test parallel_extract function."""
    # Setup mock data
    mock_result = Mock()
    mock_result.model_dump = Mock(
        return_value={
            "extract_id": "test-extract-id",
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Test Title",
                    "excerpts": ["Excerpt 1", "Excerpt 2"],
                }
            ],
            "errors": [],
        }
    )

    parallel_tools.parallel_client.beta.extract = Mock(return_value=mock_result)

    # Execute test
    result = parallel_tools.parallel_extract(urls=["https://example.com"])
    result_dict = json.loads(result)

    # Verify the result
    assert result_dict["extract_id"] == "test-extract-id"
    assert len(result_dict["results"]) == 1
    assert result_dict["results"][0]["url"] == "https://example.com"


def test_parallel_extract_with_full_content(parallel_tools):
    """Test parallel_extract with full_content."""
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"extract_id": "test-id", "results": [], "errors": []})

    parallel_tools.parallel_client.beta.extract = Mock(return_value=mock_result)

    parallel_tools.parallel_extract(urls=["https://example.com"], excerpts=False, full_content=True)

    # Verify parameters
    call_args = parallel_tools.parallel_client.beta.extract.call_args
    assert call_args[1]["excerpts"] is False
    assert call_args[1]["full_content"] is True


def test_parallel_extract_error(parallel_tools):
    """Test parallel_extract error handling."""
    parallel_tools.parallel_client.beta.extract = Mock(side_effect=Exception("API Error"))

    result = parallel_tools.parallel_extract(urls=["https://example.com"])
    result_dict = json.loads(result)

    assert "error" in result_dict
    assert "Extract failed" in result_dict["error"]
