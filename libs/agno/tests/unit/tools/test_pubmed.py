"""Unit tests for PubmedTools class."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.pubmed import PubmedTools

ESEARCH_XML = b"""<?xml version="1.0"?>
<eSearchResult><IdList><Id>111</Id><Id>222</Id></IdList></eSearchResult>"""

EFETCH_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet></PubmedArticleSet>"""


@pytest.fixture
def mock_httpx_get():
    """Mock httpx.get to return canned esearch then efetch responses."""
    with patch("agno.tools.pubmed.httpx.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(content=ESEARCH_XML),
            MagicMock(content=EFETCH_XML),
        ]
        yield mock_get


def get_retmax_sent(mock_get):
    """Return the retmax value sent to the esearch endpoint."""
    return mock_get.call_args_list[0][1]["params"]["retmax"]


# ============================================================================
# MAX RESULTS TESTS
# ============================================================================


def test_search_pubmed_uses_constructor_max_results(mock_httpx_get):
    """Test that max_results set on the toolkit reaches the esearch call."""
    tools = PubmedTools(max_results=3)
    tools.search_pubmed("test query")

    assert get_retmax_sent(mock_httpx_get) == 3


def test_search_pubmed_call_arg_overrides_constructor(mock_httpx_get):
    """Test that an explicit max_results argument wins over the constructor value."""
    tools = PubmedTools(max_results=3)
    tools.search_pubmed("test query", max_results=5)

    assert get_retmax_sent(mock_httpx_get) == 5


def test_search_pubmed_defaults_to_ten(mock_httpx_get):
    """Test that max_results falls back to 10 when not configured anywhere."""
    tools = PubmedTools()
    tools.search_pubmed("test query")

    assert get_retmax_sent(mock_httpx_get) == 10


def test_search_pubmed_passes_default_timeout(mock_httpx_get):
    """Test that both PubMed requests receive the default HTTP timeout."""
    tools = PubmedTools()
    tools.search_pubmed("test query")

    assert mock_httpx_get.call_args_list[0][1]["timeout"] == 30
    assert mock_httpx_get.call_args_list[1][1]["timeout"] == 30


def test_search_pubmed_passes_configured_timeout(mock_httpx_get):
    """Test that both PubMed requests receive the configured HTTP timeout."""
    tools = PubmedTools(timeout=12)
    tools.search_pubmed("test query")

    assert mock_httpx_get.call_args_list[0][1]["timeout"] == 12
    assert mock_httpx_get.call_args_list[1][1]["timeout"] == 12


def test_constructor_preserves_existing_positional_arguments():
    """Test adding timeout does not shift existing positional constructor arguments."""
    tools = PubmedTools("user@example.com", 3, True, True, False)

    assert tools.email == "user@example.com"
    assert tools.max_results == 3
    assert tools.results_expanded is True
    assert tools.tools == [tools.search_pubmed]
    assert tools.timeout == 30


def test_search_pubmed_reports_http_status_error():
    """Test that a failing HTTP status is reported instead of an XML parse failure."""
    request = httpx.Request("GET", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429
    response.raise_for_status.side_effect = httpx.HTTPStatusError("rate limited", request=request, response=response)

    with patch("agno.tools.pubmed.httpx.get", return_value=response):
        result = PubmedTools().search_pubmed("test query")

    assert result == "Could not fetch articles. Error: rate limited"
