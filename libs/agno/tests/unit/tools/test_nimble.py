import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agno.tools.nimble import NimbleTools


def search_response(payload=None):
    response = Mock()
    response.to_dict.return_value = payload or {"results": [{"title": "Nimble"}]}
    return response


@pytest.fixture
def mock_nimble():
    with patch("agno.tools.nimble.Nimble") as client:
        yield client


@pytest.fixture
def tools(mock_nimble):
    return NimbleTools(api_key="test-key-1234567890")


def test_builds_attributed_sdk_client(mock_nimble):
    NimbleTools(api_key="test-key-1234567890", timeout=12, max_retries=3)
    mock_nimble.assert_called_once_with(
        api_key="test-key-1234567890",
        client_source="agno",
        timeout=12,
        max_retries=3,
    )


def test_missing_key_does_not_construct_client(mock_nimble):
    with patch.dict("os.environ", {}, clear=True):
        toolkit = NimbleTools()
    assert toolkit._sync_client is None
    mock_nimble.assert_not_called()
    assert json.loads(toolkit.web_search_using_nimble("query"))["error_type"] == "configuration_error"


def test_registers_matching_sync_and_async_tool_names(tools):
    assert "web_search_using_nimble" in tools.functions
    assert "web_search_using_nimble" in tools.async_functions


def test_search_uses_current_sdk_parameter_names(tools, mock_nimble):
    mock_nimble.return_value.search.return_value = search_response()
    result = json.loads(
        tools.web_search_using_nimble(
            "latest Agno release",
            max_results=5,
            deep_search=True,
            include_answer=True,
            time_range="week",
            include_domains=["github.com"],
            exclude_domains=["example.com"],
        )
    )
    assert result["results"][0]["title"] == "Nimble"
    mock_nimble.return_value.search.assert_called_once_with(
        query="latest Agno release",
        max_results=5,
        deep_search=True,
        include_answer=True,
        locale="en",
        country="US",
        output_format="markdown",
        time_range="week",
        include_domains=["github.com"],
        exclude_domains=["example.com"],
    )


def test_real_sdk_serializes_current_search_contract_and_attribution(mock_nimble):
    """Exercise the released SDK transport without making a network request."""
    from nimble_python import Nimble

    captured = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            request=request,
            json={
                "request_id": "req_test",
                "results": [],
                "total_results": 0,
                "answer": None,
                "answer_citations": None,
                "serp_data": None,
            },
        )

    toolkit = NimbleTools(api_key="test-key-1234567890")
    toolkit._sync_client = Nimble(
        api_key="test-key-1234567890",
        client_source="agno",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = json.loads(
        toolkit.web_search_using_nimble(
            "official Agno documentation",
            max_results=4,
            deep_search=True,
            include_domains=["docs.agno.com"],
        )
    )

    assert result["request_id"] == "req_test"
    assert captured["headers"]["x-client-source"] == "agno"
    assert captured["body"]["max_results"] == 4
    assert captured["body"]["output_format"] == "markdown"
    assert captured["body"]["include_domains"] == ["docs.agno.com"]
    assert "num_results" not in captured["body"]
    assert "parsing_type" not in captured["body"]


@pytest.mark.parametrize("query,max_results", [("", 3), ("query", 0), ("query", 101)])
def test_invalid_search_input_fails_before_network(tools, mock_nimble, query, max_results):
    result = json.loads(tools.web_search_using_nimble(query, max_results=max_results))
    assert result["error_type"] == "ValueError"
    mock_nimble.return_value.search.assert_not_called()


def test_output_and_errors_are_redacted(tools, mock_nimble):
    secret = "nvapi-super-secret-value"
    with patch.dict("os.environ", {"NIMBLE_API_KEY": secret}):
        mock_nimble.return_value.search.return_value = search_response({"answer": secret})
        assert secret not in tools.web_search_using_nimble("query")

        mock_nimble.return_value.search.side_effect = RuntimeError(f"failed with Bearer {secret}")
        failure = tools.web_search_using_nimble("query")
        assert secret not in failure
        assert "<redacted>" in failure


@pytest.mark.asyncio
async def test_async_search_uses_lazy_attributed_client(tools):
    response = search_response()
    async_client = Mock()
    async_client.search = AsyncMock(return_value=response)
    with patch("agno.tools.nimble.AsyncNimble", return_value=async_client) as client:
        result = json.loads(await tools.aweb_search_using_nimble("current news"))

    assert result["results"][0]["title"] == "Nimble"
    client.assert_called_once_with(
        api_key="test-key-1234567890",
        client_source="agno",
        timeout=30,
        max_retries=2,
    )
    async_client.search.assert_awaited_once_with(
        query="current news",
        max_results=3,
        deep_search=False,
        include_answer=False,
        locale="en",
        country="US",
        output_format="markdown",
    )
