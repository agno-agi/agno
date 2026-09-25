"""Unit tests for AnySearchBackend.

No network: the backend's per-call httpx clients are routed through a MockTransport. The
page-fetching half is exercised through FetchedPage, which is the seam the knowledge readers
ride, so those tests also cover the backend's use as a page fetcher.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest

from agno.context.mode import ContextMode
from agno.context.provider import Status
from agno.context.web import AnySearchBackend, WebContextProvider
from agno.knowledge.reader.page_fetcher import FetchedPage, RateLimited

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def wire(monkeypatch):
    """Point every client the backend builds at one MockTransport, recording requests."""
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


def _tools(backend: AnySearchBackend) -> Dict[str, Any]:
    return {tool.name: tool for tool in backend.get_tools()}


def _search_response(results: List[Dict[str, Any]], request_id: str = "req-search") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": request_id,
            "data": {
                "results": results,
                "metadata": {"total_results": len(results), "search_time_ms": 12},
            },
        },
    )


def _extract_response(content: str = "Extracted page content.") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-extract",
            "data": {"url": "https://example.com/article", "title": "Example Article", "content": content},
        },
    )


def _sub_domains_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-sub-domains",
            "data": {"domains": [{"domain": "finance", "sub_domains": [{"sub_domain": "finance.quote"}]}]},
        },
    )


def _router(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/search":
        return _search_response([{"title": "T", "url": "https://e.com", "snippet": "S"}])
    if request.url.path == "/v1/extract":
        return _extract_response()
    return _sub_domains_response()


def _keyless_backend(**kwargs) -> AnySearchBackend:
    """A backend with no key, whatever the machine's environment holds."""
    return AnySearchBackend(api_key="", **kwargs)


def _capture_logs(monkeypatch) -> List[str]:
    """Every line the backend logs, so a test can prove nothing sensitive reached the log."""
    logged: List[str] = []
    monkeypatch.setattr("agno.context.web.anysearch.log_error", lambda message: logged.append(str(message)))
    monkeypatch.setattr("agno.context.web.anysearch.log_debug", lambda message: logged.append(str(message)))
    return logged


# ---------------------------------------------------------------------------
# Status and construction
# ---------------------------------------------------------------------------


def test_status_is_ok_and_keyless_without_a_key():
    backend = _keyless_backend()
    assert backend.status() == Status(ok=True, detail="api.anysearch.com (keyless)")


def test_status_reports_a_keyed_endpoint():
    backend = AnySearchBackend(api_key="secret")
    assert backend.status() == Status(ok=True, detail="api.anysearch.com (keyed)")


@pytest.mark.asyncio
async def test_astatus_matches_the_sync_status():
    backend = _keyless_backend()
    assert await backend.astatus() == backend.status()


def test_api_key_and_base_url_are_read_from_env(monkeypatch):
    monkeypatch.setenv("ANYSEARCH_API_KEY", "env-secret")
    monkeypatch.setenv("ANYSEARCH_API_BASE_URL", "https://gateway.example/")
    backend = AnySearchBackend()
    assert backend.api_key == "env-secret"
    assert backend.base_url == "https://gateway.example"
    assert backend.status().detail == "gateway.example (keyed)"


def test_explicit_key_and_base_url_win_over_env(monkeypatch):
    monkeypatch.setenv("ANYSEARCH_API_KEY", "env-secret")
    monkeypatch.setenv("ANYSEARCH_API_BASE_URL", "https://env.example")
    backend = AnySearchBackend(api_key="", base_url="https://arg.example/")
    assert backend.api_key == ""
    assert backend.base_url == "https://arg.example"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", ["api.anysearch.com", "//api.anysearch.com", "ftp://api.anysearch.com"])
async def test_base_url_without_an_http_scheme_falls_back(wire, monkeypatch, configured):
    """`httpx` raises on a URL with no http(s) scheme, so the backend falls back instead."""
    logged = _capture_logs(monkeypatch)
    wire.handler = lambda request: _search_response([])
    backend = _keyless_backend(base_url=configured)

    assert backend.base_url == "https://api.anysearch.com"
    assert backend.status() == Status(ok=True, detail="api.anysearch.com (keyless)")

    await _tools(backend)["web_search"].entrypoint(query="hello")

    assert str(wire.requests[0].url) == "https://api.anysearch.com/v1/search"
    assert any("not an http(s) URL" in message for message in logged)


@pytest.mark.parametrize("configured", ["api.anysearch.com", "api.anysearch.com:8443"])
def test_base_url_without_a_scheme_from_env_falls_back(monkeypatch, configured):
    monkeypatch.setenv("ANYSEARCH_API_BASE_URL", configured)
    backend = AnySearchBackend(api_key="")

    assert backend.base_url == "https://api.anysearch.com"
    assert backend.status().detail == "api.anysearch.com (keyless)"


def test_base_url_with_a_plain_http_scheme_is_kept():
    backend = _keyless_backend(base_url="http://gateway.example/")

    assert backend.base_url == "http://gateway.example"
    assert backend.status().detail == "gateway.example (keyless)"


def test_backend_declares_its_page_fetching_metadata():
    backend = _keyless_backend()
    assert sorted(_tools(backend)) == ["web_extract", "web_search", "web_search_batch", "web_sub_domains"]
    assert backend.extractor_id == "anysearch"
    assert backend.fetch_batch_limit == 1


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_request_shape_and_result(wire):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com", "snippet": "S"}])
    backend = _keyless_backend()

    raw = await _tools(backend)["web_search"].entrypoint(query="hello", max_results=2, tag="code.doc")
    out = json.loads(raw)

    request = wire.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.anysearch.com/v1/search"
    assert _body(request) == {"query": "hello", "max_results": 2, "format": "json", "tag": "code.doc"}
    assert "Authorization" not in request.headers
    assert request.headers["X-Anysearch-Client"].startswith("agno/")
    assert out == {
        "query": "hello",
        "results": [{"title": "T", "url": "https://e.com", "snippet": "S"}],
        "total_results": 1,
        "search_time_ms": 12,
        "request_id": "req-search",
    }


@pytest.mark.asyncio
async def test_web_search_uses_the_backend_defaults(wire):
    wire.handler = lambda request: _search_response([])
    backend = AnySearchBackend(api_key="secret", max_results=3, zone="cn", language="zh-CN")

    await _tools(backend)["web_search"].entrypoint(query="hello")

    request = wire.requests[0]
    assert request.headers["Authorization"] == "Bearer secret"
    assert _body(request) == {
        "query": "hello",
        "max_results": 3,
        "format": "json",
        "zone": "cn",
        "language": "zh-CN",
    }


@pytest.mark.asyncio
async def test_web_search_reports_rate_limits(wire):
    wire.handler = lambda request: httpx.Response(
        429, json={"code": -1, "message": "slow down", "request_id": "req-429"}
    )

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="hello"))

    assert out == {"error": "rate limit exceeded (HTTP 429)", "detail": "slow down", "request_id": "req-429"}


@pytest.mark.asyncio
async def test_web_search_never_echoes_generated_credentials(wire, monkeypatch):
    logged: List[str] = []
    monkeypatch.setattr("agno.context.web.anysearch.log_error", lambda message: logged.append(str(message)))
    monkeypatch.setattr("agno.context.web.anysearch.log_debug", lambda message: logged.append(str(message)))
    wire.handler = lambda request: httpx.Response(
        402,
        json={
            "code": -1,
            "message": "generated credentials\nusername=demo-user\npassword=super-secret\napi_key=ask_example_not_a_real_key_1",
            "request_id": "req-402",
        },
    )

    raw = await _tools(_keyless_backend())["web_search"].entrypoint(query="hello")
    out = json.loads(raw)

    assert out == {
        "error": "quota exhausted (HTTP 402); set ANYSEARCH_API_KEY or check the dashboard",
        "request_id": "req-402",
    }
    for secret in ("super-secret", "ask_example_not_a_real_key_1", "demo-user", "password="):
        assert secret not in raw
        assert secret not in " ".join(logged)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 400, 200])
@pytest.mark.parametrize(
    "message",
    [
        "generated credentials\nusername=demo-user\npassword=super-secret\napi_key=ask_example_not_a_real_key_1",
        "API key: ask_example_not_a_real_key_2",
        "api-key = ask_example_not_a_real_key_3",
        "Automatically generated credentials were attached to this response.",
    ],
)
async def test_web_search_withholds_credentials_whatever_the_status(wire, monkeypatch, status, message):
    """A quota body is redacted on its text, not on its status code: 429/400/200 all leak it."""
    logged = _capture_logs(monkeypatch)
    wire.handler = lambda request: httpx.Response(
        status, json={"code": -1, "message": message, "request_id": "req-credentials"}
    )

    raw = await _tools(_keyless_backend())["web_search"].entrypoint(query="hello")

    assert json.loads(raw) == {
        "error": "quota response withheld; set ANYSEARCH_API_KEY or check the dashboard",
        "request_id": "req-credentials",
    }
    for token in ("demo-user", "username", "password", "super-secret", "ask_example_not_a_real_key_1", "ask_example_not_a_real_key_2", "ask_example_not_a_real_key_3"):
        assert token not in raw
        assert token not in " ".join(logged)


@pytest.mark.asyncio
async def test_web_search_keeps_the_result_metadata(wire):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com"}])

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="hello"))

    assert out["total_results"] == 1
    assert out["search_time_ms"] == 12


@pytest.mark.asyncio
async def test_web_search_omits_metadata_the_envelope_does_not_carry(wire):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-search", "data": {"results": []}}
    )

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="hello"))

    assert out == {"query": "hello", "results": [], "request_id": "req-search"}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [["not", "a", "mapping"], "not a mapping", None])
async def test_web_search_reports_a_non_dict_data_envelope(wire, data):
    """A drifted envelope is an error, never a fake 'nothing found'."""
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-drift", "data": data}
    )

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="hello"))

    assert out == {"error": "unexpected response envelope from AnySearch", "request_id": "req-drift"}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{"items": [{"title": "T"}]}, {"results": {"items": []}}, {"results": "none"}])
async def test_web_search_reports_a_renamed_results_field(wire, data):
    """A renamed or restructured `results` key must not read back as no results."""
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-drift", "data": data}
    )

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="hello"))

    assert out == {"error": "unexpected response envelope from AnySearch", "request_id": "req-drift"}


# ---------------------------------------------------------------------------
# web_search_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_search_batch_runs_every_query_and_isolates_failures(wire):
    def handler(request: httpx.Request) -> httpx.Response:
        if _body(request)["query"] == "boom":
            return httpx.Response(429, json={"code": -1, "message": "slow down", "request_id": "req-429"})
        return _search_response([{"title": "T", "url": "https://e.com"}], request_id="req-ok")

    wire.handler = handler
    raw = await _tools(_keyless_backend())["web_search_batch"].entrypoint(queries=["ok", "boom", "also ok"])
    out = json.loads(raw)

    assert [entry["query"] for entry in out["searches"]] == ["ok", "boom", "also ok"]
    assert out["searches"][0]["request_id"] == "req-ok"
    assert out["searches"][1] == {
        "query": "boom",
        "error": "rate limit exceeded (HTTP 429)",
        "detail": "slow down",
        "request_id": "req-429",
    }
    assert out["searches"][2]["request_id"] == "req-ok"
    assert {_body(request)["query"] for request in wire.requests} == {"ok", "boom", "also ok"}


@pytest.mark.asyncio
async def test_web_search_batch_rejects_too_many_queries(wire):
    wire.handler = lambda request: _search_response([])

    out = json.loads(
        await _tools(_keyless_backend())["web_search_batch"].entrypoint(queries=[f"q{i}" for i in range(6)])
    )

    assert out == {"error": "queries takes at most 5 items per call"}
    assert wire.requests == []


@pytest.mark.asyncio
async def test_web_search_batch_entries_carry_the_result_metadata(wire):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com"}], request_id="req-ok")

    out = json.loads(await _tools(_keyless_backend())["web_search_batch"].entrypoint(queries=["ok"]))

    assert out["searches"][0]["total_results"] == 1
    assert out["searches"][0]["search_time_ms"] == 12


@pytest.mark.asyncio
async def test_web_search_batch_isolates_a_non_http_failure(wire, monkeypatch):
    """A per-item exception that is not an `httpx` error still only fails that one item."""
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com"}], request_id="req-ok")
    backend = _keyless_backend()
    search_one = backend._asearch_one

    async def flaky(client, item):
        if item["query"] == "boom":
            raise RuntimeError("kaboom")
        return await search_one(client, item)

    monkeypatch.setattr(backend, "_asearch_one", flaky)

    out = json.loads(await _tools(backend)["web_search_batch"].entrypoint(queries=["ok", "boom", "also ok"]))

    assert [entry["query"] for entry in out["searches"]] == ["ok", "boom", "also ok"]
    assert out["searches"][0]["request_id"] == "req-ok"
    assert out["searches"][1] == {"query": "boom", "error": "search request failed", "detail": "RuntimeError: kaboom"}
    assert out["searches"][2]["request_id"] == "req-ok"


@pytest.mark.asyncio
async def test_web_search_batch_survives_an_escaped_exception(wire, monkeypatch):
    """`asyncio.gather(return_exceptions=True)` maps an escaped exception onto its own entry."""
    wire.handler = lambda request: _search_response([])
    backend = _keyless_backend()

    async def exploding(client, item):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(backend, "_asearch_entry", exploding)

    out = json.loads(await _tools(backend)["web_search_batch"].entrypoint(queries=["one", "two"]))

    assert [entry["query"] for entry in out["searches"]] == ["one", "two"]
    assert [entry["error"] for entry in out["searches"]] == ["search request failed", "search request failed"]
    assert [entry["detail"] for entry in out["searches"]] == ["RuntimeError: kaboom", "RuntimeError: kaboom"]


def test_batch_result_maps_an_escaped_exception_to_that_entry():
    assert AnySearchBackend._batch_result(RuntimeError("kaboom")) == {
        "error": "search request failed",
        "detail": "RuntimeError: kaboom",
    }
    assert AnySearchBackend._batch_result({"query": "ok", "results": []}) == {"query": "ok", "results": []}


# ---------------------------------------------------------------------------
# web_extract and web_sub_domains
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_web_extract_sends_only_the_url(wire):
    wire.handler = lambda request: _extract_response()

    out = json.loads(await _tools(_keyless_backend())["web_extract"].entrypoint(url="https://example.com/article"))

    request = wire.requests[0]
    assert str(request.url) == "https://api.anysearch.com/v1/extract"
    assert _body(request) == {"url": "https://example.com/article"}
    assert out == {
        "url": "https://example.com/article",
        "title": "Example Article",
        "content": "Extracted page content.",
        "request_id": "req-extract",
    }


@pytest.mark.asyncio
async def test_web_sub_domains_passes_one_domain_param_per_domain(wire):
    wire.handler = lambda request: _sub_domains_response()

    out = json.loads(await _tools(_keyless_backend())["web_sub_domains"].entrypoint(domains=["finance", "code"]))

    request = wire.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/v1/sub-domains"
    assert request.url.params.get_list("domain") == ["finance", "code"]
    assert out["domains"] == [{"domain": "finance", "sub_domains": [{"sub_domain": "finance.quote"}]}]


@pytest.mark.asyncio
async def test_web_sub_domains_rejects_an_unknown_domain_before_the_request(wire):
    """The tool schema enumerates the capability domains, so the call fails at validation."""
    from pydantic import ValidationError

    wire.handler = lambda request: _sub_domains_response()

    with pytest.raises(ValidationError):
        await _tools(_keyless_backend())["web_sub_domains"].entrypoint(domains=["finance", "astrology"])
    assert wire.requests == []


@pytest.mark.asyncio
async def test_web_sub_domains_caps_the_domain_list(wire):
    wire.handler = lambda request: _sub_domains_response()

    out = json.loads(
        await _tools(_keyless_backend())["web_sub_domains"].entrypoint(
            domains=["finance", "code", "legal", "health", "business", "ip"]
        )
    )

    assert out == {"error": "web_sub_domains takes at most 5 domains per call"}
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [["not", "a", "mapping"], "Extracted text."])
async def test_web_extract_reports_a_non_dict_data_envelope(wire, data):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-drift", "data": data}
    )

    out = json.loads(await _tools(_keyless_backend())["web_extract"].entrypoint(url="https://example.com/article"))

    assert out == {"error": "unexpected response envelope from AnySearch", "request_id": "req-drift"}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [["finance"], None])
async def test_web_sub_domains_reports_a_non_dict_data_envelope(wire, data):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-drift", "data": data}
    )

    out = json.loads(await _tools(_keyless_backend())["web_sub_domains"].entrypoint(domains=["finance"]))

    assert out == {"error": "unexpected response envelope from AnySearch", "request_id": "req-drift"}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [{"capabilities": []}, {"domains": "finance"}])
async def test_web_sub_domains_reports_a_renamed_domains_field(wire, data):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-drift", "data": data}
    )

    out = json.loads(await _tools(_keyless_backend())["web_sub_domains"].entrypoint(domains=["finance"]))

    assert out == {"error": "unexpected response envelope from AnySearch", "request_id": "req-drift"}


# ---------------------------------------------------------------------------
# Page fetching for the knowledge readers
# ---------------------------------------------------------------------------


def test_fetch_many_maps_an_extracted_page(wire):
    wire.handler = lambda request: _extract_response()

    pages = _keyless_backend().fetch_many(["https://example.com/article"], max_chars=10)

    assert pages == [
        FetchedPage(
            url="https://example.com/article",
            content="Extracted ",
            title="Example Article",
            extractor="anysearch",
        )
    ]
    request = wire.requests[0]
    assert request.method == "POST"
    assert _body(request) == {"url": "https://example.com/article"}
    assert pages[0].ok is True


def test_fetch_many_reports_an_unfetchable_page_without_raising(wire):
    wire.handler = lambda request: httpx.Response(
        422, json={"code": -1, "message": "URL is invalid.", "request_id": "req-422"}
    )

    pages = _keyless_backend().fetch_many(["https://example.com/bad"])

    assert len(pages) == 1
    assert pages[0].url == "https://example.com/bad"
    assert pages[0].extractor == "anysearch"
    # The page error keeps the API's own message, like `parallel.py`'s `_failure_reason`.
    assert pages[0].error == "unable to extract content from the URL (HTTP 422): URL is invalid."
    assert pages[0].ok is False


def test_fetch_many_raises_rate_limited_with_retry_after(wire):
    wire.handler = lambda request: httpx.Response(
        429, json={"code": -1, "message": "slow down"}, headers={"Retry-After": "2.5"}
    )

    with pytest.raises(RateLimited) as excinfo:
        _keyless_backend().fetch_many(["https://example.com/article"])

    assert excinfo.value.retry_after == 2.5


def test_fetch_many_reports_transport_failures_per_page(wire):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    wire.handler = handler
    pages = _keyless_backend().fetch_many(["https://example.com/article"])

    assert pages[0].error is not None and "ConnectError" in pages[0].error
    assert pages[0].extractor == "anysearch"


def test_fetch_many_reports_an_empty_extraction(wire):
    wire.handler = lambda request: _extract_response(content="")

    pages = _keyless_backend().fetch_many(["https://example.com/article"])

    assert pages[0].error == "empty"
    assert pages[0].extractor == "anysearch"


def test_fetch_many_truncates_a_long_page_error_detail(wire):
    wire.handler = lambda request: httpx.Response(422, json={"code": -1, "message": "x" * 400, "request_id": "req-422"})

    pages = _keyless_backend().fetch_many(["https://example.com/bad"])

    assert pages[0].error is not None
    assert len(pages[0].error) == 300
    assert pages[0].error.startswith("unable to extract content from the URL (HTTP 422): x")


def test_fetch_many_reports_a_non_dict_data_envelope(wire):
    wire.handler = lambda request: httpx.Response(
        200, json={"code": 0, "message": "success", "request_id": "req-drift", "data": ["Extracted text."]}
    )

    pages = _keyless_backend().fetch_many(["https://example.com/article"])

    assert pages[0].ok is False
    assert pages[0].error == "unexpected response envelope from AnySearch"
    assert pages[0].extractor == "anysearch"


def test_fetch_many_stringifies_a_non_string_content(wire):
    """A `content` that arrives as a JSON object must not raise out of the character slice."""
    wire.handler = lambda request: httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-extract",
            "data": {"url": "https://example.com/article", "title": "Example Article", "content": {"body": "Text"}},
        },
    )

    pages = _keyless_backend().fetch_many(["https://example.com/article"], max_chars=7)

    assert pages[0].ok is True
    assert pages[0].content == "{'body'"
    assert pages[0].title == "Example Article"


@pytest.mark.parametrize("content", [None, 0, False])
def test_fetch_many_reports_a_falsy_non_string_content_as_empty(wire, content):
    wire.handler = lambda request: httpx.Response(
        200,
        json={
            "code": 0,
            "message": "success",
            "request_id": "req-extract",
            "data": {"content": content},
        },
    )

    pages = _keyless_backend().fetch_many(["https://example.com/article"])

    assert pages[0].ok is False
    assert pages[0].error == "empty"


def test_fetch_many_treats_a_402_quota_wall_as_a_page_error_not_a_rate_limit(wire):
    """The quota body can say "rate limit"; a 402 must never be retried as throttling."""
    wire.handler = lambda request: httpx.Response(
        402,
        json={"code": -1, "message": "rate limit exceeded: the free quota is used up", "request_id": "req-402"},
        headers={"Retry-After": "1"},
    )

    pages = _keyless_backend().fetch_many(["https://example.com/article"])

    assert pages[0].ok is False
    assert pages[0].error == "quota exhausted (HTTP 402); set ANYSEARCH_API_KEY or check the dashboard"
    assert pages[0].extractor == "anysearch"


def test_fetch_many_withholds_credentials_instead_of_rate_limiting(wire, monkeypatch):
    """429 plus credential text is a quota wall: no `RateLimited`, no echo, no log line."""
    logged = _capture_logs(monkeypatch)
    wire.handler = lambda request: httpx.Response(
        429,
        json={
            "code": -1,
            "message": "rate limit reached; credentials were automatically generated\n"
            "username=demo-user\npassword=super-secret",
            "request_id": "req-credentials",
        },
        headers={"Retry-After": "2.5"},
    )

    pages = _keyless_backend().fetch_many(["https://example.com/article"])

    assert pages[0].ok is False
    assert pages[0].error == "quota response withheld; set ANYSEARCH_API_KEY or check the dashboard"
    assert pages[0].extractor == "anysearch"
    for token in ("demo-user", "password", "super-secret"):
        assert token not in (pages[0].error or "")
        assert token not in " ".join(logged)


@pytest.mark.asyncio
async def test_afetch_many_matches_the_sync_path(wire):
    wire.handler = lambda request: _extract_response()
    backend = _keyless_backend()

    pages = await backend.afetch_many(["https://example.com/article"], max_chars=20)

    assert pages[0].content == "Extracted page conte"
    assert pages[0].title == "Example Article"
    assert pages[0].extractor == "anysearch"


@pytest.mark.asyncio
async def test_afetch_many_raises_rate_limited(wire):
    wire.handler = lambda request: httpx.Response(429, json={"code": -1, "message": "slow down"})

    with pytest.raises(RateLimited):
        await _keyless_backend().afetch_many(["https://example.com/article"])


def test_page_fetcher_sizes_its_batches_from_the_backend(wire):
    from agno.knowledge.reader.page_fetcher import ParallelPageFetcher

    fetcher = ParallelPageFetcher(backend=_keyless_backend(), batch_size=10)

    assert fetcher.batch_size == 1
    assert fetcher.extractor_id == "anysearch"


def test_page_fetcher_fetches_through_the_backend(wire):
    from agno.knowledge.reader.page_fetcher import ParallelPageFetcher

    wire.handler = lambda request: _extract_response()
    pages = ParallelPageFetcher(backend=_keyless_backend()).fetch_many(["https://example.com/article"])

    assert pages[0].ok is True
    assert pages[0].extractor == "anysearch"
    # The provider's own extractor id is what the provenance records, not the fallback's.
    assert pages[0].attempts == [{"extractor": "anysearch", "outcome": "ok"}]


def test_page_fetcher_does_not_retry_a_402_quota_wall(wire):
    """A quota wall is a hard stop: the rate-limit policy must not spin on it."""
    from agno.knowledge.reader.page_fetcher import ParallelPageFetcher

    wire.handler = lambda request: httpx.Response(
        402,
        json={"code": -1, "message": "rate limit: free quota exhausted", "request_id": "req-402"},
        headers={"Retry-After": "1"},
    )

    pages = ParallelPageFetcher(backend=_keyless_backend()).fetch_many(["https://example.com/article"])

    assert len([request for request in wire.requests if request.url.path == "/v1/extract"]) == 1
    assert pages[0].ok is False
    assert pages[0].attempts[0] == {
        "extractor": "anysearch",
        "outcome": "quota exhausted (HTTP 402); set ANYSEARCH_API_KEY or check the dashboard",
    }


# ---------------------------------------------------------------------------
# WebContextProvider wiring
# ---------------------------------------------------------------------------


def test_web_provider_exposes_the_query_tool_and_forwards_status():
    provider = WebContextProvider(backend=_keyless_backend())

    assert [tool.name for tool in provider.get_tools()] == ["query_web"]
    assert provider.status() == Status(ok=True, detail="api.anysearch.com (keyless)")
    assert "query_web" in provider.instructions()


def test_web_provider_in_tools_mode_surfaces_the_backend_tools():
    provider = WebContextProvider(backend=_keyless_backend(), mode=ContextMode.tools)

    assert sorted(tool.name for tool in provider.get_tools()) == [
        "web_extract",
        "web_search",
        "web_search_batch",
        "web_sub_domains",
    ]


@pytest.mark.asyncio
async def test_web_provider_aclose_is_a_no_op():
    provider = WebContextProvider(backend=_keyless_backend())
    await provider.asetup()
    await provider.aclose()
    assert provider.status().ok is True


# ---------------------------------------------------------------------------
# Review round 2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan"), "abc", None, 0, -5, 25])
def test_max_results_is_clamped_for_any_input(value):
    assert 1 <= _keyless_backend(max_results=value).max_results <= 10


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [float("inf"), object()])
async def test_search_reports_params_that_cannot_be_encoded(wire, value):
    wire.handler = lambda request: _search_response([])

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="q", params={"x": value}))

    assert out["error"] == "search request failed"
    assert "detail" in out
    assert wire.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -3])
async def test_a_non_positive_content_length_limit_keeps_the_whole_field(wire, limit):
    wire.handler = lambda request: _search_response([{"title": "T", "url": "https://e.com", "content": "x" * 3000}])

    out = json.loads(await _tools(_keyless_backend(content_length_limit=limit))["web_search"].entrypoint(query="q"))

    assert len(out["results"][0]["content"]) == 3000


@pytest.mark.asyncio
async def test_web_extract_caps_the_content(wire):
    wire.handler = lambda request: _extract_response("y" * 200_000)

    out = json.loads(await _tools(_keyless_backend())["web_extract"].entrypoint(url="https://example.com"))

    assert len(out["content"]) == 50_000


def test_fetch_many_keeps_the_whole_page_for_a_non_positive_max_chars(wire):
    wire.handler = lambda request: _extract_response("z" * 3000)

    pages = _keyless_backend().fetch_many(["https://example.com/a"], max_chars=-1)

    assert len(pages[0].content) == 3000


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html/>"), httpx.Response(204)])
async def test_a_success_status_without_the_envelope_is_reported(wire, response):
    wire.handler = lambda request: response

    out = json.loads(await _tools(_keyless_backend())["web_search"].entrypoint(query="q"))

    assert out["error"] == "unexpected response envelope from AnySearch"
