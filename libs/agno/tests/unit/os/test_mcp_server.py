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

from fastmcp import Client  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.mcp import _resolve_user_id, build_mcp_server  # noqa: E402
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


async def test_disabling_builtins_with_no_custom_tools_yields_empty_server():
    os = AgentOS(agents=[_agent()], enable_mcp_server=True, mcp_config=MCPServerConfig(enable_builtin_tools=False))
    assert await _tool_names(os) == set()


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
