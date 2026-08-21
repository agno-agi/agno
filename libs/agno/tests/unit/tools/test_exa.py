"""Unit tests for ExaTools class."""

import json
from unittest.mock import Mock, patch

import pytest
from exa_py import Exa
from exa_py.api import SearchResponse

from agno.tools.exa import ExaTools


@pytest.fixture
def mock_exa_client():
    """Create a mock Exa API client."""
    with patch("agno.tools.exa.Exa") as mock_exa:
        mock_client = Mock(spec=Exa)
        mock_exa.return_value = mock_client
        return mock_client


@pytest.fixture
def exa_tools(mock_exa_client):
    """Create ExaTools instance with mocked API."""
    with patch.dict("os.environ", {"EXA_API_KEY": "test_key"}):
        tools = ExaTools()
        tools.exa = mock_exa_client
        return tools


def create_mock_search_result(
    url: str,
    title: str = None,
    author: str = None,
    published_date: str = None,
    text: str = None,
):
    """Helper function to create mock search result."""
    result = Mock()
    result.url = url
    result.title = title
    result.author = author
    result.published_date = published_date
    result.text = text
    return result


def test_init_with_api_key():
    """Test initialization with provided API key."""
    with patch("agno.tools.exa.Exa") as mock_exa:
        with patch.dict("os.environ", {"EXA_API_KEY": "test_key"}):
            ExaTools()
            mock_exa.assert_called_once_with("test_key")


def test_init_with_selective_tools():
    """Test initialization with only selected tools."""
    with patch.dict("os.environ", {"EXA_API_KEY": "test_key"}):
        tools = ExaTools(
            enable_search=True,
            enable_get_contents=False,
            enable_find_similar=True,
            enable_answer=False,
        )

        assert "search_exa" in [func.name for func in tools.functions.values()]
        assert "get_contents" not in [func.name for func in tools.functions.values()]
        assert "find_similar" in [func.name for func in tools.functions.values()]
        assert "exa_answer" not in [func.name for func in tools.functions.values()]


def test_search_exa_success(exa_tools, mock_exa_client):
    """Test successful search operation."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://example.com",
            title="Test Article",
            author="John Doe",
            published_date="2024-01-01",
            text="Sample text content",
        )
    ]

    mock_exa_client.search_and_contents.return_value = mock_response

    result = exa_tools.search_exa("test query", num_results=5)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    assert result_data[0]["title"] == "Test Article"
    assert result_data[0]["author"] == "John Doe"
    assert result_data[0]["text"] == "Sample text content"


def test_get_contents_success(exa_tools, mock_exa_client):
    """Test successful content retrieval."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://example.com",
            title="Test Article",
            text="Article content",
        )
    ]

    mock_exa_client.get_contents.return_value = mock_response

    result = exa_tools.get_contents(["https://example.com"])
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    assert result_data[0]["title"] == "Test Article"
    assert result_data[0]["text"] == "Article content"


def test_find_similar_success(exa_tools, mock_exa_client):
    """Test successful similar content search."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://similar.com",
            title="Similar Article",
            text="Similar content",
        )
    ]

    mock_exa_client.find_similar_and_contents.return_value = mock_response

    result = exa_tools.find_similar("https://example.com", num_results=5)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://similar.com"
    assert result_data[0]["title"] == "Similar Article"
    assert result_data[0]["text"] == "Similar content"


def test_exa_answer_success(exa_tools, mock_exa_client):
    """Test successful answer generation."""
    mock_citation = Mock()
    mock_citation.id = "1"
    mock_citation.url = "https://example.com"
    mock_citation.title = "Source Article"
    mock_citation.published_date = "2024-01-01"
    mock_citation.author = "John Doe"
    mock_citation.text = "Source content"

    mock_answer = Mock()
    mock_answer.answer = "Generated answer"
    mock_answer.citations = [mock_citation]

    mock_exa_client.answer.return_value = mock_answer

    result = exa_tools.exa_answer("test question")
    result_data = json.loads(result)

    assert result_data["answer"] == "Generated answer"
    assert len(result_data["citations"]) == 1
    assert result_data["citations"][0]["url"] == "https://example.com"
    assert result_data["citations"][0]["title"] == "Source Article"


def test_search_with_category(exa_tools, mock_exa_client):
    """Test search with category filter."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://example.com",
            title="Research Paper",
            text="Research content",
        )
    ]

    mock_exa_client.search_and_contents.return_value = mock_response

    result = exa_tools.search_exa("research", category="research paper")
    result_data = json.loads(result)

    assert len(result_data) == 1
    mock_exa_client.search_and_contents.assert_called_with(
        "research",
        text=True,
        summary=False,
        num_results=5,
        category="research paper",
    )


def test_error_handling(exa_tools, mock_exa_client):
    """Test error handling in various methods."""
    # Test search error
    mock_exa_client.search_and_contents.side_effect = Exception("Search API Error")
    result = exa_tools.search_exa("test query")
    assert json.loads(result)["error"] == "Search API Error"

    # Test get_contents error
    mock_exa_client.get_contents.side_effect = Exception("Contents API Error")
    result = exa_tools.get_contents(["https://example.com"])
    assert json.loads(result)["error"] == "Contents API Error"

    # Test find_similar error
    mock_exa_client.find_similar_and_contents.side_effect = Exception("Similar API Error")
    result = exa_tools.find_similar("https://example.com")
    assert json.loads(result)["error"] == "Similar API Error"

    # Test answer error
    mock_exa_client.answer.side_effect = Exception("Answer API Error")
    result = exa_tools.exa_answer("test question")
    assert json.loads(result)["error"] == "Answer API Error"


def test_parse_results_with_missing_fields(exa_tools):
    """Test parsing results with missing optional fields."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://example.com",
            # Missing optional fields
        )
    ]

    result = exa_tools._parse_results(mock_response)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://example.com"
    assert "title" not in result_data[0]
    assert "author" not in result_data[0]
    assert "published_date" not in result_data[0]


def test_text_length_limit(exa_tools, mock_exa_client):
    """Test text length limiting functionality."""
    long_text = "x" * 2000
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://example.com",
            text=long_text,
        )
    ]

    mock_exa_client.search_and_contents.return_value = mock_response
    exa_tools.text_length_limit = 1000

    result = exa_tools.search_exa("test query")
    result_data = json.loads(result)

    assert len(result_data[0]["text"]) == 1000


def test_exa_answer_with_model_selection(exa_tools, mock_exa_client):
    """Test answer generation with different models."""
    mock_answer = Mock()
    mock_answer.answer = "Generated answer"
    mock_answer.citations = []

    mock_exa_client.answer.return_value = mock_answer

    # Test with exa model
    exa_tools.model = "exa"
    result = exa_tools.exa_answer("test question")
    result_data = json.loads(result)
    assert result_data["answer"] == "Generated answer"

    # Test with exa-pro model
    exa_tools.model = "exa-pro"
    result = exa_tools.exa_answer("test question")
    result_data = json.loads(result)
    assert result_data["answer"] == "Generated answer"

    # Test with invalid model
    exa_tools.model = "invalid-model"
    with pytest.raises(ValueError, match="Model must be either 'exa' or 'exa-pro'"):
        exa_tools.exa_answer("test question")


def test_init_with_research_tool():
    """Test initialization with research tool enabled."""
    with patch.dict("os.environ", {"EXA_API_KEY": "test_key"}):
        tools = ExaTools(enable_research=True)

        assert "research" in [func.name for func in tools.functions.values()]


def test_research_success(exa_tools, mock_exa_client):
    """Test successful research workflow using deep-reasoning search."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://source.com",
            title="AI Trends Article",
            text="AI advancement and machine learning trends",
        )
    ]

    mock_exa_client.search_and_contents.return_value = mock_response

    result = exa_tools.research("Research AI trends in 2024")
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["url"] == "https://source.com"
    assert result_data[0]["title"] == "AI Trends Article"
    assert result_data[0]["text"] == "AI advancement and machine learning trends"

    # Verify search_and_contents was called with deep-reasoning type
    call_args = mock_exa_client.search_and_contents.call_args
    assert call_args[0][0] == "Research AI trends in 2024"
    assert call_args[1]["type"] == "deep-reasoning"
    assert call_args[1]["text"] is True
    assert call_args[1]["summary"] is True


def test_research_with_custom_num_results(exa_tools, mock_exa_client):
    """Test research with custom num_results parameter."""
    mock_response = Mock(spec=SearchResponse)
    mock_response.results = [
        create_mock_search_result(
            url="https://example.com",
            title="Research Result",
            text="Research findings",
        )
    ]

    mock_exa_client.search_and_contents.return_value = mock_response

    result = exa_tools.research("What are the latest AI trends?", num_results=20)
    result_data = json.loads(result)

    assert len(result_data) == 1
    assert result_data[0]["text"] == "Research findings"

    # Verify num_results was passed correctly
    call_args = mock_exa_client.search_and_contents.call_args
    assert call_args[1]["num_results"] == 20


def test_research_timeout(exa_tools, mock_exa_client):
    """Test research timeout handling."""
    mock_exa_client.search_and_contents.side_effect = TimeoutError("Operation timed out")

    result = exa_tools.research("test instructions")
    result_data = json.loads(result)

    assert "error" in result_data
    assert "timed out" in result_data["error"].lower()


def test_research_error_handling(exa_tools, mock_exa_client):
    """Test research error handling."""
    mock_exa_client.search_and_contents.side_effect = Exception("API Error")

    result = exa_tools.research("test instructions")
    result_data = json.loads(result)

    assert "error" in result_data
    assert "Research failed: API Error" in result_data["error"]
