"""Unit tests for the AgentOS MCP server.

Covers the three things added/fixed for the MCP server:
  1. Custom tools can be registered and called over the MCP server.
  2. The built-in tools can be disabled or scoped by tag, leaving only what you want.
  3. ``run_agent`` / ``run_team`` / ``run_workflow`` thread the caller's identity into ``arun``.

The FastMCP tool surface is exercised directly with an in-memory client, without the
HTTP/JWT transport layer (that path is covered by the system tests in tests/system).
"""

import pytest

pytest.importorskip("fastmcp")

from contextlib import asynccontextmanager  # noqa: E402
from typing import Optional  # noqa: E402

import httpx  # noqa: E402
from fastmcp import Client, Context  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.mcp import _resolve_user_id, build_mcp_server, get_mcp_server  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.run.workflow import WorkflowRunOutput  # noqa: E402
from agno.team.team import Team  # noqa: E402
from agno.tools import tool  # noqa: E402
from agno.workflow.step import Step  # noqa: E402
from agno.workflow.workflow import Workflow  # noqa: E402

# The full set of built-in tools, keyed by their tag group.
CORE_TOOLS = {"get_agentos_config", "run_agent", "run_team", "run_workflow"}
SESSION_TOOLS = {
    "get_sessions",
    "get_session",
    "create_session",
    "get_session_runs",
    "get_session_run",
    "rename_session",
    "update_session",
    "delete_session",
    "delete_sessions",
}
MEMORY_TOOLS = {"create_memory", "get_memory", "get_memories", "update_memory", "delete_memory", "delete_memories"}
ALL_BUILTIN_TOOLS = CORE_TOOLS | SESSION_TOOLS | MEMORY_TOOLS


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


async def _tool_names(os: AgentOS) -> set:
    async with Client(build_mcp_server(os)) as client:
        return {t.name for t in await client.list_tools()}


async def _call_tool(os: AgentOS, name: str, args: dict):
    async with Client(build_mcp_server(os)) as client:
        return await client.call_tool(name, args)


def _stub_arun(component, run_output):
    """Replace ``component.arun`` with a stub that records the identity kwargs it was called with."""
    captured: dict = {}

    async def fake_arun(message, **kwargs):
        captured["message"] = message
        captured["user_id"] = kwargs.get("user_id")
        captured["session_id"] = kwargs.get("session_id")
        return run_output

    component.arun = fake_arun  # type: ignore[method-assign]
    return captured


# ==================== Custom tools ====================


async def test_custom_plain_callable_is_registered_and_callable():
    """A plain function is registered as an MCP tool and is callable over the server."""

    def reverse_text(text: str) -> str:
        """Reverse the given text."""
        return text[::-1]

    os = AgentOS(agents=[_agent()], enable_mcp_server=True, mcp_config=MCPServerConfig(tools=[reverse_text]))

    assert "reverse_text" in await _tool_names(os)
    result = await _call_tool(os, "reverse_text", {"text": "abc"})
    assert result.data == "cba"


async def test_custom_agno_tool_is_registered_with_its_name():
    """An Agno @tool callable is registered using its declared name/description and is callable."""

    @tool(name="lookup_widget", description="Look up a widget by id")
    def lookup_widget(widget_id: str) -> str:
        """Return a widget summary."""
        return f"widget:{widget_id}"

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[lookup_widget], enable_builtin_tools=False),
    )

    assert await _tool_names(os) == {"lookup_widget"}
    result = await _call_tool(os, "lookup_widget", {"widget_id": "42"})
    assert result.data == "widget:42"


async def test_unregisterable_custom_tool_raises():
    """A non-callable custom tool fails loudly rather than being silently dropped."""
    with pytest.raises(TypeError):
        build_mcp_server(
            AgentOS(agents=[_agent()], enable_mcp_server=True, mcp_config=MCPServerConfig(tools=[object()]))
        )


# ==================== Scoping the built-ins ====================


async def test_default_registers_all_builtin_tools():
    """With no mcp_config, every built-in tool is registered (unchanged behavior)."""
    os = AgentOS(agents=[_agent()], enable_mcp_server=True)
    assert await _tool_names(os) == ALL_BUILTIN_TOOLS


async def test_disabling_builtins_yields_only_custom_tools():
    """enable_builtin_tools=False ships ONLY the custom tools (the @context 'one tool' shape)."""

    def ping() -> str:
        """Return pong."""
        return "pong"

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[ping], enable_builtin_tools=False),
    )
    assert await _tool_names(os) == {"ping"}


def test_disabling_builtins_with_no_custom_tools_is_rejected_at_construction():
    """A config that would mount /mcp with zero tools fails fast with an actionable error.

    Almost always a typo (user disabled built-ins meaning to ship their own and forgot
    ``tools=[...]``); we'd rather surface that at config-construction than boot a server
    that happily lists no tools.
    """
    with pytest.raises(ValueError, match="zero tools"):
        MCPServerConfig(enable_builtin_tools=False)


async def test_include_tags_scopes_builtins_to_core():
    os = AgentOS(agents=[_agent()], enable_mcp_server=True, mcp_config=MCPServerConfig(include_tags={"core"}))
    assert await _tool_names(os) == CORE_TOOLS


async def test_exclude_tags_drops_memory_builtins():
    os = AgentOS(agents=[_agent()], enable_mcp_server=True, mcp_config=MCPServerConfig(exclude_tags={"memory"}))
    names = await _tool_names(os)
    assert names == CORE_TOOLS | SESSION_TOOLS
    assert not (names & MEMORY_TOOLS)


async def test_custom_tools_coexist_with_scoped_builtins():
    """Custom tools register alongside a scoped subset of the built-ins."""

    def ping() -> str:
        """Return pong."""
        return "pong"

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[ping], include_tags={"core"}),
    )
    assert await _tool_names(os) == CORE_TOOLS | {"ping"}


# ==================== Identity threading ====================


def test_resolve_user_id_binds_to_jwt_subject(monkeypatch):
    """_resolve_user_id returns the caller arg with no request, and the JWT subject with one."""
    import fastmcp.server.dependencies as deps

    class _State:
        user_id = "jwt-subject-1"

    class _Req:
        state = _State()

    # No HTTP request in flight -> the caller-provided value is returned unchanged.
    assert _resolve_user_id("caller") == "caller"
    assert _resolve_user_id(None) is None

    # An authenticated request -> the JWT subject wins over whatever the caller passed.
    monkeypatch.setattr(deps, "get_http_request", lambda: _Req())
    assert _resolve_user_id(None) == "jwt-subject-1"
    assert _resolve_user_id("caller") == "jwt-subject-1"


async def test_run_agent_threads_resolved_identity(monkeypatch):
    """run_agent passes the resolved user_id (and the caller's session_id) into agent.arun."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-alice")

    agent = _agent()
    captured = _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    await _call_tool(os, "run_agent", {"agent_id": agent.id, "message": "hi", "session_id": "s-1"})

    assert captured["message"] == "hi"
    assert captured["user_id"] == "jwt-alice"
    assert captured["session_id"] == "s-1"


async def test_run_team_threads_resolved_identity(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-alice")

    team = Team(id="demo-team", name="Demo Team", members=[_agent()])
    captured = _stub_arun(team, TeamRunOutput(content="ok"))
    os = AgentOS(teams=[team], enable_mcp_server=True)

    await _call_tool(os, "run_team", {"team_id": team.id, "message": "hi", "session_id": "s-2"})

    assert captured["user_id"] == "jwt-alice"
    assert captured["session_id"] == "s-2"


async def test_run_workflow_threads_resolved_identity(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-alice")

    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    captured = _stub_arun(workflow, WorkflowRunOutput(content="ok"))
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    await _call_tool(os, "run_workflow", {"workflow_id": workflow.id, "message": "hi", "session_id": "s-3"})

    assert captured["user_id"] == "jwt-alice"
    assert captured["session_id"] == "s-3"


# ==================== Identity in custom tools ====================


async def test_custom_tool_user_id_is_injected_and_hidden(monkeypatch):
    """A custom tool that declares user_id gets the resolved subject, and clients can't see/set it."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-owner")

    async def ask(message: str, user_id: Optional[str] = None) -> str:
        return f"{message}:{user_id}"

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[ask], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        schema = {t.name: t for t in await client.list_tools()}["ask"].inputSchema
        props = schema.get("properties", {})
        assert "message" in props
        assert "user_id" not in props  # hidden from the client-facing schema
        result = await client.call_tool("ask", {"message": "hi"})

    assert result.data == "hi:jwt-owner"  # injected server-side


async def test_custom_tool_without_user_id_is_unchanged():
    """A tool that does not declare user_id is registered as-is (no injection)."""

    def echo(text: str) -> str:
        """Echo the text."""
        return text

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[echo], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        props = {t.name: t for t in await client.list_tools()}["echo"].inputSchema.get("properties", {})
        assert set(props) == {"text"}
        result = await client.call_tool("echo", {"text": "abc"})

    assert result.data == "abc"


async def test_custom_tool_can_use_native_ctx():
    """A custom tool can declare a FastMCP Context param; it is injected and hidden from clients."""

    async def whoami(ctx: Context) -> str:
        return f"ctx:{type(ctx).__name__}"

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[whoami], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        props = {t.name: t for t in await client.list_tools()}["whoami"].inputSchema.get("properties", {})
        assert "ctx" not in props
        result = await client.call_tool("whoami", {})

    assert result.data == "ctx:Context"


# ==================== Gating + middleware (HTTP layer) ====================

# A minimal MCP initialize request — enough to reach (or be blocked before) the MCP machinery.
_MCP_INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


async def _ok_tool(message: str) -> str:
    return message


@asynccontextmanager
async def _mcp_http_client(os: AgentOS):
    """Drive the full MCP HTTP app (JWT / authorize / middleware layers included)."""
    app = get_mcp_server(os)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_authorize_gate_rejects_unauthorized_caller():
    """The authorize predicate 401s a non-authorized caller before the MCP machinery runs."""
    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(
            tools=[_ok_tool],
            enable_builtin_tools=False,
            authorize=lambda user_id: user_id == "owner",  # no JWT here -> user_id is None -> rejected
        ),
    )
    async with _mcp_http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)

    assert response.status_code == 401
    assert "unauthorized" in response.text.lower()


async def test_authorize_gate_allows_authorized_caller():
    """An allow-all authorize predicate lets the request through to the MCP machinery."""
    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False, authorize=lambda user_id: True),
    )
    async with _mcp_http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)

    assert response.status_code == 200


async def test_custom_middleware_passthrough_runs():
    """App-provided middleware is added to the MCP app and runs on every request."""

    class HeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            response.headers["X-Passthrough"] = "1"
            return response

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(
            tools=[_ok_tool],
            enable_builtin_tools=False,
            middleware=[Middleware(HeaderMiddleware)],
        ),
    )
    async with _mcp_http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)

    assert response.headers.get("X-Passthrough") == "1"


# ==================== Built-in transport security (DNS-rebinding) ====================


def _headers(host: Optional[str] = None, origin: Optional[str] = None) -> dict:
    headers = dict(_MCP_HEADERS)
    if host is not None:
        headers["Host"] = host
    if origin is not None:
        headers["Origin"] = origin
    return headers


def _security_os(**kwargs) -> AgentOS:
    return AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False, **kwargs),
    )


async def test_transport_security_allows_localhost_by_default():
    """With allowed_hosts set (even to []), localhost is allowed out of the box."""
    async with _mcp_http_client(_security_os(allowed_hosts=[])) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_headers(host="localhost:7777"))
    assert response.status_code == 200


async def test_transport_security_rejects_unknown_host():
    """A rebound / unknown Host is rejected with 400 before the MCP machinery runs."""
    async with _mcp_http_client(_security_os(allowed_hosts=[])) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_headers(host="evil.example.com"))
    assert response.status_code == 400
    assert "invalid_host" in response.text


async def test_transport_security_allows_configured_deploy_host():
    """The configured deploy host is allowed alongside the localhost defaults."""
    async with _mcp_http_client(_security_os(allowed_hosts=["myapp.com"])) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_headers(host="myapp.com"))
    assert response.status_code == 200


async def test_transport_security_rejects_unknown_origin():
    """A present-but-unknown Origin is rejected even when the Host is allowed."""
    async with _mcp_http_client(_security_os(allowed_hosts=[])) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers=_headers(host="localhost", origin="http://evil.example.com")
        )
    assert response.status_code == 400
    assert "invalid_origin" in response.text


async def test_no_transport_security_when_unset():
    """Without allowed_hosts, no host validation is added (unchanged behavior)."""
    async with _mcp_http_client(_security_os()) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_headers(host="anything.example.com"))
    assert response.status_code == 200
