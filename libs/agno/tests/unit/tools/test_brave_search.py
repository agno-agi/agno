import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.bravesearch import BraveSearchTools


@pytest.fixture
def mock_brave_client():
    with patch("agno.tools.bravesearch.Brave") as mock_brave:
        # Create a mock instance that will be returned when Brave() is called
        mock_instance = MagicMock()

        # Mock the search method to return a proper result
        mock_result = MagicMock()
        mock_result.web = MagicMock()
        mock_result.web.results = []
        mock_instance.search.return_value = mock_result

        # Mock the _get method to return a proper response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"web": {"results": []}}
        mock_instance._get.return_value = mock_response

        mock_brave.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def brave_search_tools(mock_brave_client):
    os.environ["BRAVE_API_KEY"] = "test_api_key"
    return BraveSearchTools()


def test_init_with_api_key():
    with patch("agno.tools.bravesearch.Brave"):
        tools = BraveSearchTools(api_key="test_key")
        assert tools.api_key == "test_key"
        assert tools.fixed_max_results is None
        assert tools.fixed_language is None


def test_init_with_env_var():
    os.environ["BRAVE_API_KEY"] = "env_test_key"
    with patch("agno.tools.bravesearch.Brave"):
        tools = BraveSearchTools()
        assert tools.api_key == "env_test_key"


def test_init_without_api_key():
    if "BRAVE_API_KEY" in os.environ:
        del os.environ["BRAVE_API_KEY"]
    with pytest.raises(ValueError, match="BRAVE_API_KEY is required"):
        BraveSearchTools()


def test_init_with_fixed_params():
    with patch("agno.tools.bravesearch.Brave"):
        tools = BraveSearchTools(api_key="test_key", fixed_max_results=10, fixed_language="fr")
        assert tools.fixed_max_results == 10
        assert tools.fixed_language == "fr"


def test_toolkit_integration():
    """Test that the toolkit is properly initialized with name and tools"""
    with patch("agno.tools.bravesearch.Brave"):
        tools = BraveSearchTools(api_key="test_key")
        assert tools.name == "brave_search"
        assert len(tools.tools) == 1
        assert tools.tools[0].__name__ == "brave_search"


def test_brave_search_empty_query(brave_search_tools):
    result = brave_search_tools.brave_search("")
    assert json.loads(result) == {"error": "Please provide a query to search for"}


def test_brave_search_none_query(brave_search_tools):
    """Test with None query"""
    result = brave_search_tools.brave_search(None)
    assert json.loads(result) == {"error": "Please provide a query to search for"}


def test_brave_search_whitespace_query(brave_search_tools, mock_brave_client):
    """Test with whitespace-only query - currently treated as valid query"""
    # Note: Current implementation treats whitespace as valid query
    # This could be a future improvement to strip/validate queries
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("   ")
    result_dict = json.loads(result)

    # Current behavior: whitespace queries are processed as normal
    assert result_dict["query"] == "   "
    assert result_dict["web_results"] == []
    assert result_dict["total_results"] == 0


def test_brave_search_successful(brave_search_tools, mock_brave_client):
    # Mock the search results
    mock_web_result = MagicMock()
    mock_web_result.title = "Test Title"
    mock_web_result.url = "https://test.com"
    mock_web_result.description = "Test Description"

    mock_result = MagicMock()
    mock_result.web.results = [mock_web_result]
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["query"] == "test query"
    assert len(result_dict["web_results"]) == 1
    assert result_dict["web_results"][0]["title"] == "Test Title"
    assert result_dict["web_results"][0]["url"] == "https://test.com"
    assert result_dict["web_results"][0]["description"] == "Test Description"
    assert result_dict["total_results"] == 1


def test_brave_search_with_multiple_results(brave_search_tools, mock_brave_client):
    """Test search with multiple results"""
    mock_results = []
    for i in range(3):
        mock_result = MagicMock()
        mock_result.title = f"Title {i}"
        mock_result.url = f"https://test{i}.com"
        mock_result.description = f"Description {i}"
        mock_results.append(mock_result)

    mock_search_result = MagicMock()
    mock_search_result.web.results = mock_results
    mock_brave_client.search.return_value = mock_search_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["query"] == "test query"
    assert len(result_dict["web_results"]) == 3
    assert result_dict["total_results"] == 3
    for i in range(3):
        assert result_dict["web_results"][i]["title"] == f"Title {i}"
        assert result_dict["web_results"][i]["url"] == f"https://test{i}.com"
        assert result_dict["web_results"][i]["description"] == f"Description {i}"


def test_brave_search_with_malformed_results(brave_search_tools, mock_brave_client):
    """Test search with results missing attributes"""
    mock_web_result = MagicMock()
    mock_web_result.title = None
    mock_web_result.url = None
    mock_web_result.description = None

    mock_result = MagicMock()
    mock_result.web.results = [mock_web_result]
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["query"] == "test query"
    assert len(result_dict["web_results"]) == 1
    assert result_dict["web_results"][0]["title"] is None
    assert result_dict["web_results"][0]["url"] == "None"  # str() conversion
    assert result_dict["web_results"][0]["description"] is None
    assert result_dict["total_results"] == 1


def test_brave_search_with_custom_params(brave_search_tools, mock_brave_client):
    # Mock the search results
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    brave_search_tools.brave_search(query="test query", max_results=3, country="UK", search_lang="fr")

    # Verify the search was called with correct parameters
    mock_brave_client.search.assert_called_once_with(
        q="test query", count=3, country="UK", search_lang="fr", result_filter="web"
    )


def test_brave_search_with_default_params(brave_search_tools, mock_brave_client):
    """Test that default parameters are used when not specified"""
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    brave_search_tools.brave_search(query="test query")

    # Verify the search was called with default parameters
    mock_brave_client.search.assert_called_once_with(
        q="test query", count=5, country="US", search_lang="en", result_filter="web"
    )


def test_brave_search_with_none_params(brave_search_tools, mock_brave_client):
    """Test search with None parameters - should use defaults"""
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    # Note: max_results and search_lang now have defaults, None parameters will be overridden
    brave_search_tools.brave_search(query="test query", country=None)

    # Verify the search was called with default values for max_results and search_lang
    mock_brave_client.search.assert_called_once_with(
        q="test query", count=5, country=None, search_lang="en", result_filter="web"
    )


def test_brave_search_with_fixed_params():
    with patch("agno.tools.bravesearch.Brave") as mock_brave:
        mock_instance = MagicMock()

        # Mock the search method
        mock_result = MagicMock()
        mock_result.web = MagicMock()
        mock_result.web.results = []
        mock_instance.search.return_value = mock_result

        # Mock the _get method
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"web": {"results": []}}
        mock_instance._get.return_value = mock_response

        mock_brave.return_value = mock_instance

        tools = BraveSearchTools(api_key="test_key", fixed_max_results=5, fixed_language="fr")

        result = tools.brave_search(query="test query", max_results=10, search_lang="en")
        result_dict = json.loads(result)

        # Verify the response structure
        assert result_dict["query"] == "test query"
        assert result_dict["web_results"] == []
        assert result_dict["total_results"] == 0

        # Verify fixed parameters override the provided ones
        mock_instance.search.assert_called_once_with(
            q="test query",
            count=5,  # Should use fixed_max_results (not the provided 10)
            country="US",  # Should use default value
            search_lang="fr",  # Should use fixed_language (not the provided "en")
            result_filter="web",
        )


def test_brave_search_no_web_results(brave_search_tools, mock_brave_client):
    # Mock the search results with no web results
    mock_result = MagicMock()
    mock_result.web = None
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["query"] == "test query"
    assert result_dict["web_results"] == []
    assert result_dict["total_results"] == 0


def test_brave_search_web_attribute_missing(brave_search_tools, mock_brave_client):
    """Test when search results object doesn't have 'web' attribute"""
    mock_result = MagicMock()
    del mock_result.web  # Remove the web attribute
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["query"] == "test query"
    assert result_dict["web_results"] == []
    assert result_dict["total_results"] == 0


def test_brave_search_empty_web_results(brave_search_tools, mock_brave_client):
    """Test when web.results is empty list"""
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["query"] == "test query"
    assert result_dict["web_results"] == []
    assert result_dict["total_results"] == 0


def test_brave_search_exception_handling(brave_search_tools, mock_brave_client):
    """Test that exceptions from Brave client are handled gracefully"""
    mock_brave_client.search.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        brave_search_tools.brave_search("test query")


@patch("agno.tools.bravesearch.log_info")
def test_brave_search_logging(mock_log_info, brave_search_tools, mock_brave_client):
    """Test that logging is called correctly"""
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    brave_search_tools.brave_search("test query")

    mock_log_info.assert_called_once_with("Searching Brave for: test query")


def test_brave_search_result_filter_always_web(brave_search_tools, mock_brave_client):
    """Test that result_filter is always set to 'web'"""
    mock_result = MagicMock()
    mock_result.web.results = []
    mock_brave_client.search.return_value = mock_result

    brave_search_tools.brave_search("test query")

    # Verify result_filter is always 'web'
    call_args = mock_brave_client.search.call_args
    assert call_args[1]["result_filter"] == "web"


def test_brave_search_url_conversion(brave_search_tools, mock_brave_client):
    """Test that URL is converted to string using str()"""
    mock_web_result = MagicMock()
    mock_web_result.title = "Test Title"
    mock_web_result.url = 12345  # Non-string URL
    mock_web_result.description = "Test Description"

    mock_result = MagicMock()
    mock_result.web.results = [mock_web_result]
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")
    result_dict = json.loads(result)

    assert result_dict["web_results"][0]["url"] == "12345"


def test_json_serialization_integrity(brave_search_tools, mock_brave_client):
    """Test that the returned JSON is valid and can be parsed"""
    mock_web_result = MagicMock()
    mock_web_result.title = "Test Title"
    mock_web_result.url = "https://test.com"
    mock_web_result.description = "Test Description"

    mock_result = MagicMock()
    mock_result.web.results = [mock_web_result]
    mock_brave_client.search.return_value = mock_result

    result = brave_search_tools.brave_search("test query")

    # Should not raise an exception
    parsed = json.loads(result)

    # Verify structure
    assert "web_results" in parsed
    assert "query" in parsed
    assert "total_results" in parsed

    # Verify it can be serialized again (round-trip test)
    json.dumps(parsed)
