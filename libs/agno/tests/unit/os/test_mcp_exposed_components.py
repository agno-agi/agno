"""Unit tests for exposing agents/teams/workflows as individual MCP tools.

Covers the ``MCPConfig.tools`` exposure surface (bare components and
``component.as_tool(name=..., description=...)`` markers) and the API rename set
(``mcp=`` / ``MCPConfig`` / ``default_tools``):
  1. Exposed components register as tools -- named after their ids, or the as_tool
     override -- and run through the same machinery as the generic run tools
     (identity, session minting, scopes).
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
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

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
        mcp=MCPConfig(default_tools=False, tools=[team, workflow]),
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
    os = AgentOS(agents=[agent], mcp=MCPConfig(tools=[agent, ping]))

    names = await _tool_names(os)
    assert "chief" in names
    assert "ping" in names
    assert set(mcp_mod._BUILTIN_TOOL_NAMES) <= names


async def test_exposed_tool_description_carries_component_description():
    """The tool description is the component's own plus the fixed session sentence."""
    agent = _agent(description="Handles executive requests")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.description is not None
    assert tool.description.startswith("Handles executive requests.")
    assert "session_id" in tool.description


async def test_exposed_tool_schema_shows_only_client_facing_params():
    """The client-facing schema is message/user_id/session_id; ctx is injected, hidden."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert set(tool.inputSchema.get("properties", {})) == {"message", "user_id", "session_id"}
    assert tool.inputSchema.get("required") == ["message"]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.openWorldHint is True


async def test_exposed_tool_description_fallback_without_component_description():
    """A component without a description gets the documented fallback plus the fixed sentence."""
    agent = _agent()  # name "Chief", no description
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.description == (
        "Run the Chief agent with a message. "
        "Pass the returned session_id back to continue the conversation; omit it to start a new one."
    )


def test_exposed_id_outside_tool_name_charset_raises_with_candidate():
    """Ids are never sanitized into a different-looking tool name: the id doubles as the
    continue_run handle and the per-resource scope segment, so a mismatch would break
    HITL resume and make the visible name disagree with the scope that grants it. The
    error suggests a clean candidate id without applying it."""
    agent = _agent(id="chief agent (v2)")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError, match="set id='chief-agent-v2'"):
        build_mcp_server(os)


def test_exposed_id_with_trailing_newline_raises():
    """fullmatch, not match: a trailing newline must not slip through as 'already valid'."""
    agent = _agent(id="chief\n")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError, match="letters"):
        build_mcp_server(os)


def test_exposed_id_with_slash_raises():
    """A slash in the id would take the synthetic scope route out of single-segment
    shape, so it is rejected with the rest of the charset."""
    agent = _agent(id="support/admin")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError, match="letters"):
        build_mcp_server(os)


def test_auto_derived_id_error_names_the_source_and_suggests_cleanly():
    """The user typed name=..., not the derived id -- the error must say where the id
    came from, and the candidate must collapse the hyphen-flanked fold (never
    'research---writing-team')."""
    agent = Agent(name="Research & Writing Team")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError) as exc_info:
        build_mcp_server(os)
    message = str(exc_info.value)
    assert "auto-derived from name='Research & Writing Team'" in message
    assert "set id='research-writing-team'" in message


def test_leading_digit_id_is_rejected_with_prefixed_suggestion():
    """Gemini 400s tool names starting with a digit -- and validates per request, so one
    bad name would take down every exposed tool. Rejected at build instead."""
    agent = Agent(name="2024 Reporter")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError) as exc_info:
        build_mcp_server(os)
    message = str(exc_info.value)
    assert "'2024-reporter'" in message
    assert "set id='agent-2024-reporter'" in message


def test_accented_id_suggestion_transliterates():
    """NFKD folding gives 'reviseur', not the mangled 'r-viseur'."""
    agent = _agent(id="r\u00e9viseur")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError, match="set id='reviseur'"):
        build_mcp_server(os)


def test_non_latin_id_gets_generic_advice_not_a_bogus_candidate():
    agent = _agent(id="\u7814\u7a76\u5458")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError) as exc_info:
        build_mcp_server(os)
    message = str(exc_info.value)
    assert "For example" not in message
    assert "Set an id on the component" in message


def test_suggestion_is_omitted_when_it_would_collide():
    """The candidate id must not point at a name already taken on the server -- that
    would be a two-round failure (fix the id, then hit the collision error)."""
    holder = _agent(id="ops-risk", name="Ops Risk")
    invalid = _agent(id="ops-&-risk", name="Ops And Risk")
    os = AgentOS(agents=[holder, invalid], mcp=MCPConfig(default_tools=False, tools=[holder, invalid]))
    with pytest.raises(ValueError) as exc_info:
        build_mcp_server(os)
    message = str(exc_info.value)
    assert "set id='ops-risk'" not in message
    assert "Set an id on the component" in message


# ==================== Session + identity contract ====================


async def test_exposed_agent_mints_distinct_sessions_and_honours_explicit():
    """Omitted session_id mints a fresh one per call; an explicit one is reused."""
    agent = _agent()
    calls = _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

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
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    await _call_tool(os, "chief", {"message": "hi", "user_id": "spoofed", "session_id": "s-1"})
    assert calls[0]["user_id"] == "jwt-alice"
    assert calls[0]["session_id"] == "s-1"


async def test_exposed_agent_enforces_run_scopes(monkeypatch):
    """A sessions:read-only PAT is denied on the named tool exactly as on run_agent."""
    _patch_request(monkeypatch, _pat_request(["sessions:read"]))
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"}, raise_on_error=False)
    assert result.is_error
    assert "Insufficient permissions" in str(result.content)
    assert "agents:run" in str(result.content)


async def test_exposed_agent_allows_matching_scope(monkeypatch):
    """agents:run passes the gate and the tool proceeds to the run."""
    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    agent = _agent()
    _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"}, raise_on_error=False)
    assert not result.is_error


async def test_exposed_agent_surfaces_paused_runs():
    """A PAUSED (HITL) run comes back with its status and requirements visible, not swallowed."""
    from agno.models.response import ToolExecution
    from agno.run.requirement import RunRequirement

    agent = _agent()
    _stub_arun(
        agent,
        RunOutput(
            run_id="r-1",
            session_id="s-1",
            content=None,
            status=RunStatus.paused,
            requirements=[
                RunRequirement(tool_execution=ToolExecution(tool_name="send_email", requires_confirmation=True))
            ],
        ),
    )
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("status") == RunStatus.paused.value
    assert len(structured.get("requirements") or []) == 1


async def test_exposed_tool_resolves_at_call_time(monkeypatch):
    """The tool must run the component the resolver returns, not a build-time capture.

    Per-run copies, registry lookup, and versioning all live in _resolve_run_component;
    if the factory closed over the roster instance instead, this substitute would never
    run and the roster stub would."""
    roster_agent = _agent()
    roster_calls = _stub_arun(roster_agent, RunOutput(content="roster"))
    substitute = Agent(id="chief", name="Chief Substitute")
    substitute_calls = _stub_arun(substitute, RunOutput(content="substitute"))
    os = AgentOS(agents=[roster_agent], mcp=MCPConfig(default_tools=False, tools=[roster_agent]))

    async def _resolve(os_, kind, component_id, **kwargs):
        assert kind == "agents" and component_id == "chief"
        return substitute

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)
    await _call_tool(os, "chief", {"message": "hi"})

    assert substitute_calls and substitute_calls[0]["message"] == "hi"
    assert not roster_calls


async def test_exposed_tools_apply_the_session_ownership_gate(monkeypatch):
    """All three exposed kinds run the ownership gate with their own SessionType and the
    minted session -- deleting the gate call or crossing the SessionType fails here."""
    from agno.db.base import SessionType

    recorded: list = []

    async def _record_gate(os_app, component, session_id, user_id, session_type):
        recorded.append({"session_id": session_id, "session_type": session_type})

    monkeypatch.setattr(mcp_mod, "_assert_session_writable_mcp", _record_gate)

    agent, team, workflow = _agent(), _team(), _workflow()
    _stub_arun(agent, RunOutput(content="ok"))
    _stub_arun(team, TeamRunOutput(content="ok"))
    _stub_arun(workflow, WorkflowRunOutput(content="ok"))
    os = AgentOS(
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        mcp=MCPConfig(default_tools=False, tools=[agent, team, workflow]),
    )

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("chief", {"message": "a"})
        await client.call_tool("support-team", {"message": "b"})
        await client.call_tool("daily-brief", {"message": "c"})

    assert [r["session_type"] for r in recorded] == [SessionType.AGENT, SessionType.TEAM, SessionType.WORKFLOW]
    assert all(r["session_id"] for r in recorded)


async def test_exposed_workflow_enforces_scopes_and_mints_sessions(monkeypatch):
    """The workflow factory is its own code path: pin its scope gate and session minting."""
    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    workflow = _workflow()
    wf_calls = _stub_arun(workflow, WorkflowRunOutput(content="ok"))
    os = AgentOS(workflows=[workflow], mcp=MCPConfig(default_tools=False, tools=[workflow]))

    denied = await _call_tool(os, "daily-brief", {"message": "go"}, raise_on_error=False)
    assert denied.is_error
    assert "workflows:run" in str(denied.content)

    _patch_request(monkeypatch, _pat_request(["workflows:run"]))
    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("daily-brief", {"message": "one"})
        await client.call_tool("daily-brief", {"message": "two"})
    minted = [c["session_id"] for c in wf_calls]
    assert all(minted) and minted[0] != minted[1]


async def test_exposed_agent_honours_per_resource_scopes(monkeypatch):
    """agents:<id>:run grants exactly that agent's tool -- the fail-open regression guard."""
    agent = _agent()
    _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    _patch_request(monkeypatch, _pat_request(["agents:chief:run"]))
    allowed = await _call_tool(os, "chief", {"message": "hi"}, raise_on_error=False)
    assert not allowed.is_error

    _patch_request(monkeypatch, _pat_request(["agents:other-agent:run"]))
    blocked = await _call_tool(os, "chief", {"message": "hi"}, raise_on_error=False)
    assert blocked.is_error
    assert "Insufficient permissions" in str(blocked.content)


# ==================== Build-time validation ====================


async def test_exposed_id_colliding_with_default_tool_raises():
    """An exposed component whose tool name matches a default tool is a hard build error."""
    agent = _agent(id="run_agent")
    os = AgentOS(agents=[agent], mcp=MCPConfig(tools=[agent]))
    with pytest.raises(ValueError, match='"run_agent"'):
        build_mcp_server(os)


async def test_colliding_default_tool_name_is_fine_when_builtins_off():
    """The same id is fine when the default tools are off -- the name is free."""
    agent = _agent(id="run_agent")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    assert await _tool_names(os) == {"run_agent"}


def test_exposed_id_colliding_with_custom_tool_raises():
    def chief() -> str:
        """Custom chief."""
        return "custom"

    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent, chief]))
    with pytest.raises(ValueError, match='custom tool "chief"'):
        build_mcp_server(os)


def test_exposing_two_components_with_same_tool_name_raises():
    """Cross-kind id reuse (legal in AgentOS) still collides on the one tool namespace."""
    agent = _agent(id="shared-name")
    team = Team(id="shared-name", name="Shared Team", members=[_agent(id="member")])
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[agent, team]))
    with pytest.raises(ValueError, match='"shared-name"'):
        build_mcp_server(os)


def test_kind_derives_from_roster_membership():
    """A Team in tools= is gated on teams:run -- kind comes from the roster it lives
    in, never from which parameter it was passed to (there is only one now)."""
    team = _team()
    _stub_arun(team, TeamRunOutput(content="ok"))
    os = AgentOS(teams=[team], mcp=MCPConfig(default_tools=False, tools=[team]))
    assert build_mcp_server(os) is not None


def test_ambiguous_id_copy_across_rosters_raises():
    """AgentOS permits an Agent and a Team to share an id. The roster INSTANCE resolves
    by identity, but an equal-id COPY matches two rosters -- ambiguous, and silently
    picking one would publish a component under the other kind's scopes."""
    agent = _agent(id="shared", name="The Agent")
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    stray_copy = Team(id="shared", name="Stray Copy", members=[_agent(id="m2")])
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[stray_copy]))
    with pytest.raises(ValueError, match="more than one"):
        build_mcp_server(os)


def test_roster_instance_wins_by_identity_even_with_shared_id():
    """The actual roster Team resolves by identity, shared id or not."""
    agent = _agent(id="shared", name="The Agent")
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[team]))
    with pytest.raises(ValueError, match="collides") as exc_info:
        # Both roster components exposed under the same id: the second collides -- but
        # BOTH resolved (the collision message proves the team resolved as a team).
        build_mcp_server(AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[agent, team])))
    assert 'exposed agent "shared"' in str(exc_info.value)
    assert build_mcp_server(os) is not None


def test_exposing_non_roster_instance_raises():
    roster_agent = _agent()
    outsider = _agent(id="outsider", name="Outsider")
    os = AgentOS(agents=[roster_agent], mcp=MCPConfig(default_tools=False, tools=[outsider]))
    with pytest.raises(ValueError, match="not part of the AgentOS roster"):
        build_mcp_server(os)


def test_id_string_in_tools_raises_type_error():
    """Strings are ambiguous in tools= -- pass the component instance."""
    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=["chief"]))
    with pytest.raises(TypeError, match="instance"):
        build_mcp_server(os)


def test_exposed_id_colliding_with_fastmcp_derived_name_raises():
    """The collision registry must hold the names FastMCP actually registered, not a
    re-derivation: a functools.partial has no __name__ and registers as 'partial'."""
    import functools

    def base_tool(x: str, y: str) -> str:
        """Combine two strings."""
        return x + y

    partial_tool = functools.partial(base_tool, y="fixed")
    agent = _agent(id="partial", name="Partial Agent")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent, partial_tool]))
    with pytest.raises(ValueError, match='custom tool "partial"'):
        build_mcp_server(os)


def test_exposed_id_colliding_with_named_agno_function_raises():
    """The Agno @tool branch of custom-name resolution feeds collision detection too."""
    from agno.tools import tool

    @tool(name="chief", description="Custom chief function")
    def chief_fn() -> str:
        """Custom chief."""
        return "custom"

    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent, chief_fn]))
    with pytest.raises(ValueError, match='custom tool "chief"'):
        build_mcp_server(os)


async def test_exposure_composes_with_include_tags():
    """Tag scoping keeps applying to the default tools while exposure adds its own names."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(include_tags={"core"}, tools=[agent]))

    names = await _tool_names(os)
    core = {name for name, tag in mcp_mod._BUILTIN_TOOL_NAMES.items() if tag == "core"}
    session = {name for name, tag in mcp_mod._BUILTIN_TOOL_NAMES.items() if tag == "session"}
    assert names == core | {"chief"}
    assert not (names & session)


async def test_named_component_without_id_gets_its_deterministic_id():
    """A named, id-less component works: AgentOS mints its name-derived id at
    construction (stable across boots), and the exposed tool follows it."""
    agent = Agent(name="Solo Named")
    _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    assert await _tool_names(os) == {"solo-named"}
    assert agent.id == "solo-named"


async def test_tool_name_cap_is_128():
    """OpenAI, Anthropic, and Gemini all accept 128-char tool names and reject 129
    (probed live in review) -- so 65 registers fine and 129 is the hard error."""
    ok_agent = _agent(id="a" * 65)
    os = AgentOS(agents=[ok_agent], mcp=MCPConfig(default_tools=False, tools=[ok_agent]))
    assert await _tool_names(os) == {"a" * 65}

    long_agent = _agent(id="b" * 129)
    os2 = AgentOS(agents=[long_agent], mcp=MCPConfig(default_tools=False, tools=[long_agent]))
    with pytest.raises(ValueError, match="128"):
        build_mcp_server(os2)


async def test_two_exposed_components_of_same_kind_run_their_own_component():
    """Each closure must capture its own id -- the classic late-binding loop bug would
    route every tool to the last component and no single-exposure test would notice."""
    chief = _agent(id="chief", name="Chief")
    researcher = _agent(id="researcher", name="Researcher")
    chief_calls = _stub_arun(chief, RunOutput(content="chief"))
    researcher_calls = _stub_arun(researcher, RunOutput(content="researcher"))
    os = AgentOS(agents=[chief, researcher], mcp=MCPConfig(default_tools=False, tools=[chief, researcher]))

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("chief", {"message": "to chief"})
        await client.call_tool("researcher", {"message": "to researcher"})

    assert [c["message"] for c in chief_calls] == ["to chief"]
    assert [c["message"] for c in researcher_calls] == ["to researcher"]


async def test_exposed_tool_honours_result_mode_full():
    """result_mode='full' applies to exposed tools exactly as to run_agent."""
    agent = _agent()
    _stub_arun(agent, RunOutput(run_id="r-full", session_id="s-full", content="done", status=RunStatus.completed))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent], result_mode="full"))

    result = await _call_tool(os, "chief", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    # The full run dict carries fields the trimmed mode deliberately omits.
    assert structured.get("run_id") == "r-full"
    assert structured.get("content") == "done"


async def test_exposed_tool_progress_label_uses_the_resolved_component(monkeypatch):
    """The progress label comes from the call-time resolved component, not a build-time
    capture -- a published/registry version may carry a different name."""
    roster_agent = _agent(id="chief", name="Roster Name")
    substitute = Agent(id="chief", name="Resolved Name")
    _stub_arun(substitute, RunOutput(content="ok"))
    os = AgentOS(agents=[roster_agent], mcp=MCPConfig(default_tools=False, tools=[roster_agent]))

    async def _resolve(os_, kind, component_id, **kwargs):
        return substitute

    labels: list = []
    real_run = mcp_mod._run_agentic_component

    async def _record_label(ctx, component, message, user_id, session_id, label):
        labels.append(label)
        return await real_run(ctx, component, message, user_id, session_id, label)

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)
    monkeypatch.setattr(mcp_mod, "_run_agentic_component", _record_label)
    await _call_tool(os, "chief", {"message": "hi"})

    assert labels == ["Agent Resolved Name"]


def test_exposure_only_config_does_not_warn(caplog):
    """Tags scoped to zero default tools normally warn about an empty server; exposure
    is a registered surface, so the warning must not fire."""
    import logging

    agent = _agent()
    with caplog.at_level(logging.WARNING):
        MCPConfig(include_tags=set(), tools=[agent])
    assert "zero tools" not in caplog.text


def test_zero_tools_validator_accepts_exposure_and_still_rejects_empty():
    MCPConfig(default_tools=False, tools=[_agent()])
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


def test_enable_builtin_tools_assignment_still_works():
    """Pre-rename this was a plain field write; the alias keeps assignment working."""
    config = MCPConfig(tools=[lambda: "x"])
    config.enable_builtin_tools = False
    assert config.default_tools is False
    assert config.enable_builtin_tools is False


def test_enable_builtin_tools_alias_does_not_mutate_caller_dict():
    data = {"enable_builtin_tools": False, "tools": [lambda: "x"]}
    MCPConfig.model_validate(data)
    assert "enable_builtin_tools" in data


def test_enable_builtin_tools_alias_covers_non_dict_mappings():
    """Pydantic accepts any Mapping; the alias must not silently drop the key for one."""
    from collections import UserDict

    config = MCPConfig.model_validate(UserDict({"enable_builtin_tools": False, "tools": [lambda: "x"]}))
    assert config.default_tools is False


def test_unknown_config_key_is_rejected():
    """extra='forbid': a typo like agent= (for agents=) must fail loudly, not silently
    serve a different tool surface. Pinned to the extra_forbidden error at the typo'd
    key -- a broad match would also pass via the unrelated zero-tools error."""
    from pydantic import ValidationError

    agent = _agent()
    with pytest.raises(ValidationError) as exc_info:
        MCPConfig(default_tools=False, tools=[agent], agent=[agent])
    assert [(e["type"], e["loc"]) for e in exc_info.value.errors()] == [("extra_forbidden", ("agent",))]


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


# ==================== Review round: remote metadata, paused hint, dict guard ====================


async def test_exposing_unreachable_remote_does_not_fail_the_build():
    """RemoteTeam/RemoteWorkflow name/description are network-backed properties; an
    unreachable remote at boot must degrade the tool description to the id, not take
    down get_app() -- REST included -- before anything called the component."""
    from agno.team.remote import RemoteTeam

    remote = RemoteTeam(base_url="http://127.0.0.1:9", team_id="remote-team")
    os = AgentOS(teams=[remote], mcp=MCPConfig(default_tools=False, tools=[remote]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.name == "remote-team"
    assert tool.description is not None
    assert tool.description.startswith("Run the remote-team team with a message.")


async def test_whitespace_only_description_falls_back():
    """A whitespace-only description must not produce a tool description starting '. '."""
    agent = _agent(description="   ")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.description is not None
    assert tool.description.startswith("Run the Chief agent with a message.")


async def test_paused_run_without_continue_run_points_at_rest():
    """With the core default tools off there is no continue_run; the paused result says
    so instead of leaving the client hunting for an unregistered tool."""
    from agno.models.response import ToolExecution
    from agno.run.requirement import RunRequirement

    paused = RunOutput(
        run_id="r-p",
        session_id="s-p",
        content=None,
        status=RunStatus.paused,
        requirements=[RunRequirement(tool_execution=ToolExecution(tool_name="x", requires_confirmation=True))],
    )
    agent = _agent()
    _stub_arun(agent, paused)
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    result = await _call_tool(os, "chief", {"message": "hi"})
    assert "continue_run tool is not registered" in result.content[0].text

    agent2 = _agent(id="chief2")
    _stub_arun(agent2, paused)
    os2 = AgentOS(agents=[agent2], mcp=MCPConfig(include_tags={"core"}, tools=[agent2]))
    result2 = await _call_tool(os2, "chief2", {"message": "hi"})
    assert "continue_run tool is not registered" not in result2.content[0].text


def test_assigning_dict_to_mcp_raises_type_error():
    """bool(dict) would enable the server while silently discarding every setting in it,
    including authorize -- a dict is always a mistake and must say so."""
    os = AgentOS(agents=[_agent()])
    with pytest.raises(TypeError, match="MCPConfig"):
        os.mcp = {"default_tools": False, "authorize": lambda user_id: False}  # type: ignore[assignment]
    with pytest.raises(TypeError, match="MCPConfig"):
        AgentOS(agents=[_agent(id="d2")], mcp={"default_tools": False})  # type: ignore[arg-type]


# ==================== as_tool: model-facing name/description overrides ====================


async def test_as_tool_overrides_name_and_description():
    """as_tool decouples the model-facing presentation from the running component."""
    agent = _agent(description="Digs into topics.")
    _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(
            default_tools=False,
            tools=[agent.as_tool(name="deep_research", description="Thorough, sourced research. Send one question.")],
        ),
    )

    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.name == "deep_research"
    assert tool.description is not None
    assert tool.description.startswith("Thorough, sourced research. Send one question.")
    assert "session_id" in tool.description


async def test_as_tool_partial_overrides_fall_back_to_component():
    """Omitted overrides fall back: name to the id, description to the component's."""
    agent = _agent(description="The component description.")
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(description="Only the pitch changes.")]),
    )
    async with Client(build_mcp_server(os)) as client:
        (tool,) = await client.list_tools()
    assert tool.name == "chief"
    assert tool.description is not None and tool.description.startswith("Only the pitch changes.")

    agent2 = _agent(id="chief2", description="Kept description.")
    os2 = AgentOS(agents=[agent2], mcp=MCPConfig(default_tools=False, tools=[agent2.as_tool(name="ask_chief")]))
    async with Client(build_mcp_server(os2)) as client:
        (tool2,) = await client.list_tools()
    assert tool2.name == "ask_chief"
    assert tool2.description is not None and tool2.description.startswith("Kept description.")


async def test_as_tool_runs_the_wrapped_component_with_full_machinery(monkeypatch):
    """The override changes presentation only: scopes still gate on the component id,
    and the run threads through the same chain as a bare exposure."""
    _patch_request(monkeypatch, _pat_request(["agents:researcher:run"]))
    agent = _agent(id="researcher", name="Researcher")
    calls = _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(name="deep_research")]))

    allowed = await _call_tool(os, "deep_research", {"message": "hi"}, raise_on_error=False)
    assert not allowed.is_error
    assert calls[0]["message"] == "hi"

    _patch_request(monkeypatch, _pat_request(["agents:other:run"]))
    blocked = await _call_tool(os, "deep_research", {"message": "hi"}, raise_on_error=False)
    assert blocked.is_error
    assert "Insufficient permissions" in str(blocked.content)


def test_as_tool_invalid_override_name_raises_with_candidate():
    """The override goes through the same provider-shape validation as ids."""
    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(name="Ask Chief")]),
    )
    with pytest.raises(ValueError, match="as_tool"):
        try:
            build_mcp_server(os)
        except ValueError as e:
            assert "name='ask-chief'" in str(e)
            raise


def test_as_tool_override_collision_raises():
    a1 = _agent(id="one", name="One")
    a2 = _agent(id="two", name="Two")
    os = AgentOS(
        agents=[a1, a2],
        mcp=MCPConfig(default_tools=False, tools=[a1.as_tool(name="ask"), a2.as_tool(name="ask")]),
    )
    with pytest.raises(ValueError, match='"ask"'):
        build_mcp_server(os)


async def test_team_and_workflow_as_tool_work():
    team = _team()
    workflow = _workflow()
    _stub_arun(team, TeamRunOutput(content="ok"))
    _stub_arun(workflow, WorkflowRunOutput(content="ok"))
    os = AgentOS(
        teams=[team],
        workflows=[workflow],
        mcp=MCPConfig(
            default_tools=False,
            tools=[team.as_tool(name="ask_support"), workflow.as_tool(name="run_brief")],
        ),
    )
    assert await _tool_names(os) == {"ask_support", "run_brief"}


async def test_structured_content_carries_the_component_id():
    """With the tool name decoupled from the id, the result must carry the id -- it is
    the continue_run/get_sessions handle."""
    agent = _agent(id="researcher", name="Researcher")
    _stub_arun(agent, RunOutput(agent_id="researcher", content="ok", status=RunStatus.completed))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(name="deep_research")]))

    result = await _call_tool(os, "deep_research", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("agent_id") == "researcher"


def test_component_tool_marker_is_declarative():
    """as_tool returns a marker, not a callable -- binding a callable here would bypass
    the exposure machinery."""
    from agno.tools import ComponentTool

    marker = _agent().as_tool(name="ask_chief", description="d")
    assert isinstance(marker, ComponentTool)
    assert not callable(marker)
    assert marker.name == "ask_chief"
    assert marker.description == "d"


def test_as_tool_of_non_roster_component_raises():
    outsider = _agent(id="outsider")
    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[outsider.as_tool(name="ask")]))
    with pytest.raises(ValueError, match="not part of the AgentOS roster"):
        build_mcp_server(os)
