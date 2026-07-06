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

import asyncio  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Any, AsyncIterator, Iterator, Optional  # noqa: E402
from uuid import uuid4  # noqa: E402

import httpx  # noqa: E402
from fastmcp import Client, Context  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.db.schemas.service_accounts import ServiceAccount  # noqa: E402
from agno.models.base import Model  # noqa: E402
from agno.models.message import MessageMetrics  # noqa: E402
from agno.models.response import ModelResponse  # noqa: E402
from agno.os import AgentOS, MCPServerConfig  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402
from agno.os.mcp import _resolve_user_id, build_mcp_server, get_mcp_server  # noqa: E402
from agno.os.service_accounts import ServiceAccountVerification, VerificationStatus, generate_token  # noqa: E402
from agno.os.settings import AgnoAPISettings  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.run.workflow import WorkflowRunOutput  # noqa: E402
from agno.team.team import Team  # noqa: E402
from agno.tools import tool  # noqa: E402
from agno.workflow.step import Step  # noqa: E402
from agno.workflow.workflow import Workflow  # noqa: E402

# The full set of built-in tools, keyed by their tag group. The surface is deliberately
# 8 tools: an operator surface for LLM frontends, not a database console.
CORE_TOOLS = {"get_agentos_config", "run_agent", "run_team", "run_workflow", "continue_run", "cancel_run"}
SESSION_TOOLS = {"get_sessions", "get_session_runs"}
ALL_BUILTIN_TOOLS = CORE_TOOLS | SESSION_TOOLS


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


async def _tool_names(os: AgentOS) -> set:
    async with Client(build_mcp_server(os)) as client:
        return {t.name for t in await client.list_tools()}


async def _call_tool(os: AgentOS, name: str, args: dict):
    async with Client(build_mcp_server(os)) as client:
        return await client.call_tool(name, args)


def _stub_arun(component, run_output):
    """Replace ``component.arun`` with a streaming stub that records the identity kwargs.

    The run tools consume ``arun`` as a stream (``stream=True, yield_run_output=True``),
    so the stub is an async generator whose last item is the final run output.
    """
    captured: dict = {}

    async def fake_arun(message, **kwargs):
        captured["message"] = message
        captured["user_id"] = kwargs.get("user_id")
        captured["session_id"] = kwargs.get("session_id")
        # Agent/team tools must request the final output explicitly; workflows have no
        # yield_run_output kwarg (the consumer accepts a bare WorkflowRunOutput instead).
        # Gating on this catches a regression where the tools stop passing it.
        if kwargs.get("yield_run_output") or isinstance(run_output, WorkflowRunOutput):
            yield run_output

    component.arun = fake_arun  # type: ignore[method-assign]
    return captured


@pytest.fixture(autouse=True)
def _resolve_by_identity(monkeypatch):
    """Resolve run tools to the in-memory (stubbed) component instance.

    Production ``_resolve_run_component`` deep-copies (create_fresh) and consults the DB
    registry, which would discard the ``.arun`` stub these tests set on the instance. The
    real resolution behaviour (create_fresh isolation, db/registry, factories) is covered
    by test_mcp_resolution.py.
    """

    async def _resolve(os, kind, component_id, *, user_id, session_id):
        pool = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}.get(kind) or []
        for component in pool:
            if getattr(component, "id", None) == component_id:
                return component
        singular = {"agents": "Agent", "teams": "Team", "workflows": "Workflow"}[kind]
        raise Exception(f"{singular} {component_id} not found")

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)


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


async def test_exclude_tags_drops_session_builtins():
    os = AgentOS(agents=[_agent()], enable_mcp_server=True, mcp_config=MCPServerConfig(exclude_tags={"session"}))
    names = await _tool_names(os)
    assert names == CORE_TOOLS
    assert not (names & SESSION_TOOLS)


def test_unknown_include_tag_is_rejected():
    """A typo like ``{"sessions"}`` (plural) would silently produce an empty server. The
    ``MCPBuiltinTag`` Literal makes pydantic reject it at construction."""
    with pytest.raises(ValueError, match="Input should be 'core' or 'session'"):
        MCPServerConfig(include_tags={"sessions"})


def test_removed_memory_tag_is_rejected():
    """The memory tools were removed from the MCP surface; the old tag must fail loudly
    instead of silently scoping nothing."""
    with pytest.raises(ValueError, match="Input should be 'core' or 'session'"):
        MCPServerConfig(exclude_tags={"memory"})


def test_known_tags_are_accepted():
    """Sanity: the typed fields don't fight the documented values."""
    MCPServerConfig(include_tags={"core", "session"})
    MCPServerConfig(exclude_tags={"core"})


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


def test_detached_trace_context_starts_a_new_root_trace():
    """The MCP tracing fix: `_detached_trace_context` makes a span started inside it the
    ROOT of a new trace. FastMCP wraps every tool call in an identity-less `tools/call ...`
    span; without detaching, the agno run span nests under it and the trace layer (which
    reads a trace's identity from its root span) attributes the run to that protocol span,
    producing a NULL/mislabeled trace. Detaching makes the run its own root, attributed like
    a REST run."""
    pytest.importorskip("opentelemetry")
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("tools/call run_agent") as protocol_span:
        protocol_ctx = protocol_span.get_span_context()
        assert protocol_ctx.is_valid

        with mcp_mod._detached_trace_context():
            # No current recording span inside the detach -> the run span cannot inherit
            # FastMCP's protocol span.
            assert not otel_trace.get_current_span().get_span_context().is_valid
            with tracer.start_as_current_span("Demo.arun") as run_span:
                assert run_span.parent is None, "run span must be a root, not nested"
                assert run_span.get_span_context().trace_id != protocol_ctx.trace_id

        # The FastMCP span is current again once the run completes.
        assert otel_trace.get_current_span().get_span_context().trace_id == protocol_ctx.trace_id


# ==================== Session minting (omitted session_id -> fresh session per call) ====================
#
# The run tools must mint a fresh session_id when the caller omits one, exactly like the
# REST run routes, rather than forwarding session_id=None and letting the component fall
# back to its sticky per-instance session. The autouse _resolve_by_identity fixture hands
# the run tools the SHARED instance -- the same resolution shape as an AgentProtocol /
# RemoteAgent / RemoteTeam / remote workflow, which get_agent_by_id returns without a
# per-call deep_copy -- so these tests exercise exactly the path where the bug (every
# "sessionless" call collapsing into one ever-growing conversation) manifested.


class _MockModel(Model):
    """Minimal offline model: returns a canned response with no network call, so the run
    tools can drive the real ``arun`` / ``initialize_session`` path in a unit test."""

    def __init__(self) -> None:
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._r = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    def get_system_message_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    async def aget_instructions_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    async def aget_system_message_for_model(self, *a: Any, **k: Any) -> Any:
        return None

    def parse_args(self, *a: Any, **k: Any) -> dict:
        return {}

    def invoke(self, *a: Any, **k: Any) -> ModelResponse:
        return self._r

    async def ainvoke(self, *a: Any, **k: Any) -> ModelResponse:
        return self._r

    def invoke_stream(self, *a: Any, **k: Any) -> Iterator[ModelResponse]:
        yield self._r

    async def ainvoke_stream(self, *a: Any, **k: Any) -> AsyncIterator[ModelResponse]:
        yield self._r
        return

    def _parse_provider_response(self, response: Any, **k: Any) -> ModelResponse:
        return self._r

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._r


def _capture_run_sessions(component, run_output) -> list:
    """Record the session_id the run tool hands ``arun`` on every call.

    Returns a list appended to per call, so distinctness across sequential and parallel
    calls can be asserted. Mirrors ``_stub_arun`` but keeps every call's session_id instead
    of only the last. Before the fix the tool forwarded ``session_id=None``; after it, a
    fresh uuid per call.
    """
    sessions: list = []

    async def fake_arun(message, **kwargs):
        sessions.append(kwargs.get("session_id"))
        if kwargs.get("yield_run_output") or isinstance(run_output, WorkflowRunOutput):
            yield run_output

    component.arun = fake_arun  # type: ignore[method-assign]
    return sessions


def _result_session_id(result) -> Optional[str]:
    structured = result.structured_content or {}
    return (structured.get("result", structured) or {}).get("session_id")


async def test_run_agent_mints_a_new_session_when_omitted():
    """Omitting session_id makes run_agent pass a fresh (non-None) session_id to arun."""
    agent = _agent()
    sessions = _capture_run_sessions(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    await _call_tool(os, "run_agent", {"agent_id": agent.id, "message": "hi"})

    assert len(sessions) == 1
    assert sessions[0] is not None and sessions[0] != ""


async def test_run_agent_omitted_session_is_distinct_per_call():
    """Two sessionless run_agent calls against the SAME instance get two distinct sessions
    -- the core regression: sessionless runs must not collapse into one shared conversation."""
    agent = _agent()
    sessions = _capture_run_sessions(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("run_agent", {"agent_id": agent.id, "message": "one"})
        await client.call_tool("run_agent", {"agent_id": agent.id, "message": "two"})

    assert all(s for s in sessions)  # both non-empty
    assert sessions[0] != sessions[1]


async def test_run_agent_parallel_omitted_sessions_are_distinct():
    """Concurrent sessionless run_agent calls still mint distinct sessions (no shared default)."""
    agent = _agent()
    sessions = _capture_run_sessions(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        await asyncio.gather(
            client.call_tool("run_agent", {"agent_id": agent.id, "message": "a"}),
            client.call_tool("run_agent", {"agent_id": agent.id, "message": "b"}),
        )

    assert len(sessions) == 2
    assert all(s for s in sessions)
    assert sessions[0] != sessions[1]


async def test_run_agent_explicit_session_is_reused():
    """An explicit session_id is honoured verbatim across calls -- continuity still works."""
    agent = _agent()
    sessions = _capture_run_sessions(agent, RunOutput(content="ok"))
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("run_agent", {"agent_id": agent.id, "message": "one", "session_id": "fixed-1"})
        await client.call_tool("run_agent", {"agent_id": agent.id, "message": "two", "session_id": "fixed-1"})

    assert sessions == ["fixed-1", "fixed-1"]


async def test_run_team_omitted_session_is_distinct_per_call():
    """run_team applies the same fix: sessionless calls mint distinct sessions."""
    team = Team(id="demo-team", name="Demo Team", members=[_agent()])
    sessions = _capture_run_sessions(team, TeamRunOutput(content="ok"))
    os = AgentOS(teams=[team], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("run_team", {"team_id": team.id, "message": "one"})
        await client.call_tool("run_team", {"team_id": team.id, "message": "two"})

    assert all(s for s in sessions)
    assert sessions[0] != sessions[1]


async def test_run_team_explicit_session_is_reused():
    team = Team(id="demo-team", name="Demo Team", members=[_agent()])
    sessions = _capture_run_sessions(team, TeamRunOutput(content="ok"))
    os = AgentOS(teams=[team], enable_mcp_server=True)

    await _call_tool(os, "run_team", {"team_id": team.id, "message": "hi", "session_id": "team-sess"})

    assert sessions == ["team-sess"]


async def test_run_workflow_omitted_session_is_distinct_per_call():
    """run_workflow applies the same fix: sessionless calls mint distinct sessions."""
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    sessions = _capture_run_sessions(workflow, WorkflowRunOutput(content="ok"))
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        await client.call_tool("run_workflow", {"workflow_id": workflow.id, "message": "one"})
        await client.call_tool("run_workflow", {"workflow_id": workflow.id, "message": "two"})

    assert all(s for s in sessions)
    assert sessions[0] != sessions[1]


async def test_run_workflow_explicit_session_is_reused():
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    sessions = _capture_run_sessions(workflow, WorkflowRunOutput(content="ok"))
    os = AgentOS(workflows=[workflow], enable_mcp_server=True)

    await _call_tool(os, "run_workflow", {"workflow_id": workflow.id, "message": "hi", "session_id": "wf-sess"})

    assert sessions == ["wf-sess"]


async def test_run_agent_omitted_session_end_to_end_returns_distinct_ids(monkeypatch):
    """End-to-end reproduction: driving the REAL arun on a shared instance, two sessionless
    calls return two distinct session_ids in structuredContent, and nothing sticks to the
    instance (the tool always hands arun a concrete session, so the sticky branch never fires)."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)
    agent = Agent(id="demo-agent", name="Demo Agent", model=_MockModel())
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        r1 = await client.call_tool("run_agent", {"agent_id": agent.id, "message": "one"})
        r2 = await client.call_tool("run_agent", {"agent_id": agent.id, "message": "two"})

    s1, s2 = _result_session_id(r1), _result_session_id(r2)
    assert s1 and s2 and s1 != s2
    # No sticky session leaked onto the shared instance.
    assert agent.session_id is None


async def test_continue_run_targets_the_given_session_and_never_mints(monkeypatch):
    """continue_run must resume the exact session it was handed, never mint a new one --
    so the PAUSED -> continue_run HITL flow resolves the original run/session."""
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: None)
    agent = _agent()
    captured: dict = {}

    async def fake_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        captured.update(run_id=run_id, session_id=session_id)
        return RunOutput(run_id=run_id, session_id=session_id, content="resumed")

    agent.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[agent], enable_mcp_server=True)

    result = await _call_tool(os, "continue_run", {"run_id": "run-1", "session_id": "orig-sess", "agent_id": agent.id})

    assert captured["session_id"] == "orig-sess"
    assert _result_session_id(result) == "orig-sess"


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
    """Drive the full AgentOS app and hit /mcp through the whole stack.

    Auth lives on the parent app's single AuthMiddleware (not the mounted /mcp app),
    so requests must flow through the full app for the auth layer to run.
    """
    app = os.get_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        # base_url sets the default Host header. Use localhost so the default-on
        # rebinding protection for open servers allows it; host-gating tests override
        # the Host explicitly to exercise the reject path.
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
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


def test_authorize_without_jwt_warns_at_startup(monkeypatch):
    """``authorize`` with ``authorization=False`` is a silent foot-gun: nothing populates
    ``request.state.user_id``, so the gate sees ``None`` on every call. Warn at startup so
    the user notices before discovering that every request is rejected (or, worse, allowed).
    """
    warnings: list = []
    monkeypatch.setattr("agno.utils.log.log_warning", lambda msg, *a, **kw: warnings.append(msg))

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        authorization=False,
        mcp_config=MCPServerConfig(
            tools=[_ok_tool],
            enable_builtin_tools=False,
            authorize=lambda user_id: user_id == "owner",
        ),
    )
    get_mcp_server(os)

    relevant = [w for w in warnings if "authorize" in w and "authorization=False" in w]
    assert relevant, f"expected an authorize-without-JWT warning, got: {warnings}"


def test_authorize_with_jwt_does_not_warn(monkeypatch):
    """Sanity check: the warning is only emitted in the misconfigured case."""
    warnings: list = []
    monkeypatch.setattr("agno.utils.log.log_warning", lambda msg, *a, **kw: warnings.append(msg))

    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["dummy"]),
        mcp_config=MCPServerConfig(
            tools=[_ok_tool],
            enable_builtin_tools=False,
            authorize=lambda user_id: user_id == "owner",
        ),
    )
    get_mcp_server(os)

    relevant = [w for w in warnings if "authorize" in w and "authorization=False" in w]
    assert not relevant, f"unexpected authorize-without-JWT warning: {relevant}"


def _parent_auth_middleware(os: AgentOS):
    """The single AuthMiddleware on the parent app (covers REST + the mounted /mcp)."""
    app = os.get_app()
    return next(m for m in app.user_middleware if m.cls.__name__ == "AuthMiddleware")


def test_auth_middleware_carries_jwt_constraints():
    """``user_isolation`` / ``audience`` / ``admin_scope`` from ``AuthorizationConfig`` reach
    the single parent-app auth layer, which covers /mcp -- so a token that passes REST's
    audience check (or honours user_isolation / a custom admin scope) is held to the same
    constraints over /mcp (same middleware instance, no second layer to drift)."""
    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=["dummy"],
            user_isolation=True,
            audience="myapi",
            admin_scope="admin",
        ),
    )
    mw = _parent_auth_middleware(os)
    assert mw.kwargs.get("user_isolation") is True
    assert mw.kwargs.get("audience") == "myapi"
    assert mw.kwargs.get("admin_scope") == "admin"


def test_auth_middleware_omits_unset_kwargs():
    """Unset optional kwargs must not be forwarded -- they shouldn't override the
    middleware's own defaults."""
    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["dummy"]),
    )
    mw = _parent_auth_middleware(os)
    assert "user_isolation" not in mw.kwargs
    assert "audience" not in mw.kwargs
    assert "admin_scope" not in mw.kwargs


def test_mounted_mcp_app_carries_no_auth_middleware():
    """Auth lives only on the parent app; the mounted /mcp app has no auth layer of its own."""
    os = AgentOS(
        agents=[_agent()],
        enable_mcp_server=True,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=["dummy"]),
        settings=AgnoAPISettings(os_security_key="test-key"),
    )
    names = [m.cls.__name__ for m in get_mcp_server(os).user_middleware]
    assert "AuthMiddleware" not in names
    assert "JWTMiddleware" not in names
    assert "_MCPKeyAuthMiddleware" not in names


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


async def test_open_server_gets_default_rebinding_protection():
    """An OPEN server (no JWT, no security key) with no allowed_hosts still gets localhost-only
    protection by default: a rebound / non-localhost Host is rejected. This is the one config a
    malicious web page could drive, so it must not serve anonymous cross-host requests."""
    async with _mcp_http_client(_security_os()) as client:
        rejected = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_headers(host="evil.example.com"))
        allowed = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_headers(host="localhost:7777"))
    assert rejected.status_code == 400
    assert "invalid_host" in rejected.text
    assert allowed.status_code == 200


async def test_authenticated_server_does_not_gate_hosts_by_default():
    """A server with auth configured relies on the bearer token to defeat rebinding, so its real
    deployed hostname is not gated without allowed_hosts (no 421/400 regression). The security key
    still guards the request; the Host itself passes."""
    async with _mcp_http_client(_auth_os(security_key="test-key")) as client:
        response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers={**_bearer("test-key"), "Host": "myapp.example.com"}
        )
    assert response.status_code == 200


def test_manual_jwt_middleware_on_base_app_is_not_open():
    """A base_app carrying a manually installed JWTMiddleware is authenticated, so /mcp must not
    be treated as open: no default localhost host gate is added (its deployed hostname would
    otherwise be 400'd). Mirrors get_effective_auth_mode / the /info auth-mode detection, which
    both recognize the manual-middleware path."""
    from fastapi import FastAPI

    from agno.os.middleware.jwt import JWTMiddleware

    base = FastAPI()
    base.add_middleware(JWTMiddleware, validate=False)  # validate=False counts as a JWT key source
    os = AgentOS(
        agents=[_agent()],
        base_app=base,
        enable_mcp_server=True,
        mcp_config=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False),
    )
    assert mcp_mod._mcp_server_is_open(os) is False
    names = [m.cls.__name__ for m in get_mcp_server(os).user_middleware]
    assert "_MCPTransportSecurityMiddleware" not in names


# ==================== Security key + service account auth (non-JWT modes) ====================

# Router dependencies never run for mounted sub-apps, so in non-JWT modes /mcp gets its own
# middleware mirroring the REST rules (agno.os.auth.get_authentication_dependency).


def _sqlite_db(tmp_path):
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=str(tmp_path / "mcp_auth_test.db"))


def _mint_pat(db, name="mcp-bot", revoked=False):
    """Create a service account directly in the db and return its plaintext token."""
    plaintext, token_hash, token_prefix = generate_token()
    now = int(time.time())
    account = ServiceAccount(
        id=str(uuid4()),
        name=name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        scopes=["agents:run"],
        created_at=now,
        revoked_at=now if revoked else None,
    )
    db.create_service_account(account.to_dict())
    return plaintext


def _auth_os(security_key=None, db=None, **config_kwargs) -> AgentOS:
    return AgentOS(
        agents=[_agent()],
        db=db,
        enable_mcp_server=True,
        settings=AgnoAPISettings(os_security_key=security_key),
        mcp_config=MCPServerConfig(tools=[_ok_tool], enable_builtin_tools=False, **config_kwargs),
    )


def _bearer(token: str) -> dict:
    return {**_MCP_HEADERS, "Authorization": f"Bearer {token}"}


async def test_security_key_mode_rejects_missing_token():
    async with _mcp_http_client(_auth_os(security_key="test-key")) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)
    assert response.status_code == 401
    assert response.json()["detail"] == "Authorization header required"


async def test_security_key_mode_rejects_invalid_token():
    async with _mcp_http_client(_auth_os(security_key="test-key")) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer("wrong-key"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication token"


async def test_security_key_mode_accepts_the_key():
    async with _mcp_http_client(_auth_os(security_key="test-key")) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer("test-key"))
    assert response.status_code == 200


async def test_security_key_mode_accepts_raw_token():
    """A raw (non-Bearer) Authorization header is accepted, like the JWT middleware."""
    headers = {**_MCP_HEADERS, "Authorization": "test-key"}
    async with _mcp_http_client(_auth_os(security_key="test-key")) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=headers)
    assert response.status_code == 200


async def test_security_key_mode_accepts_valid_pat_and_attributes(tmp_path):
    """A valid agno_pat token authenticates, and the account principal + scopes land on
    request.state so _resolve_user_id attributes tool calls to sa:<name>."""
    db = _sqlite_db(tmp_path)
    pat = _mint_pat(db)
    captured: dict = {}

    class _CaptureState(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            captured["user_id"] = getattr(request.state, "user_id", None)
            captured["scopes"] = getattr(request.state, "scopes", None)
            return response

    os = _auth_os(security_key="test-key", db=db, middleware=[Middleware(_CaptureState)])
    async with _mcp_http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(pat))

    assert response.status_code == 200
    assert captured["user_id"] == "sa:mcp-bot"
    assert captured["scopes"] == ["agents:run"]


async def test_security_key_mode_rejects_revoked_pat(tmp_path):
    db = _sqlite_db(tmp_path)
    pat = _mint_pat(db, revoked=True)
    async with _mcp_http_client(_auth_os(security_key="test-key", db=db)) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer(pat))
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired service account token"


async def test_pat_without_db_gets_service_accounts_disabled_401():
    """Without a db there is no verifier: a PAT gets REST's 'not enabled' 401, not a key check."""
    async with _mcp_http_client(_auth_os(security_key="test-key")) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer("agno_pat_notenabled0000000"))
    assert response.status_code == 401
    assert response.json()["detail"] == "Service accounts are not enabled on this AgentOS instance"


async def test_open_mode_with_db_stays_open_and_ignores_stale_pats(tmp_path):
    """A db-only AgentOS (no security key, no JWT) installs no auth layer on /mcp.

    The verifier still lives on app.state (the WS authenticate action and manually
    added JWTMiddleware resolve it at request time), but no middleware runs for the
    mounted app, so a stale ``agno_pat_...`` in a client is ignored -- same as any
    other bearer on an open instance.
    """
    db = _sqlite_db(tmp_path)
    async with _mcp_http_client(_auth_os(security_key=None, db=db)) as client:
        open_response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)
        stale_pat_response = await client.post(
            "/mcp", json=_MCP_INIT_BODY, headers=_bearer("agno_pat_invalid00000000000")
        )
    assert open_response.status_code == 200
    # Stale PAT passes through anonymously: no auth middleware is installed on an
    # open instance, so nothing is looking at the token.
    assert stale_pat_response.status_code == 200


def test_no_auth_mode_installs_no_auth_layer():
    """No security key and no db (no verifier): no auth middleware anywhere, /mcp stays open."""
    os = _auth_os(security_key=None)
    assert not any(m.cls.__name__ == "AuthMiddleware" for m in os.get_app().user_middleware)
    assert not any(m.cls.__name__ == "AuthMiddleware" for m in get_mcp_server(os).user_middleware)


async def test_no_auth_mode_stays_open():
    async with _mcp_http_client(_auth_os(security_key=None)) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_MCP_HEADERS)
    assert response.status_code == 200


class _FakeVerifier:
    def __init__(self, status):
        self.status = status

    async def verify(self, token, client_key=None):
        return ServiceAccountVerification(status=self.status)


@pytest.mark.parametrize(
    "status,expected_status_code",
    [(VerificationStatus.THROTTLED, 429), (VerificationStatus.UNAVAILABLE, 503)],
)
async def test_pat_verifier_statuses_map_like_rest(tmp_path, status, expected_status_code):
    """THROTTLED -> 429 and UNAVAILABLE -> 503, matching the REST path in agno.os.auth."""
    os = _auth_os(security_key="test-key", db=_sqlite_db(tmp_path))
    os._service_account_verifier = _FakeVerifier(status)
    async with _mcp_http_client(os) as client:
        response = await client.post("/mcp", json=_MCP_INIT_BODY, headers=_bearer("agno_pat_whatever0000000000"))
    assert response.status_code == expected_status_code


def test_mounted_mcp_middleware_layer_position():
    """The mounted /mcp app's own layers stay ordered transport security -> app middleware
    -> authorize gate (add_middleware wraps outside-in). Auth is not among them -- it ran
    on the parent app before the request reached the mount."""

    class _Passthrough(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
            return await call_next(request)

    os = _auth_os(
        security_key="test-key",
        allowed_hosts=[],
        middleware=[Middleware(_Passthrough)],
        authorize=lambda user_id: True,
    )
    names = [m.cls.__name__ for m in get_mcp_server(os).user_middleware]
    expected_order = [
        "_MCPTransportSecurityMiddleware",
        "_Passthrough",
        "_MCPAuthorizeMiddleware",
    ]
    positions = [names.index(name) for name in expected_order]
    assert positions == sorted(positions), f"unexpected middleware order: {names}"
