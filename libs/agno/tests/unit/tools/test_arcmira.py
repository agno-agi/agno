import json
from unittest.mock import patch

import httpx
import pytest

from agno.tools.arcmira import ArcmiraTools


@pytest.fixture
def response_body():
    return {
        "query": "open source",
        "limit": 5,
        "returned": 1,
        "filters": {"channel_ids": [], "entity_ids": [], "about": [], "by": [], "kind": []},
        "window": {},
        "chunks": [
            {
                "id": "fixture-1",
                "video_id": "example0001",
                "text": "We released the project as open source.",
                "start_seconds": 12,
                "watch_url": "/watch?v=example0001&t=12",
                "score": 0.8,
                "source": "creator_captions",
            }
        ],
        "partial": True,
        "failed_batches": 1,
        "search_index": {"state": "catching_up", "missing_before": "2026-07-01"},
        "access": {
            "type": "permission_error",
            "code": "freshness_requires_paid",
            "gate": "freshness",
            "message": "Synthetic freshness limit.",
            "doc_url": "https://arcmira.com/docs/errors#freshness_requires_paid",
            "request_id": "fixture-request",
        },
        "note": "Synthetic coverage fixture.",
    }


def call_with_response(status, body, **search_args):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with patch("agno.tools.arcmira.httpx.Client", return_value=client) as factory:
        tools = ArcmiraTools(api_key="synthetic-test-key", limit=3, request_timeout=7)
        result = tools.search_transcripts("open source", **search_args)
        factory.assert_called_once_with(timeout=7, follow_redirects=False)

    return result, requests


def test_response_and_filters_preserved(response_body):
    result, requests = call_with_response(
        200,
        response_body,
        channel_ids="UCfixture",
        after="2026-09-01",
        before="2026-10-01",
        source="arcmira_premium",
    )
    assert json.loads(result) == response_body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?")[0] == "https://api.arcmira.com/v1/search"
    assert dict(request.url.params) == {
        "q": "open source",
        "limit": "3",
        "channel_ids": "UCfixture",
        "after": "2026-09-01",
        "before": "2026-10-01",
        "source": "arcmira_premium",
    }
    assert request.headers["Authorization"] == "Bearer synthetic-test-key"


@pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500])
def test_errors_preserve_body_without_retry_or_fallback(status):
    body = {"error": {"code": "test_refusal", "message": "Test refusal", "request_id": "fixture-id"}}
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    with patch("agno.tools.arcmira.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError) as exc:
            ArcmiraTools(api_key="test-key").search_transcripts("test", source="arcmira_premium")

    assert f"HTTP {status}" in str(exc.value)
    assert json.dumps(body) in str(exc.value)
    assert len(calls) == 1
    assert calls[0].url.params["source"] == "arcmira_premium"


@pytest.mark.parametrize("status", [200, 302, 503])
def test_non_json_response_does_not_echo_body(status):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text="private proxy error")))
    with patch("agno.tools.arcmira.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match=f"non-JSON response \\(HTTP {status}\\)") as exc:
            ArcmiraTools(api_key="test-key").search_transcripts("test")

    assert "private" not in str(exc.value)


def test_timeout_does_not_echo_credentials_or_retry():
    with patch("agno.tools.arcmira.httpx.Client") as factory:
        request = factory.return_value.__enter__.return_value.get
        request.side_effect = httpx.ReadTimeout("Bearer secret-test-key")
        with pytest.raises(RuntimeError, match="No automatic retry") as exc:
            ArcmiraTools(api_key="test-key").search_transcripts("test")
        assert request.call_count == 1
    assert "secret-test-key" not in str(exc.value)


@pytest.mark.parametrize("query", ["", " ", "x"])
def test_short_query_does_not_send_request(query):
    with patch("agno.tools.arcmira.httpx.Client") as factory:
        with pytest.raises(ValueError, match="two non-whitespace"):
            ArcmiraTools(api_key="test-key").search_transcripts(query)
        factory.assert_not_called()


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_invalid_limit(limit):
    with pytest.raises(ValueError, match="limit"):
        ArcmiraTools(api_key="test-key", limit=limit)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="request_timeout"):
        ArcmiraTools(api_key="test-key", request_timeout=timeout)


def test_key_and_registration(monkeypatch):
    monkeypatch.delenv("ARCMIRA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ARCMIRA_API_KEY"):
        ArcmiraTools()
    monkeypatch.setenv("ARCMIRA_API_KEY", "test-env-key")
    assert ArcmiraTools().api_key == "test-env-key"
    assert ArcmiraTools(api_key="explicit-key").api_key == "explicit-key"
    assert list(ArcmiraTools().functions) == ["search_transcripts"]
    assert not ArcmiraTools(enable_search=False).functions
    assert list(ArcmiraTools(enable_search=False, all=True).functions) == ["search_transcripts"]


def test_model_schema_keeps_key_and_limit_private():
    tool = ArcmiraTools(api_key="test-key").get_functions()["search_transcripts"]
    tool.process_entrypoint()
    assert set(tool.parameters["properties"]) == {"query", "channel_ids", "after", "before", "source"}
    assert "test-key" not in json.dumps(tool.to_dict())


@pytest.mark.parametrize("status", [200, 402])
def test_agno_function_call_reports_success_or_error(status, response_body):
    from agno.tools import FunctionCall

    body = response_body if status == 200 else {"error": {"code": "quota_exceeded", "message": "Test allowance"}}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)))
    tools = ArcmiraTools(api_key="test-key")
    function = tools.get_functions()["search_transcripts"]
    function.process_entrypoint()
    call = FunctionCall(function=function, arguments={"query": "open source"})
    with patch("agno.tools.arcmira.httpx.Client", return_value=client):
        outcome = call.execute()
    assert outcome.status == ("success" if status == 200 else "failure")
    if status == 200:
        assert json.loads(call.result) == response_body
    else:
        assert "quota_exceeded" in call.error


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 402, 403, 429, 500])
async def test_async_agno_call_preserves_results_filters_and_errors(status, response_body):
    from agno.tools import FunctionCall

    body = response_body if status == 200 else {"error": {"code": "quota_exceeded", "message": "Test allowance"}}
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    tools = ArcmiraTools(api_key="synthetic-test-key", limit=3, request_timeout=7)
    function = tools.get_async_functions()["search_transcripts"]
    function.process_entrypoint()
    assert set(function.parameters["properties"]) == {"query", "channel_ids", "after", "before", "source"}
    assert "synthetic-test-key" not in json.dumps(function.to_dict())
    call = FunctionCall(
        function=function,
        arguments={
            "query": "open source",
            "channel_ids": "UCfixture",
            "after": "2026-09-01",
            "before": "2026-10-01",
            "source": "arcmira_premium",
        },
    )
    with patch("agno.tools.arcmira.httpx.AsyncClient", return_value=client) as factory:
        outcome = await call.aexecute()
        factory.assert_called_once_with(timeout=7, follow_redirects=False)

    assert outcome.status == ("success" if status == 200 else "failure")
    if status == 200:
        assert json.loads(call.result) == response_body
    else:
        assert f"HTTP {status}" in call.error
        assert json.dumps(body) in call.error
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url).split("?")[0] == "https://api.arcmira.com/v1/search"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-test-key"
    assert dict(requests[0].url.params) == {
        "q": "open source",
        "limit": "3",
        "channel_ids": "UCfixture",
        "after": "2026-09-01",
        "before": "2026-10-01",
        "source": "arcmira_premium",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 302, 503])
async def test_async_non_json_response_does_not_echo_body(status):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text="private proxy error"))
    )
    with patch("agno.tools.arcmira.httpx.AsyncClient", return_value=client):
        with pytest.raises(RuntimeError, match=f"non-JSON response \\(HTTP {status}\\)") as exc:
            await ArcmiraTools(api_key="test-key").asearch_transcripts("test")
    assert "private" not in str(exc.value)


@pytest.mark.asyncio
async def test_async_timeout_does_not_echo_credentials_or_retry():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("Bearer secret-test-key")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("agno.tools.arcmira.httpx.AsyncClient", return_value=client):
        with pytest.raises(RuntimeError, match="No automatic retry") as exc:
            await ArcmiraTools(api_key="test-key").asearch_transcripts("test")
    assert len(calls) == 1
    assert "secret-test-key" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", " ", "x"])
async def test_async_short_query_does_not_send_request(query):
    with patch("agno.tools.arcmira.httpx.AsyncClient") as factory:
        with pytest.raises(ValueError, match="two non-whitespace"):
            await ArcmiraTools(api_key="test-key").asearch_transcripts(query)
        factory.assert_not_called()


def test_async_registration_respects_enable_search():
    import inspect

    tools = ArcmiraTools(api_key="test-key")
    assert inspect.iscoroutinefunction(tools.get_async_functions()["search_transcripts"].entrypoint)
    assert not ArcmiraTools(api_key="test-key", enable_search=False).get_async_functions()
    assert list(ArcmiraTools(api_key="test-key", enable_search=False, all=True).get_async_functions()) == [
        "search_transcripts"
    ]
