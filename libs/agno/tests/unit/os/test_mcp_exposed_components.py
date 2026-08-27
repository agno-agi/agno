"""Unit tests for exposing agents/teams/workflows as individual MCP tools.

Covers the ``MCPConfig.agents/teams/workflows`` exposure surface and the API rename set
(``mcp=`` / ``MCPConfig`` / ``default_tools``):
  1. Exposed components register as tools named after their ids and run through the
     same machinery as the generic run tools (identity, session minting, scopes).
  2. Collisions and non-roster components fail fast at build.
  3. The deprecated spellings (``mcp_server=``, ``MCPServerConfig``,
     ``enable_builtin_tools``) keep working via silent aliases.

The FastMCP tool surface is exercised directly with an in-memory client, without the
HTTP/JWT transport layer, matching test_mcp_server.py.
"""

import pytest

pytest.importorskip("fastmcp")

from types import SimpleNamespace  # noqa: E402
from typing import Optional  # noqa: E402

from fastmcp import Client  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS, MCPConfig, MCPServerConfig  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.run.workflow import WorkflowRunOutput  # noqa: E402
from agno.team.team import Team  # noqa: E402
from agno.workflow.step import Step  # noqa: E402
from agno.workflow.workflow import Workflow  # noqa: E402


def _agent(id: str = "chief", name: str = "Chief", description: Optional[str] = None) -> Agent:
    return Agent(id=id, name=name, description=description)


def _team(id: str = "support-team") -> Team:
    return Team(id=id, name="Support Team", members=[_agent(id=f"{id}-member")])


def _workflow(id: str = "daily-brief") -> Workflow:
    return Workflow(id=id, name="Daily Brief", steps=[Step(agent=_agent(id=f"{id}-step-agent"))])


async def _tool_names(os: AgentOS) -> set:
    async with Client(build_mcp_server(os)) as client:
        return {t.name for t in await client.list_tools()}


async def _call_tool(os: AgentOS, name: str, args: dict, raise_on_error: bool = True):
    async with Client(build_mcp_server(os)) as client:
        return await client.call_tool(name, args, raise_on_error=raise_on_error)


def _stub_arun(component, run_output):
    """Replace ``component.arun`` with a streaming stub that records identity kwargs.

    Mirrors test_mcp_server.py: the run tools consume ``arun`` as a stream, so the stub
    is an async generator whose last item is the final run output. ``captured`` keeps
    one entry per call so multi-call session assertions can compare them.
    """
    calls: list = []

    async def fake_arun(message, **kwargs):
        calls.append({"message": message, "user_id": kwargs.get("user_id"), "session_id": kwargs.get("session_id")})
        if kwargs.get("yield_run_output") or isinstance(run_output, WorkflowRunOutput):
            yield run_output

    component.arun = fake_arun  # type: ignore[method-assign]
    return calls


@pytest.fixture(autouse=True)
def _resolve_by_identity(monkeypatch):
    """Resolve run tools to the in-memory (stubbed) component instance.

    Production ``_resolve_run_component`` deep-copies (create_fresh) and consults the DB
    registry, which would discard the ``.arun`` stub these tests set on the instance.
    The real resolution behaviour is covered by test_mcp_resolution.py.
    """

    async def _resolve(os, kind, component_id, *, user_id, session_id, strict=True, version=None, published_only=True):
        pool = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}.get(kind) or []
        for component in pool:
            if getattr(component, "id", None) == component_id:
                return component
        singular = {"agents": "Agent", "teams": "Team", "workflows": "Workflow"}[kind]
        raise Exception(f"{singular} {component_id} not found")

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)


def _patch_request(monkeypatch, request):
    import fastmcp.server.dependencies as fastmcp_deps

    monkeypatch.setattr(fastmcp_deps, "get_http_request", lambda: request)


def _pat_request(scopes, name="bot"):
    return SimpleNamespace(
        state=SimpleNamespace(
            authenticated=True,
            user_id="sa:" + name,
            session_id=None,
            scopes=list(scopes),
            authorization_enabled=True,
            service_account_name=name,
        ),
        scope={},
    )


# ==================== Exposure surface ====================


async def test_exposed_agent_is_the_only_tool_with_default_tools_off():
    """default_tools=False + agents=[chief] serves exactly one tool named after the id."""
    agent = _agent()
    calls = _stub_arun(agent, RunOutput(content="done", status=RunStatus.completed))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    assert await _tool_names(os) == {"chief"}
    result = await _call_tool(os, "chief", {"message": "hi"})
    assert calls[0]["message"] == "hi"
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("status") == RunStatus.completed.value


async def test_exposed_team_and_workflow_register_and_run():
    """Teams and workflows expose the same way, via instances or id strings."""
    team = _team()
    workflow = _workflow()
    team_calls = _stub_arun(team, TeamRunOutput(content="team done"))
    wf_calls = _stub_arun(workflow, WorkflowRunOutput(content="wf done"))
    os = AgentOS(
        teams=[team],
        workflows=[workflow],
        mcp=MCPConfig(default_tools=False, teams=[team], workflows=["daily-brief"]),
    )

    assert await _tool_names(os) == {"support-team", "daily-brief"}
    await _call_tool(os, "support-team", {"message": "help"})
    await _call_tool(os, "daily-brief", {"message": "go"})
    assert team_calls[0]["message"] == "help"
    assert wf_calls[0]["message"] == "go"


async def test_exposure_composes_with_default_tools_and_custom_tools():
    """default_tools=True + exposure + custom tools serve side by side."""

    def ping() -> str:
        """Return pong."""
        return "pong"

    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(agents=[agent], tools=[ping]))

    names = await _tool_names(os)
    assert "chief" in names
    assert "ping" in names
    assert set(mcp_mod._BUILTIN_TOOL_NAMES) <= names


async def test_exposed_tool_description_carries_component_description():
    """The tool description is the component's own plus the fixed session sentence."""
    agent = _agent(description="Handles executive requests")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.description is not None
    assert tool.description.startswith("Handles executive requests.")
    assert "session_id" in tool.description


async def test_exposed_tool_schema_shows_only_client_facing_params():
    """The client-facing schema is message/user_id/session_id; ctx is injected, hidden."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert set(tool.inputSchema.get("properties", {})) == {"message", "user_id", "session_id"}
    assert tool.inputSchema.get("required") == ["message"]


async def test_exposed_tool_name_is_sanitized():
    """An id outside the MCP tool-name charset folds to hyphens; valid ids pass verbatim."""
    agent = _agent(id="chief agent (v2)")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))
    assert await _tool_names(os) == {"chief-agent-v2"}


# ==================== Session + identity contract ====================


async def test_exposed_agent_mints_distinct_sessions_and_honours_explicit():
    """Omitted session_id mints a fresh one per call; an explicit one is reused."""
    agent = _agent()
    calls = _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("chief", {"message": "one"})
        await client.call_tool("chief", {"message": "two"})
        await client.call_tool("chief", {"message": "three", "session_id": "fixed-1"})

    minted = [c["session_id"] for c in calls[:2]]
    assert all(minted) and minted[0] != minted[1]
    assert calls[2]["session_id"] == "fixed-1"


async def test_exposed_agent_threads_resolved_identity(monkeypatch):
    """The JWT subject wins over a caller-passed user_id, as on the generic run tools."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-alice")
    agent = _agent()
    calls = _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    await _call_tool(os, "chief", {"message": "hi", "user_id": "spoofed", "session_id": "s-1"})
    assert calls[0]["user_id"] == "jwt-alice"
    assert calls[0]["session_id"] == "s-1"


async def test_exposed_agent_enforces_run_scopes(monkeypatch):
    """A sessions:read-only PAT is denied on the named tool exactly as on run_agent."""
    _patch_request(monkeypatch, _pat_request(["sessions:read"]))
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"}, raise_on_error=False)
    assert result.is_error
    assert "Insufficient permissions" in str(result.content)
    assert "agents:run" in str(result.content)


async def test_exposed_agent_allows_matching_scope(monkeypatch):
    """agents:run passes the gate and the tool proceeds to the run."""
    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    agent = _agent()
    _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"}, raise_on_error=False)
    assert not result.is_error


async def test_exposed_agent_surfaces_paused_runs():
    """A PAUSED (HITL) run comes back with its status visible, not swallowed."""
    agent = _agent()
    _stub_arun(agent, RunOutput(run_id="r-1", session_id="s-1", content=None, status=RunStatus.paused))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("status") == RunStatus.paused.value


# ==================== Build-time validation ====================


async def test_exposed_id_colliding_with_default_tool_raises():
    """An exposed component whose tool name matches a default tool is a hard build error."""
    agent = _agent(id="run_agent")
    os = AgentOS(agents=[agent], mcp=MCPConfig(agents=[agent]))
    with pytest.raises(ValueError, match='"run_agent"'):
        build_mcp_server(os)


async def test_colliding_default_tool_name_is_fine_when_builtins_off():
    """The same id is fine when the default tools are off -- the name is free."""
    agent = _agent(id="run_agent")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent]))
    assert await _tool_names(os) == {"run_agent"}


def test_exposed_id_colliding_with_custom_tool_raises():
    def chief() -> str:
        """Custom chief."""
        return "custom"

    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, agents=[agent], tools=[chief]))
    with pytest.raises(ValueError, match='custom tool "chief"'):
        build_mcp_server(os)


def test_exposing_two_components_with_same_tool_name_raises():
    a1 = _agent(id="chief agent")
    a2 = _agent(id="chief-agent")
    os = AgentOS(agents=[a1, a2], mcp=MCPConfig(default_tools=False, agents=[a1, a2]))
    with pytest.raises(ValueError, match='"chief-agent"'):
        build_mcp_server(os)


def test_exposing_non_roster_instance_raises():
    roster_agent = _agent()
    outsider = _agent(id="outsider", name="Outsider")
    os = AgentOS(agents=[roster_agent], mcp=MCPConfig(default_tools=False, agents=[outsider]))
    with pytest.raises(ValueError, match="not part of the AgentOS roster"):
        build_mcp_server(os)


def test_exposing_unknown_id_string_raises():
    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, agents=["ghost"]))
    with pytest.raises(ValueError, match="'ghost'"):
        build_mcp_server(os)


def test_zero_tools_validator_accepts_exposure_and_still_rejects_empty():
    MCPConfig(default_tools=False, agents=[_agent()])
    with pytest.raises(ValueError, match="zero tools"):
        MCPConfig(default_tools=False)


async def test_builtin_tool_name_map_matches_registered_tools():
    """_BUILTIN_TOOL_NAMES (used for collision checks) mirrors what a default server
    actually registers -- catches a new default tool missing from the map."""
    os = AgentOS(agents=[_agent()], mcp=True)
    assert await _tool_names(os) == set(mcp_mod._BUILTIN_TOOL_NAMES)


# ==================== Rename aliases ====================


def test_mcp_server_config_is_mcp_config():
    assert MCPServerConfig is MCPConfig


def test_enable_builtin_tools_maps_to_default_tools():
    config = MCPConfig(enable_builtin_tools=False, tools=[lambda: "x"])
    assert config.default_tools is False
    assert config.enable_builtin_tools is False


def test_conflicting_default_tools_spellings_raise():
    with pytest.raises(ValueError, match="deprecated alias"):
        MCPConfig(default_tools=True, enable_builtin_tools=False)


def test_enable_builtin_tools_alias_does_not_mutate_caller_dict():
    data = {"enable_builtin_tools": False, "tools": [lambda: "x"]}
    MCPConfig.model_validate(data)
    assert "enable_builtin_tools" in data


def test_agentos_mcp_server_kwarg_still_works():
    os = AgentOS(agents=[_agent()], mcp_server=True)
    assert os.mcp is True
    assert os.mcp_server is True


def test_agentos_conflicting_mcp_spellings_raise():
    with pytest.raises(ValueError, match="deprecated alias"):
        AgentOS(agents=[_agent()], mcp=False, mcp_server=True)


def test_agentos_equal_mcp_spellings_are_accepted():
    os = AgentOS(agents=[_agent()], mcp=True, mcp_server=True)
    assert os.mcp is True


def test_assigning_config_to_mcp_property_applies_config():
    os = AgentOS(agents=[_agent()])
    assert os.mcp is False
    config = MCPConfig(tools=[lambda: "x"])
    os.mcp = config
    assert os.mcp is True
    assert os.mcp_config is config


def test_assigning_via_deprecated_mcp_server_property_applies_config():
    os = AgentOS(agents=[_agent()])
    config = MCPConfig(tools=[lambda: "x"])
    os.mcp_server = config
    assert os.mcp is True
    assert os.mcp_config is config
