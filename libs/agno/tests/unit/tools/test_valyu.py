import json
from unittest.mock import patch

import pytest

from agno.tools.valyu import ValyuTools


class MockSearchResult:
    def __init__(
        self,
        title="Test Paper",
        url="https://example.com",
        content="Test content",
        source="test",
        relevance_score=0.8,
        description="Test description",
    ):
        self.title = title
        self.url = url
        self.content = content
        self.source = source
        self.relevance_score = relevance_score
        self.description = description


class MockSearchResponse:
    def __init__(self, success=True, results=None, error=None):
        self.success = success
        self.results = results or []
        self.error = error


@pytest.fixture
def mock_valyu():
    with patch("agno.tools.valyu.Valyu") as mock:
        yield mock


@pytest.fixture
def valyu_tools(mock_valyu):
    return ValyuTools(api_key="test_key")


class TestValyuTools:
    def test_init_with_api_key(self, mock_valyu):
        """Test initialization with API key."""
        tools = ValyuTools(api_key="test_key")
        assert tools.api_key == "test_key"
        assert tools.max_price == 30.0
        assert tools.text_length == 1000
        mock_valyu.assert_called_once_with(api_key="test_key")

    def test_init_without_api_key_raises_error(self, mock_valyu):
        """Test initialization without API key raises ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="VALYU_API_KEY not set"):
                ValyuTools()

    @patch.dict("os.environ", {"VALYU_API_KEY": "env_key"})
    def test_init_with_env_api_key(self, mock_valyu):
        """Test initialization with API key from environment."""
        tools = ValyuTools()
        assert tools.api_key == "env_key"

    def test_parse_results_basic(self, valyu_tools):
        """Test basic result parsing."""
        results = [MockSearchResult()]
        parsed = valyu_tools._parse_results(results)
        data = json.loads(parsed)

        assert len(data) == 1
        assert data[0]["title"] == "Test Paper"
        assert data[0]["url"] == "https://example.com"
        assert data[0]["content"] == "Test content"
        assert data[0]["relevance_score"] == 0.8

    def test_parse_results_with_text_truncation(self, valyu_tools):
        """Test result parsing with text length truncation."""
        valyu_tools.text_length = 10
        long_content = "A" * 20
        results = [MockSearchResult(content=long_content)]
        parsed = valyu_tools._parse_results(results)
        data = json.loads(parsed)

        assert data[0]["content"] == "A" * 10 + "..."

    def test_parse_results_empty(self, valyu_tools):
        """Test parsing empty results."""
        parsed = valyu_tools._parse_results([])
        data = json.loads(parsed)
        assert data == []

    def test_search_academic_sources_success(self, valyu_tools):
        """Test successful academic search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Academic Paper")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.search_academic_sources("test query")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Academic Paper"

        # Verify search was called with correct parameters
        valyu_tools.valyu.search.assert_called_once()
        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["query"] == "test query"
        assert call_args["search_type"] == "proprietary"
        assert "valyu/valyu-arxiv" in call_args["included_sources"]
        assert "valyu/valyu-pubmed" in call_args["included_sources"]

    def test_search_academic_sources_with_dates(self, valyu_tools):
        """Test academic search with date filters."""
        mock_response = MockSearchResponse(success=True, results=[])
        valyu_tools.valyu.search.return_value = mock_response

        valyu_tools.search_academic_sources("test query", start_date="2023-01-01", end_date="2023-12-31")

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["start_date"] == "2023-01-01"
        assert call_args["end_date"] == "2023-12-31"

    def test_search_web_success(self, valyu_tools):
        """Test successful web search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Web Article")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.search_web("test query")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Web Article"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "web"

    def test_search_web_with_category(self, valyu_tools):
        """Test web search with category."""
        mock_response = MockSearchResponse(success=True, results=[])
        valyu_tools.valyu.search.return_value = mock_response

        valyu_tools.search_web("test query", content_category="technology")

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["category"] == "technology"

    def test_search_within_paper_success(self, valyu_tools):
        """Test successful within-paper search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Paper Section")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.search_within_paper("https://arxiv.org/abs/1234.5678", "test query")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Paper Section"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["included_sources"] == ["https://arxiv.org/abs/1234.5678"]

    def test_search_within_paper_invalid_url(self, valyu_tools):
        """Test within-paper search with invalid URL."""
        result = valyu_tools.search_within_paper("invalid-url", "test query")
        assert "Error: Invalid paper URL format" in result

    def test_search_api_error(self, valyu_tools):
        """Test handling of API error."""
        mock_response = MockSearchResponse(success=False, error="API Error")
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.search_academic_sources("test query")
        assert "Error: API Error" in result

    def test_search_exception_handling(self, valyu_tools):
        """Test exception handling during search."""
        valyu_tools.valyu.search.side_effect = Exception("Network error")

        result = valyu_tools.search_academic_sources("test query")
        assert "Error: Valyu search failed: Network error" in result

    def test_constructor_parameters_used_in_search(self, mock_valyu):
        """Test that constructor parameters are properly used in searches."""
        tools = ValyuTools(
            api_key="test_key",
            max_results=5,
            relevance_threshold=0.7,
            content_category="science",
            search_start_date="2023-01-01",
        )

        mock_response = MockSearchResponse(success=True, results=[])
        tools.valyu.search.return_value = mock_response

        tools.search_academic_sources("test query")

        call_args = tools.valyu.search.call_args[1]
        assert call_args["max_num_results"] == 5
        assert call_args["relevance_threshold"] == 0.7
        assert call_args["category"] == "science"
        assert call_args["start_date"] == "2023-01-01"

    def test_method_parameters_override_constructor(self, valyu_tools):
        """Test that method parameters override constructor defaults."""
        valyu_tools.content_category = "default_category"
        valyu_tools.search_start_date = "2023-01-01"

        mock_response = MockSearchResponse(success=True, results=[])
        valyu_tools.valyu.search.return_value = mock_response

        valyu_tools.search_web("test query", content_category="override_category", start_date="2024-01-01")

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["category"] == "override_category"
        assert call_args["start_date"] == "2024-01-01"

    def test_tools_registration(self, valyu_tools):
        """Test that all tools are properly registered."""
        tool_names = list(valyu_tools.functions.keys())
        expected_tools = ["search_academic_sources", "search_web", "search_within_paper"]

        for tool in expected_tools:
            assert tool in tool_names
