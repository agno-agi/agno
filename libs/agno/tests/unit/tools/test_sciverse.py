import json
from unittest.mock import MagicMock, patch

import httpx

from agno.tools.sciverse import SciverseTools


def _mock_client(mock_client_class, payload=None):
    """Wire a mocked httpx.Client and return the client mock for assertions."""
    response = MagicMock()
    response.json.return_value = payload if payload is not None else {"hits": []}
    response.raise_for_status.return_value = None
    client = mock_client_class.return_value.__enter__.return_value
    client.request.return_value = response
    return client


def test_initialization_registers_default_tools():
    tools = SciverseTools(api_key="test-key")

    assert tools.name == "sciverse"
    assert set(tools.functions) == {
        "semantic_search",
        "search_papers",
        "read_paper_content",
    }


def test_list_paper_relations_is_opt_in():
    assert "list_paper_relations" not in SciverseTools(api_key="test-key").functions
    assert "list_paper_relations" in SciverseTools(api_key="test-key", all=True).functions


def test_disabled_tool_is_not_registered():
    tools = SciverseTools(api_key="test-key", enable_search_papers=False)

    assert "search_papers" not in tools.functions
    assert "semantic_search" in tools.functions


def test_initialization_reads_api_key_from_environment():
    with patch.dict("os.environ", {"SCIVERSE_API_TOKEN": "env-key"}):
        tools = SciverseTools()

    assert tools.api_key == "env-key"


def test_base_url_defaults_and_strips_trailing_slash():
    assert SciverseTools(api_key="k").base_url == "https://api.sciverse.space"
    assert SciverseTools(api_key="k", base_url="https://example.test/").base_url == "https://example.test"


@patch("agno.tools.sciverse.httpx.Client")
def test_semantic_search_posts_query_with_auth_and_source_header(mock_client_class):
    client = _mock_client(mock_client_class, {"hits": [{"doc_id": "p_x", "chunk": "text"}]})
    tools = SciverseTools(api_key="test-key")

    result = tools.semantic_search("how does attention work", top_k=3, mode="quality")

    assert json.loads(result)["hits"][0]["doc_id"] == "p_x"
    client.request.assert_called_once_with(
        "POST",
        "/agentic-search",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
            "X-Sciverse-Source": "oss_agno",
        },
        json={"query": "how does attention work", "top_k": 3, "retrieval": "hybrid", "sub_queries": 3},
    )


@patch("agno.tools.sciverse.httpx.Client")
def test_semantic_search_maps_modes_to_retrieval_params(mock_client_class):
    client = _mock_client(mock_client_class)
    tools = SciverseTools(api_key="test-key")

    tools.semantic_search("q", mode="fast")
    assert client.request.call_args.kwargs["json"] == {"query": "q", "top_k": 10, "retrieval": "es"}

    tools.semantic_search("q")  # default: balanced
    assert client.request.call_args.kwargs["json"] == {"query": "q", "top_k": 10, "retrieval": "hybrid"}

    tools.semantic_search("q", mode="bogus")  # unknown mode falls back to balanced
    assert client.request.call_args.kwargs["json"] == {"query": "q", "top_k": 10, "retrieval": "hybrid"}


@patch("agno.tools.sciverse.httpx.Client")
def test_search_papers_builds_filters_from_convenience_arguments(mock_client_class):
    client = _mock_client(mock_client_class, {"items": []})
    tools = SciverseTools(api_key="test-key")

    tools.search_papers(query="crispr", authors=["Jennifer Doudna"], year_from=2020, year_to=2023)

    payload = client.request.call_args.kwargs["json"]
    assert payload["query"] == "crispr"
    assert payload["filters"] == [
        {"field": "author", "operator": "FILTER_OP_IN", "value": ["Jennifer Doudna"]},
        {"field": "publication_published_year", "operator": "FILTER_OP_GTE", "value": 2020},
        {"field": "publication_published_year", "operator": "FILTER_OP_LTE", "value": 2023},
    ]


@patch("agno.tools.sciverse.httpx.Client")
def test_search_papers_omits_filters_when_no_criteria_given(mock_client_class):
    client = _mock_client(mock_client_class, {"items": []})
    tools = SciverseTools(api_key="test-key")

    tools.search_papers(query="transformer")

    payload = client.request.call_args.kwargs["json"]
    assert "filters" not in payload
    assert payload["page"] == 1


@patch("agno.tools.sciverse.httpx.Client")
def test_read_paper_content_passes_byte_range_as_query_params(mock_client_class):
    client = _mock_client(mock_client_class, {"content": "abc", "next_offset": 100})
    tools = SciverseTools(api_key="test-key")

    tools.read_paper_content("p_x", offset=64, limit=128)

    assert client.request.call_args.args == ("GET", "/content")
    assert client.request.call_args.kwargs["params"] == {"doc_id": "p_x", "offset": 64, "limit": 128}


@patch("agno.tools.sciverse.httpx.Client")
def test_list_paper_relations_posts_unique_id_and_relation(mock_client_class):
    client = _mock_client(mock_client_class, {"items": []})
    tools = SciverseTools(api_key="test-key", all=True)

    tools.list_paper_relations("u_1", relation="CITATIONS")

    payload = client.request.call_args.kwargs["json"]
    assert payload["unique_id"] == "u_1"
    assert payload["relation"] == "CITATIONS"


@patch("agno.tools.sciverse.httpx.Client")
def test_http_error_is_returned_to_the_model_instead_of_raising(mock_client_class):
    response = MagicMock()
    response.status_code = 401
    response.json.return_value = {"code": "UNAUTHORIZED", "message": "Invalid token"}
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "unauthorized", request=MagicMock(), response=response
    )
    mock_client_class.return_value.__enter__.return_value.request.return_value = response
    tools = SciverseTools(api_key="bad-key")

    result = json.loads(tools.semantic_search("anything"))

    assert result["error"] == "HTTP 401"
    assert result["message"] == "Invalid token"


@patch("agno.tools.sciverse.httpx.Client")
def test_transport_error_is_returned_to_the_model_instead_of_raising(mock_client_class):
    mock_client_class.return_value.__enter__.return_value.request.side_effect = httpx.ConnectError("boom")
    tools = SciverseTools(api_key="test-key")

    assert "boom" in json.loads(tools.semantic_search("anything"))["error"]
