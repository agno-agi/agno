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


async def _tool_by_name(os: AgentOS, name: str):
    async with Client(build_mcp_server(os)) as client:
        return {t.name: t for t in await client.list_tools()}[name]


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


def _request_with_bearer(token, scopes=("agents:run", "teams:run", "workflows:run")):
    req = _pat_request(scopes)
    req.headers = {"Authorization": f"Bearer {token}"}
    return req


def _seed_agent_run(agent, session_id, run_id, user_id=None):
    """Persist a real AgentSession containing a run belonging to ``agent`` (via the
    agent's own db), so the run-ownership gate reads a genuine session, not a stub."""
    from agno.session.agent import AgentSession

    agent.db.upsert_session(AgentSession(session_id=session_id, agent_id=agent.id, user_id=user_id))
    agent.db.upsert_run(
        RunOutput(run_id=run_id, agent_id=agent.id, session_id=session_id),
        session_id=session_id,
        user_id=user_id,
    )


def _seed_team_run(team, session_id, run_id, user_id=None):
    from agno.session.team import TeamSession

    team.db.upsert_session(TeamSession(session_id=session_id, team_id=team.id, user_id=user_id))
    team.db.upsert_run(
        TeamRunOutput(run_id=run_id, team_id=team.id, session_id=session_id),
        session_id=session_id,
        user_id=user_id,
    )


# ==================== Exposure surface ====================


async def test_exposed_agent_is_the_only_tool_with_default_tools_off():
    """default_tools=False + agents=[chief] serves exactly one tool named after the id."""
    agent = _agent()
    calls = _stub_arun(agent, RunOutput(content="done", status=RunStatus.completed))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    # continue_run/cancel_run ride along with exposure so HITL works by default.
    assert await _tool_names(os) == {"chief", "continue_run", "cancel_run"}
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

    assert await _tool_names(os) == {"support-team", "daily-brief", "continue_run", "cancel_run"}
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

    tool = await _tool_by_name(os, "chief")
    assert tool.description is not None
    assert tool.description.startswith("Handles executive requests.")
    assert "session_id" in tool.description


async def test_exposed_tool_schema_shows_only_client_facing_params():
    """The client-facing schema is message/user_id/session_id; ctx is injected, hidden."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    tool = await _tool_by_name(os, "chief")
    assert set(tool.inputSchema.get("properties", {})) == {"message", "user_id", "session_id"}
    assert tool.inputSchema.get("required") == ["message"]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.openWorldHint is True


async def test_exposed_tool_description_fallback_without_component_description():
    """A component without a description gets the documented fallback plus the fixed sentence."""
    agent = _agent()  # name "Chief", no description
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    tool = await _tool_by_name(os, "chief")
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
        recorded.append(
            {"component": component, "session_id": session_id, "user_id": user_id, "session_type": session_type}
        )

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
    # The gate must receive the RESOLVED component and the resolved caller identity --
    # a fake that drops these would stay green while the gate checked nothing.
    assert [r["component"] for r in recorded] == [agent, team, workflow]
    assert all(r["user_id"] is None for r in recorded)


async def test_ownership_gate_refusal_propagates_to_the_caller(monkeypatch):
    """The gate's raise must surface as a tool error and stop the run -- a handler that
    swallowed it and ran the component anyway would still pass the invocation pin
    above (audit-without-enforcement is the fail-open this exists to catch)."""

    async def _deny(os_app, component, session_id, user_id, session_type):
        raise Exception("session belongs to another user")

    monkeypatch.setattr(mcp_mod, "_assert_session_writable_mcp", _deny)
    agent = _agent()
    calls = _stub_arun(agent, RunOutput(content="must not run"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi", "session_id": "sess-x"}, raise_on_error=False)
    assert result.is_error
    assert "another user" in str(result.content)
    assert calls == []


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
    assert await _tool_names(os) == {"run_agent", "continue_run", "cancel_run"}


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


async def test_kind_derives_from_roster_membership(monkeypatch):
    """A Team in tools= is gated on teams scopes -- kind comes from the roster it lives
    in, never from which parameter it was passed to (there is only one now). The scope
    ROUTE is the pin: an agents:run PAT must be denied on the exposed team tool."""
    team = _team()
    calls = _stub_arun(team, TeamRunOutput(content="ok"))
    os = AgentOS(teams=[team], mcp=MCPConfig(default_tools=False, tools=[team]))

    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    denied = await _call_tool(os, "support-team", {"message": "hi"}, raise_on_error=False)
    assert denied.is_error
    assert "teams:run" in str(denied.content)
    assert calls == []

    _patch_request(monkeypatch, _pat_request(["teams:run"]))
    allowed = await _call_tool(os, "support-team", {"message": "hi"}, raise_on_error=False)
    assert not allowed.is_error
    assert calls[0]["message"] == "hi"


def test_ambiguous_id_copy_across_rosters_raises():
    """AgentOS permits an Agent and a Team to share an id. A concrete-class entry
    resolves within its own kind's roster, but a duck-typed entry (the Remote* shape)
    carries no kind on its class -- an equal-id copy matching two rosters is ambiguous,
    and silently picking one would publish a component under the other kind's scopes."""
    agent = _agent(id="shared", name="The Agent")
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])

    async def _arun(message, **kwargs):
        yield None

    stray_duck = SimpleNamespace(id="shared", name="Stray Remote", arun=_arun)
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[stray_duck]))
    with pytest.raises(ValueError, match="more than one"):
        build_mcp_server(os)


async def test_concrete_copy_with_cross_kind_shared_id_resolves_to_its_own_kind():
    """An equal-id Team COPY resolves to the roster team even when an agent shares the
    id: the concrete class names the kind, so nothing is ambiguous."""
    agent = _agent(id="shared", name="The Agent")
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    agent_calls = _stub_arun(agent, RunOutput(content="agent ran"))
    team_calls = _stub_arun(team, TeamRunOutput(content="team ran"))
    stray_copy = Team(id="shared", name="Stray Copy", members=[_agent(id="m2")])
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[stray_copy]))

    await _call_tool(os, "shared", {"message": "go"})
    assert team_calls[0]["message"] == "go"
    assert agent_calls == []


def test_wrong_kind_entry_with_roster_id_of_another_kind_raises():
    """A non-roster Agent entry must never resolve to a same-id roster TEAM: that would
    run the team under the agent entry's name and description, gated by the wrong
    kind's scopes. Regression pin: the tools= reshape briefly dropped this guard and
    silently published the team."""
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    stray_agent = _agent(id="shared", name="Stray Agent")
    os = AgentOS(agents=[_agent()], teams=[team], mcp=MCPConfig(default_tools=False, tools=[stray_agent]))
    with pytest.raises(ValueError, match="different kind"):
        build_mcp_server(os)


def test_wrong_kind_as_tool_entry_raises_too():
    """The same guard applies through the as_tool wrapper."""
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    stray_agent = _agent(id="shared", name="Stray Agent")
    os = AgentOS(
        agents=[_agent()],
        teams=[team],
        mcp=MCPConfig(default_tools=False, tools=[stray_agent.as_tool(name="ask")]),
    )
    with pytest.raises(ValueError, match="different kind"):
        build_mcp_server(os)


def test_wrong_kind_remote_entry_raises_too():
    """Remote* classes name their kind just like the concrete ones: a non-roster
    RemoteAgent must not resolve to a same-id roster TEAM. Only truly kindless
    duck-typed protocol objects keep the all-roster scan."""
    from agno.agent.remote import RemoteAgent

    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    stray_remote = RemoteAgent(base_url="http://127.0.0.1:9", agent_id="shared")
    os = AgentOS(agents=[_agent()], teams=[team], mcp=MCPConfig(default_tools=False, tools=[stray_remote]))
    with pytest.raises(ValueError, match="different kind"):
        build_mcp_server(os)


async def test_roster_factory_in_tools_exposes_as_named_tool():
    """A component factory registered on the roster is a component entry: passed bare
    in tools=, it exposes under its id instead of dying in Tool.from_function (a
    BaseFactory is neither callable nor arun-shaped)."""
    from agno.agent.factory import AgentFactory
    from agno.db.in_memory.in_memory_db import InMemoryDb

    factory = AgentFactory(
        id="made-to-order",
        db=InMemoryDb(),
        factory=lambda ctx: _agent(id="made-to-order"),
        description="Built per request.",
    )
    os = AgentOS(agents=[factory], mcp=MCPConfig(default_tools=False, tools=[factory]))
    names = await _tool_names(os)
    assert "made-to-order" in names


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
    core = {name for name, tags in mcp_mod._BUILTIN_TOOL_NAMES.items() if "core" in tags}
    session = {name for name, tags in mcp_mod._BUILTIN_TOOL_NAMES.items() if "session" in tags}
    assert names == core | {"chief"}
    assert not (names & session)


async def test_named_component_without_id_gets_its_deterministic_id():
    """A named, id-less component works: AgentOS mints its name-derived id at
    construction (stable across boots), and the exposed tool follows it."""
    agent = Agent(name="Solo Named")
    _stub_arun(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    assert await _tool_names(os) == {"solo-named", "continue_run", "cancel_run"}
    assert agent.id == "solo-named"


async def test_tool_name_cap_is_128():
    """OpenAI, Anthropic, and Gemini all accept 128-char tool names and reject 129
    (probed live in review) -- so 65 registers fine and 129 is the hard error."""
    ok_agent = _agent(id="a" * 65)
    os = AgentOS(agents=[ok_agent], mcp=MCPConfig(default_tools=False, tools=[ok_agent]))
    assert await _tool_names(os) == {"a" * 65, "continue_run", "cancel_run"}

    long_agent = _agent(id="b" * 129)
    os2 = AgentOS(agents=[long_agent], mcp=MCPConfig(default_tools=False, tools=[long_agent]))
    with pytest.raises(ValueError, match="128"):
        build_mcp_server(os2)


async def test_as_tool_name_cap_is_128_too():
    """The cap applies to the override path as well, and 128 exactly registers."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(name="x" * 129)]))
    with pytest.raises(ValueError, match="128") as exc_info:
        build_mcp_server(os)
    assert "as_tool" in str(exc_info.value)

    ok = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(name="x" * 128)]))
    assert "x" * 128 in await _tool_names(ok)


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
    from agno.models.message import Message

    agent = _agent()
    _stub_arun(
        agent,
        RunOutput(
            run_id="r-full",
            session_id="s-full",
            content="done",
            status=RunStatus.completed,
            messages=[Message(role="user", content="hi")],
        ),
    )
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent], result_mode="full"))

    result = await _call_tool(os, "chief", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("run_id") == "r-full"
    # The discriminator must be a field TRIMMED mode deliberately omits -- "content"
    # is mirrored in both modes now, so it proves nothing about the mode.
    assert "messages" in structured


async def test_exposed_tool_trimmed_mode_omits_the_transcript():
    """The trimmed direction: default results carry the answer and ids, never the
    message transcript the full mode returns."""
    agent = _agent()
    _stub_arun(
        agent,
        RunOutput(run_id="r-trim", session_id="s-trim", content="done", status=RunStatus.completed),
    )
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    result = await _call_tool(os, "chief", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("content") == "done"
    assert "messages" not in structured
    assert "metrics" not in structured


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


def test_enable_builtin_tools_survives_model_copy_update():
    """model_copy bypasses validators; the legacy key must still map (it was a real
    field pre-rename, and the class-level property would otherwise shadow the copy's
    __dict__ entry and silently drop the update)."""

    def noop() -> str:
        """Return ok."""
        return "ok"

    config = MCPConfig(tools=[noop])
    copied = config.model_copy(update={"enable_builtin_tools": False})
    assert copied.default_tools is False
    assert copied.enable_builtin_tools is False
    assert config.default_tools is True


def test_conflicting_spellings_in_model_copy_update_raise():
    config = MCPConfig()
    with pytest.raises(ValueError, match="deprecated alias"):
        config.model_copy(update={"enable_builtin_tools": False, "default_tools": True})


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

    tool = await _tool_by_name(os, "remote-team")
    assert tool.name == "remote-team"
    assert tool.description is not None
    assert tool.description.startswith("Run the remote-team team with a message.")


async def test_remote_with_both_overrides_skips_the_metadata_fetch(monkeypatch):
    """On a remote, name/description are network-backed. When as_tool supplies both,
    neither is needed at build -- so the (blocking, uncached) metadata read must be
    skipped entirely, not just tolerated on failure."""
    from agno.team.remote import RemoteTeam

    def _boom(component):
        raise AssertionError("metadata was fetched despite both overrides being supplied")

    monkeypatch.setattr(mcp_mod, "_safe_component_metadata", _boom)
    remote = RemoteTeam(base_url="http://127.0.0.1:9", team_id="remote-team")
    os = AgentOS(
        teams=[remote],
        mcp=MCPConfig(
            default_tools=False,
            tools=[remote.as_tool(name="ask_remote", description="Ask the remote team.")],
        ),
    )
    tool = await _tool_by_name(os, "ask_remote")
    assert tool.description.startswith("Ask the remote team.")


async def test_whitespace_only_description_falls_back():
    """A whitespace-only description must not produce a tool description starting '. '."""
    agent = _agent(description="   ")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    tool = await _tool_by_name(os, "chief")
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
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent], lifecycle_tools=False))
    result = await _call_tool(os, "chief", {"message": "hi"})
    assert "continue_run tool is not registered" in result.content[0].text
    # The recovery hint must reach structuredContent-only clients too: the "content"
    # key mirrors the final text block, not the raw (empty) paused content.
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("content") == result.content[0].text
    assert "REST" in (structured.get("content") or "")

    # Default: the lifecycle pair rides along, so the hint must NOT appear.
    agent2 = _agent(id="chief2")
    _stub_arun(agent2, paused)
    os2 = AgentOS(agents=[agent2], mcp=MCPConfig(default_tools=False, tools=[agent2]))
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

    tool = await _tool_by_name(os, "deep_research")
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
    tool = await _tool_by_name(os, "chief")
    assert tool.name == "chief"
    assert tool.description is not None and tool.description.startswith("Only the pitch changes.")

    agent2 = _agent(id="chief2", description="Kept description.")
    os2 = AgentOS(agents=[agent2], mcp=MCPConfig(default_tools=False, tools=[agent2.as_tool(name="ask_chief")]))
    tool2 = await _tool_by_name(os2, "ask_chief")
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
    """The error attributes the name to the as_tool override the user typed, not to the
    component id (which is a different string they would hunt for in vain)."""
    a1 = _agent(id="one", name="One")
    a2 = _agent(id="two", name="Two")
    os = AgentOS(
        agents=[a1, a2],
        mcp=MCPConfig(default_tools=False, tools=[a1.as_tool(name="ask"), a2.as_tool(name="ask")]),
    )
    with pytest.raises(ValueError, match='as_tool\\(name="ask"\\) on agent "two"') as exc_info:
        build_mcp_server(os)
    assert 'from agent id "two"' not in str(exc_info.value)


def test_remote_components_have_as_tool_too():
    """Remote* components get the same as_tool escape hatch: their id is minted by the
    remote deployment, so the override is the only local way to pick the tool name."""
    from agno.agent.remote import RemoteAgent
    from agno.tools import ComponentTool

    marker = RemoteAgent(base_url="http://localhost:9", agent_id="far-away").as_tool(name="ask_remote", description="d")
    assert isinstance(marker, ComponentTool)
    assert marker.name == "ask_remote"
    assert marker.description == "d"


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
    assert await _tool_names(os) == {"ask_support", "run_brief", "continue_run", "cancel_run"}


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


async def test_structured_content_carries_the_team_id_too():
    """The id contract holds for every kind, not just agents."""
    team = _team()
    _stub_arun(team, TeamRunOutput(team_id="support-team", content="ok", status=RunStatus.completed))
    os = AgentOS(teams=[team], mcp=MCPConfig(default_tools=False, tools=[team.as_tool(name="ask_support")]))

    result = await _call_tool(os, "ask_support", {"message": "hi"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert structured.get("team_id") == "support-team"


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


# ==================== Lifecycle tools ride along with exposure (HITL) ====================


async def test_lifecycle_tools_opt_out_gives_exactly_the_configured_tools():
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent], lifecycle_tools=False))
    assert await _tool_names(os) == {"chief"}


async def test_explicit_lifecycle_exclude_is_honoured():
    """exclude_tags={'lifecycle'} beats the ride-along -- an explicit exclusion is never
    silently overridden. This gates only the ride-along: with the default surface on the
    pair are core tools (test_exclude_lifecycle_keeps_the_default_surface_intact in
    test_mcp_server.py pins that side)."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent], exclude_tags={"lifecycle"}))
    assert await _tool_names(os) == {"chief"}


async def test_exposure_with_exclude_core_still_rides_lifecycle():
    """The ride-along composes with tag scoping: excluding ``core`` drops the generic
    run tools AND the pair's core membership, but the exposure adds ``lifecycle`` back
    so a paused exposed run stays resumable."""
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(tools=[agent], exclude_tags={"core"}))
    names = await _tool_names(os)
    assert names == {"chief", "continue_run", "cancel_run", "get_sessions", "get_session_runs"}
    assert "run_agent" not in names


async def test_exposed_id_collides_with_riding_lifecycle_tool():
    """With the lifecycle pair riding along by default, an exposed id 'continue_run'
    collides -- and is free again once the deployer opts out."""
    agent = _agent(id="continue_run")
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))
    with pytest.raises(ValueError, match='"continue_run"'):
        build_mcp_server(os)

    os2 = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent], lifecycle_tools=False))
    assert await _tool_names(os2) == {"continue_run"}


async def test_custom_tool_named_like_riding_builtin_raises():
    """A custom tool named continue_run must be a hard error, same as the exposure
    path: FastMCP replaces on duplicate names, so it would otherwise silently shadow
    the riding builtin while paused results still describe the builtin's schema."""

    async def continue_run(message: str) -> str:
        """Impostor."""
        return message

    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent, continue_run]))
    with pytest.raises(ValueError, match='custom tool name "continue_run"'):
        build_mcp_server(os)


async def test_custom_tool_named_like_default_tool_raises_on_default_surface():
    """The same guard covers the full default surface, not just the riding pair."""

    def run_agent() -> str:
        """Impostor."""
        return "no"

    os = AgentOS(agents=[_agent()], mcp=MCPConfig(tools=[run_agent]))
    with pytest.raises(ValueError, match='custom tool name "run_agent"'):
        build_mcp_server(os)


async def test_lifecycle_collision_advice_matches_how_the_name_was_claimed():
    """continue_run/cancel_run are tagged BOTH core and lifecycle. The collision advice
    must key on HOW the name is on the server, not on the tag set: when the pair rode in
    via an exposure (core off) the lifecycle switches free it; when core is enabled the
    pair is a core default and lifecycle_tools=False does nothing, so the advice must not
    prescribe it."""

    async def continue_run(message: str) -> str:
        """Impostor."""
        return message

    # Exposure-only surface: the pair rides along, core is off -> lifecycle advice.
    ride_only = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[_agent(), continue_run]))
    with pytest.raises(ValueError) as exc_ride:
        build_mcp_server(ride_only)
    assert "lifecycle_tools=False" in str(exc_ride.value)

    # Default surface: the pair is core-registered; lifecycle_tools=False can't free it.
    core_on = AgentOS(agents=[_agent()], mcp=MCPConfig(tools=[continue_run]))
    with pytest.raises(ValueError) as exc_core:
        build_mcp_server(core_on)
    assert "lifecycle_tools=False" not in str(exc_core.value)
    assert "default_tools" in str(exc_core.value)


async def test_exposed_id_collision_advice_is_lifecycle_aware_on_core_surface():
    """The exposed-component collision site gets the same correct advice: an exposed id
    that collides with the core-registered lifecycle pair must not be told to flip the
    lifecycle switches (they don't free a core-served name)."""
    agent = _agent(id="cancel_run")
    core_on = AgentOS(agents=[agent], mcp=MCPConfig(tools=[agent]))
    with pytest.raises(ValueError) as exc:
        build_mcp_server(core_on)
    assert "lifecycle_tools=False" not in str(exc.value)


async def test_duplicate_custom_tool_names_raise():
    """Two custom tools registering under the same name hard-error like every other
    collision on the server -- FastMCP would otherwise warn-and-replace, and the
    first tool would silently vanish from tools/list."""

    def helper() -> str:
        """First helper."""
        return "one"

    def helper2() -> str:
        """Second helper."""
        return "two"

    helper2.__name__ = "helper"
    os = AgentOS(agents=[_agent()], mcp=MCPConfig(default_tools=False, tools=[helper, helper2]))
    with pytest.raises(ValueError, match='custom tool name "helper"') as exc_info:
        build_mcp_server(os)
    assert 'custom tool "helper"' in str(exc_info.value)


async def test_custom_tool_may_claim_a_scoped_out_builtin_name():
    """Collision means an actual server conflict: a default-tool name whose tags are
    scoped out is claimable by a custom tool, exactly as it is by an exposure."""

    async def continue_run(message: str) -> str:
        """My own continue."""
        return message

    agent = _agent()
    os = AgentOS(
        agents=[agent],
        mcp=MCPConfig(default_tools=False, tools=[agent, continue_run], lifecycle_tools=False),
    )
    assert await _tool_names(os) == {"chief", "continue_run"}


async def test_hitl_pause_and_continue_loop_through_exposed_tool(monkeypatch):
    """The full HITL loop with default_tools=False: the exposed tool pauses with the
    component id + requirements in structuredContent, and the riding continue_run
    resumes that exact run."""
    from agno.db.in_memory.in_memory_db import InMemoryDb
    from agno.models.response import ToolExecution
    from agno.run.requirement import RunRequirement

    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)
    agent = _agent()
    agent.db = InMemoryDb()
    paused = RunOutput(
        agent_id="chief",
        run_id="run-hitl",
        session_id="sess-hitl",
        content=None,
        status=RunStatus.paused,
        requirements=[RunRequirement(tool_execution=ToolExecution(tool_name="send_email", requires_confirmation=True))],
    )
    _stub_arun(agent, paused)
    # A paused run is persisted before continue_run is called (as production does),
    # so the run-ownership binding can locate it.
    _seed_agent_run(agent, session_id="sess-hitl", run_id="run-hitl")

    continued: dict = {}

    async def fake_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        continued.update(run_id=run_id, session_id=session_id, requirements=requirements)
        return RunOutput(agent_id="chief", run_id=run_id, session_id=session_id, content="resumed")

    agent.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent.as_tool(name="ask_chief")]))

    async with Client(build_mcp_server(os)) as client:
        names = {t.name for t in await client.list_tools()}
        assert names == {"ask_chief", "continue_run", "cancel_run"}

        result = await client.call_tool("ask_chief", {"message": "send the email"})
        structured = result.structured_content or {}
        structured = structured.get("result", structured) or {}
        assert structured.get("status") == RunStatus.paused.value
        assert structured.get("agent_id") == "chief"
        assert len(structured.get("requirements") or []) == 1
        assert "continue_run tool is not registered" not in result.content[0].text

        # The recipe the cookbook client uses: resolution fields are NESTED. A
        # top-level "confirmed" key is ignored by RunRequirement.from_dict, so a run
        # "resumed" that way would re-pause on the still-unconfirmed tool.
        requirement = structured["requirements"][0]
        requirement["confirmation"] = True
        requirement["tool_execution"]["confirmed"] = True
        resumed = await client.call_tool(
            "continue_run",
            {
                "agent_id": structured["agent_id"],
                "run_id": structured["run_id"],
                "session_id": structured["session_id"],
                "requirements": [requirement],
            },
        )
        resumed_structured = resumed.structured_content or {}
        resumed_structured = resumed_structured.get("result", resumed_structured) or {}
        assert resumed_structured.get("session_id") == "sess-hitl"

    assert continued["run_id"] == "run-hitl"
    assert continued["session_id"] == "sess-hitl"
    # The resolution must round-trip: the component receives parsed RunRequirement
    # objects with the confirmation applied, not raw dicts or dropped fields.
    parsed = continued["requirements"]
    assert len(parsed) == 1 and isinstance(parsed[0], RunRequirement)
    assert parsed[0].confirmation is True
    assert parsed[0].tool_execution.confirmed is True
    assert parsed[0].tool_execution.tool_name == "send_email"


async def test_riding_pair_refuses_unpublished_components(monkeypatch):
    """The escalation guard: on an exposure-only server the riding pair must not act
    on roster components the deployer left off tools= -- continue_run could otherwise
    resume (and execute) a confirmation-gated tool on an unpublished component."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)
    public = _agent(id="public-agent")
    internal = _agent(id="internal-treasury")
    resumed: list = []

    async def fake_acontinue_run(**kwargs):
        resumed.append(kwargs)
        return RunOutput(agent_id="internal-treasury", content="resumed")

    internal.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[public, internal], mcp=MCPConfig(default_tools=False, tools=[public]))

    continued = await _call_tool(
        os,
        "continue_run",
        {"agent_id": "internal-treasury", "run_id": "r1", "session_id": "s1"},
        raise_on_error=False,
    )
    assert continued.is_error
    assert "published components" in str(continued.content)
    assert resumed == []

    cancelled = await _call_tool(
        os, "cancel_run", {"agent_id": "internal-treasury", "run_id": "r1"}, raise_on_error=False
    )
    assert cancelled.is_error
    assert "published components" in str(cancelled.content)


async def test_riding_pair_gate_is_keyed_by_kind(monkeypatch):
    """A published agent id does not unlock a same-id team: the gate matches
    (kind, id), never the bare id. The published agent's OWN run still cancels."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    agent = _agent(id="shared")
    agent.db = InMemoryDb()
    _seed_agent_run(agent, session_id="s1", run_id="r1")
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[agent]))

    refused = await _call_tool(
        os, "cancel_run", {"team_id": "shared", "run_id": "r1", "session_id": "s1"}, raise_on_error=False
    )
    assert refused.is_error
    assert "published components" in str(refused.content)

    allowed = await _call_tool(
        os, "cancel_run", {"agent_id": "shared", "run_id": "r1", "session_id": "s1"}, raise_on_error=False
    )
    assert not allowed.is_error
    assert reached == ["r1"]


async def test_pair_reaches_roster_when_core_is_served(monkeypatch):
    """With the default surface on, the pair keeps REST parity: run_agent reaches the
    whole roster, so continue_run/cancel_run do too -- the publication bound applies
    only when the pair exists purely via the ride-along."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)
    exposed = _agent(id="exposed-agent")
    unexposed = _agent(id="unexposed-agent")
    unexposed.db = InMemoryDb()
    _seed_agent_run(unexposed, session_id="s9", run_id="r9")
    resumed: list = []

    async def fake_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        resumed.append(run_id)
        return RunOutput(agent_id="unexposed-agent", run_id=run_id, session_id=session_id, content="resumed")

    unexposed.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[exposed, unexposed], mcp=MCPConfig(tools=[exposed]))

    result = await _call_tool(
        os,
        "continue_run",
        {"agent_id": "unexposed-agent", "run_id": "r9", "session_id": "s9"},
        raise_on_error=False,
    )
    assert not result.is_error
    assert resumed == ["r9"]


async def test_explicit_lifecycle_include_is_roster_wide(monkeypatch):
    """include_tags={'lifecycle'} under the default surface is the deployer explicitly
    choosing a roster-wide resume surface; adding exposures does not narrow it."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)
    exposed = _agent(id="exposed-agent")
    unexposed = _agent(id="unexposed-agent")
    unexposed.db = InMemoryDb()
    _seed_agent_run(unexposed, session_id="s7", run_id="r7")
    resumed: list = []

    async def fake_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        resumed.append(run_id)
        return RunOutput(agent_id="unexposed-agent", run_id=run_id, session_id=session_id, content="resumed")

    unexposed.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(
        agents=[exposed, unexposed],
        mcp=MCPConfig(include_tags={"lifecycle"}, tools=[exposed]),
    )

    result = await _call_tool(
        os,
        "continue_run",
        {"agent_id": "unexposed-agent", "run_id": "r7", "session_id": "s7"},
        raise_on_error=False,
    )
    assert not result.is_error
    assert resumed == ["r7"]


async def test_riding_pair_scope_route_uses_the_target_kind(monkeypatch):
    """cancel_run(team_id=...) gates on the teams route: an agents:run PAT is denied,
    teams:run passes -- the pair's scope path is built from the target's kind."""
    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    team = _team()
    os = AgentOS(teams=[team], mcp=MCPConfig(default_tools=False, tools=[team]))

    denied = await _call_tool(os, "cancel_run", {"team_id": "support-team", "run_id": "r1"}, raise_on_error=False)
    assert denied.is_error
    assert "teams:run" in str(denied.content)

    _patch_request(monkeypatch, _pat_request(["teams:run"]))
    past_gate = await _call_tool(
        os,
        "cancel_run",
        {"team_id": "support-team", "run_id": "r1", "session_id": "s1"},
        raise_on_error=False,
    )
    # teams:run clears the scope gate; the authenticated call then fails on run
    # ownership (no such run exists) -- proof the gate consulted the /teams/ route
    # and that the ownership check runs for the riding pair.
    assert past_gate.is_error
    assert "Insufficient permissions" not in str(past_gate.content)
    assert "Run not found" in str(past_gate.content)


def test_as_tool_override_still_validates_the_scope_unsafe_id():
    """The override renames the tool, but the component id is still the RBAC scope
    segment: a slash id would truncate the synthetic scope path and authorize a
    different component, so the id is validated even when a name override hides it."""
    slash = _agent(id="billing/admin", name="Billing Admin")
    os = AgentOS(agents=[slash], mcp=MCPConfig(default_tools=False, tools=[slash.as_tool(name="billing_admin")]))
    with pytest.raises(ValueError, match="scope segment") as exc_info:
        build_mcp_server(os)
    assert "billing/admin" in str(exc_info.value)


def test_team_in_agents_roster_is_refused_by_kind_mismatch():
    """A Team placed in AgentOS.agents (violating the annotation) must not run under
    agent scopes/SessionType: the identity fast path checks the concrete kind against
    the roster it was found in."""
    team = Team(id="squad", name="Squad", members=[_agent(id="m1")])
    os = AgentOS(agents=[team], mcp=MCPConfig(default_tools=False, tools=[team]))  # type: ignore[list-item]
    with pytest.raises(ValueError, match="by type but is registered"):
        build_mcp_server(os)


async def test_remote_run_propagates_the_caller_bearer_token_to_arun(monkeypatch):
    """Pins ARGUMENT PROPAGATION only: the exposed run tool passes the caller's bearer
    to Remote*.arun. The session-writability preflight is stubbed out because it
    dereferences the remote's network-backed ``db`` property before the token is used --
    end-to-end protected-remote runs do not work yet and are documented as unsupported
    (see the PR's protected-remote deferral note)."""
    from agno.agent.remote import RemoteAgent

    async def _gate(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_mod, "_assert_session_writable_mcp", _gate)
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)

    remote = RemoteAgent(base_url="http://127.0.0.1:9", agent_id="downstream")
    captured: dict = {}

    async def fake_arun(message, **kwargs):
        captured.update(auth_token=kwargs.get("auth_token"))
        return RunOutput(agent_id="downstream", content="ok", status=RunStatus.completed)

    remote.arun = fake_arun  # type: ignore[method-assign]
    os = AgentOS(agents=[remote], mcp=MCPConfig(default_tools=False, tools=[remote]))

    _patch_request(monkeypatch, _request_with_bearer("tok-123"))
    await _call_tool(os, "downstream", {"message": "hi"})
    assert captured["auth_token"] == "tok-123"


async def test_remote_cancel_propagates_the_caller_bearer_token(monkeypatch):
    """Pins ARGUMENT PROPAGATION only: cancel_run passes the caller's bearer to
    Remote*.acancel_run. The ownership verifier is stubbed out because a bearer-scoped
    caller fails closed on remote components today -- scoped remote cancellation is
    documented as unsupported (see the PR's protected-remote deferral note)."""
    from agno.agent.remote import RemoteAgent

    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)

    async def _verify(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_mod, "_make_run_ownership_verifier", lambda os: _verify)

    remote = RemoteAgent(base_url="http://127.0.0.1:9", agent_id="downstream")
    captured: dict = {}

    async def fake_acancel_run(run_id, auth_token=None, **kwargs):
        captured.update(run_id=run_id, auth_token=auth_token)
        return True

    remote.acancel_run = fake_acancel_run  # type: ignore[method-assign]
    os = AgentOS(agents=[remote], mcp=MCPConfig(default_tools=False, tools=[remote]))

    _patch_request(monkeypatch, _request_with_bearer("tok-cancel"))
    result = await _call_tool(os, "cancel_run", {"agent_id": "downstream", "run_id": "r1"}, raise_on_error=False)
    assert not result.is_error
    assert captured["auth_token"] == "tok-cancel"


async def test_remote_cancel_never_touches_the_local_queue(monkeypatch):
    """A published Remote* must not become a handle on the LOCAL queue: the tombstone is
    keyed on run_id alone, so firing it for a remote cancel would tombstone an unrelated
    local run (a hidden component's queued ticket) whose id the caller passed. Runs the
    real gate and the real cancel service -- only the HTTP hop is faked."""
    import agno.os.job_queue as job_queue_mod
    from agno.agent.remote import RemoteAgent

    tombstoned: list = []

    class FakeWorker:
        async def acancel_queued(self, run_id):
            tombstoned.append(run_id)

    monkeypatch.setattr(job_queue_mod, "get_active_queue_worker", lambda: FakeWorker())

    remote = RemoteAgent(base_url="http://127.0.0.1:9", agent_id="published-remote")
    forwarded: list = []

    async def fake_acancel_run(run_id, auth_token=None, **kwargs):
        forwarded.append(run_id)
        return True

    remote.acancel_run = fake_acancel_run  # type: ignore[method-assign]
    os = AgentOS(agents=[remote], mcp=MCPConfig(default_tools=False, tools=[remote]))

    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "published-remote", "run_id": "hidden-local-ticket"},
        raise_on_error=False,
    )
    assert not result.is_error
    # The cancel reached ONLY the downstream OS; the local queue was untouched.
    assert forwarded == ["hidden-local-ticket"]
    assert tombstoned == []


async def test_local_cancel_still_tombstones_the_queued_ticket(monkeypatch):
    """The counterpart pin: for a LOCAL component the queue tombstone must keep firing
    before the cancellation intent, or a waiting ticket gets claimed and burns an
    attempt before its first cancellation checkpoint."""
    import agno.os.job_queue as job_queue_mod
    from agno.os.services import runs as runs_service

    tombstoned: list = []

    class FakeWorker:
        async def acancel_queued(self, run_id):
            tombstoned.append(run_id)

    monkeypatch.setattr(job_queue_mod, "get_active_queue_worker", lambda: FakeWorker())

    agent = _agent(id="local-agent")
    cancelled: list = []

    async def fake_acancel_run(run_id, **kwargs):
        cancelled.append(run_id)
        return True

    agent.acancel_run = fake_acancel_run  # type: ignore[method-assign]
    await runs_service.cancel_component_run(agent, "queued-run")
    assert tombstoned == ["queued-run"]
    assert cancelled == ["queued-run"]


async def test_remote_workflow_run_propagates_the_caller_bearer_token(monkeypatch):
    """Pins ARGUMENT PROPAGATION only, for BOTH RemoteWorkflow.arun call sites: the
    exposed workflow tool and the generic run_workflow builtin each have their own
    branch, so each forward is pinned separately. Preflight stubbed as in the
    agent-side pin; end-to-end protected-remote runs are documented as unsupported."""
    from agno.workflow.remote import RemoteWorkflow

    async def _gate(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_mod, "_assert_session_writable_mcp", _gate)
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)

    remote = RemoteWorkflow(base_url="http://127.0.0.1:9", workflow_id="far-flow")
    captured: list = []

    async def fake_arun(message, **kwargs):
        captured.append(kwargs.get("auth_token"))
        return WorkflowRunOutput(workflow_id="far-flow", content="ok", status=RunStatus.completed)

    remote.arun = fake_arun  # type: ignore[method-assign]
    # default_tools on so the generic run_workflow registers alongside the exposure.
    os = AgentOS(workflows=[remote], mcp=MCPConfig(tools=[remote]))

    _patch_request(monkeypatch, _request_with_bearer("tok-wf"))
    await _call_tool(os, "far-flow", {"message": "go"})
    await _call_tool(os, "run_workflow", {"workflow_id": "far-flow", "message": "go"})
    assert captured == ["tok-wf", "tok-wf"]


def test_wrong_kind_external_adapter_entry_raises_too():
    """BaseExternalAgent adapters name their kind (agents): a non-roster adapter must
    not resolve to a same-id roster TEAM."""
    from agno.agents.base import BaseExternalAgent

    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    stray = BaseExternalAgent(name="Stray Adapter", id="shared")
    os = AgentOS(agents=[_agent()], teams=[team], mcp=MCPConfig(default_tools=False, tools=[stray]))
    with pytest.raises(ValueError, match="different kind"):
        build_mcp_server(os)


def test_factory_and_external_adapter_have_as_tool():
    """Every exposure-capable family carries the as_tool escape hatch the error
    messages prescribe -- factories and external adapters included."""
    from agno.agent.factory import AgentFactory
    from agno.agents.base import BaseExternalAgent
    from agno.db.in_memory.in_memory_db import InMemoryDb
    from agno.tools import ComponentTool

    factory = AgentFactory(id="fab", db=InMemoryDb(), factory=lambda ctx: _agent(id="fab"))
    marker = factory.as_tool(name="build_fab")
    assert isinstance(marker, ComponentTool) and marker.name == "build_fab"

    adapter = BaseExternalAgent(name="Ext", id="ext-1")
    marker2 = adapter.as_tool(description="external")
    assert isinstance(marker2, ComponentTool) and marker2.description == "external"


def test_component_tool_in_agent_or_team_tools_raises():
    """as_tool() markers belong in MCPConfig.tools; the Agent/Team tool chains would
    otherwise silently skip them (nothing registers). The guard lives at the API
    boundary -- every path that populates a concrete tools list (the constructor,
    set_tools, add_tool) -- so the mistake fails loudly where it is made, with a pointer
    to the right place, and the per-run tool loop stays guard-free."""
    marker = _agent(id="helper").as_tool(name="ask_helper")

    # The construction boundary itself: Agent(tools=[marker]) must raise, not
    # construct silently and defer the failure to set_tools or the first run.
    with pytest.raises(ValueError, match="MCPConfig"):
        Agent(id="boss", name="Boss", tools=[marker])
    with pytest.raises(ValueError, match="MCPConfig"):
        Team(id="squad", name="Squad", members=[_agent(id="m1")], tools=[marker])

    boss = Agent(id="boss", name="Boss")
    with pytest.raises(ValueError, match="MCPConfig"):
        boss.set_tools([marker])
    with pytest.raises(ValueError, match="MCPConfig"):
        boss.add_tool(marker)

    team = Team(id="squad", name="Squad", members=[_agent(id="m1")])
    with pytest.raises(ValueError, match="MCPConfig"):
        team.set_tools([marker])
    with pytest.raises(ValueError, match="MCPConfig"):
        team.add_tool(marker)


# ==================== Cancellation is bound to the run, not just the named component ====================


async def test_cancel_refuses_a_run_of_an_unpublished_component(monkeypatch):
    """The publication bound governs which component a caller may NAME; the run-ownership
    gate governs which RUN they may act on. Naming a published agent must not let a
    caller cancel a run that belongs to an unpublished team -- even on the default
    (non-isolated) deployment, and even sharing one db. Runs the real gate (no stub of
    _make_run_ownership_verifier)."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    db = InMemoryDb()
    public = _agent(id="public-agent", name="Public")
    public.db = db
    hidden = Team(id="hidden-team", name="Hidden", members=[_agent(id="m1")])
    hidden.db = db
    _seed_team_run(hidden, session_id="hidden-sess", run_id="hidden-run")

    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], teams=[hidden], mcp=MCPConfig(default_tools=False, tools=[public]))

    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "hidden-run", "session_id": "hidden-sess"},
        raise_on_error=False,
    )
    assert result.is_error
    assert "Run not found" in str(result.content)
    # The hidden run was neither cancelled nor queue-tombstoned: the gate refused before
    # cancel_component_run (which does both) could run.
    assert reached == []


async def test_cancel_of_the_named_components_own_run_succeeds(monkeypatch):
    """The legitimate path still works: a run that genuinely belongs to the published
    component passes the binding and reaches cancellation."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    public = _agent(id="public-agent", name="Public")
    public.db = InMemoryDb()
    _seed_agent_run(public, session_id="own-sess", run_id="own-run")

    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], mcp=MCPConfig(default_tools=False, tools=[public]))

    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "own-run", "session_id": "own-sess"},
        raise_on_error=False,
    )
    assert not result.is_error
    assert reached == ["own-run"]


async def test_cancel_cross_kind_same_id_is_rejected(monkeypatch):
    """AgentOS allows an agent and a team to share an id. Naming the published AGENT must
    not reach a run that lives under the same-id TEAM's session."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    db = InMemoryDb()
    agent = _agent(id="shared", name="The Agent")
    agent.db = db
    team = Team(id="shared", name="The Team", members=[_agent(id="m1")])
    team.db = db
    _seed_team_run(team, session_id="team-sess", run_id="team-run")

    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    # Expose only the agent; the team is unpublished.
    os = AgentOS(agents=[agent], teams=[team], mcp=MCPConfig(default_tools=False, tools=[agent]))

    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "shared", "run_id": "team-run", "session_id": "team-sess"},
        raise_on_error=False,
    )
    assert result.is_error
    assert "Run not found" in str(result.content)
    assert reached == []


async def test_cancel_of_an_in_flight_run_succeeds_for_admin(monkeypatch):
    """THE case cancellation exists for: a foreground run persists no row until it
    pauses or finishes, so for the whole window where cancel is meaningful there is
    nothing to bind. An admin / non-isolated caller must still cancel (REST parity) --
    run_id-only, and mid-conversation where the session row exists but the current
    run's row does not yet."""
    from agno.db.in_memory.in_memory_db import InMemoryDb
    from agno.session.agent import AgentSession

    public = _agent(id="public-agent", name="Public")
    public.db = InMemoryDb()
    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], mcp=MCPConfig(default_tools=False, tools=[public]))

    # Cancel-before-start / burst cancel: no session_id, no rows anywhere.
    result = await _call_tool(
        os, "cancel_run", {"agent_id": "public-agent", "run_id": "in-flight-1"}, raise_on_error=False
    )
    assert not result.is_error

    # Mid-conversation: the session persisted on an earlier turn, the live run has no row.
    public.db.upsert_session(AgentSession(session_id="live-sess", agent_id=public.id))
    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "in-flight-2", "session_id": "live-sess"},
        raise_on_error=False,
    )
    assert not result.is_error
    assert reached == ["in-flight-1", "in-flight-2"]


async def test_scoped_caller_cancel_requires_session_ownership(monkeypatch):
    """A user-isolation-scoped caller must prove they own the session the run lives in
    (the REST scoped rule): no session_id fails closed, and a session_id whose run row
    is absent fails closed too -- never a global intent on someone else's run."""
    from agno.db.in_memory.in_memory_db import InMemoryDb
    from agno.session.agent import AgentSession

    _patch_request(monkeypatch, _request_with_bearer("tok-scoped", scopes=["agents:run"]))
    public = _agent(id="public-agent", name="Public")
    public.db = InMemoryDb()
    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], mcp=MCPConfig(default_tools=False, tools=[public]))

    result = await _call_tool(
        os, "cancel_run", {"agent_id": "public-agent", "run_id": "some-run"}, raise_on_error=False
    )
    assert result.is_error
    assert "session_id is required" in str(result.content)

    # A session this caller does NOT own (no user_id stamp -> not theirs under isolation).
    public.db.upsert_session(AgentSession(session_id="other-sess", agent_id=public.id))
    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "some-run", "session_id": "other-sess"},
        raise_on_error=False,
    )
    assert result.is_error
    assert "Run not found" in str(result.content)
    assert reached == []

    # The legitimate scoped path: their own session holding the run passes the gate.
    _seed_agent_run(public, session_id="own-sess", run_id="own-run", user_id="sa:bot")
    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "own-run", "session_id": "own-sess"},
        raise_on_error=False,
    )
    assert not result.is_error
    assert reached == ["own-run"]


async def test_factory_run_cancels_statically_without_building_the_factory(monkeypatch):
    """A factory component's run must be cancellable over MCP without invoking the
    factory -- cancellation is a run_id-keyed global intent. Generic resolution would
    build the factory (400ing a required-input factory), so cancel must take the static
    path the REST factory-cancel routes use. Real gate, real static cancel."""
    from pydantic import BaseModel, Field

    from agno.agent.factory import AgentFactory
    from agno.db.in_memory.in_memory_db import InMemoryDb

    class RequiredInput(BaseModel):
        topic: str = Field(...)

    built: list = []

    def _build(ctx):
        built.append(ctx)  # must never run for a cancel
        return _agent(id="made-to-order")

    factory = AgentFactory(id="made-to-order", db=InMemoryDb(), factory=_build, input_schema=RequiredInput)

    import agno.os.job_queue as job_queue_mod

    tombstoned: list = []

    class FakeWorker:
        async def acancel_queued(self, run_id):
            tombstoned.append(run_id)

    monkeypatch.setattr(job_queue_mod, "get_active_queue_worker", lambda: FakeWorker())

    import agno.agent._run as agent_run_mod

    cancelled: list = []

    async def fake_static_cancel(run_id):
        cancelled.append(run_id)
        return True

    monkeypatch.setattr(agent_run_mod, "acancel_run", fake_static_cancel)

    os = AgentOS(agents=[factory], mcp=MCPConfig(default_tools=False, tools=[factory]))
    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "made-to-order", "run_id": "factory-run"},
        raise_on_error=False,
    )
    assert not result.is_error, str(result.content)
    assert built == [], "the factory was invoked during a cancel"
    assert tombstoned == ["factory-run"]
    assert cancelled == ["factory-run"]


async def test_scoped_caller_cannot_cancel_another_users_run_in_a_matching_session(monkeypatch):
    """The scoped tier pins per-USER ownership, not just the component binding: a run
    that lives in a session belonging to a DIFFERENT user (same component) must be
    refused. Without this, the user_id pin in verify_run_ownership is untested."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    _patch_request(monkeypatch, _request_with_bearer("tok-bob", scopes=["agents:run"]))
    public = _agent(id="public-agent", name="Public")
    public.db = InMemoryDb()
    # A run owned by alice, in a session bound to the SAME component the caller names.
    _seed_agent_run(public, session_id="alice-sess", run_id="alice-run", user_id="alice")

    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], mcp=MCPConfig(default_tools=False, tools=[public]))

    # Caller is sa:bot (from _request_with_bearer), not alice.
    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "alice-run", "session_id": "alice-sess"},
        raise_on_error=False,
    )
    assert result.is_error
    assert "Run not found" in str(result.content)
    assert reached == []


async def test_admin_binding_fails_open_when_the_db_read_raises(monkeypatch):
    """verify_persisted_run_binding is deliberately fail-OPEN on a db read error: a
    broken db must not make a live run uncancellable (REST admin does no db read at
    all). Pin that direction so deleting the try/except is caught."""
    from agno.db.in_memory.in_memory_db import InMemoryDb
    from agno.os.services import sessions as sessions_service

    class ExplodingDb(InMemoryDb):
        def get_run(self, run_id, deserialize=True):
            raise RuntimeError("db is on fire")

    public = _agent(id="public-agent", name="Public")
    public.db = ExplodingDb()

    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], mcp=MCPConfig(default_tools=False, tools=[public]))

    # Admin / non-isolated caller (no scoped request patched): the read raises, but the
    # cancel must still proceed rather than fail closed.
    result = await _call_tool(
        os,
        "cancel_run",
        {"agent_id": "public-agent", "run_id": "some-run", "session_id": "s1"},
        raise_on_error=False,
    )
    assert not result.is_error, str(result.content)
    assert reached == ["some-run"]

    # And the helper itself proceeds (no RunOwnershipError) on a raising db.
    await sessions_service.verify_persisted_run_binding(
        ExplodingDb(), run_id="x", component_type="agents", component_id="public-agent"
    )


async def test_cancel_of_a_hidden_persisted_run_is_refused_regardless_of_session_id(monkeypatch):
    """The admin-tier binding keys on the run row looked up by run_id -- the one value
    the caller must supply truthfully. Omitting session_id or passing a bogus one must
    not dodge the refusal the correct session_id gets."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    db = InMemoryDb()
    public = _agent(id="public-agent", name="Public")
    public.db = db
    hidden = Team(id="hidden-team", name="Hidden", members=[_agent(id="m1")])
    hidden.db = db
    _seed_team_run(hidden, session_id="hidden-sess", run_id="hidden-run")

    reached: list = []

    async def spy_cancel(component, run_id, auth_token=None):
        reached.append(run_id)

    monkeypatch.setattr(mcp_mod.run_service, "cancel_component_run", spy_cancel)
    os = AgentOS(agents=[public], teams=[hidden], mcp=MCPConfig(default_tools=False, tools=[public]))

    for session_id in (None, "no-such-session", "hidden-sess"):
        args = {"agent_id": "public-agent", "run_id": "hidden-run"}
        if session_id is not None:
            args["session_id"] = session_id
        result = await _call_tool(os, "cancel_run", args, raise_on_error=False)
        assert result.is_error, f"session_id={session_id!r} dodged the binding"
        assert "Run not found" in str(result.content)
    assert reached == []


async def test_continue_run_refuses_a_run_of_an_unpublished_component():
    """continue_run gets the same binding as cancel: naming a published agent must not
    resume a run that belongs to an unpublished team."""
    from agno.db.in_memory.in_memory_db import InMemoryDb

    db = InMemoryDb()
    public = _agent(id="public-agent", name="Public")
    public.db = db
    hidden = Team(id="hidden-team", name="Hidden", members=[_agent(id="m1")])
    hidden.db = db
    _seed_team_run(hidden, session_id="hidden-sess", run_id="hidden-run")

    resumed: list = []

    async def fake_acontinue_run(**kwargs):
        resumed.append(kwargs.get("run_id"))
        return RunOutput(agent_id="public-agent", content="resumed")

    public.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[public], teams=[hidden], mcp=MCPConfig(default_tools=False, tools=[public]))

    result = await _call_tool(
        os,
        "continue_run",
        {"agent_id": "public-agent", "run_id": "hidden-run", "session_id": "hidden-sess"},
        raise_on_error=False,
    )
    assert result.is_error
    assert "Run not found" in str(result.content)
    assert resumed == []


async def test_riding_lifecycle_pair_is_scope_gated(monkeypatch):
    """continue_run/cancel_run ride along with every exposure, so their scope gate is
    the only thing between a read-only PAT and run mutation -- pin the refusal."""
    _patch_request(monkeypatch, _pat_request(["sessions:read"]))
    agent = _agent()
    os = AgentOS(agents=[agent], mcp=MCPConfig(default_tools=False, tools=[agent]))

    continued = await _call_tool(
        os, "continue_run", {"agent_id": "chief", "run_id": "r1", "session_id": "s1"}, raise_on_error=False
    )
    assert continued.is_error
    assert "Insufficient permissions" in str(continued.content)

    cancelled = await _call_tool(
        os, "cancel_run", {"agent_id": "chief", "run_id": "r1", "session_id": "s1"}, raise_on_error=False
    )
    assert cancelled.is_error
    assert "Insufficient permissions" in str(cancelled.content)


async def test_remote_workflow_runs_through_the_non_streaming_branch(monkeypatch):
    """RemoteWorkflow.arun is awaited directly -- there is no local step stream to
    consume -- and the result still flows through build_run_tool_result with a minted
    session and the workflow id attached. The ownership gate is stubbed: it reads the
    component's db, which on a remote is a network-backed property."""
    from agno.workflow.remote import RemoteWorkflow

    async def _gate(*args, **kwargs):
        return None

    monkeypatch.setattr(mcp_mod, "_assert_session_writable_mcp", _gate)
    remote = RemoteWorkflow(base_url="http://127.0.0.1:9", workflow_id="remote-wf")
    captured: dict = {}

    async def fake_arun(message, **kwargs):
        captured.update(message=message, session_id=kwargs.get("session_id"))
        return WorkflowRunOutput(
            workflow_id="remote-wf",
            run_id="r-remote",
            session_id=kwargs.get("session_id"),
            content="remote done",
            status=RunStatus.completed,
        )

    remote.arun = fake_arun  # type: ignore[method-assign]
    os = AgentOS(workflows=[remote], mcp=MCPConfig(default_tools=False, tools=[remote]))

    result = await _call_tool(os, "remote-wf", {"message": "go"})
    structured = result.structured_content or {}
    structured = structured.get("result", structured) or {}
    assert captured["message"] == "go"
    assert captured["session_id"]
    assert structured.get("workflow_id") == "remote-wf"
    assert structured.get("status") == RunStatus.completed.value
