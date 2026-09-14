import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS, MCPConfig
from agno.os.config import AuthorizationConfig
from agno.os.public import PublicSurface
from agno.os.public._limits import Admission

HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
KEY = "mcp-routing-regression-signing-key"


def echo(value: str) -> str:
    return value


class Limiter:
    ready = True
    allowed = True
    calls = 0

    async def aconsume(self, bucket, *, client_id):
        self.calls += 1
        assert bucket == "mcp"
        return Admission(self.allowed, retry_after=60)


@asynccontextmanager
async def client(*, host="mcp.example.com", mounted=False, **options):
    surface = PublicSurface(mcp=True)
    limiter = Limiter()
    surface._limiter = limiter
    server = AgentOS(
        id="mcp-routing",
        agents=[Agent(id="docs", telemetry=False)],
        db=PostgresDb(db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused"),
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[KEY], algorithm="HS256"),
        public=surface,
        mcp=MCPConfig(tools=[echo], default_tools=False, stateless=True, root_host="mcp.example.com", **options),
        auto_provision_dbs=False,
        telemetry=False,
    )
    app = server.get_app()
    if mounted:
        parent = FastAPI()
        parent.mount("/runtime", app)
        app = parent
    async with server._mcp_app.lifespan(server._mcp_app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=f"https://{host}") as http:
            yield http, limiter


def result(response):
    assert response.status_code == 200, response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
    return response.json()


@pytest.mark.parametrize("mounted", [False, True])
@pytest.mark.parametrize("path", ["/", "/mcp", "/mcp/"])
async def test_root_native_and_mounted_transport_share_catalog_and_limits(mounted, path):
    async with client(mounted=mounted) as (http, limiter):
        prefix = "/runtime" if mounted else ""
        initialized = result(
            await http.post(
                prefix + path,
                headers=HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
        )
        assert "serverInfo" in initialized["result"]
        tools = result(
            await http.post(prefix + path, headers=HEADERS, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        )
        assert [t["name"] for t in tools["result"]["tools"]] == ["echo"]
        assert limiter.calls == 2
        limiter.allowed = False
        denied = await http.post(
            prefix + path, headers=HEADERS, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
        )
        assert denied.status_code == 429
        assert (await http.get(prefix + "/config")).status_code == 401
        assert (await http.get(prefix + "/health")).status_code == 200


@pytest.mark.parametrize("mounted", [False, True])
async def test_card_and_browser_redirect_use_public_path(mounted):
    async with client(mounted=mounted) as (http, _):
        prefix = "/runtime" if mounted else ""
        browser = await http.get(prefix + "/", headers={"Accept": "text/html"})
        assert browser.status_code == 302
        assert browser.headers["location"] == prefix + "/server-card"
        card = await http.get(browser.headers["location"])
        assert card.status_code == 200, card.text
        assert card.json()["remotes"] == [{"type": "streamable-http", "url": "https://mcp.example.com" + prefix + "/"}]
        protocol = await http.get(prefix + "/", headers={"Accept": "text/event-stream"})
        assert protocol.status_code != 302 and "location" not in protocol.headers


async def test_custom_path_requires_explicit_legacy_alias():
    async with client(host="localhost", path="/api/rpc") as (http, _):
        assert (await http.get("/mcp")).status_code == 404
        response = await http.get("/api/rpc")
        assert response.headers["location"] == "/api/rpc/server-card"
        card = await http.get(response.headers["location"])
        assert card.json()["remotes"][0]["url"] == "https://localhost/api/rpc"
    async with client(host="localhost", path="/api/rpc", path_aliases=["/mcp"]) as (http, _):
        response = await http.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert "tools" in result(response)["result"]


async def test_unknown_and_duplicate_hosts_and_forwarding_headers():
    async with client() as (http, _):
        assert (await http.get("/", headers=[("host", "mcp.example.com"), ("host", "evil.example")])).status_code == 400
        assert (await http.get("/mcp", headers={"host": "evil.example"})).status_code == 400
        response = await http.get("/", headers={"host": "localhost", "x-forwarded-host": "mcp.example.com"})
        assert response.status_code == 200 and "location" not in response.headers
        response = await http.get(
            "/server-card", headers={"host": "mcp.example.com", "x-forwarded-host": "evil.example"}
        )
        assert response.json()["remotes"][0]["url"] == "https://mcp.example.com/"


@pytest.mark.parametrize(
    "options",
    [
        {"path": "/"},
        {"path": "/../mcp"},
        {"path": "/mcp/"},
        {"path_aliases": ["/mcp"]},
        {"root_host": "https://mcp.example.com"},
        {"root_host": "*.example.com"},
    ],
)
def test_invalid_configuration(options):
    with pytest.raises(ValueError):
        MCPConfig(**options)


def test_transport_cannot_hide_rest_routes():
    server = AgentOS(agents=[Agent(id="docs", telemetry=False)], mcp=MCPConfig(path="/health"), telemetry=False)
    with pytest.raises(ValueError, match="conflicts"):
        server.get_app()


@pytest.mark.parametrize("host", ["MCP.EXAMPLE.COM", "mcp.example.com:443"])
async def test_root_hostname_is_case_insensitive_and_accepts_port(host):
    async with client() as (http, _):
        response = await http.get("/", headers={"host": host})
        assert response.status_code == 302
        assert response.headers["location"] == "/server-card"


async def test_malformed_host_cannot_select_root():
    async with client() as (http, _):
        for host in ("mcp.example.com:invalid", "mcp.example.com,evil.example", "mcp.example.com@evil.example"):
            assert (await http.get("/", headers={"host": host})).status_code == 400


async def test_configured_canonical_url_is_preserved():
    async with client(server_card_url="https://mcp.example.com") as (http, _):
        card = await http.get("/server-card")
        assert card.json()["remotes"][0]["url"] == "https://mcp.example.com"


def test_custom_oauth_routing_fails_before_serving_incorrect_metadata():
    from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider

    server = AgentOS(
        agents=[Agent(id="docs", telemetry=False)],
        mcp=MCPConfig(root_host="mcp.example.com"),
        mcp_auth=InMemoryOAuthProvider(base_url="https://mcp.example.com"),
        telemetry=False,
    )
    with pytest.raises(ValueError, match="OAuth resource discovery"):
        server.get_app()


@pytest.mark.parametrize("prefix,path,conflict", [("/prefix", "/prefix/rpc", True), ("/prefix", "/rpc", False)])
def test_route_conflicts_respect_included_router_prefixes(prefix, path, conflict):
    from fastapi import APIRouter

    base = FastAPI()
    router = APIRouter()

    @router.post("/rpc")
    def other_service():
        return {}

    base.include_router(router, prefix=prefix)
    server = AgentOS(
        agents=[Agent(id="docs", telemetry=False)], base_app=base, mcp=MCPConfig(path=path), telemetry=False
    )
    if conflict:
        with pytest.raises(ValueError, match="conflicts"):
            server.get_app()
    else:
        server.get_app()
