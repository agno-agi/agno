import json
from unittest.mock import Mock, patch

import httpx
import pytest

from agno.tools.semantic_scholar import SemanticScholarTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)


@pytest.fixture
def semantic_scholar_tools():
    return SemanticScholarTools(api_key="test_key", max_results=5)


@pytest.fixture
def sample_paper():
    return {
        "paperId": "abc123",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "abstract": "A paper about retrieval augmented generation.",
        "year": 2020,
        "publicationDate": "2020-05-01",
        "venue": "NeurIPS",
        "url": "https://www.semanticscholar.org/paper/abc123",
        "externalIds": {"DOI": "10.0000/test", "ArXiv": "2005.11401", "PubMed": "12345"},
        "authors": [{"authorId": "1741101", "name": "Patrick Lewis"}],
        "citationCount": 1234,
        "referenceCount": 42,
        "fieldsOfStudy": ["Computer Science"],
        "isOpenAccess": True,
        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        "tldr": {"text": "Retrieval improves generation."},
    }


def mock_response(json_data):
    response = Mock(spec=httpx.Response)
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def test_init_with_api_key():
    tools = SemanticScholarTools(api_key="direct_key")
    assert tools.api_key == "direct_key"


def test_init_with_env_api_key(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "env_key")
    tools = SemanticScholarTools()
    assert tools.api_key == "env_key"


def test_init_constructor_key_overrides_env(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "env_key")
    tools = SemanticScholarTools(api_key="direct_key")
    assert tools.api_key == "direct_key"


def test_init_default_tools():
    tools = SemanticScholarTools(api_key="test_key")
    tool_names = [tool.name for tool in tools.functions.values()]
    assert "search_papers" in tool_names
    assert "get_paper" in tool_names
    assert "get_author_papers" not in tool_names


def test_init_all_tools():
    tools = SemanticScholarTools(api_key="test_key", all=True)
    tool_names = [tool.name for tool in tools.functions.values()]
    assert "search_papers" in tool_names
    assert "get_paper" in tool_names
    assert "get_author_papers" in tool_names


def test_headers_with_api_key(semantic_scholar_tools):
    assert semantic_scholar_tools._headers() == {"x-api-key": "test_key"}


def test_headers_without_api_key():
    tools = SemanticScholarTools()
    assert tools._headers() == {}


def test_get_uses_timeout_headers_and_params(semantic_scholar_tools):
    with patch("httpx.get", return_value=mock_response({"data": []})) as mock_get:
        semantic_scholar_tools._get("paper/search", {"query": "rag"})

    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert kwargs["params"] == {"query": "rag"}
    assert kwargs["headers"] == {"x-api-key": "test_key"}
    assert kwargs["timeout"] == 30


def test_get_http_error(semantic_scholar_tools):
    request = httpx.Request("GET", "https://api.semanticscholar.org/graph/v1/paper/search")
    response = httpx.Response(429, request=request, text="rate limited")
    error = httpx.HTTPStatusError("too many requests", request=request, response=response)
    mocked_response = Mock(spec=httpx.Response)
    mocked_response.raise_for_status.side_effect = error

    with patch("httpx.get", return_value=mocked_response):
        result = semantic_scholar_tools._get("paper/search", {"query": "rag"})

    assert "error" in result
    assert "HTTP 429" in result["error"]


def test_get_request_error(semantic_scholar_tools):
    request = httpx.Request("GET", "https://api.semanticscholar.org/graph/v1/paper/search")
    with patch("httpx.get", side_effect=httpx.RequestError("network down", request=request)):
        result = semantic_scholar_tools._get("paper/search", {"query": "rag"})

    assert result["error"] == "network down"


def test_get_invalid_json(semantic_scholar_tools):
    response = Mock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.side_effect = ValueError("No JSON object")

    with patch("httpx.get", return_value=response):
        result = semantic_scholar_tools._get("paper/search", {"query": "rag"})

    assert "Invalid JSON response" in result["error"]


def test_search_papers_success(semantic_scholar_tools, sample_paper):
    with patch.object(
        semantic_scholar_tools,
        "_get",
        return_value={"total": 1, "offset": 0, "data": [sample_paper]},
    ) as mock_get:
        result = json.loads(semantic_scholar_tools.search_papers("retrieval augmented generation"))

    mock_get.assert_called_once()
    path, params = mock_get.call_args.args
    assert path == "paper/search"
    assert params["query"] == "retrieval augmented generation"
    assert params["limit"] == 5
    assert result["total"] == 1
    assert result["papers"][0]["paper_id"] == "abc123"
    assert result["papers"][0]["doi"] == "10.0000/test"
    assert result["papers"][0]["authors"] == [{"author_id": "1741101", "name": "Patrick Lewis"}]


def test_search_papers_validates_query(semantic_scholar_tools):
    result = json.loads(semantic_scholar_tools.search_papers(""))
    assert "error" in result


def test_search_papers_validates_max_results(semantic_scholar_tools):
    result = json.loads(semantic_scholar_tools.search_papers("rag", max_results=0))
    assert result["error"] == "max_results must be greater than 0"


def test_search_papers_caps_limit_at_100(semantic_scholar_tools):
    with patch.object(semantic_scholar_tools, "_get", return_value={"data": []}) as mock_get:
        semantic_scholar_tools.search_papers("rag", max_results=500)

    _, params = mock_get.call_args.args
    assert params["limit"] == 100


def test_search_papers_returns_error(semantic_scholar_tools):
    with patch.object(semantic_scholar_tools, "_get", return_value={"error": "rate limited"}):
        result = json.loads(semantic_scholar_tools.search_papers("rag"))

    assert result["error"] == "rate limited"


def test_get_paper_success(semantic_scholar_tools, sample_paper):
    with patch.object(semantic_scholar_tools, "_get", return_value=sample_paper) as mock_get:
        result = json.loads(semantic_scholar_tools.get_paper("ARXIV:2005.11401"))

    mock_get.assert_called_once()
    path, params = mock_get.call_args.args
    assert path == "paper/ARXIV:2005.11401"
    assert "fields" in params
    assert result["title"] == sample_paper["title"]
    assert result["open_access_pdf_url"] == "https://example.com/paper.pdf"


def test_get_paper_validates_paper_id(semantic_scholar_tools):
    result = json.loads(semantic_scholar_tools.get_paper(""))
    assert result["error"] == "Please provide a paper_id"


def test_get_author_papers_success(semantic_scholar_tools, sample_paper):
    with patch.object(semantic_scholar_tools, "_get", return_value={"data": [sample_paper]}) as mock_get:
        result = json.loads(semantic_scholar_tools.get_author_papers("1741101", max_results=3))

    path, params = mock_get.call_args.args
    assert path == "author/1741101/papers"
    assert params["limit"] == 3
    assert result["author_id"] == "1741101"
    assert result["papers"][0]["title"] == sample_paper["title"]


def test_get_author_papers_validates_author_id(semantic_scholar_tools):
    result = json.loads(semantic_scholar_tools.get_author_papers(""))
    assert result["error"] == "Please provide an author_id"
