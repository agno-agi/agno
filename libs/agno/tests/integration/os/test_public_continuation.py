"""Public continuation through native HTTP/MCP with shared PostgreSQL persistence."""

import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, MCPConfig
from agno.os.config import AuthorizationConfig
from agno.os.public import PublicSurface, RateLimit
from agno.team import Team
from agno.tools import tool
from agno.workflow import Step, StepOutput, Workflow

pytestmark = pytest.mark.skipif(not os.getenv("AGNO_PAGE_TEST_DB_URL"), reason="requires isolated local PostgreSQL")
HEADERS = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}


@pytest.fixture
def database():
    url = make_url(os.environ["AGNO_PAGE_TEST_DB_URL"])
    assert url.host in ("localhost", "127.0.0.1", "::1")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = "public_continue_" + uuid4().hex[:12]
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(url.set(database=name))
    try:
        yield PostgresDb(db_engine=engine)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


class ApprovalModel(Model):
    def __init__(self):
        super().__init__(id="approval-test", name="approval-test", provider="test")

    def invoke(self, *args, **kwargs):
        messages = kwargs.get("messages", args[0] if args else [])
        if any(message.role == "tool" for message in messages):
            return ModelResponse(role="assistant", content="Finished", response_usage=MessageMetrics())
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {"id": "approval-call", "type": "function", "function": {"name": "approval_action", "arguments": "{}"}}
            ],
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

    def _parse_provider_response_delta(self, response, **kwargs):
        return response


def application(database, effects, *, team=False, limits=None, authorization=False, **bounds):
    @tool(requires_confirmation=True)
    def approval_action() -> str:
        effects.append("executed")
        return "Approved action executed"

    agent = Agent(id="public-agent", db=database, model=ApprovalModel(), tools=[approval_action], telemetry=False)
    component = (
        Team(
            id="public-team",
            db=database,
            model=ApprovalModel(),
            tools=[approval_action],
            members=[agent],
            telemetry=False,
        )
        if team
        else agent
    )
    surface = PublicSurface(
        agents=[] if team else [agent], teams=[component] if team else [], mcp=True, limits=limits, **bounds
    )
    server = AgentOS(
        id="public-continuation",
        authorization=authorization,
        authorization_config=AuthorizationConfig(
            verification_keys=["public-continuation-test-signing-key"], algorithm="HS256", user_isolation=True
        )
        if authorization
        else None,
        agents=[agent],
        teams=[component] if team else [],
        db=database,
        public=surface,
        mcp=MCPConfig(tools=[component], default_tools=False, stateless=True),
        auto_provision_dbs=False,
        telemetry=False,
    )
    return server, surface, component


def payload(response):
    assert response.status_code == 200, response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        if events and "jsonrpc" in events[0]:
            return events[0]
        return next(
            event
            for event in reversed(events)
            if event.get("event") in ("RunPaused", "RunCompleted", "TeamRunPaused", "TeamRunCompleted")
        )
    return response.json()


def mcp(client, name, arguments):
    result = payload(
        client.post(
            "/mcp",
            headers=HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        )
    )
    return result["result"]


def start(client, component, transport, stream=False):
    if transport == "mcp":
        result = mcp(client, component.id, {"message": "Do the action"})
        assert not result.get("isError"), result
        return result["structuredContent"]
    kind = "teams" if isinstance(component, Team) else "agents"
    return payload(
        client.post(f"/{kind}/{component.id}/runs", data={"message": "Do the action", "stream": str(stream).lower()})
    )


def resume(client, component, paused, transport, confirmed=True, stream=False):
    requirements = paused["requirements"]
    for requirement in requirements:
        requirement["tool_execution"]["confirmed"] = confirmed
    kind = "teams" if isinstance(component, Team) else "agents"
    if transport == "mcp":
        return mcp(
            client,
            "continue_run",
            {
                "run_id": paused["run_id"],
                "session_id": paused["session_id"],
                kind[:-1] + "_id": component.id,
                "requirements": requirements,
            },
        )
    field = "requirements" if kind == "teams" else "tools"
    values = requirements if kind == "teams" else [r["tool_execution"] for r in requirements]
    return client.post(
        f"/{kind}/{component.id}/runs/{paused['run_id']}/continue",
        data={"session_id": paused["session_id"], "stream": str(stream).lower(), field: json.dumps(values)},
    )


@pytest.mark.parametrize("team", [False, True])
@pytest.mark.parametrize(
    "start_transport,continue_transport", [("rest", "rest"), ("mcp", "mcp"), ("rest", "mcp"), ("mcp", "rest")]
)
@pytest.mark.parametrize("confirmed", [False, True])
def test_pause_and_resume_on_another_instance(database, team, start_transport, continue_transport, confirmed):
    effects = []
    first, _, component = application(database, effects, team=team)
    with TestClient(first.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, start_transport)
        assert paused["status"] == "PAUSED" and effects == []
    second, _, component = application(database, effects, team=team)
    with TestClient(second.get_app(), base_url="http://localhost") as client:
        result = resume(client, component, paused, continue_transport, confirmed)
        if continue_transport == "mcp":
            assert not result.get("isError"), result
            result = result["structuredContent"]
        else:
            result = payload(result)
        assert result["status"] == "COMPLETED", result
        assert effects == (["executed"] if confirmed else [])


@pytest.mark.parametrize("team", [False, True])
def test_streamed_pause_and_continuation(database, team):
    effects = []
    server, _, component = application(database, effects, team=team)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "rest", stream=True)
        result = payload(resume(client, component, paused, "rest", stream=True))
        assert result["event"] in ("RunCompleted", "TeamRunCompleted")
        assert effects == ["executed"]


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_wrong_session_and_unknown_runs_are_rejected(database, transport):
    effects = []
    server, _, component = application(database, effects)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")
        paused["session_id"] = str(uuid4())
        result = resume(client, component, paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 404
        result = mcp(
            client, "cancel_run", {"agent_id": component.id, "run_id": str(uuid4()), "session_id": str(uuid4())}
        )
        assert result["isError"]
        assert effects == []


def test_mcp_execution_shares_rest_run_quota(database):
    server, _, component = application(database, [], limits={"run": RateLimit(1, 1)})
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "rest")
        result = resume(client, component, paused, "mcp")
        assert result["isError"] and "rate_limited" in str(result)
        result = mcp(
            client,
            "cancel_run",
            {"agent_id": component.id, "run_id": paused["run_id"], "session_id": paused["session_id"]},
        )
        assert not result.get("isError"), result


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_resolution_cannot_change_the_saved_tool_call(database, transport):
    effects = []
    server, _, component = application(database, effects)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")
        paused["requirements"][0]["tool_execution"]["tool_args"] = {"injected": True}
        result = resume(client, component, paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 400
        assert effects == []


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_anonymous_continuation_cannot_bypass_required_admin_approval(database, transport):
    effects = []
    server, _, component = application(database, effects)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")
        database.create_approval(
            {
                "id": str(uuid4()),
                "run_id": paused["run_id"],
                "session_id": paused["session_id"],
                "status": "pending",
                "source_type": "agent",
                "approval_type": "required",
                "pause_type": "confirmation",
            }
        )
        result = resume(client, component, paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 403
        assert effects == []


def test_public_workflow_requires_authentication_on_both_transports(database):
    effects = []

    def execute(step_input):
        effects.append("workflow")
        return StepOutput(content="Workflow completed")

    workflow = Workflow(id="protected", steps=[Step(name="work", executor=execute)], db=database, telemetry=False)
    surface = PublicSurface(workflows=[workflow], mcp=True)
    server = AgentOS(
        id="workflow-policy",
        workflows=[workflow],
        db=database,
        public=surface,
        mcp=MCPConfig(tools=[workflow], default_tools=False, stateless=True),
        internal_service_token="test-workflow-token",
        auto_provision_dbs=False,
        telemetry=False,
    )
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        assert client.post("/workflows/protected/runs", data={"message": "{}"}).status_code == 401
        assert mcp(client, "protected", {"message": "{}"})["isError"]
        assert effects == []
        client.headers["Authorization"] = "Bearer test-workflow-token"
        result = mcp(client, "protected", {"message": "{}"})
        assert not result.get("isError"), result
        assert client.post("/workflows/protected/runs", data={"message": "{}", "stream": "false"}).status_code == 200
        assert effects == ["workflow", "workflow"]


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_authenticated_session_cannot_be_resumed_by_another_user(database, transport):
    import jwt

    from agno.os.middleware.jwt import JWTMiddleware

    key = "public-continuation-test-signing-key"
    effects = []
    server, _, component = application(database, effects)
    app = server.get_app()
    app.add_middleware(
        JWTMiddleware, verification_keys=[key], algorithm="HS256", user_isolation=True, authorization=True
    )

    def token(user):
        return "Bearer " + jwt.encode({"sub": user, "scopes": ["agents:run", "mcp:read"]}, key, algorithm="HS256")

    with TestClient(app, base_url="http://localhost") as client:
        client.headers["Authorization"] = token("alice")
        paused = start(client, component, "mcp")
        client.headers["Authorization"] = token("bob")
        result = resume(client, component, paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 404
        client.headers["Authorization"] = token("alice")
        result = resume(client, component, paused, transport)
        assert not result.get("isError") if transport == "mcp" else result.status_code == 200
        assert effects == ["executed"]
    # Even possession of Alice's handles does not permit anonymous continuation.
    second, _, component = application(database, [])
    with TestClient(second.get_app(), base_url="http://localhost") as client:
        result = resume(client, component, paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 404


@pytest.mark.parametrize("transport", ["rest", "mcp"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_live_binding_can_be_cancelled_from_another_instance(database, transport, authenticated):
    import asyncio

    from agno.run.cancel import cleanup_run, is_cancelled

    first, surface, component = application(database, [])
    second, _, _ = application(database, [])
    run_id, session_id = str(uuid4()), str(uuid4())
    second_app = second.get_app()
    headers = {}
    if authenticated:
        import jwt

        from agno.os.middleware.jwt import JWTMiddleware

        key = "public-live-binding-test-signing-key"
        second_app.add_middleware(
            JWTMiddleware, verification_keys=[key], algorithm="HS256", user_isolation=True, authorization=True
        )
        headers["Authorization"] = "Bearer " + jwt.encode(
            {"sub": "alice", "scopes": ["agents:run", "mcp:read"]}, key, algorithm="HS256"
        )
    with (
        TestClient(first.get_app(), base_url="http://localhost"),
        TestClient(second_app, base_url="http://localhost", headers=headers) as client,
    ):
        lease = asyncio.run(
            surface._bindings._claim("agents", component.id, session_id, run_id, "alice" if authenticated else None, 30)
        )
        try:
            if transport == "mcp":
                bad = mcp(
                    client, "cancel_run", {"agent_id": component.id, "session_id": str(uuid4()), "run_id": run_id}
                )
                assert bad["isError"] and not is_cancelled(run_id)
                good = mcp(client, "cancel_run", {"agent_id": component.id, "session_id": session_id, "run_id": run_id})
                assert not good.get("isError"), good
            else:
                route = f"/agents/{component.id}/runs/{run_id}/cancel"
                bad = client.post(route, params={"session_id": str(uuid4())})
                assert bad.status_code == 404 and not is_cancelled(run_id)
                good = client.post(route, params={"session_id": session_id})
                assert good.status_code == 200, good.text
            assert is_cancelled(run_id)
        finally:
            asyncio.run(surface._bindings._release(run_id, lease))
            cleanup_run(run_id)


def test_concurrent_resume_claim_does_not_execute_twice(database):
    import asyncio

    effects = []
    server, surface, component = application(database, effects)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")
        lease = asyncio.run(
            surface._bindings._claim("agents", component.id, paused["session_id"], paused["run_id"], None, 30)
        )
        try:
            result = resume(client, component, paused, "mcp")
            assert result["isError"] and "run_in_progress" in str(result)
            assert effects == []
        finally:
            asyncio.run(surface._bindings._release(paused["run_id"], lease))
        assert not resume(client, component, paused, "mcp").get("isError")
        assert effects == ["executed"]


def test_mcp_respects_run_capacity_and_releases_it_after_timeout(database):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    started, released = threading.Event(), threading.Event()

    class WaitingModel(ApprovalModel):
        async def ainvoke(self, *args, **kwargs):
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                released.set()

        async def ainvoke_stream(self, *args, **kwargs):
            await self.ainvoke(*args, **kwargs)
            yield ModelResponse(role="assistant", content="done", response_usage=MessageMetrics())

    server, surface, component = application(database, [], max_active_runs=1, max_run_seconds=0.5)
    component.model = WaitingModel()
    with TestClient(server.get_app(), base_url="http://localhost") as client, ThreadPoolExecutor() as pool:
        pending = pool.submit(mcp, client, component.id, {"message": "wait"})
        assert started.wait(5)
        response = client.post("/agents/public-agent/runs", data={"message": "hi", "stream": "false"})
        assert response.status_code == 503 and response.json()["error"]["code"] == "run_capacity"
        result = pending.result(timeout=5)
        assert result["isError"] and released.is_set()
        # The next request reaches the model rather than retaining the old reservation.
        started.clear()
        result = mcp(client, component.id, {"message": "wait again"})
        assert result["isError"] and started.is_set() and "run_capacity" not in str(result)


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_team_can_resume_its_members_paused_tool(database, transport):
    class DelegateModel(ApprovalModel):
        def invoke(self, *args, **kwargs):
            messages = kwargs.get("messages", args[0] if args else [])
            if any(message.role == "tool" for message in messages):
                return ModelResponse(role="assistant", content="Finished", response_usage=MessageMetrics())
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "delegate-call",
                        "type": "function",
                        "function": {
                            "name": "delegate_task_to_member",
                            "arguments": json.dumps({"member_id": "public-agent", "task": "Do the action"}),
                        },
                    }
                ],
                response_usage=MessageMetrics(),
            )

    effects = []
    server, _, component = application(database, effects, team=True)
    component.model, component.tools = DelegateModel(), []
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")
        assert paused["status"] == "PAUSED" and effects == []
        assert paused["requirements"][0]["member_agent_id"] == "public-agent"
        assert client.post("/agents/public-agent/runs", data={"message": "hi"}).status_code == 404
        result = resume(client, component, paused, transport)
        assert not result.get("isError") if transport == "mcp" else result.status_code == 200
        assert effects == ["executed"]


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_wrong_component_handles_do_not_authorize_continuation(database, transport):
    effects = []
    server, surface, component = application(database, effects, team=True)
    # Publish both components under their own identities.
    surface.agents = server.agents
    server.mcp = MCPConfig(tools=[component, server.agents[0]], default_tools=False, stateless=True)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")
        result = resume(client, server.agents[0], paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 404
        assert effects == []


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_approval_storage_failure_cannot_skip_required_check(database, transport, monkeypatch):
    effects = []
    server, _, component = application(database, effects)
    with TestClient(server.get_app(), base_url="http://localhost") as client:
        paused = start(client, component, "mcp")

        def unavailable(**kwargs):
            raise RuntimeError("private approval database diagnostic")

        monkeypatch.setattr(database, "get_approvals", unavailable)
        result = resume(client, component, paused, transport)
        assert result.get("isError") if transport == "mcp" else result.status_code == 503
        assert "private approval database diagnostic" not in str(result)
        assert effects == []


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_authenticated_workflow_can_pause_and_resume(database, transport):
    import jwt

    from agno.os.middleware.jwt import JWTMiddleware
    from agno.workflow.types import HumanReview

    effects = []

    def execute(step_input):
        effects.append("workflow")
        return StepOutput(content="Workflow completed")

    workflow = Workflow(
        id="protected",
        db=database,
        telemetry=False,
        steps=[Step(name="work", executor=execute, human_review=HumanReview(requires_confirmation=True))],
    )
    server = AgentOS(
        id="workflow-pause",
        workflows=[workflow],
        db=database,
        public=PublicSurface(workflows=[workflow], mcp=True),
        mcp=MCPConfig(tools=[workflow], default_tools=False, stateless=True),
        auto_provision_dbs=False,
        telemetry=False,
    )
    app = server.get_app()
    key = "public-workflow-test-signing-key"
    app.add_middleware(
        JWTMiddleware, verification_keys=[key], algorithm="HS256", user_isolation=True, authorization=True
    )
    token = jwt.encode({"sub": "alice", "scopes": ["workflows:run", "mcp:read"]}, key, algorithm="HS256")
    with TestClient(app, base_url="http://localhost") as client:
        client.headers["Authorization"] = "Bearer " + token
        if transport == "mcp":
            initial = mcp(client, "protected", {"message": "{}"})
            assert not initial.get("isError"), initial
            paused = initial["structuredContent"]
            requirements = paused["requirements"]
        else:
            paused = payload(client.post("/workflows/protected/runs", data={"message": "{}", "stream": "false"}))
            requirements = paused["step_requirements"]
        assert paused["status"] == "PAUSED" and effects == []
        for requirement in requirements:
            requirement["confirmed"] = True
        if transport == "mcp":
            result = mcp(
                client,
                "continue_run",
                {
                    "workflow_id": "protected",
                    "run_id": paused["run_id"],
                    "session_id": paused["session_id"],
                    "requirements": requirements,
                },
            )
            assert not result.get("isError"), result
            assert result["structuredContent"]["status"] == "COMPLETED"
        else:
            result = payload(
                client.post(
                    f"/workflows/protected/runs/{paused['run_id']}/continue",
                    data={
                        "session_id": paused["session_id"],
                        "step_requirements": json.dumps(requirements),
                        "stream": "false",
                    },
                )
            )
            assert result["status"] == "COMPLETED"
        assert effects == ["workflow"]


@pytest.mark.parametrize("team", [False, True])
def test_anonymous_continuation_with_native_jwt_policy(database, team):
    effects = []
    server, _, component = application(database, effects, team=team, authorization=True)
    with TestClient(server.get_app(), base_url="http://localhost", root_path="/runtime") as client:
        paused = start(client, component, "rest")
        result = resume(client, component, paused, "rest")
        assert result.status_code == 200, result.text
        assert effects == ["executed"]
        assert client.get("/config").status_code == 401


@pytest.mark.parametrize("form", [False, True])
def test_anonymous_cancel_with_native_jwt_policy(database, form):
    import asyncio

    from agno.run.cancel import cleanup_run, is_cancelled

    server, surface, component = application(database, [], authorization=True)
    run_id, session_id = str(uuid4()), str(uuid4())
    with TestClient(server.get_app(), base_url="http://localhost", root_path="/runtime") as client:
        lease = asyncio.run(surface._bindings._claim("agents", component.id, session_id, run_id, None, 30))
        try:
            route = f"/agents/{component.id}/runs/{run_id}/cancel"
            duplicate = client.post(route, params={"session_id": session_id}, data={"session_id": session_id})
            assert duplicate.status_code == 400 and not is_cancelled(run_id)
            result = client.post(route, **{"data" if form else "params": {"session_id": session_id}})
            assert result.status_code == 200, result.text
            assert is_cancelled(run_id)
        finally:
            asyncio.run(surface._bindings._release(run_id, lease))
            cleanup_run(run_id)
