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


# ---------------------------------------------------------------------------
# Bounded output
#
# A deep search carries full page content per result, so an unbounded response
# can dwarf the model's context. The cap must hold without ever handing back a
# string the model cannot parse.
# ---------------------------------------------------------------------------


def deep_search_payload(pages=4, page_chars=20000):
    return {
        "results": [
            {
                "url": f"https://example.com/{index}",
                "title": f"Result {index}",
                "content": "x" * page_chars,
            }
            for index in range(pages)
        ]
    }


def test_max_content_chars_is_validated():
    with pytest.raises(ValueError, match="at least"):
        NimbleTools(api_key="test-key-1234567890", max_content_chars=10)


def test_deep_search_output_is_hard_bounded_and_still_valid_json(mock_nimble):
    toolkit = NimbleTools(api_key="test-key-1234567890", max_content_chars=2000)
    toolkit._sync_client.search.return_value = search_response(deep_search_payload())

    raw = toolkit.web_search_using_nimble("query", deep_search=True)

    assert len(raw) <= 2000
    decoded = json.loads(raw)  # must remain parseable, not a sliced string
    assert decoded["truncation"]["truncated"] is True
    assert decoded["truncation"]["original_characters"] > 2000


async def test_async_deep_search_output_is_hard_bounded(mock_nimble):
    with patch("agno.tools.nimble.AsyncNimble") as async_client:
        toolkit = NimbleTools(api_key="test-key-1234567890", max_content_chars=2000)
        async_client.return_value.search = AsyncMock(return_value=search_response(deep_search_payload()))

        raw = await toolkit.aweb_search_using_nimble("query", deep_search=True)

    assert len(raw) <= 2000
    assert json.loads(raw)["truncation"]["truncated"] is True


def test_small_response_is_returned_untruncated(mock_nimble):
    toolkit = NimbleTools(api_key="test-key-1234567890")
    toolkit._sync_client.search.return_value = search_response({"results": [{"title": "Nimble"}]})

    decoded = json.loads(toolkit.web_search_using_nimble("query"))

    assert "truncation" not in decoded
    assert decoded["results"][0]["title"] == "Nimble"


def test_bounded_output_still_redacts_credentials(mock_nimble):
    # Assembled from fragments so the test file holds no contiguous secret shape.
    leaked = "token " + "nvapi-" + "abcdefgh1234567890" + " tail " + "a" * 40
    toolkit = NimbleTools(api_key="test-key-1234567890", max_content_chars=1000)
    toolkit._sync_client.search.return_value = search_response(
        {"results": [{"content": leaked + "y" * 50000, "title": leaked}]}
    )

    raw = toolkit.web_search_using_nimble("query", deep_search=True)

    assert len(raw) <= 1000
    json.loads(raw)
    assert "nvapi-" not in raw
    assert "a" * 40 not in raw


def test_bound_holds_even_when_structure_alone_is_too_large(mock_nimble):
    """Many tiny fields: no per-field trimming can help, so it must degrade safely."""
    toolkit = NimbleTools(api_key="test-key-1234567890", max_content_chars=500)
    toolkit._sync_client.search.return_value = search_response(
        {"results": [{"a": 1, "b": 2, "c": 3} for _ in range(500)]}
    )

    raw = toolkit.web_search_using_nimble("query", deep_search=True)

    assert len(raw) <= 500
    assert json.loads(raw)["truncation"]["truncated"] is True
