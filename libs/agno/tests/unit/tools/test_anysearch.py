"""Unit tests for AnySearchTools.

No network: every test routes the per-call httpx clients through a MockTransport, so what is
pinned here is the wire shape (URL, headers, body) and the mapping back into the tool result.
"""

from __future__ import annotations

import json
from inspect import iscoroutinefunction
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import pytest

from agno.tools.anysearch import AnySearchTools

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def wire(monkeypatch):
    """Point every client the toolkit builds at one MockTransport, recording requests."""
    state = SimpleNamespace(handler=None, requests=[])
    transport = httpx.MockTransport(lambda request: _handle(state, request))
    sync_client = httpx.Client
    async_client = httpx.AsyncClient

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: sync_client(transport=transport, **kwargs))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(transport=transport, **kwargs))
    return state


def _handle(state, request: httpx.Request) -> httpx.Response:
    state.requests.append(request)
    assert state.handler is not None, "this test did not install a response handler"
    return state.handler(request)


def _body(request: httpx.Request) -> Dict[str, Any]:
    return json.loads(request.content.decode())


def _search_response(
    results: List[Dict[str, Any]],
    request_id: str = "req-search",
    total: Optional[int] = None,
    elapsed: int = 12,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": request_id,
            "data": {
                "results": results,
                "metadata": {
                    "total_results": len(results) if total is None else total,
                    "search_time_ms": elapsed,
                },
            },
        },
    )


def _extract_response(url: str = "https://example.com/article") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-extract",
            "data": {"url": url, "title": "Example Article", "content": "Extracted page content."},
        },
    )


def _sub_domains_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-sub-domains",
            "data": {
                "domains": [
                    {
                        "domain": "finance",
                        "sub_domains": [
                            {
                                "sub_domain": "finance.quote",
                                "description": "Live quotes",
                                "params": {"ticker": {"required": True, "description": "Stock ticker"}},
                            }
                        ],
                    }
                ]
            },
        },
    )


def _router(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/search":
        return _search_response([{"title": "T", "url": "https://e.com", "snippet": "S"}])
    if request.url.path == "/v1/extract":
        return _extract_response()
    return _sub_domains_response()


@pytest.fixture
def keyless(monkeypatch):
    monkeypatch.delenv("ANYSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ANYSEARCH_API_BASE_URL", raising=False)
    return None


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------


def test_toolkit_registers_the_four_tools_in_both_modes(keyless):
    tools = AnySearchTools()
    assert tools.name == "anysearch_tools"
    assert list(tools.functions) == ["search", "batch_search", "extract", "get_sub_domains"]
    assert list(tools.async_functions) == ["search", "batch_search", "extract", "get_sub_domains"]


def test_sync_surface_holds_no_coroutines_and_async_surface_holds_only_coroutines(keyless):
    """agent.run() refuses a toolkit whose sync Functions wrap coroutines."""
    tools = AnySearchTools()
    for function in tools.functions.values():
        assert not iscoroutinefunction(function.entrypoint)
    for function in tools.async_functions.values():
        assert iscoroutinefunction(function.entrypoint)


def test_enable_flags_prune_the_surface(keyless):
    none_enabled = AnySearchTools(
        enable_search=False, enable_batch_search=False, enable_extract=False, enable_sub_domains=False
    )
    assert list(none_enabled.functions) == []
    assert list(none_enabled.async_functions) == []

    search_only = AnySearchTools(enable_batch_search=False, enable_extract=False, enable_sub_domains=False)
    assert list(search_only.functions) == ["search"]
    assert list(search_only.async_functions) == ["search"]


def test_all_flag_restores_tools_disabled_individually(keyless):
    tools = AnySearchTools(enable_batch_search=False, enable_extract=False, enable_sub_domains=False, all=True)
    assert list(tools.functions) == ["search", "batch_search", "extract", "get_sub_domains"]
    assert list(tools.async_functions) == ["search", "batch_search", "extract", "get_sub_domains"]


def test_include_tools_keeps_only_the_named_tools(keyless):
    tools = AnySearchTools(include_tools=["extract"])
    assert list(tools.functions) == ["extract"]
    assert list(tools.async_functions) == ["extract"]


def test_api_key_and_base_url_are_read_from_env(monkeypatch):
    monkeypatch.setenv("ANYSEARCH_API_KEY", "env-secret")
    monkeypatch.setenv("ANYSEARCH_API_BASE_URL", "https://gateway.example/")
    tools = AnySearchTools()
    assert tools.api_key == "env-secret"
    assert tools.base_url == "https://gateway.example"


def test_explicit_key_and_base_url_win_over_env(monkeypatch):
    monkeypatch.setenv("ANYSEARCH_API_KEY", "env-secret")
    monkeypatch.setenv("ANYSEARCH_API_BASE_URL", "https://env.example")
    tools = AnySearchTools(api_key="explicit", base_url="https://arg.example/")
    assert tools.api_key == "explicit"
    assert tools.base_url == "https://arg.example"


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_request_shape_without_a_key(wire, keyless):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com", "snippet": "S"}])

    out = json.loads(AnySearchTools().search("hello world"))

    request = wire.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.anysearch.com/v1/search"
    assert _body(request) == {"query": "hello world", "max_results": 10, "format": "json"}
    assert "Authorization" not in request.headers
    assert request.headers["X-Anysearch-Client"].startswith("agno/")
    assert request.headers["User-Agent"] == request.headers["X-Anysearch-Client"]
    assert out == {
        "query": "hello world",
        "results": [{"title": "T", "url": "https://e.com", "snippet": "S"}],
        "total_results": 1,
        "search_time_ms": 12,
        "request_id": "req-search",
    }


def test_search_sends_the_key_and_every_optional_field(wire, keyless):
    wire.handler = lambda request: _search_response([])
    tools = AnySearchTools(api_key="secret", zone="cn", language="zh-CN", max_results=4)

    json.loads(tools.search("q", tag="finance.quote", params={"ticker": "AAPL"}))

    request = wire.requests[0]
    assert request.headers["Authorization"] == "Bearer secret"
    assert _body(request) == {
        "query": "q",
        "max_results": 4,
        "format": "json",
        "tag": "finance.quote",
        "params": {"ticker": "AAPL"},
        "zone": "cn",
        "language": "zh-CN",
    }


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(0, 1), (-5, 1), (25, 10), (3, 3), (None, 10)],
)
def test_search_clamps_max_results(wire, keyless, requested, expected):
    wire.handler = lambda request: _search_response([])

    json.loads(AnySearchTools().search("q", max_results=requested))

    assert _body(wire.requests[0])["max_results"] == expected


def test_constructor_max_results_is_the_per_call_default(wire, keyless):
    wire.handler = lambda request: _search_response([])

    json.loads(AnySearchTools(max_results=4).search("q"))

    assert _body(wire.requests[0])["max_results"] == 4


def test_search_maps_results_and_truncates_content(wire, keyless):
    wire.handler = lambda request: _search_response(
        [
            {"title": "T", "url": "https://e.com", "snippet": "S", "content": "x" * 50},
            {"title": "", "url": "https://f.com"},
        ]
    )

    out = json.loads(AnySearchTools(content_length_limit=10).search("q"))

    assert out["results"][0] == {"title": "T", "url": "https://e.com", "snippet": "S", "content": "x" * 10}
    assert out["results"][1] == {"title": "", "url": "https://f.com"}
    assert out["total_results"] == 2


def test_content_limit_of_none_keeps_the_whole_field(wire, keyless):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com", "content": "y" * 500}])

    out = json.loads(AnySearchTools(content_length_limit=None).search("q"))

    assert out["results"][0]["content"] == "y" * 500


def test_blank_search_query_is_rejected_without_a_request(wire, keyless):
    wire.handler = lambda request: _search_response([])
    assert json.loads(AnySearchTools().search("   ")) == {"error": "query is required"}
    assert wire.requests == []


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, "invalid request (HTTP 400)"),
        (401, "invalid API key (HTTP 401)"),
        (403, "expired API key or disabled account (HTTP 403)"),
        (415, "unsupported content type (HTTP 415)"),
        (429, "rate limit exceeded (HTTP 429)"),
        (502, "search service unavailable (HTTP 502)"),
        (503, "AnySearch request failed (HTTP 503)"),
    ],
)
def test_search_reports_status_errors(wire, keyless, status, expected):
    wire.handler = lambda request: httpx.Response(status, json={"code": -1, "message": "boom", "request_id": "req-err"})

    out = json.loads(AnySearchTools().search("q"))

    assert out == {"error": expected, "detail": "boom", "request_id": "req-err"}


def test_search_reports_an_error_envelope_on_http_200(wire, keyless):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": -1, "message": "Query is required.", "request_id": "req-x"}
    )

    out = json.loads(AnySearchTools().search("q"))

    assert out == {
        "error": "AnySearch returned an error response (code != 0)",
        "detail": "Query is required.",
        "request_id": "req-x",
    }


def test_search_tolerates_a_non_json_body(wire, keyless):
    wire.handler = lambda request: httpx.Response(502, text="<html>bad gateway</html>")

    out = json.loads(AnySearchTools().search("q"))

    assert out == {"error": "search service unavailable (HTTP 502)"}


def test_search_reports_transport_failures(wire, keyless):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    wire.handler = handler
    out = json.loads(AnySearchTools().search("q"))

    assert out["error"] == "search request failed"
    assert "ConnectError" in out["detail"]


CREDENTIAL_BODY = (
    "Your account and API key have been automatically generated. Use the API key below to continue.\n"
    "username=demo-user\npassword=super-secret-password\napi_key=ask_example_not_a_real_key"
)


def test_quota_exhaustion_never_echoes_generated_credentials(wire, keyless, monkeypatch):
    logged: List[str] = []
    monkeypatch.setattr("agno.tools.anysearch.log_error", lambda message: logged.append(str(message)))
    monkeypatch.setattr("agno.tools.anysearch.log_debug", lambda message: logged.append(str(message)))
    wire.handler = lambda request: httpx.Response(
        402, json={"code": -1, "message": CREDENTIAL_BODY, "request_id": "req-402"}
    )

    raw = AnySearchTools().search("q")
    out = json.loads(raw)

    assert out == {
        "error": "quota exhausted (HTTP 402); set ANYSEARCH_API_KEY or check the dashboard",
        "request_id": "req-402",
    }
    for secret in ("super-secret-password", "ask_example_not_a_real_key", "demo-user", "password=", "api_key="):
        assert secret not in raw
        assert secret not in " ".join(logged)


# ---------------------------------------------------------------------------
# batch_search
# ---------------------------------------------------------------------------


def test_batch_search_rejects_more_than_five_queries(wire, keyless):
    wire.handler = lambda request: _search_response([])

    out = json.loads(AnySearchTools().batch_search([f"q{i}" for i in range(6)]))

    assert out == {"error": "batch_search takes at most 5 queries per call"}
    assert wire.requests == []


@pytest.mark.parametrize("queries", [[], "not-a-list", None])
def test_batch_search_rejects_an_empty_or_malformed_list(wire, keyless, queries):
    wire.handler = lambda request: _search_response([])

    out = json.loads(AnySearchTools().batch_search(queries))

    assert out == {"error": "queries must be a non-empty list of one to five queries"}
    assert wire.requests == []


def test_batch_search_rejects_a_malformed_item(wire, keyless):
    wire.handler = lambda request: _search_response([])

    out = json.loads(AnySearchTools().batch_search([{"tag": "code.doc"}]))

    assert out == {"error": "each query item needs a non-empty query"}
    assert wire.requests == []


def test_batch_search_normalizes_strings_and_objects(wire, keyless):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com"}])
    tools = AnySearchTools(zone="intl")

    out = json.loads(
        tools.batch_search(["first", {"query": "second", "tag": "code.doc", "max_results": 3}], max_results=2)
    )

    bodies = {_body(request)["query"]: _body(request) for request in wire.requests}
    assert bodies["first"] == {"query": "first", "max_results": 2, "format": "json", "zone": "intl"}
    assert bodies["second"] == {
        "query": "second",
        "max_results": 3,
        "format": "json",
        "zone": "intl",
        "tag": "code.doc",
    }
    assert [entry["query"] for entry in out["searches"]] == ["first", "second"]
    assert all(entry["results"][0]["url"] == "https://e.com" for entry in out["searches"])


def test_batch_search_isolates_a_failing_query(wire, keyless):
    def handler(request: httpx.Request) -> httpx.Response:
        if _body(request)["query"] == "boom":
            return httpx.Response(429, json={"code": -1, "message": "slow down", "request_id": "req-429"})
        return _search_response([{"title": "T", "url": "https://e.com"}], request_id="req-ok")

    wire.handler = handler
    out = json.loads(AnySearchTools().batch_search(["ok", "boom"]))

    assert out["searches"][0]["request_id"] == "req-ok"
    assert out["searches"][0]["results"][0]["url"] == "https://e.com"
    assert out["searches"][1] == {
        "query": "boom",
        "error": "rate limit exceeded (HTTP 429)",
        "detail": "slow down",
        "request_id": "req-429",
    }


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


def test_extract_sends_only_the_url(wire, keyless):
    wire.handler = lambda request: _extract_response()

    out = json.loads(AnySearchTools().extract("https://example.com/article"))

    request = wire.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.anysearch.com/v1/extract"
    assert _body(request) == {"url": "https://example.com/article"}
    assert out == {
        "url": "https://example.com/article",
        "title": "Example Article",
        "content": "Extracted page content.",
        "request_id": "req-extract",
    }


def test_extract_does_not_truncate_the_page(wire, keyless):
    long_page = "z" * 5000
    wire.handler = lambda request: httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-extract",
            "data": {"url": "https://e.com", "title": "T", "content": long_page},
        },
    )

    out = json.loads(AnySearchTools(content_length_limit=10).extract("https://e.com"))

    assert out["content"] == long_page


def test_extract_rejects_a_blank_url_without_a_request(wire, keyless):
    wire.handler = lambda request: _extract_response()
    assert json.loads(AnySearchTools().extract("   ")) == {"error": "url is required"}
    assert wire.requests == []


def test_extract_reports_an_unfetchable_url(wire, keyless):
    wire.handler = lambda request: httpx.Response(
        422,
        json={"code": -1, "message": "URL is invalid.", "request_id": "req-422", "error_code": "invalid_extract_url"},
    )

    out = json.loads(AnySearchTools().extract("https://e.com"))

    assert out == {
        "error": "unable to extract content from the URL (HTTP 422)",
        "detail": "URL is invalid.",
        "request_id": "req-422",
    }


# ---------------------------------------------------------------------------
# get_sub_domains
# ---------------------------------------------------------------------------


def test_get_sub_domains_passes_one_domain_param_per_domain(wire, keyless):
    wire.handler = lambda request: _sub_domains_response()

    out = json.loads(AnySearchTools().get_sub_domains(["finance", "code"]))

    request = wire.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/sub-domains"
    assert request.url.params.get_list("domain") == ["finance", "code"]
    assert out["request_id"] == "req-sub-domains"
    assert out["domains"] == [
        {
            "domain": "finance",
            "sub_domains": [
                {
                    "sub_domain": "finance.quote",
                    "description": "Live quotes",
                    "params": {"ticker": {"required": True, "description": "Stock ticker"}},
                }
            ],
        }
    ]


def test_get_sub_domains_caps_the_domain_list(wire, keyless):
    wire.handler = lambda request: _sub_domains_response()

    out = json.loads(AnySearchTools().get_sub_domains(["finance", "code", "legal", "health", "business", "ip"]))

    assert out == {"error": "get_sub_domains takes at most 5 domains per call"}
    assert wire.requests == []


def test_get_sub_domains_rejects_unknown_and_empty_domains(wire, keyless):
    wire.handler = lambda request: _sub_domains_response()
    tools = AnySearchTools()

    assert json.loads(tools.get_sub_domains(["finance", "astrology"])) == {"error": "unknown domain(s): astrology"}
    assert json.loads(tools.get_sub_domains([])) == {"error": "domains must be a non-empty list of one to five domains"}
    assert wire.requests == []


# ---------------------------------------------------------------------------
# Async parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_search_matches_the_sync_shape(wire, keyless):
    wire.handler = _router
    tools = AnySearchTools()

    assert json.loads(await tools.asearch("q")) == json.loads(tools.search("q"))
    assert len(wire.requests) == 2
    assert all(_body(request) == {"query": "q", "max_results": 10, "format": "json"} for request in wire.requests)


@pytest.mark.asyncio
async def test_async_batch_search_matches_the_sync_shape(wire, keyless):
    wire.handler = _router
    tools = AnySearchTools()

    assert json.loads(await tools.abatch_search(["a", "b"])) == json.loads(tools.batch_search(["a", "b"]))


@pytest.mark.asyncio
async def test_async_extract_and_sub_domains_match_the_sync_shapes(wire, keyless):
    wire.handler = _router
    tools = AnySearchTools()

    assert json.loads(await tools.aextract("https://example.com/article")) == json.loads(
        tools.extract("https://example.com/article")
    )
    assert json.loads(await tools.aget_sub_domains(["finance"])) == json.loads(tools.get_sub_domains(["finance"]))


@pytest.mark.asyncio
async def test_async_search_reports_errors_like_the_sync_path(wire, keyless):
    wire.handler = lambda request: httpx.Response(429, json={"code": -1, "message": "slow down"})

    out = json.loads(await AnySearchTools().asearch("q"))

    assert out == {"error": "rate limit exceeded (HTTP 429)", "detail": "slow down"}


# ---------------------------------------------------------------------------
# Regression: failures reach the model, shape drift is loud, batches stay isolated
# ---------------------------------------------------------------------------


def test_infinite_max_results_is_clamped_instead_of_raising(wire):
    wire.handler = lambda request: _search_response([{"title": "t", "url": "https://example.com"}])

    out = json.loads(AnySearchTools().search("q", max_results=float("inf")))

    assert out["results"][0]["url"] == "https://example.com"
    assert _body(wire.requests[0])["max_results"] == 10


def test_unserializable_params_are_reported_not_raised(wire):
    wire.handler = lambda request: _search_response([])

    out = json.loads(AnySearchTools().search("q", tag="finance.quote", params={"x": object()}))

    assert out["error"] == "search request failed"
    assert "TypeError" in out["detail"]


def test_base_url_without_a_scheme_falls_back_instead_of_raising(wire, monkeypatch):
    logged: List[str] = []
    monkeypatch.setattr("agno.tools.anysearch.log_error", lambda message: logged.append(str(message)))
    wire.handler = lambda request: _search_response([])

    tools = AnySearchTools(base_url="api.anysearch.com")
    out = json.loads(tools.search("q"))

    assert tools.base_url == "https://api.anysearch.com"
    assert "error" not in out
    assert str(wire.requests[0].url).startswith("https://api.anysearch.com/v1/search")
    assert any("not an http(s) URL" in line for line in logged)


def test_envelope_drift_is_reported_instead_of_an_empty_result_set(wire):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "data": {"items": [{"title": "t"}]}, "request_id": "req-drift"}
    )

    out = json.loads(AnySearchTools().search("q"))

    assert out == {"error": "unexpected response envelope from AnySearch", "request_id": "req-drift"}


def test_non_dict_data_is_reported_for_every_endpoint(wire):
    wire.handler = lambda request: httpx.Response(200, json={"code": 0, "data": ["nope"]})

    tools = AnySearchTools()

    assert json.loads(tools.search("q"))["error"] == "unexpected response envelope from AnySearch"
    assert json.loads(tools.extract("https://example.com"))["error"] == "unexpected response envelope from AnySearch"
    assert json.loads(tools.get_sub_domains(["finance"]))["error"] == "unexpected response envelope from AnySearch"


def test_renamed_sub_domain_field_is_reported_instead_of_an_empty_list(wire):
    wire.handler = lambda request: httpx.Response(200, json={"code": 0, "data": {"capabilities": []}})

    out = json.loads(AnySearchTools().get_sub_domains(["finance"]))

    assert out == {"error": "unexpected response envelope from AnySearch"}


def test_credential_shaped_message_is_withheld_under_any_status(wire, keyless, monkeypatch):
    logged: List[str] = []
    monkeypatch.setattr("agno.tools.anysearch.log_error", lambda message: logged.append(str(message)))
    monkeypatch.setattr("agno.tools.anysearch.log_debug", lambda message: logged.append(str(message)))
    wire.handler = lambda request: httpx.Response(429, json={"code": -1, "message": CREDENTIAL_BODY})

    raw = AnySearchTools().search("q")
    out = json.loads(raw)

    assert "withheld" in out["error"]
    assert "super-secret-password" not in raw
    assert "ask_example_not_a_real_key" not in raw
    assert all("super-secret" not in line for line in logged)
    assert all("ask_example_not_a_real_key" not in line for line in logged)


def test_batch_isolates_a_query_that_fails_before_the_wire(wire):
    wire.handler = lambda request: _search_response([{"title": "ok", "url": "https://example.com"}])

    out = json.loads(AnySearchTools().batch_search(["good", {"query": "bad", "params": {"x": object()}}, "third"]))
    searches = out["searches"]

    assert [entry.get("query") for entry in searches] == ["good", "bad", "third"]
    assert "error" in searches[1]
    assert searches[0]["results"][0]["url"] == "https://example.com"


def test_extract_content_is_capped_by_default_and_configurable(wire):
    page = "x" * 120_000
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "data": {"url": "https://example.com", "title": "t", "content": page}}
    )

    assert len(json.loads(AnySearchTools().extract("https://example.com"))["content"]) == 50_000
    assert len(json.loads(AnySearchTools(extract_length_limit=10).extract("https://example.com"))["content"]) == 10
    whole = AnySearchTools(extract_length_limit=None).extract("https://example.com")
    assert len(json.loads(whole)["content"]) == 120_000


def test_non_positive_length_limits_keep_whole_fields(wire):
    wire.handler = lambda request: _search_response(
        [{"title": "t", "url": "https://example.com", "content": "abcdefghij"}]
    )

    out = json.loads(AnySearchTools(content_length_limit=0).search("q"))

    assert out["results"][0]["content"] == "abcdefghij"


# ---------------------------------------------------------------------------
# Review round 2
# ---------------------------------------------------------------------------


def test_non_dict_metadata_is_ignored_instead_of_raising(wire):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "data": {"results": [{"title": "t", "url": "u"}], "metadata": "success"}}
    )

    out = json.loads(AnySearchTools().search("q"))

    assert out == {"query": "q", "results": [{"title": "t", "url": "u"}]}


def test_extract_reads_a_null_body_as_empty_rather_than_the_string_none(wire):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "data": {"url": "https://e.com", "title": "t", "content": None}}
    )

    out = json.loads(AnySearchTools().extract("https://e.com"))

    assert out["content"] == ""


@pytest.mark.parametrize("response", [httpx.Response(200, text="<html/>"), httpx.Response(204)])
def test_a_success_status_without_the_envelope_is_reported(wire, response):
    wire.handler = lambda request: response

    out = json.loads(AnySearchTools().search("q"))

    assert out["error"] == "unexpected response envelope from AnySearch"
