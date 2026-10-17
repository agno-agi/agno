import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import httpx2
import pytest
from jsonschema import validate

from agno.tools import baizhi
from agno.tools.baizhi import BaizhiTools
from agno.tools.function import FunctionCall

KEY = "SYNTHETIC-BAIZHI-TEST-KEY"
METADATA = json.loads((Path(__file__).parent / "fixtures" / "baizhi_tools.json").read_text())
SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in METADATA["tools"]}


@pytest.fixture(autouse=True)
def isolated_key(monkeypatch):
    monkeypatch.delenv("BAIZHI_API_KEY", raising=False)


@pytest.fixture
def server(monkeypatch):
    """Real MCP SDK + HTTP transport, with all network traffic handled in memory."""
    requests = []
    client_options = []
    state = {"status": 200, "result": {"content": [{"type": "text", "text": "ok"}], "structuredContent": {"ok": True}}}
    real_client = httpx2.AsyncClient

    def handler(request):
        state.setdefault("urls", []).append(str(request.url))
        assert str(request.url) == "https://agent-toolkit.app.baizhi.cloud/mcp"
        assert request.headers["authorization"] == "Bearer " + KEY
        if state["status"] != 200:
            return httpx2.Response(
                state["status"],
                text="Request failed: " + KEY,
                headers={"Location": state.get("location", "/redirected")},
            )
        if request.method == "GET":
            return httpx2.Response(405)
        if request.method == "DELETE":
            return httpx2.Response(200)
        data = json.loads(request.content)
        requests.append(data)
        method = data["method"]
        if method == "notifications/initialized":
            return httpx2.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": METADATA["tools"]}
        elif method == "tools/call":
            validate(data["params"]["arguments"], SCHEMAS[data["params"]["name"]])
            if state.get("malformed") == "json":
                return httpx2.Response(200, text=KEY + " malformed JSON", headers={"Content-Type": "application/json"})
            if state.get("malformed") == "sse":
                return httpx2.Response(
                    200,
                    text="event: message\ndata: " + KEY + " malformed JSON\n\n",
                    headers={"Content-Type": "text/event-stream"},
                )
            result = state["result"]
        else:
            raise AssertionError(method)
        return httpx2.Response(200, json={"jsonrpc": "2.0", "id": data["id"], "result": result})

    def factory(**kwargs):
        client_options.append(kwargs)
        return real_client(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr(baizhi.httpx2, "AsyncClient", factory)
    return requests, client_options, state


def test_missing_and_explicit_empty_keys_fail_before_network(monkeypatch):
    with pytest.raises(ValueError, match="Set BAIZHI_API_KEY"):
        BaizhiTools()
    monkeypatch.setenv("BAIZHI_API_KEY", KEY)
    assert BaizhiTools()._api_key.get_secret_value() == KEY
    with pytest.raises(ValueError, match="Set BAIZHI_API_KEY"):
        BaizhiTools(api_key="")
    for bad in ("Bearer " + KEY, KEY + "\n"):
        with pytest.raises(ValueError, match="raw key"):
            BaizhiTools(api_key=bad)
    assert KEY not in repr(BaizhiTools()._api_key)
    with pytest.raises(ValueError, match="positive"):
        BaizhiTools(timeout=0)


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({}, set(SCHEMAS)),
        ({"enable_scrape": False, "enable_extract": False}, {"websearch_search"}),
        ({"enable_search": False, "enable_scrape": False, "enable_extract": False}, set()),
        ({"enable_search": False, "enable_scrape": False, "enable_extract": False, "all": True}, set(SCHEMAS)),
    ],
)
def test_sync_and_async_tool_surface(flags, expected):
    tools = BaizhiTools(api_key=KEY, **flags)
    assert set(tools.get_functions()) == set(tools.get_async_functions()) == expected


def test_sync_search_uses_real_mcp_protocol_and_nested_filter(server):
    requests, options, _ = server
    tools = BaizhiTools(api_key=KEY)
    result = json.loads(
        tools.websearch_search("MCP", count=3, domains=["example.com"], exclude_domains=["example.net"])
    )
    assert result["structuredContent"] == {"ok": True}
    assert result["isError"] is False
    call = next(r for r in requests if r["method"] == "tools/call")
    assert call["params"]["name"] == "websearch_search"
    assert call["params"]["arguments"]["filter"] == {"domains": ["example.com"], "exclude_domains": ["example.net"]}
    assert requests[0]["method"] == "initialize"
    assert options[0]["follow_redirects"] is False
    assert options[0]["trust_env"] is False


@pytest.mark.asyncio
async def test_async_scrape_and_extract_use_current_object_schema(server):
    requests, _, _ = server
    tools = BaizhiTools(api_key=KEY)
    assert not json.loads(await tools.aweb_scrape("https://example.com", accept_language="zh-CN"))["isError"]
    assert not json.loads(await tools.aweb_extract("https://example.com", fields={"title": "string"}))["isError"]
    calls = [r["params"] for r in requests if r["method"] == "tools/call"]
    assert calls[0]["arguments"] == {
        "url": "https://example.com",
        "return_format": "markdown",
        "accept_language": "zh-CN",
        "download": False,
    }
    assert calls[1]["arguments"] == {"url": "https://example.com", "fields": {"title": "string"}, "download": False}
    assert len([r for r in requests if r["method"] == "initialize"]) == 2


def test_agno_function_dispatch_preserves_native_tool_schema_and_result(server):
    tools = BaizhiTools(api_key=KEY)
    function = tools.get_functions()["web_extract"]
    function.process_entrypoint()
    assert function.parameters["properties"]["fields"]["type"] == "object"
    call = FunctionCall(function=function, arguments={"url": "https://example.com", "fields": {"title": "string"}})
    call.execute()
    assert json.loads(call.result)["structuredContent"] == {"ok": True}


@pytest.mark.asyncio
async def test_agno_async_function_dispatch(server):
    tools = BaizhiTools(api_key=KEY)
    function = tools.get_async_functions()["websearch_search"]
    function.process_entrypoint()
    call = FunctionCall(function=function, arguments={"query": "MCP"})
    await call.aexecute()
    assert json.loads(call.result)["isError"] is False


@pytest.mark.parametrize(
    "method,args",
    [
        ("websearch_search", {"query": " "}),
        ("websearch_search", {"query": "MCP", "count": 51}),
        ("websearch_search", {"query": "MCP", "time_range": "invalid"}),
        ("web_scrape", {"url": "file:///etc/passwd"}),
        ("web_scrape", {"url": "https://example.com", "return_format": "html"}),
        ("web_extract", {"url": "https://example.com"}),
        ("web_extract", {"url": "https://example.com", "fields": {"title": "invalid"}}),
    ],
)
def test_invalid_arguments_never_make_billable_calls(server, method, args):
    requests, options, _ = server
    assert json.loads(getattr(BaizhiTools(api_key=KEY), method)(**args))["isError"]
    assert requests == options == []


def test_disabled_direct_method_never_connects(server):
    requests, options, _ = server
    tools = BaizhiTools(api_key=KEY, enable_search=False)
    assert json.loads(tools.websearch_search("MCP"))["isError"]
    assert requests == options == []


@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_http_failures_do_not_echo_key_or_retry(server, caplog, status):
    requests, options, state = server
    state["status"] = status
    result = BaizhiTools(api_key=KEY).websearch_search("MCP")
    assert json.loads(result)["isError"]
    assert KEY not in result + caplog.text
    assert len(options) == 1
    assert not [r for r in requests if r["method"] == "tools/call"]


def test_mcp_tool_error_and_structured_content_are_preserved_and_redacted(server):
    _, _, state = server
    state["result"] = {
        "isError": True,
        "content": [{"type": "text", "text": "denied " + KEY}],
        "structuredContent": {KEY: [KEY]},
    }
    result = BaizhiTools(api_key=KEY).websearch_search("MCP")
    assert json.loads(result)["isError"]
    assert KEY not in result
    assert "[REDACTED]" in result


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_cancellation_propagates(monkeypatch):
    class SlowSession:
        async def __aenter__(self):
            await asyncio.sleep(10)

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(baizhi.httpx2, "AsyncClient", lambda **kwargs: SlowSession())
    tools = BaizhiTools(api_key=KEY)
    tools.timeout = 0.01
    assert "timed out" in await tools.awebsearch_search("MCP")
    tools.timeout = 60
    task = asyncio.create_task(tools.awebsearch_search("MCP"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_sync_call_in_event_loop_does_not_create_unawaited_coroutine(monkeypatch):
    tools = BaizhiTools(api_key=KEY)
    call = AsyncMock()
    monkeypatch.setattr(tools, "awebsearch_search", call)
    assert "async" in tools.websearch_search("MCP")
    call.assert_not_called()


@pytest.fixture
def agent():
    from agno.agent import Agent
    from agno.models.base import Model
    from agno.models.response import ModelResponse

    class SearchModel(Model):
        """Local model double; the agent's real approval and tool loop still run."""

        def __init__(self):
            super().__init__(id="baizhi-local-test", name="local-test", provider="test")
            self.calls = 0

        def invoke(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "search-1",
                            "type": "function",
                            "function": {"name": "websearch_search", "arguments": '{"query":"MCP"}'},
                        }
                    ],
                )
            return ModelResponse(role="assistant", content="Finished.")

        async def ainvoke(self, *args, **kwargs):
            return self.invoke(*args, **kwargs)

        def invoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

        async def ainvoke_stream(self, *args, **kwargs):
            yield await self.ainvoke(*args, **kwargs)

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response):
            return response

    return Agent(
        model=SearchModel(),
        tools=[
            BaizhiTools(
                api_key=KEY, enable_scrape=False, enable_extract=False, requires_confirmation_tools=["websearch_search"]
            )
        ],
        tool_call_limit=1,
        telemetry=False,
    )


def test_real_sync_agent_requires_approval_before_sdk_call(server, agent):
    requests, _, _ = server
    response = agent.run("Search MCP")
    assert response.active_requirements
    assert requests == []
    for requirement in response.active_requirements:
        requirement.confirm()
    response = agent.continue_run(response, requirements=response.requirements)
    assert response.content == "Finished."
    assert len([r for r in requests if r["method"] == "tools/call"]) == 1


@pytest.mark.asyncio
async def test_real_async_agent_requires_approval_before_sdk_call(server, agent):
    requests, _, _ = server
    response = await agent.arun("Search MCP")
    assert response.active_requirements
    assert requests == []
    for requirement in response.active_requirements:
        requirement.confirm()
    response = await agent.acontinue_run(response, requirements=response.requirements)
    assert response.content == "Finished."
    assert len([r for r in requests if r["method"] == "tools/call"]) == 1


@pytest.mark.parametrize(
    "url", ["https://user:password@example.com", "http://user@example.com", "https://:password@example.com"]
)
def test_page_credentials_are_not_sent_to_service(server, url):
    requests, options, _ = server
    tools = BaizhiTools(api_key=KEY)
    assert json.loads(tools.web_scrape(url))["isError"]
    assert json.loads(tools.web_extract(url, instruction="title"))["isError"]
    assert requests == options == []


@pytest.mark.parametrize(
    "domain",
    [
        "https://example.com",
        "example.com/path",
        "user@example.com",
        "localhost",
        "example.com?q=x",
        "example.com#x",
        " example.com",
        "*.example.com",
        "example..com",
        "-example.com",
        "example.com:443",
    ],
)
@pytest.mark.parametrize("field", ["domains", "exclude_domains"])
def test_domain_filters_reject_non_bare_hosts_before_network(server, domain, field):
    requests, options, _ = server
    assert json.loads(BaizhiTools(api_key=KEY).websearch_search("MCP", **{field: [domain]}))["isError"]
    assert requests == options == []


@pytest.mark.parametrize("domain", ["example.com", "docs.example.com", "127.0.0.1", "::1", "xn--fsqu00a.xn--0zwm56d"])
def test_valid_bare_domains_and_ips(domain):
    assert BaizhiTools._valid_domain(domain)


@pytest.mark.parametrize("status,location", [(307, "/redirected"), (308, "https://unrelated.example/mcp")])
def test_sdk_redirects_cannot_override_fixed_endpoint(server, status, location):
    _, _, state = server
    state["status"] = status
    state["location"] = location
    assert json.loads(BaizhiTools(api_key=KEY).websearch_search("MCP"))["isError"]
    assert state["urls"] == ["https://agent-toolkit.app.baizhi.cloud/mcp"]


@pytest.mark.parametrize("response_format", ["json", "sse"])
def test_malformed_responses_cannot_echo_key_in_sdk_error_logs(server, caplog, response_format):
    requests, options, state = server
    state["malformed"] = response_format
    caplog.set_level(logging.ERROR)
    result = BaizhiTools(api_key=KEY).websearch_search("MCP")
    assert json.loads(result)["isError"]
    assert "Error parsing" in caplog.text
    assert KEY not in result + caplog.text
    assert len(options) == 1
    assert len([r for r in requests if r["method"] == "tools/call"]) == 1
    assert baizhi._ACTIVE_KEY.get() is None


@pytest.mark.asyncio
async def test_sdk_log_filter_is_scoped_to_call_and_resets_on_cancellation(monkeypatch, caplog):
    entered = asyncio.Event()
    logger = logging.getLogger("mcp.client.streamable_http")
    caplog.set_level(logging.ERROR)

    class WaitingClient:
        async def __aenter__(self):
            try:
                raise ValueError(KEY)
            except ValueError:
                logger.exception("call diagnostic: %s", KEY)
            entered.set()
            await asyncio.sleep(10)

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(baizhi.httpx2, "AsyncClient", lambda **kwargs: WaitingClient())
    task = asyncio.create_task(BaizhiTools(api_key=KEY).awebsearch_search("MCP"))
    await entered.wait()
    inside = caplog.records[-1]
    assert KEY not in inside.getMessage()
    assert inside.exc_info is None
    # The parent task has no Baizhi call context, even while the call is active.
    assert baizhi._ACTIVE_KEY.get() is None
    try:
        raise ValueError("unrelated diagnostic")
    except ValueError:
        logger.exception("outside call: %s", KEY)
    outside = caplog.records[-1]
    assert outside.args == (KEY,)
    assert outside.exc_info is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert baizhi._ACTIVE_KEY.get() is None


def test_successful_call_leaves_sdk_logging_unchanged(server, caplog):
    assert not json.loads(BaizhiTools(api_key=KEY).websearch_search("MCP"))["isError"]
    assert baizhi._ACTIVE_KEY.get() is None
    logger = logging.getLogger("mcp.client.streamable_http")
    caplog.set_level(logging.ERROR)
    logger.error("unrelated message: %s", KEY)
    assert caplog.records[-1].args == (KEY,)
    assert KEY in caplog.records[-1].getMessage()
