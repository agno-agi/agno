"""Unit tests for the v2.7 MCP surface: run-lifecycle tools, read-only session tools
backed by the shared service layer, tool annotations, and the app wiring fixes.
"""

import pytest

pytest.importorskip("fastmcp")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from fastmcp import Client  # noqa: E402

import agno.os.mcp as mcp_mod  # noqa: E402
from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.mcp import build_mcp_server  # noqa: E402
from agno.os.services.sessions import SessionNotFoundError, get_session_runs, get_sessions_page  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.requirement import RunRequirement  # noqa: E402
from agno.workflow.step import Step  # noqa: E402
from agno.workflow.workflow import Workflow  # noqa: E402


def _agent() -> Agent:
    return Agent(id="demo-agent", name="Demo Agent")


@pytest.fixture(autouse=True)
def _resolve_by_identity(monkeypatch):
    """Resolve run/lifecycle tools to the in-memory (stubbed) component instance.

    Production ``_resolve_run_component`` deep-copies (create_fresh) and consults the DB
    registry, which would discard the ``.arun`` / ``.acontinue_run`` / ``.acancel_run``
    stubs these tests set on the instance. The scope-gate tests are unaffected (the gate
    runs before resolution, and a missing id still raises "<Type> <id> not found"). Real
    resolution behaviour is covered by test_mcp_resolution.py.
    """

    async def _resolve(os, kind, component_id, *, user_id, session_id):
        pool = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}.get(kind) or []
        for component in pool:
            if getattr(component, "id", None) == component_id:
                return component
        singular = {"agents": "Agent", "teams": "Team", "workflows": "Workflow"}[kind]
        raise Exception(f"{singular} {component_id} not found")

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)


# ==================== Tool annotations ====================


async def test_annotations_mark_reads_and_destructive_tools():
    """Clients use readOnlyHint/destructiveHint for permission UX; reads and the one
    destructive tool must be distinguishable."""
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        tools = {t.name: t for t in await client.list_tools()}

    assert tools["get_agentos_config"].annotations.readOnlyHint is True
    assert tools["get_sessions"].annotations.readOnlyHint is True
    assert tools["get_session_runs"].annotations.readOnlyHint is True
    assert tools["cancel_run"].annotations.destructiveHint is True
    assert tools["run_agent"].annotations.readOnlyHint is False


async def test_config_payload_is_compact():
    """get_agentos_config is a discovery payload: ids and summaries, not the full config."""
    os = AgentOS(agents=[_agent()], mcp_server=True)
    os.get_app()  # populates db discovery (os.dbs), as at serve time
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("get_agentos_config", {})

    structured = result.structured_content or {}
    payload = structured.get("result", structured)
    assert payload["agents"][0]["id"] == "demo-agent"
    for heavy_key in ("session", "memory", "knowledge", "evals", "metrics", "traces"):
        assert heavy_key not in payload


# ==================== continue_run / cancel_run ====================


async def test_continue_run_requires_exactly_one_component():
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("continue_run", {"run_id": "r1"}, raise_on_error=False)
        assert result.is_error
        result = await client.call_tool(
            "continue_run",
            {"run_id": "r1", "agent_id": "demo-agent", "team_id": "demo-team"},
            raise_on_error=False,
        )
        assert result.is_error


async def test_continue_run_threads_identity_and_parses_requirements(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_resolve_user_id", lambda caller: "jwt-alice")
    agent = _agent()
    captured = {}

    async def fake_acontinue_run(*, run_id, session_id, user_id, requirements, stream=False):
        captured.update(run_id=run_id, session_id=session_id, user_id=user_id, requirements=requirements, stream=stream)
        return RunOutput(run_id=run_id, session_id=session_id, content="resumed", status=RunStatus.completed)

    agent.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(agents=[agent], mcp_server=True)

    requirement_dict = {"tool_execution": {"tool_name": "send_email"}, "confirmation": True}
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool(
            "continue_run",
            {
                "run_id": "run-9",
                "session_id": "sess-9",
                "agent_id": "demo-agent",
                "requirements": [requirement_dict],
            },
        )

    assert captured["run_id"] == "run-9"
    assert captured["user_id"] == "jwt-alice"
    assert captured["stream"] is False  # pinned so a stream=True agent can't return an iterator
    assert isinstance(captured["requirements"][0], RunRequirement)
    assert result.content[0].text == "resumed"
    assert (result.structured_content or {})["status"] == "COMPLETED"


async def test_continue_run_dispatches_workflow_step_requirements():
    workflow = Workflow(id="demo-wf", name="Demo WF", steps=[Step(agent=_agent())])
    captured = {}

    async def fake_acontinue_run(*, run_id, session_id, step_requirements, stream=False):
        captured.update(run_id=run_id, step_requirements=step_requirements, stream=stream)
        from agno.run.workflow import WorkflowRunOutput

        return WorkflowRunOutput(run_id=run_id, session_id=session_id, content="wf resumed")

    workflow.acontinue_run = fake_acontinue_run  # type: ignore[method-assign]
    os = AgentOS(workflows=[workflow], mcp_server=True)

    step_requirement = {"step_id": "s1", "step_name": "approve", "step_type": "Step", "requires_confirmation": True}
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool(
            "continue_run",
            {"run_id": "wf-run-9", "workflow_id": "demo-wf", "requirements": [step_requirement]},
        )

    assert captured["run_id"] == "wf-run-9"
    assert captured["step_requirements"][0].step_id == "s1"
    assert result.content[0].text == "wf resumed"


async def test_cancel_run_requires_exactly_one_component():
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("cancel_run", {"run_id": "r1"}, raise_on_error=False)
    assert result.is_error


async def test_cancel_run_requests_cancellation_on_the_named_component():
    agent = _agent()
    captured = {}

    async def fake_acancel_run(run_id):
        captured["run_id"] = run_id
        return True

    agent.acancel_run = fake_acancel_run  # type: ignore[method-assign]
    os = AgentOS(agents=[agent], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("cancel_run", {"run_id": "run-x", "agent_id": "demo-agent"})
    assert captured["run_id"] == "run-x"
    assert "cancellation requested" in result.content[0].text


async def test_continue_run_rejects_remote_component():
    """Remote components can't carry resolved requirements downstream; continue must fail
    clearly (like the REST 400) rather than crash."""
    from agno.agent.remote import RemoteAgent

    remote = RemoteAgent(base_url="http://example.invalid", agent_id="remote-agent")
    os = AgentOS(agents=[remote], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool(
            "continue_run",
            {"run_id": "r1", "session_id": "s1", "agent_id": "remote-agent"},
            raise_on_error=False,
        )
    assert result.is_error
    assert "remote" in result.content[0].text.lower()


async def test_lifecycle_ownership_gate_blocks_other_users(monkeypatch):
    """A scoped (non-admin) caller cannot cancel a run in a session they do not own."""
    monkeypatch.setattr(mcp_mod, "_scoped_caller_user_id", lambda: "user-b")
    agent = _agent()
    cancelled = {"called": False}

    async def fake_acancel_run(run_id):
        cancelled["called"] = True
        return True

    async def fake_aget_session(session_id, user_id):
        return None  # user-b owns no such session

    agent.acancel_run = fake_acancel_run  # type: ignore[method-assign]
    agent.aget_session = fake_aget_session  # type: ignore[method-assign]
    os = AgentOS(agents=[agent], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool(
            "cancel_run",
            {"run_id": "run-a", "session_id": "sess-a", "agent_id": "demo-agent"},
            raise_on_error=False,
        )
    assert result.is_error
    assert cancelled["called"] is False  # never reached the cancellation registry


async def test_get_session_runs_history_is_trimmed():
    """History reads must not ship the message transcript / system prompt to the client."""
    session = {
        "session_id": "s1",
        "agent_id": "a-1",
        "runs": [
            {
                "run_id": "r1",
                "agent_id": "a-1",
                "run_input": "hello",
                "content": "hi there",
                "status": "COMPLETED",
                "messages": [{"role": "system", "content": "SECRET_PROMPT"}],
                "events": [{"event": "x"}],
            }
        ],
    }
    from agno.os.mcp_results import trim_session_run
    from agno.os.schema import RunSchema

    trimmed = trim_session_run(RunSchema.from_dict(session["runs"][0]))
    assert trimmed["content"] == "hi there"
    assert trimmed["status"] == "COMPLETED"
    assert trimmed["agent_id"] == "a-1"
    assert "messages" not in trimmed
    assert "events" not in trimmed
    assert "SECRET_PROMPT" not in str(trimmed)


def test_trim_session_run_keeps_workflow_id():
    """Workflow runs keep the id of the workflow that produced them, exactly like
    agent and team runs keep agent_id/team_id in trimmed history."""
    from agno.os.mcp_results import trim_session_run
    from agno.os.schema import WorkflowRunSchema

    run = WorkflowRunSchema.from_dict(
        {"run_id": "wr-1", "workflow_id": "wf-1", "content": "wf result", "status": "COMPLETED"}
    )
    trimmed = trim_session_run(run)
    assert trimmed["workflow_id"] == "wf-1"
    assert trimmed["run_id"] == "wr-1"
    assert "step_results" not in trimmed


# ==================== Run-lifecycle ownership gate ====================


async def test_run_ownership_gate_fails_closed_for_scoped_callers_on_remotes(monkeypatch):
    """A scoped caller acting on a remote component gets a clean refusal, not a raw
    AttributeError (BaseRemote has no aget_session) -- and NOT a pass-through: skipping
    the gate would let any scoped run-scope holder cancel other users' runs on the
    remote, which forwards without this caller's identity."""
    from agno.agent.remote import RemoteAgent

    monkeypatch.setattr(mcp_mod, "_scoped_caller_user_id", lambda: "user-1")
    verify = mcp_mod._make_run_ownership_verifier(None)  # type: ignore[arg-type]
    remote = RemoteAgent(base_url="http://remote.invalid:1", agent_id="remote-agent")

    with pytest.raises(Exception, match="administrator"):
        await verify(remote, "agents", "remote-agent", "session-1", "run-1")


async def test_run_ownership_gate_admin_passes_on_remotes(monkeypatch):
    """Admins (no scoped user id) bypass the ownership gate for remotes, exactly as
    they do for local components -- and without any network call."""
    from agno.agent.remote import RemoteAgent

    monkeypatch.setattr(mcp_mod, "_scoped_caller_user_id", lambda: None)
    verify = mcp_mod._make_run_ownership_verifier(None)  # type: ignore[arg-type]
    remote = RemoteAgent(base_url="http://remote.invalid:1", agent_id="remote-agent")

    await verify(remote, "agents", "remote-agent", "session-1", "run-1")


async def test_run_ownership_gate_still_blocks_unowned_local_runs(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_scoped_caller_user_id", lambda: "user-1")
    verify = mcp_mod._make_run_ownership_verifier(None)  # type: ignore[arg-type]

    class _LocalAgent:
        async def aget_session(self, session_id, user_id):
            return None

    with pytest.raises(Exception, match="Run not found"):
        await verify(_LocalAgent(), "agents", "demo-agent", "session-1", "run-1")


async def test_cancel_component_run_surfaces_remote_failure(monkeypatch):
    """A remote acancel_run swallows transport errors into False; the service must
    turn that into an error instead of reporting 'cancellation requested'."""
    from agno.agent.remote import RemoteAgent
    from agno.os.services import runs as run_service

    remote = RemoteAgent(base_url="http://remote.invalid:1", agent_id="remote-agent")

    async def _failed_cancel(run_id, auth_token=None):
        return False

    monkeypatch.setattr(remote, "acancel_run", _failed_cancel)
    with pytest.raises(Exception, match="could not be delivered"):
        await run_service.cancel_component_run(remote, "run-1")


async def test_cancel_component_run_local_false_is_cancel_before_start():
    """The local cancellation manager returns False when it stores intent for a
    not-yet-registered run (cancel-before-start). That is success, not failure."""
    from agno.os.services import runs as run_service

    class _LocalComponent:
        async def acancel_run(self, run_id):
            return False

    await run_service.cancel_component_run(_LocalComponent(), "run-1")  # must not raise


# ==================== Session service ====================


class _FakeSyncDb:
    """Sync BaseDb-shaped stub: exercises the threadpool path in the service."""

    def __init__(self, session=None, sessions=None):
        self._session = session
        self._sessions = sessions or []

    def get_session(self, session_id, session_type, user_id, deserialize):
        return self._session

    def get_sessions(self, **kwargs):
        return self._sessions, len(self._sessions)


async def test_service_auto_detects_workflow_session_and_classifies_runs():
    session = {
        "session_id": "s1",
        "workflow_id": "wf-1",
        "runs": [
            {"run_id": "r1", "workflow_id": "wf-1", "content": "wf run"},
            {"run_id": "r2", "agent_id": "a-1", "content": "member agent run"},
        ],
    }
    runs = await get_session_runs(_FakeSyncDb(session=session), session_id="s1", session_type=None)  # type: ignore[arg-type]

    # workflow_id run renders as a workflow run, the bare agent run falls back to RunSchema
    assert runs[0].__class__.__name__ == "WorkflowRunSchema"
    assert runs[1].__class__.__name__ == "RunSchema"


async def test_service_raises_session_not_found():
    with pytest.raises(SessionNotFoundError):
        await get_session_runs(_FakeSyncDb(session=None), session_id="missing")  # type: ignore[arg-type]


async def test_service_lists_sessions_via_threadpool():
    from agno.db.base import SessionType

    db = _FakeSyncDb(sessions=[{"session_id": "s1", "session_type": "agent"}])
    sessions, total = await get_sessions_page(db, session_type=SessionType.AGENT)  # type: ignore[arg-type]
    assert total == 1
    assert sessions[0]["session_id"] == "s1"


# ==================== App wiring ====================


def test_resync_reuses_started_mcp_app_and_mount():
    """resync() must not replace the MCP app (a fresh one's lifespan never runs) and
    must not accumulate duplicate mounts."""
    os = AgentOS(agents=[_agent()], mcp_server=True)
    app = os.get_app()
    mcp_app_before = os._mcp_app
    assert mcp_app_before is not None

    os.resync(app=app)

    assert os._mcp_app is mcp_app_before
    mounts = [r for r in app.router.routes if getattr(r, "app", None) is mcp_app_before]
    assert len(mounts) == 1


def test_home_route_works_with_mcp_enabled():
    os = AgentOS(agents=[_agent()], mcp_server=True)
    app = os.get_app()
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "AgentOS" in response.text


def test_get_app_idempotent_with_base_app():
    base_app = FastAPI()
    os = AgentOS(agents=[_agent()], mcp_server=True, base_app=base_app)
    first = os.get_app()
    route_count = len(first.router.routes)
    mcp_app_first = os._mcp_app

    second = os.get_app()

    assert second is first
    assert len(second.router.routes) == route_count
    assert os._mcp_app is mcp_app_first
    mounts = [r for r in second.router.routes if getattr(r, "app", None) is mcp_app_first]
    assert len(mounts) == 1


# ==================== Tool scope enforcement ====================


def _request_with_state(**state):
    from types import SimpleNamespace

    # scope: fastmcp's get_access_token reads request.scope.get("user") on the
    # request our patched get_http_request returns.
    return SimpleNamespace(state=SimpleNamespace(**state), scope={})


def _pat_request(scopes, name="bot", **extra_state):
    return _request_with_state(
        authenticated=True,
        user_id="sa:" + name,
        session_id=None,
        scopes=list(scopes),
        authorization_enabled=True,
        service_account_name=name,
        **extra_state,
    )


def _patch_request(monkeypatch, request):
    import fastmcp.server.dependencies as fastmcp_deps

    monkeypatch.setattr(fastmcp_deps, "get_http_request", lambda: request)


async def test_scope_gate_blocks_underscoped_pat_on_run_agent(monkeypatch):
    """A sessions:read-only PAT must get the same 403-equivalent on MCP as on REST."""
    _patch_request(monkeypatch, _pat_request(["sessions:read"]))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_agent", {"agent_id": "demo-agent", "message": "hi"}, raise_on_error=False)
    assert result.is_error
    assert "Insufficient permissions" in str(result.content)
    assert "agents:run" in str(result.content)


async def test_scope_gate_allows_matching_scope_through(monkeypatch):
    """With agents:run the gate passes and the tool proceeds to component lookup."""
    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_agent", {"agent_id": "ghost", "message": "hi"}, raise_on_error=False)
    assert result.is_error
    assert "Agent ghost not found" in str(result.content)
    assert "Insufficient permissions" not in str(result.content)


async def test_scope_gate_honours_per_resource_scopes(monkeypatch):
    """agents:<id>:run grants that agent only, mirroring REST per-resource scopes."""
    _patch_request(monkeypatch, _pat_request(["agents:ghost:run"]))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        allowed = await client.call_tool("run_agent", {"agent_id": "ghost", "message": "hi"}, raise_on_error=False)
        blocked = await client.call_tool("run_agent", {"agent_id": "demo-agent", "message": "hi"}, raise_on_error=False)
    assert "Agent ghost not found" in str(allowed.content)
    assert "Insufficient permissions" in str(blocked.content)


async def test_scope_gate_covers_session_and_config_tools(monkeypatch):
    """get_sessions needs sessions:read; get_agentos_config needs config:read."""
    _patch_request(monkeypatch, _pat_request(["agents:run"]))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        sessions_result = await client.call_tool("get_sessions", {}, raise_on_error=False)
        config_result = await client.call_tool("get_agentos_config", {}, raise_on_error=False)
    assert "Insufficient permissions" in str(sessions_result.content)
    assert "Insufficient permissions" in str(config_result.content)


async def test_scope_gate_default_scopes_cover_the_golden_path(monkeypatch):
    """The default mint scopes must be able to discover and run: the agno connect flow."""
    from agno.os.service_accounts import DEFAULT_SERVICE_ACCOUNT_SCOPES

    _patch_request(monkeypatch, _pat_request(DEFAULT_SERVICE_ACCOUNT_SCOPES))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    os.get_app()
    async with Client(build_mcp_server(os)) as client:
        config_result = await client.call_tool("get_agentos_config", {}, raise_on_error=False)
        run_result = await client.call_tool("run_agent", {"agent_id": "ghost", "message": "hi"}, raise_on_error=False)
    assert not config_result.is_error
    assert "Agent ghost not found" in str(run_result.content)


async def test_scope_gate_admin_scope_bypasses(monkeypatch):
    _patch_request(monkeypatch, _pat_request(["admin"], admin_scope="admin"))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_agent", {"agent_id": "ghost", "message": "hi"}, raise_on_error=False)
    assert "Agent ghost not found" in str(result.content)


async def test_scope_gate_skips_anonymous_and_security_key_callers(monkeypatch):
    """Callers without ACL-bearing identities (open / security-key humans) pass, as on REST."""
    _patch_request(monkeypatch, _request_with_state(authenticated=True))
    os = AgentOS(agents=[_agent()], mcp_server=True)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_agent", {"agent_id": "ghost", "message": "hi"}, raise_on_error=False)
    assert "Agent ghost not found" in str(result.content)


# ==================== include_tags / history detail ====================


async def test_empty_include_tags_registers_no_builtin_tools():
    """An explicitly empty include_tags set means no built-in tools, not all of them."""
    from agno.os.config import MCPServerConfig

    os = AgentOS(agents=[_agent()], mcp_server=MCPServerConfig(include_tags=set()))
    async with Client(build_mcp_server(os)) as client:
        tools = await client.list_tools()
    assert tools == []


async def test_get_session_runs_run_id_returns_full_detail(monkeypatch):
    """run_id is the full-detail escape hatch: one untrimmed run, or a loud not-found."""
    from agno.os.schema import RunSchema

    run = RunSchema.from_dict(
        {
            "run_id": "r1",
            "agent_id": "a-1",
            "run_input": "hello",
            "content": "hi there",
            "status": "COMPLETED",
            "messages": [{"role": "system", "content": "FULL_TRANSCRIPT"}],
        }
    )

    async def fake_get_db(dbs, db_id):
        return object()

    async def fake_get_session_runs(db, session_id, session_type, user_id):
        return [run]

    monkeypatch.setattr(mcp_mod, "get_db", fake_get_db)
    monkeypatch.setattr(mcp_mod.session_service, "get_session_runs", fake_get_session_runs)

    os = AgentOS(agents=[_agent()], mcp_server=True)
    os.get_app()  # populates os.dbs, as at serve time
    async with Client(build_mcp_server(os)) as client:
        trimmed = await client.call_tool("get_session_runs", {"session_id": "s1"})
        full = await client.call_tool("get_session_runs", {"session_id": "s1", "run_id": "r1"})
        missing = await client.call_tool(
            "get_session_runs", {"session_id": "s1", "run_id": "zzz"}, raise_on_error=False
        )

    assert "FULL_TRANSCRIPT" not in str(trimmed.content)
    assert "FULL_TRANSCRIPT" in str(full.content)
    assert missing.is_error
    assert "Run zzz not found" in str(missing.content)
