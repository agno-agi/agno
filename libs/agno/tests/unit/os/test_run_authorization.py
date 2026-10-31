"""Caller permissions survive manager tools, delegation and deferred execution."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, OSManager
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.authz.run_context import request_authorization, restore_authorization
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.job_queue import QueueWorker, aenqueue_ticket
from agno.registry import Registry
from agno.registry._reserved import MANAGER_TEAM_ID, OPERATOR_ID
from agno.run import RunContext
from agno.run.authorization import (
    AUTHORIZATION_HEADER,
    AUTHORIZATION_KEY,
    RunAuthorization,
    authorization_scope,
    current_authorization,
    require_permission,
)
from agno.scheduler.manager import ScheduleManager
from agno.tools.studio import StudioTools

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

SECRET = "manager-action-test-key-at-least-32-characters"


class ScriptedModel(Model):
    def __init__(self, tool=None, arguments=None):
        super().__init__(id="fixture", provider="test")
        self.tool = tool
        self.arguments = arguments or {}
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.tool and messages[-1].role != "tool":
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call",
                        "type": "function",
                        "function": {"name": self.tool, "arguments": json.dumps(self.arguments)},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(
            role="assistant",
            content=str(messages[-1].content) if self.tool else "allowed target ran",
            response_usage=MessageMetrics(),
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def authority(scopes, provider=None):
    return RunAuthorization(
        provider or ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"}),
    )


def headers(scopes):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": "alice",
                "aud": "test",
                "scopes": scopes,
                "exp": int(time.time()) + 300,
            },
            SECRET,
            algorithm="HS256",
        )
    }


def make_os(tmp_path, model, agents=None, auth=None):
    return AgentOS(
        id="test",
        db=SqliteDb(db_file=str(tmp_path / "test.db")),
        telemetry=False,
        user_isolation=True,
        authorization=auth or Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test"),
        agents=agents,
        registry=Registry(models=[ScriptedModel()]),
        manager=OSManager(model=model),
    )


@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("identity", ["jwt", "managed_role", "service_account"])
def test_manager_can_dispatch_only_an_authorized_target(tmp_path, allowed, identity):
    target_model = ScriptedModel()
    target = Agent(id="allowed", name="Friendly target", model=target_model)
    model = ScriptedModel("run_agent", {"agent_id": "Friendly target", "message": "hello"})
    scopes = ["teams:os-manager-internal:run"] + (["agents:allowed:run"] if allowed else [])
    token_headers = headers(scopes)
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test")
    if identity == "managed_role":
        auth.define_role("caller", scopes)
        auth.assign("alice", "caller")
        # A forged admin claim cannot override the role's actual grants.
        token_headers = headers(["agent_os:admin"])
    os = make_os(tmp_path, model, [target], auth=auth)
    if identity == "service_account":
        from agno.db.schemas.service_accounts import ServiceAccount
        from agno.os.service_accounts import generate_token

        token, hashed, prefix = generate_token()
        os.db.create_service_account(
            ServiceAccount(id="caller", name="caller", token_hash=hashed, token_prefix=prefix, scopes=scopes).to_dict()
        )
        token_headers = {"Authorization": "Bearer " + token}
    response = TestClient(os.get_app()).post(
        "/teams/os-manager-internal/runs", headers=token_headers, data={"message": "run target", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    assert ("allowed target ran" if allowed else "Permission required: agents:allowed:run") in response.text
    assert bool(target_model.calls) == allowed


@pytest.mark.parametrize("allowed", [False, True])
def test_builder_publish_checks_component_write(tmp_path, allowed):
    builder_model = ScriptedModel("create_agent", {"name": "Alice calc", "instructions": "Calculate", "publish": True})
    os = make_os(tmp_path, ScriptedModel())
    builder = next(member for member in os.manager.members if member.id == "platform-builder-internal")
    builder.model = builder_model
    os.manager.model = ScriptedModel(
        "delegate_task_to_member", {"member_id": "platform-builder-internal", "task": "Build Alice calc"}
    )
    path = "/teams/os-manager-internal/runs"
    scopes = ["teams:os-manager-internal:run"]
    if allowed:
        scopes.append("components:write")
    response = TestClient(os.get_app()).post(
        path, headers=headers(scopes), data={"message": "build", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    rows, _ = os.db.list_components()
    assert bool(rows) == allowed, response.text
    if not allowed:
        assert "Permission required: components:write" in response.text


@pytest.mark.parametrize("use_async", [False, True])
def test_studio_actions_refuse_before_writing(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "studio.db"))
    studio = StudioTools(registry=Registry(models=[ScriptedModel()]), db=db, versions=True, schedules=True)
    with authorization_scope(lambda: authority(["teams:os-manager-internal:run"])):
        ctx = RunContext(run_id="run", session_id="session", user_id="alice")
        fn = studio.acreate_agent if use_async else studio.create_agent
        with pytest.raises(PermissionError, match="components:write"):
            result = fn(name="calc", instructions="Calculate", publish=True, _agno_run_context=ctx)
            if use_async:
                asyncio.run(result)
    assert not db.list_components()[0]


@pytest.mark.parametrize("use_async", [False, True])
def test_schedule_checks_target_and_persists_caller_not_payload(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "schedule.db"))
    manager = ScheduleManager(db)
    auth = authority(["schedules:write", "agents:allowed:run"])
    with authorization_scope(lambda: auth):
        fn = manager.acreate if use_async else manager.create
        with pytest.raises(PermissionError, match="agents:restricted:run"):
            value = fn(name="bad", cron="0 0 * * *", endpoint="/agents/restricted/runs")
            if use_async:
                asyncio.run(value)
        value = fn(
            name="good",
            cron="0 0 * * *",
            endpoint="/agents/allowed/runs",
            payload={"message": "hi", AUTHORIZATION_KEY: None},
        )
        schedule = asyncio.run(value) if use_async else value
    assert schedule.payload[AUTHORIZATION_KEY] == auth.snapshot()
    # Updates cannot retain an earlier editor's stronger authority.
    with authorization_scope(lambda: authority(["schedules:write"])):
        fn = manager.aupdate if use_async else manager.update
        with pytest.raises(PermissionError, match="agents:allowed:run"):
            value = fn(schedule.id, payload={"message": "changed", AUTHORIZATION_KEY: None})
            if use_async:
                asyncio.run(value)


def test_executor_authority_is_never_used_for_tool_calls():
    app = SimpleNamespace(state=SimpleNamespace())
    state = SimpleNamespace(is_internal_service=True, authorization_enabled=True, scopes=["agents:run"])
    request = SimpleNamespace(app=app, state=state, headers={})
    with pytest.raises(PermissionError):
        request_authorization(request).require("agents", "run", "restricted")
    request.headers[AUTHORIZATION_HEADER] = json.dumps(authority(["agents:allowed:run"]).snapshot())
    auth = request_authorization(request)
    auth.require("agents", "run", "allowed")
    with pytest.raises(PermissionError):
        auth.require("agents", "run", "restricted")
    # External requests cannot inject the internal header.
    state.is_internal_service = False
    state.user_id = "alice"
    state.scopes = []
    request.headers[AUTHORIZATION_HEADER] = "null"
    with pytest.raises(PermissionError):
        request_authorization(request).require("agents", "run", "restricted")


@pytest.mark.asyncio
async def test_queue_captures_and_restores_authority_for_continuation(monkeypatch):
    store = SimpleNamespace(enqueue_job=AsyncMock(side_effect=lambda job, **kwargs: job))
    worker = QueueWorker(store, lambda *args: None, QueueConfig())
    original = authority(["agents:allowed:run"])
    with authorization_scope(lambda: original):
        job = await aenqueue_ticket(worker, {"id": "job", "attempt": 1, "payload": {AUTHORIZATION_KEY: None}})
    assert job["payload"][AUTHORIZATION_KEY] == original.snapshot()
    observed = []

    async def execute(job, ownership):
        observed.append(current_authorization())
        with pytest.raises(PermissionError):
            require_permission("components", "write")

    monkeypatch.setattr(worker, "_execute_claimed_inner", execute)
    await worker._execute_claimed(job)
    observed[0].require("agents", "run", "allowed")
    job["payload"]["continue"] = {AUTHORIZATION_KEY: authority([]).snapshot()}
    await worker._execute_claimed(job)
    with pytest.raises(PermissionError):
        observed[1].require("agents", "run", "allowed")
    assert current_authorization() is None


@pytest.mark.asyncio
async def test_concurrent_callers_do_not_share_authority():
    async def run(scopes):
        with authorization_scope(lambda: authority(scopes)):
            ctx = RunContext(run_id="run", session_id="session")
            await asyncio.sleep(0)
            return await asyncio.to_thread(lambda: ctx.authorization.context.scopes)

    assert await asyncio.gather(run(["agents:a:run"]), run(["agents:b:run"])) == [["agents:a:run"], ["agents:b:run"]]


class Policy(AuthorizationProvider):
    def check(self, ctx):
        return ctx.principal_id == "alice" and ctx.resource_id == "allowed" and ctx.action == "run"

    def accessible_resource_ids(self, ctx):
        return {"allowed"}


def test_stored_authority_uses_current_provider_and_keeps_pat_plane():
    app = SimpleNamespace(state=SimpleNamespace(authorization_provider=Policy()))
    auth = restore_authorization(app, authority(["agent_os:admin"]).snapshot())
    auth.require("agents", "run", "allowed")
    with pytest.raises(PermissionError):
        auth.require("agents", "run", "restricted")
    snapshot = authority(["agents:restricted:run"]).snapshot()
    snapshot["service_account"] = True
    restore_authorization(app, snapshot).require("agents", "run", "restricted")


@pytest.mark.parametrize("use_async", [False, True])
def test_permission_sensitive_tools_do_not_reuse_cached_authorized_results(tmp_path, use_async):
    from agno.run.authorization import requires_permission
    from agno.tools.function import Function, FunctionCall

    @requires_permission("components", "read")
    def read_catalog() -> str:
        return "private catalog"

    fn = Function.from_callable(read_catalog)
    fn.cache_results = True
    fn.cache_dir = str(tmp_path)
    # Prime a cache from trusted Python. A later restricted caller must not
    # bypass the entrypoint permission check by receiving that cached value.
    initial = FunctionCall(function=fn, arguments={})
    assert initial.execute()
    assert initial.result == "private catalog"
    with authorization_scope(lambda: authority([])):
        call = FunctionCall(function=fn, arguments={})
        succeeded = asyncio.run(call.aexecute()) if use_async else call.execute()
        assert succeeded.status == "failure"
        assert "Permission required" in succeeded.error


@pytest.mark.parametrize("use_async", [False, True])
def test_runner_discovery_filters_per_component_permissions(use_async):
    from agno.tools.studio_runner import StudioRunnerTools

    allowed = Agent(id="allowed", model=ScriptedModel())
    restricted = Agent(id="restricted", model=ScriptedModel())
    runner = StudioRunnerTools(registry=Registry(), include_agents=[allowed, restricted])
    with authorization_scope(lambda: authority(["agents:allowed:read"])):
        result = asyncio.run(runner.alist_agents()) if use_async else runner.list_agents()
    data = json.loads(result)
    assert [row["id"] for row in data["agents"]] == ["allowed"]
    assert data["total"] == 1
    assert "other_components" not in data


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_mcp_call_carries_permissions_into_manager_tools(tmp_path, monkeypatch, allowed):
    from fastmcp import Client
    from fastmcp.server import dependencies

    from agno.os.mcp import build_mcp_server

    target = Agent(id="allowed", model=ScriptedModel())
    os = make_os(tmp_path, ScriptedModel("run_agent", {"agent_id": "allowed", "message": "hi"}), [target])
    app = os.get_app()
    request = SimpleNamespace(
        app=app,
        headers={},
        state=SimpleNamespace(
            authorization_enabled=True,
            user_id="alice",
            claims={},
            scopes=["teams:os-manager-internal:run"] + (["agents:allowed:run"] if allowed else []),
            admin_scope="agent_os:admin",
            user_isolation_enabled=True,
        ),
    )
    request.scope = {}
    monkeypatch.setattr(dependencies, "get_http_request", lambda: request)
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("run_team", {"team_id": "os-manager-internal", "message": "run"})
    text = str(result)
    assert ("allowed target ran" if allowed else "Permission required: agents:allowed:run") in text


@pytest.mark.parametrize("allowed", [False, True])
def test_scheduled_manager_run_keeps_original_caller_permissions(tmp_path, allowed):
    from agno.db.schemas.scheduler import Schedule
    from agno.scheduler.executor import ScheduleExecutor

    target = Agent(id="allowed", model=ScriptedModel())
    os = make_os(tmp_path, ScriptedModel("run_agent", {"agent_id": "allowed", "message": "hi"}), [target])
    app = os.get_app()
    app.state.internal_service_token = "internal-test-token"
    client = TestClient(app)
    scopes = ["teams:os-manager-internal:run", "schedules:write"] + (["agents:allowed:run"] if allowed else [])
    created = client.post(
        "/schedules",
        headers=headers(scopes),
        json={
            "name": "manager",
            "cron_expr": "0 0 * * *",
            "endpoint": "/teams/os-manager-internal/runs",
            "payload": {"message": "run", AUTHORIZATION_KEY: None},
        },
    )
    assert created.status_code == 201, created.text
    assert AUTHORIZATION_KEY not in created.json()["payload"]
    schedule = Schedule.from_dict(os.db.get_schedule(created.json()["id"]))
    # Exercise the real executor's header construction without a socket or poll loop.
    executor = ScheduleExecutor(base_url="http://testserver", internal_service_token="internal-test-token")
    captured = {}

    async def fake_background(http_client, url, request_headers, data, *args, **kwargs):
        captured.update(headers=request_headers, data=data)
        return {}

    # The helper signature is checked below by running the executor itself.
    executor._background_run = fake_background
    executor._get_client = AsyncMock(return_value=object())
    asyncio.run(executor._call_endpoint(schedule))
    response = client.post(
        "/teams/os-manager-internal/runs",
        headers=captured["headers"],
        data={**captured["data"], "stream": "false", "background": "false"},
    )
    assert response.status_code == 200, response.text
    assert ("allowed target ran" if allowed else "Permission required: agents:allowed:run") in response.text


@pytest.mark.parametrize("use_async", [False, True])
def test_custom_provider_must_explicitly_authorize_global_tool_operations(use_async):
    class ResourceOnlyPolicy(AuthorizationProvider):
        def check(self, ctx):
            return True  # Per-resource policy defers global routes.

        def accessible_resource_ids(self, ctx):
            return {"*"}

    auth = authority(["agent_os:admin"], ResourceOnlyPolicy())
    with pytest.raises(PermissionError, match="components:write"):
        result = auth.arequire("components", "write") if use_async else auth.require("components", "write")
        if use_async:
            asyncio.run(result)


@pytest.mark.parametrize("scopes", [["agents:run"], ["agents:*:run"], ["agents:allowed:run"]])
def test_run_permissions_match_rest_scope_vocabulary(scopes):
    authority(scopes).require("agents", "run", "allowed")


@pytest.mark.parametrize("allowed", [False, True])
def test_durable_background_manager_run_preserves_caller(tmp_path, allowed):
    from agno.job_queue.store import InMemoryQueueStore

    target = Agent(id="allowed", model=ScriptedModel())
    os = make_os(tmp_path, ScriptedModel("run_agent", {"agent_id": "allowed", "message": "hi"}), [target])
    os.queue = QueueConfig(durable=True, db=InMemoryQueueStore(), poll_interval=0.01)
    scopes = ["teams:os-manager-internal:run"] + (["agents:allowed:run"] if allowed else [])
    with TestClient(os.get_app()) as client:
        response = client.post(
            "/teams/os-manager-internal/runs",
            headers=headers(scopes),
            data={
                "message": "run",
                "stream": "false",
                "background": "true",
                "metadata": json.dumps({AUTHORIZATION_KEY: None}),
            },
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["run_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            output = os.manager.get_run_output(run_id, session_id=response.json()["session_id"])
            if output is not None and output.content:
                break
            time.sleep(0.01)
        assert output is not None
        assert ("allowed target ran" if allowed else "Permission required: agents:allowed:run") in output.content


def test_service_account_tool_authority_is_enforced_even_when_rbac_flag_is_off():
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace()),
        headers={},
        state=SimpleNamespace(
            authorization_enabled=False,
            service_account_name="caller",
            user_id="sa:caller",
            scopes=["teams:os-manager-internal:run"],
            claims={},
        ),
    )
    auth = request_authorization(request)
    with pytest.raises(PermissionError, match="agents:restricted:run"):
        auth.require("agents", "run", "restricted")


def test_parallel_sync_task_delegation_keeps_caller_authority():
    from agno.run.team import TeamRunOutput
    from agno.session import TeamSession
    from agno.team import Team
    from agno.team._task_tools import _get_task_management_tools
    from agno.team.task import TaskList

    member = Agent(id="helper", model=ScriptedModel())
    team = Team(id="parent", members=[member], model=ScriptedModel(), mode="tasks")
    observed = []

    def run_member(**kwargs):
        observed.append(current_authorization())
        require_permission("components", "write")

    member.run = run_member
    tasks = TaskList()
    task = tasks.create_task("Build", assignee="helper")
    with authorization_scope(lambda: authority(["teams:parent:run"])):
        functions = _get_task_management_tools(
            team,
            tasks,
            TeamRunOutput(run_id="parent-run"),
            RunContext(run_id="parent-run", session_id="session", session_state={}),
            TeamSession(session_id="session"),
            {},
            user_id="alice",
        )
        parallel = next(fn for fn in functions if fn.name == "execute_tasks_parallel")
        result = list(parallel.entrypoint(task_ids=[task.id]))
    assert observed and observed[0] is not None
    assert "Permission required: components:write" in str(result)


@pytest.mark.asyncio
async def test_mounted_application_cannot_replace_the_parent_authorization_policy():
    from agno.os.authz.run_context import RunAuthorizationMiddleware

    parent = SimpleNamespace(state=SimpleNamespace(authorization_provider=Policy()))

    async def child(scope, receive, send):
        scope["app"] = SimpleNamespace(state=SimpleNamespace())
        scope["state"].update(authorization_enabled=True, user_id="alice", scopes=["agent_os:admin"], claims={})
        # The scope claim cannot replace the parent's managed/custom policy.
        with pytest.raises(PermissionError):
            await current_authorization().arequire("components", "write")

    middleware = RunAuthorizationMiddleware(child, authorization_app=parent)
    await middleware({"type": "http", "app": parent, "headers": []}, AsyncMock(), AsyncMock())
    assert current_authorization() is None


def test_manager_run_discovery_and_session_permissions_remain_separate(tmp_path):
    os = make_os(tmp_path, ScriptedModel())
    client = TestClient(os.get_app())
    manager_id = os.manager.id
    run_headers = headers([f"teams:{manager_id}:run"])
    run = client.post(f"/teams/{manager_id}/runs", headers=run_headers, data={"message": "hi", "stream": "false"})
    assert run.status_code == 200
    session_id = run.json()["session_id"]
    assert client.get(f"/teams/{manager_id}", headers=run_headers).status_code == 403
    assert client.get(f"/sessions/{session_id}", headers=run_headers).status_code == 403

    read_headers = headers(["teams:read"])
    assert client.get(f"/teams/{manager_id}", headers=read_headers).status_code == 200
    assert client.get(f"/sessions/{session_id}", headers=read_headers).status_code == 403
    assert client.post(f"/teams/{manager_id}/runs", headers=read_headers, data={"message": "hi"}).status_code == 403

    session_headers = headers(["sessions:read"])
    assert client.get(f"/sessions/{session_id}", headers=session_headers).status_code == 200
    assert client.get(f"/teams/{manager_id}", headers=session_headers).status_code == 403
    other = os.manager.run("hi", user_id="bob")
    assert client.get(f"/sessions/{other.session_id}", headers=session_headers).status_code == 404


def _operator_permission_os(tmp_path, scopes, identity="jwt", tool="read_file", arguments=None, delegated=False):
    root = tmp_path / "source"
    root.mkdir()
    (root / "example.py").write_text("READABLE_SOURCE_SENTINEL = 42\n")
    (root / ".env").write_text("SECRET_SENTINEL_NEVER_RETURN=synthetic\n")
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test", verify_audience=True)
    request_headers = headers(scopes)
    if identity == "managed":
        auth.define_role("caller", scopes)
        auth.assign("alice", "caller")
        request_headers = headers(["agent_os:admin"])
    os = AgentOS(
        id="test",
        db=SqliteDb(db_file=str(tmp_path / "db.sqlite")),
        authorization=auth,
        user_isolation=True,
        manager=OSManager(model=ScriptedModel(), root=root),
        telemetry=False,
    )
    operator = next(m for m in os.manager.members if m.id == OPERATOR_ID)
    operator.model = ScriptedModel(tool, arguments or {})
    path = f"/agents/{OPERATOR_ID}/runs"
    if delegated:
        os.manager.model = ScriptedModel(
            "delegate_task_to_member", {"member_id": OPERATOR_ID, "task": "Execute the tool"}
        )
        path = f"/teams/{MANAGER_TEAM_ID}/runs"
    if identity == "pat":
        from agno.db.schemas.service_accounts import ServiceAccount
        from agno.os.service_accounts import generate_token

        token, hashed, prefix = generate_token()
        os.db.create_service_account(
            ServiceAccount(
                id="probe-caller", name="probe-caller", token_hash=hashed, token_prefix=prefix, scopes=scopes
            ).to_dict()
        )
        request_headers = {"Authorization": "Bearer " + token}
    return os, TestClient(os.get_app()), path, request_headers


@pytest.mark.parametrize("identity", ["jwt", "managed", "pat"])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize(
    "tool,args,grant,marker",
    [
        ("read_file", {"path": "example.py"}, "filesystem:read", "READABLE_SOURCE_SENTINEL"),
        ("run_diagnostics", {}, "config:read", "checks"),
        ("get_platform_metrics", {}, "agent_os:admin", "window_days"),
    ],
)
def test_operator_action_grants(tmp_path, identity, allowed, tool, args, grant, marker):
    scopes = [f"teams:{MANAGER_TEAM_ID}:run"]
    if allowed:
        scopes.append(grant)
    os, client, path, request_headers = _operator_permission_os(tmp_path, scopes, identity, tool, args, delegated=True)
    response = client.post(path, headers=request_headers, data={"message": "Execute", "stream": "false"})
    assert response.status_code == 200, response.text
    content = response.json()["content"]
    if allowed:
        assert "Permission required:" not in content, content
        assert marker in content, content
    else:
        assert "Permission required: " + grant in content, content
        assert marker not in content, content


@pytest.mark.parametrize("scope", ["filesystem:read", "agent_os:admin"])
def test_even_authorized_source_reads_cannot_read_credential_files(tmp_path, scope):
    scopes = [f"teams:{MANAGER_TEAM_ID}:run", scope]
    os, client, path, h = _operator_permission_os(tmp_path, scopes, arguments={"path": ".env"}, delegated=True)
    response = client.post(path, headers=h, data={"message": "Read", "stream": "false"})
    assert response.status_code == 200
    assert "SECRET_SENTINEL_NEVER_RETURN" not in response.text
    assert "Error:" in response.json()["content"]


@pytest.mark.parametrize("mode", ["missing", "malformed", "expired", "wrong_audience"])
def test_invalid_credentials_cannot_start_manager(tmp_path, mode):
    os, client, _, _ = _operator_permission_os(tmp_path, [])
    claims = {"sub": "alice", "aud": "test", "scopes": ["agent_os:admin"], "exp": int(time.time()) + 300}
    h = {}
    if mode == "malformed":
        h = {"Authorization": "Bearer invalid-token"}
    elif mode != "missing":
        if mode == "expired":
            claims["exp"] = int(time.time()) - 300
        if mode == "wrong_audience":
            claims["aud"] = "another-os"
        h = {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}
    response = client.post(f"/teams/{MANAGER_TEAM_ID}/runs", headers=h, data={"message": "Hello", "stream": "false"})
    assert response.status_code == 401, response.text
    assert os.manager.model.calls == 0


def test_regular_user_cookbook_permissions_and_session_history(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    from pathlib import Path

    from agno.models.openai import OpenAIResponses
    from agno.os import create_dev_token

    examples = Path(__file__).resolve().parents[5] / "cookbook/05_agent_os/29_manager"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JWT_VERIFICATION_KEY", SECRET)
    monkeypatch.delenv("AGNO_API_KEY", raising=False)
    monkeypatch.syspath_prepend(str(examples))
    monkeypatch.delitem(sys.modules, "manager_user_access", raising=False)

    def unexpected_model_call(*args, **kwargs):
        pytest.fail("The permission checker must never call a live model")

    monkeypatch.setattr(OpenAIResponses, "invoke", unexpected_model_call)
    monkeypatch.setattr(OpenAIResponses, "ainvoke", unexpected_model_call)
    runpy.run_path(str(examples / "check_manager_permissions.py"), run_name="__main__")
    assert "All seven permission checks passed" in capsys.readouterr().out

    os = sys.modules["manager_user_access"].agent_os
    os.manager.model = ScriptedModel()
    client = TestClient(os.get_app())
    token = create_dev_token("alice", secret=SECRET, audience="manager-access-demo")
    alice_headers = {"Authorization": f"Bearer {token}"}
    own = client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs", headers=alice_headers, data={"message": "Hello", "stream": "false"}
    )
    assert own.status_code == 200
    assert client.get(f"/sessions/{own.json()['session_id']}", headers=alice_headers).status_code == 200
    other = os.manager.run("Hello", user_id="bob")
    assert client.get(f"/sessions/{other.session_id}", headers=alice_headers).status_code == 404
    # Do not retain the temporary app across unrelated cookbook imports.
    monkeypatch.delitem(sys.modules, "manager_user_access")


@pytest.mark.parametrize("manager_mode", ["omitted", "none", "disabled", "enabled"])
@pytest.mark.parametrize("identity", ["jwt", "managed_role", "service_account"])
@pytest.mark.parametrize("operation", ["list_models", "create_agent"])
def test_existing_studio_agents_keep_run_only_permissions(tmp_path, manager_mode, identity, operation):
    db = SqliteDb(db_file=str(tmp_path / "legacy.db"))
    registry = Registry(models=[ScriptedModel()])
    studio = StudioTools(registry=registry, db=db, create_agents=True)
    arguments = (
        {}
        if operation == "list_models"
        else {"name": "Built by legacy agent", "instructions": "Answer plainly", "publish": True}
    )
    legacy = Agent(id="legacy", model=ScriptedModel(operation, arguments), tools=[studio])
    scopes = ["agents:legacy:run"]
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test")
    token_headers = headers(scopes)
    if identity == "managed_role":
        auth.define_role("legacy-user", scopes)
        auth.assign("alice", "legacy-user")
        token_headers = headers([])
    elif identity == "service_account":
        from agno.db.schemas.service_accounts import ServiceAccount
        from agno.os.service_accounts import generate_token

        token, hashed, prefix = generate_token()
        db.create_service_account(
            ServiceAccount(id="legacy", name="legacy", token_hash=hashed, token_prefix=prefix, scopes=scopes).to_dict()
        )
        token_headers = {"Authorization": f"Bearer {token}"}
    kwargs = (
        {}
        if manager_mode == "omitted"
        else {
            "manager": OSManager(model=ScriptedModel())
            if manager_mode == "enabled"
            else None
            if manager_mode == "none"
            else False
        }
    )
    os = AgentOS(db=db, registry=registry, agents=[legacy], authorization=auth, telemetry=False, **kwargs)
    response = TestClient(os.get_app()).post(
        "/agents/legacy/runs", headers=token_headers, data={"message": "Use studio", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    assert "Permission required" not in response.text
    result = json.loads(response.json()["content"])
    assert result["ok"], result
    if operation == "list_models":
        assert result["data"]["models"][0]["id"] == "fixture"
    else:
        assert len(db.list_components()[0]) == 1


@pytest.mark.parametrize("allowed", [False, True])
def test_manager_dispatch_keeps_checks_on_existing_studio_agent(tmp_path, allowed):
    db = SqliteDb(db_file=str(tmp_path / "nested.db"))
    registry = Registry(models=[ScriptedModel()])
    studio = StudioTools(registry=registry, db=db)
    legacy = Agent(id="legacy", model=ScriptedModel("list_models"), tools=[studio])
    os = AgentOS(
        db=db,
        registry=registry,
        agents=[legacy],
        manager=OSManager(model=ScriptedModel("run_agent", {"agent_id": "legacy", "message": "List models"})),
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test"),
        telemetry=False,
    )
    client = TestClient(os.get_app())
    scopes = ["teams:os-manager-internal:run", "agents:legacy:run"] + (["registry:read"] if allowed else [])
    response = client.post(
        "/teams/os-manager-internal/runs", headers=headers(scopes), data={"message": "List models", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    assert ("Permission required: registry:read" in response.text) is not allowed
    # A manager delegation must not permanently tighten an ordinary agent or its shared toolkit.
    response = client.post(
        "/agents/legacy/runs",
        headers=headers(["agents:legacy:run"]),
        data={"message": "List models", "stream": "false"},
    )
    assert response.status_code == 200, response.text
    assert json.loads(response.json()["content"])["ok"]


@pytest.mark.parametrize("allowed", [False, True])
def test_ordinary_runner_cannot_dispatch_private_manager_member(tmp_path, allowed):
    from agno.tools.studio_runner import StudioRunnerTools

    os = make_os(tmp_path, ScriptedModel())
    operator = next(member for member in os.manager.members if member.id == OPERATOR_ID)
    operator.model = ScriptedModel("run_diagnostics")
    legacy = Agent(
        id="legacy",
        model=ScriptedModel("run_agent", {"agent_id": OPERATOR_ID, "message": "Diagnose"}),
        tools=[StudioRunnerTools(db=os.db, include_agents=[operator])],
    )
    os.agents.append(legacy)
    app = os.get_app()
    os.resync(app)
    scopes = ["agents:legacy:run"] + (["config:read"] if allowed else [])
    response = TestClient(app).post(
        "/agents/legacy/runs", headers=headers(scopes), data={"message": "Diagnose", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    assert "not found" in response.json()["content"]
    assert operator.model.calls == 0


@pytest.mark.parametrize("use_async", [False, True])
def test_shared_studio_tool_keeps_manager_checks_without_affecting_ordinary_agent(tmp_path, use_async):
    from agno.tools.function import Function, FunctionCall

    os = make_os(tmp_path, ScriptedModel())
    builder = next(member for member in os.manager.members if member.id == "platform-builder-internal")
    studio = builder.tools[0]
    fn = Function.from_callable(studio.list_models)
    fn._agent = builder
    fn.cache_results = True
    fn.cache_dir = str(tmp_path / "cache")
    # A trusted call may prime the same tool's cache.
    assert FunctionCall(function=fn, arguments={}).execute().status == "success"
    caller = authority(["agents:legacy:run"])
    caller.enforce_tools = False
    with authorization_scope(lambda: caller):
        call = FunctionCall(function=fn, arguments={})
        outcome = asyncio.run(call.aexecute()) if use_async else call.execute()
        assert outcome.status == "failure" and "registry:read" in outcome.error
        assert current_authorization() is caller and not caller.enforce_tools
        fn._agent = Agent(id="legacy")
        call = FunctionCall(function=fn, arguments={})
        outcome = asyncio.run(call.aexecute()) if use_async else call.execute()
        assert outcome.status == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_mode", ["legacy", "ordinary", "manager"])
async def test_queue_keeps_legacy_tools_compatible_and_manager_tools_protected(tmp_path, monkeypatch, snapshot_mode):
    from agno.tools.function import FunctionCall

    os = make_os(tmp_path, ScriptedModel())
    worker = QueueWorker(SimpleNamespace(), lambda *args: None, QueueConfig(), authorization_app=os.get_app())
    builder = next(member for member in os.manager.members if member.id == "platform-builder-internal")
    manager_function = builder.tools[0].functions["list_models"].model_copy(deep=False)
    manager_function._agent = builder
    ordinary_studio = StudioTools(registry=os.registry, db=os.db)
    payload = {}
    if snapshot_mode != "legacy":
        caller = authority([])
        caller.enforce_tools = snapshot_mode == "manager"
        payload[AUTHORIZATION_KEY] = caller.snapshot()

    async def execute(job, ownership):
        if snapshot_mode == "manager":
            with pytest.raises(PermissionError, match="registry:read"):
                ordinary_studio.list_models()
        else:
            assert json.loads(ordinary_studio.list_models())["ok"]
        outcome = await FunctionCall(function=manager_function, arguments={}).aexecute()
        assert outcome.status == "failure" and "registry:read" in outcome.error

    monkeypatch.setattr(worker, "_execute_claimed_inner", execute)
    await worker._execute_claimed({"id": "job", "attempt": 1, "payload": payload})
    assert current_authorization() is None


@pytest.mark.parametrize("manager_owned", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
def test_lazy_tool_work_keeps_authority_without_leaking_it(manager_owned, allowed, use_async):
    from agno.run.authorization import require_permission
    from agno.tools.function import Function, FunctionCall

    observed = []

    def values():
        try:
            observed.append(current_authorization().enforce_tools)
            yield "first"
            require_permission("registry", "read")
            yield "second"
        finally:
            observed.append(current_authorization().enforce_tools)

    async def avalues():
        try:
            observed.append(current_authorization().enforce_tools)
            yield "first"
            require_permission("registry", "read")
            yield "second"
        finally:
            observed.append(current_authorization().enforce_tools)

    fn = Function.from_callable(avalues if use_async else values)
    fn._agent = Agent(id=OPERATOR_ID if manager_owned else "ordinary")
    caller = authority(["registry:read"] if allowed else [])
    caller.enforce_tools = False
    with authorization_scope(lambda: caller):
        call = FunctionCall(function=fn, arguments={})
        if use_async:

            async def run():
                outcome = await call.aexecute()
                assert await outcome.result.__anext__() == "first"
                assert current_authorization() is caller
                if manager_owned and not allowed:
                    with pytest.raises(PermissionError, match="registry:read"):
                        await outcome.result.__anext__()
                else:
                    assert await outcome.result.__anext__() == "second"
                await outcome.result.aclose()

            asyncio.run(run())
        else:
            outcome = call.execute()
            assert next(outcome.result) == "first"
            assert current_authorization() is caller
            if manager_owned and not allowed:
                with pytest.raises(PermissionError, match="registry:read"):
                    next(outcome.result)
            else:
                assert next(outcome.result) == "second"
            outcome.result.close()
        assert current_authorization() is caller
        assert observed == [manager_owned, manager_owned]


@pytest.mark.parametrize("allowed", [False, True])
def test_shared_custom_decorated_tool_is_protected_only_in_manager_execution(tmp_path, allowed):
    from agno.run.authorization import requires_permission

    @requires_permission("registry", "read")
    def inspect_registry() -> str:
        return "REGISTRY_SENTINEL"

    legacy = Agent(id="legacy", model=ScriptedModel("inspect_registry"), tools=[inspect_registry])
    os = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "shared.db")),
        agents=[legacy],
        manager=OSManager(model=ScriptedModel("inspect_registry"), tools=[inspect_registry]),
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test"),
        telemetry=False,
    )
    client = TestClient(os.get_app())
    scopes = ["teams:os-manager-internal:run", "agents:legacy:run"] + (["registry:read"] if allowed else [])
    response = client.post(
        "/teams/os-manager-internal/runs", headers=headers(scopes), data={"message": "Inspect", "stream": "false"}
    )
    assert response.status_code == 200
    assert ("REGISTRY_SENTINEL" in response.text) is allowed
    response = client.post(
        "/agents/legacy/runs", headers=headers(scopes), data={"message": "Inspect", "stream": "false"}
    )
    assert response.status_code == 200
    assert "REGISTRY_SENTINEL" in response.text


@pytest.mark.parametrize("snapshot_mode", ["legacy", "ordinary", "manager"])
def test_scheduled_runs_keep_ordinary_tools_compatible_but_protect_manager(tmp_path, snapshot_mode):
    from agno.tools.function import FunctionCall

    os = make_os(tmp_path, ScriptedModel())
    request = SimpleNamespace(
        app=os.get_app(),
        state=SimpleNamespace(is_internal_service=True, authorization_enabled=True),
        headers={},
    )
    if snapshot_mode != "legacy":
        caller = authority([])
        caller.enforce_tools = snapshot_mode == "manager"
        request.headers[AUTHORIZATION_HEADER] = json.dumps(caller.snapshot())
    builder = next(member for member in os.manager.members if member.id == "platform-builder-internal")
    fn = builder.tools[0].functions["list_models"].model_copy(deep=False)
    fn._agent = builder
    with authorization_scope(lambda: request_authorization(request)):
        outcome = FunctionCall(function=fn, arguments={}).execute()
        assert outcome.status == "failure" and "registry:read" in outcome.error
        if snapshot_mode == "manager":
            with pytest.raises(PermissionError, match="registry:read"):
                builder.tools[0].list_models()
        else:
            assert json.loads(builder.tools[0].list_models())["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_target", [False, True])
async def test_mcp_preserves_ordinary_studio_access_and_enforces_manager_tools(tmp_path, monkeypatch, manager_target):
    from fastmcp import Client
    from fastmcp.server import dependencies

    from agno.os.mcp import build_mcp_server

    os = make_os(tmp_path, ScriptedModel())
    studio = StudioTools(registry=os.registry, db=os.db)
    legacy = Agent(id="legacy", model=ScriptedModel("list_models"), tools=[studio])
    os.agents.append(legacy)
    builder = next(member for member in os.manager.members if member.id == "platform-builder-internal")
    builder.model = ScriptedModel("list_models")
    os.manager.model = ScriptedModel("delegate_task_to_member", {"member_id": builder.id, "task": "List models"})
    app = os.get_app()
    os.resync(app)
    request = SimpleNamespace(
        app=app,
        scope={},
        headers={},
        state=SimpleNamespace(
            authenticated=True,
            authorization_enabled=True,
            user_id="alice",
            claims={"sub": "alice"},
            scopes=["agents:run", "teams:run"],
        ),
    )
    monkeypatch.setattr(dependencies, "get_http_request", lambda: request)
    async with Client(build_mcp_server(os)) as client:
        if manager_target:
            with pytest.raises(Exception, match="is reserved"):
                await client.call_tool("run_agent", {"agent_id": builder.id, "message": "List models"})
            assert builder.model.calls == 0
            result = await client.call_tool("run_team", {"team_id": MANAGER_TEAM_ID, "message": "List models"})
        else:
            result = await client.call_tool("run_agent", {"agent_id": "legacy", "message": "List models"})
    assert not result.is_error
    text = " ".join(block.text for block in result.content if hasattr(block, "text"))
    assert ("Permission required: registry:read" in text) is manager_target
    if not manager_target:
        assert "fixture" in text


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("manager_owned", [False, True])
def test_authorization_scope_preserves_post_hook_result_mutations(use_async, manager_owned):
    from agno.tools.function import Function, FunctionCall

    def answer() -> str:
        return "entrypoint result"

    def post_hook(fc):
        fc.result = "post-hook result"

    fn = Function(name="answer", entrypoint=answer, post_hook=post_hook)
    fn._agent = Agent(id=OPERATOR_ID if manager_owned else "ordinary")
    caller = authority([])
    caller.enforce_tools = False
    with authorization_scope(lambda: caller):
        call = FunctionCall(function=fn, arguments={})
        outcome = asyncio.run(call.aexecute()) if use_async else call.execute()
        assert outcome.status == "success"
        assert outcome.result == "entrypoint result"
        assert call.result == "post-hook result"


@pytest.mark.parametrize("changes", [{"cron_expr": "0 1 * * *"}, {"description": "Updated description"}])
def test_schedule_metadata_edit_preserves_execution_authority(tmp_path, changes):
    from agno.db.schemas.scheduler import Schedule
    from agno.scheduler.executor import ScheduleExecutor

    db = SqliteDb(db_file=str(tmp_path / "schedules.db"))
    target = Agent(id="scheduled", model=ScriptedModel(), telemetry=False)
    os = AgentOS(
        db=db,
        agents=[target],
        telemetry=False,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="test"),
    )
    app = os.get_app()
    app.state.internal_service_token = "internal-test-token"
    client = TestClient(app)
    created = client.post(
        "/schedules",
        headers=headers(["agent_os:admin"]),
        json={
            "name": "scheduled",
            "cron_expr": "0 0 * * *",
            "endpoint": "/agents/scheduled/runs",
            "payload": {"message": "run"},
        },
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]
    original_payload = db.get_schedule(schedule_id)["payload"]
    edited = client.patch("/schedules/" + schedule_id, headers=headers(["schedules:write"]), json=changes)
    assert edited.status_code == 200, edited.text
    saved = db.get_schedule(schedule_id)
    assert saved["payload"] == original_payload
    assert AUTHORIZATION_KEY not in edited.json()["payload"]

    executor = ScheduleExecutor(base_url="http://testserver", internal_service_token="internal-test-token")
    captured = {}

    async def fake_background(http_client, url, request_headers, data, *args, **kwargs):
        captured.update(headers=request_headers, data=data)
        return {}

    executor._background_run = fake_background
    executor._get_client = AsyncMock(return_value=object())
    asyncio.run(executor._call_endpoint(Schedule.from_dict(saved)))
    response = client.post(
        saved["endpoint"],
        headers=captured["headers"],
        data={**captured["data"], "stream": "false", "background": "false"},
    )
    assert response.status_code == 200, response.text
    assert "allowed target ran" in response.text

    # Executable edits must still be checked and must not retain the admin's authority.
    for execution_change in (
        {"endpoint": "/agents/scheduled/runs"},
        {"method": "POST"},
        {"payload": {"message": "changed", AUTHORIZATION_KEY: original_payload[AUTHORIZATION_KEY]}},
    ):
        denied = client.patch("/schedules/" + schedule_id, headers=headers(["schedules:write"]), json=execution_change)
        assert denied.status_code == 403, denied.text
        assert db.get_schedule(schedule_id)["payload"] == original_payload

    allowed = client.patch(
        "/schedules/" + schedule_id,
        headers=headers(["schedules:write", "agents:scheduled:run"]),
        json={"payload": {"message": "changed", AUTHORIZATION_KEY: original_payload[AUTHORIZATION_KEY]}},
    )
    assert allowed.status_code == 200, allowed.text
    snapshot = db.get_schedule(schedule_id)["payload"][AUTHORIZATION_KEY]
    assert snapshot["context"]["scopes"] == ["schedules:write", "agents:scheduled:run"]


@pytest.mark.parametrize(
    "tool,arguments,component_id,permission,expected",
    [
        ("list_agents", {}, MANAGER_TEAM_ID, "agents:visible:read", "visible"),
        ("list_teams", {}, MANAGER_TEAM_ID, "teams:visible:read", "visible"),
        ("list_workflows", {}, MANAGER_TEAM_ID, "workflows:visible:read", "visible"),
        ("read_file", {"path": "public.txt"}, OPERATOR_ID, "filesystem:read", "source content"),
        ("list_files", {}, OPERATOR_ID, "filesystem:read", "public.txt"),
        ("search_content", {"query": "source content"}, OPERATOR_ID, "filesystem:read", "public.txt"),
    ],
)
@pytest.mark.parametrize("allowed", [True, False])
def test_manager_tools_with_async_managed_roles(tmp_path, tool, arguments, component_id, permission, expected, allowed):
    from agno.db.sqlite import AsyncSqliteDb
    from agno.os.authz.native_engine import NativePolicyEngine
    from agno.team import Team
    from agno.workflow import Workflow

    (tmp_path / "public.txt").write_text("source content")
    policy_db = AsyncSqliteDb(db_file=str(tmp_path / "policy.db"))
    engine = NativePolicyEngine(db=policy_db)
    scopes = [(f"teams:{MANAGER_TEAM_ID}:run", "allow")]
    if allowed:
        scopes.append((permission, "allow"))

    async def seed():
        await engine.aset_role_scopes("reader", scopes)
        await engine.aassign("alice", "reader")

    asyncio.run(seed())
    visible = Agent(id="visible", model=ScriptedModel(), telemetry=False)
    hidden = Agent(id="hidden", model=ScriptedModel(), telemetry=False)
    visible_team = Team(id="visible", members=[visible], model=ScriptedModel(), telemetry=False)
    hidden_team = Team(id="hidden", members=[hidden], model=ScriptedModel(), telemetry=False)
    os = AgentOS(
        db=SqliteDb(db_file=str(tmp_path / "runs.db")),
        agents=[visible, hidden],
        teams=[visible_team, hidden_team],
        workflows=[Workflow(id="visible", steps=[visible]), Workflow(id="hidden", steps=[hidden])],
        manager=OSManager(model=ScriptedModel(tool, arguments), root=tmp_path, access_docs=False),
        telemetry=False,
        authorization=Authorization(
            verification_keys=[SECRET], algorithm="HS256", audience="test", db=policy_db, roles_claim="roles"
        ),
    )
    if component_id == OPERATOR_ID:
        os.manager.model = ScriptedModel(
            "delegate_task_to_member", {"member_id": OPERATOR_ID, "task": "Read the source"}
        )
    response = TestClient(os.get_app()).post(
        f"/teams/{MANAGER_TEAM_ID}/runs", headers=headers([]), data={"message": "run", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    content = response.json()["content"]
    assert "synchronously against an async database" not in content
    if tool.startswith("list_") and component_id == MANAGER_TEAM_ID:
        listing_family = tool.removeprefix("list_")
        listing = json.loads(content)
        assert [item["id"] for item in listing[listing_family]] == (["visible"] if allowed else [])
        assert listing["count"] == listing["total"] == int(allowed)
        assert "other_components" not in listing
    elif allowed:
        assert expected in content
    else:
        assert "Permission required: filesystem:read" in content
        assert "source content" not in content
