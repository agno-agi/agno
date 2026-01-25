import json
from unittest.mock import patch

import pytest

from agno.tools.valyu import (
    ECONOMICS_SOURCES,
    FINANCE_SOURCES,
    LIFE_SCIENCES_SOURCES,
    PAPER_SOURCES,
    PATENT_SOURCES,
    SEC_SOURCES,
    ValyuTools,
)


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

    def test_general_search_success(self, valyu_tools):
        """Test successful general search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Search Result")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.search("test query")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Search Result"

        valyu_tools.valyu.search.assert_called_once()
        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["query"] == "test query"
        assert call_args["search_type"] == "all"

    def test_web_search_success(self, valyu_tools):
        """Test successful web search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Web Article")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.web_search("test query")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Web Article"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "web"

    def test_web_search_with_source_filters(self, valyu_tools):
        """Test web search with source filters."""
        mock_response = MockSearchResponse(success=True, results=[])
        valyu_tools.valyu.search.return_value = mock_response

        valyu_tools.web_search(
            "test query",
            included_sources=["nature.com"],
            excluded_sources=["reddit.com"],
        )

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["included_sources"] == ["nature.com"]
        assert call_args["excluded_sources"] == ["reddit.com"]

    def test_life_sciences_search_success(self, valyu_tools):
        """Test successful life sciences search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="PubMed Article")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.life_sciences_search("GLP-1 agonists")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "PubMed Article"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "proprietary"
        assert call_args["included_sources"] == LIFE_SCIENCES_SOURCES

    def test_sec_search_success(self, valyu_tools):
        """Test successful SEC search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="SEC Filing")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.sec_search("Tesla 10-K")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "SEC Filing"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "proprietary"
        assert call_args["included_sources"] == SEC_SOURCES

    def test_patent_search_success(self, valyu_tools):
        """Test successful patent search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Patent Result")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.patent_search("solid-state battery")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Patent Result"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "proprietary"
        assert call_args["included_sources"] == PATENT_SOURCES

    def test_finance_search_success(self, valyu_tools):
        """Test successful finance search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Financial Data")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.finance_search("Apple revenue")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Financial Data"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "proprietary"
        assert call_args["included_sources"] == FINANCE_SOURCES

    def test_economics_search_success(self, valyu_tools):
        """Test successful economics search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Economic Data")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.economics_search("US unemployment rate")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Economic Data"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "proprietary"
        assert call_args["included_sources"] == ECONOMICS_SOURCES

    def test_paper_search_success(self, valyu_tools):
        """Test successful paper search."""
        mock_response = MockSearchResponse(success=True, results=[MockSearchResult(title="Academic Paper")])
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.paper_search("transformer attention")
        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["title"] == "Academic Paper"

        call_args = valyu_tools.valyu.search.call_args[1]
        assert call_args["search_type"] == "proprietary"
        assert call_args["included_sources"] == PAPER_SOURCES

    def test_search_api_error(self, valyu_tools):
        """Test handling of API error."""
        mock_response = MockSearchResponse(success=False, error="API Error")
        valyu_tools.valyu.search.return_value = mock_response

        result = valyu_tools.search("test query")
        assert "Error: API Error" in result

    def test_search_exception_handling(self, valyu_tools):
        """Test exception handling during search."""
        valyu_tools.valyu.search.side_effect = Exception("Network error")

        result = valyu_tools.search("test query")
        assert "Error: Valyu search failed: Network error" in result

    def test_constructor_parameters_used_in_search(self, mock_valyu):
        """Test that constructor parameters are properly used in searches."""
        tools = ValyuTools(
            api_key="test_key",
            max_results=5,
            relevance_threshold=0.7,
        )

        mock_response = MockSearchResponse(success=True, results=[])
        tools.valyu.search.return_value = mock_response

        tools.search("test query")

        call_args = tools.valyu.search.call_args[1]
        assert call_args["max_num_results"] == 5
        assert call_args["relevance_threshold"] == 0.7

    def test_tools_registration(self, valyu_tools):
        """Test that all tools are properly registered."""
        tool_names = list(valyu_tools.functions.keys())
        expected_tools = [
            "search",
            "web_search",
            "life_sciences_search",
            "sec_search",
            "patent_search",
            "finance_search",
            "economics_search",
            "paper_search",
        ]

        for tool in expected_tools:
            assert tool in tool_names
