"""Human chat creates Company declarations across all four SQL adapters."""

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.company.execution import _ExecutorAuthorization
from agno.company.routines import _RoutineAuthorization
from agno.db.base import AsyncBaseDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.registry import Registry
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, RunAuthorization
from agno.tools.company import CompanyTools
from tests.integration.db.test_company_playbook_parity import db as company_db

db = company_db

ROUTINE = dict(name="intake", template="intake", executor_type="agent", executor_id="reader")
SOURCE = dict(type="website", reference="https://docs.agno.com")
# POST /company/routines requires the same pair, so chat and HTTP agree on who may create a Routine.
WRITE_SCOPES = ["products:write", "schedules:write", "routines:write"]


def context(scopes=None, wrapper=None):
    authority = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id="ana", scopes=scopes if scopes is not None else ["agent_os:admin"]),
    )
    if wrapper:
        authority = wrapper(authority)
    return RunContext(run_id="chat-run", session_id="chat", user_id="untrusted-user", authorization=authority)


async def invoke(tools, tool_name, use_async, **kwargs):
    fn = getattr(tools, ("a" if use_async else "") + tool_name)
    if use_async:
        return json.loads(await fn(**kwargs))
    if isinstance(tools.db, AsyncBaseDb):
        pytest.skip("Sync tools require a sync database")
    return json.loads(await asyncio.to_thread(fn, **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_founder_creates_product_source_and_routines_visible_over_http(db, use_async):
    reader = Agent(id="reader")
    registry = Registry(agents=[reader])
    tools = CompanyTools(db)
    os = AgentOS(db=db, agents=[Agent(id="chat", tools=[tools]), reader], company=CompanyConfig(), registry=registry)
    product = await invoke(
        tools,
        "create_company_product",
        use_async,
        name="Documentation",
        purpose="Help people build agents",
        sources=[SOURCE],
        routines=[ROUTINE],
        _agno_run_context=context(),
        _agno_agent=os.agents[0],
    )
    assert product["user_id"] == "ana"
    routine = await invoke(
        tools,
        "create_product_routine",
        use_async,
        product_id=product["id"],
        name="custom",
        instructions="Read the Product and report changes",
        executor_type="agent",
        executor_id="reader",
        cron_expr="0 9 * * *",
        timezone="Europe/London",
        _agno_run_context=context(),
    )
    async with AsyncClient(transport=ASGITransport(app=os.get_app()), base_url="http://test") as client:
        products = (await client.get("/company/products")).json()["data"]
        sources = (await client.get("/company/sources")).json()["data"]
        routines = (await client.get("/company/routines")).json()["data"]
        assert [p["id"] for p in products] == [product["id"]]
        assert len(sources) == 1 and sources[0]["reference"] == SOURCE["reference"]
        assert sources[0]["user_id"] == "ana" and sources[0]["config"]["metadata"]["run_id"] == "chat-run"
        assert len(routines) == 2 and all(r["enabled"] and r["user_id"] == "ana" for r in routines)
        assert {r["schedule_type"] for r in routines} == {"scheduled", "on_demand"}
        assert set(products[0]["metadata"]["routine_ids"]) == {r["id"] for r in routines}
    assert AUTHORIZATION_KEY not in routine["payload"]
    from agno.scheduler import ScheduleManager

    saved = await ScheduleManager(db).aget(routine["id"])
    assert saved.payload[AUTHORIZATION_KEY]["context"]["principal_id"] == "ana"


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("owner", [None, "owner"])
async def test_isolated_member_adds_a_routine_to_a_product_they_do_not_own(db, use_async, owner):
    from agno.company.execution import _call

    product_id = "declared" if owner is None else "owned"
    await _call(
        db,
        "create_product",
        {"id": product_id, "name": "Docs", "user_id": owner, "created_at": 1, "updated_at": None, "deleted_at": None},
    )
    tools = CompanyTools(db, registry=Registry(agents=[Agent(id="reader")]), user_isolation=True)
    routine = await invoke(
        tools,
        "create_product_routine",
        use_async,
        product_id=product_id,
        **ROUTINE,
        _agno_run_context=context([*WRITE_SCOPES, "agents:reader:run"]),
    )
    assert routine["user_id"] == "ana" and routine["enabled"]
    assert (await _call(db, "get_product", product_id))["metadata"]["routine_ids"] == [routine["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("tool", ["create_company_product", "create_product_routine"])
@pytest.mark.parametrize("wrapper", [None, _RoutineAuthorization, _ExecutorAuthorization])
async def test_creation_refuses_missing_product_scope_and_automated_runs(db, use_async, tool, wrapper):
    tools = CompanyTools(db)
    kwargs = {"name": "Forbidden"}
    if tool == "create_product_routine":
        kwargs.update(product_id="missing", template="intake", executor_type="agent", executor_id="reader")
    ctx = context(scopes=[] if wrapper is None else ["agent_os:admin"], wrapper=wrapper)
    with pytest.raises(PermissionError, match="products:write" if wrapper is None else "automated"):
        await invoke(tools, tool, use_async, **kwargs, _agno_run_context=ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("scope", ["sources:write", "schedules:write", "routines:write", "agents:reader:run"])
async def test_nested_permissions_fail_before_creating_product(db, use_async, scope):
    tools = CompanyTools(db, registry=Registry(agents=[Agent(id="reader")]))
    scopes = [s for s in [*WRITE_SCOPES, "sources:write", "agents:reader:run"] if s != scope]
    with pytest.raises(PermissionError, match=scope):
        await invoke(
            tools,
            "create_company_product",
            use_async,
            name="No partial Product",
            sources=[SOURCE],
            routines=[ROUTINE],
            _agno_agent=Agent(id="chat"),
            _agno_run_context=context(scopes),
        )
    from agno.company.execution import _call

    assert (await _call(db, "get_products"))[1] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize(
    "invalid", ["local_source", "unknown_executor", "bad_cron", "auto_accept", "duplicate_routine"]
)
async def test_invalid_declarations_leave_no_product(db, use_async, invalid):
    tools = CompanyTools(db, registry=Registry(agents=[Agent(id="reader")]))
    sources, routines = [SOURCE], [dict(ROUTINE)]
    if invalid == "local_source":
        sources = [dict(type="markdown", reference="/tmp/private.md")]
    elif invalid == "unknown_executor":
        routines[0]["executor_id"] = "missing"
    elif invalid == "bad_cron":
        routines[0]["cron_expr"] = "not a cron"
    elif invalid == "duplicate_routine":
        routines.append(dict(ROUTINE))
    else:
        routines[0]["auto_accept"] = dict(
            executor_type="agent", executor_id="reader", limits=dict(expires_at=9999999999)
        )
    with pytest.raises((ValueError, PermissionError)):
        await invoke(
            tools,
            "create_company_product",
            use_async,
            name="Invalid",
            sources=sources,
            routines=routines,
            _agno_agent=Agent(id="chat"),
            _agno_run_context=context(),
        )
    from agno.company.execution import _call

    assert (await _call(db, "get_products"))[1] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_routine_creation_checks_the_product_before_its_executor(db, use_async):
    tools = CompanyTools(db, user_isolation=True, registry=Registry(agents=[Agent(id="reader")]))
    unknown = {**ROUTINE, "executor_id": "missing"}
    with pytest.raises(LookupError, match="Product not found"):
        await invoke(
            tools, "create_product_routine", use_async, product_id="missing", **unknown, _agno_run_context=context()
        )


def _failing_link(db, calls, error=None):
    def record(args):
        calls.append(args)
        if error is not None:
            raise error
        return None

    if isinstance(db, AsyncBaseDb):

        async def failing(self, *args, **kwargs):
            return record(args)

    else:

        def failing(self, *args, **kwargs):
            return record(args)

    return failing


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("failing", ["add_product_routine", "update_schedule"])
async def test_failed_link_or_enable_leaves_no_schedule_and_the_name_stays_usable(db, use_async, failing, monkeypatch):
    from agno.company.execution import _call

    tools = CompanyTools(db, registry=Registry(agents=[Agent(id="reader")]))
    product = await invoke(tools, "create_company_product", use_async, name="Docs", _agno_run_context=context())
    original, calls = getattr(type(db), failing), []
    monkeypatch.setattr(type(db), failing, _failing_link(db, calls))
    with pytest.raises(RuntimeError, match="linked" if failing == "add_product_routine" else "enabled"):
        await invoke(
            tools, "create_product_routine", use_async, product_id=product["id"], **ROUTINE, _agno_run_context=context()
        )
    assert calls and (await _call(db, "get_schedules"))[1] == 0
    assert (await _call(db, "get_product", product["id"]))["metadata"].get("routine_ids", []) == []
    monkeypatch.setattr(type(db), failing, original)
    routine = await invoke(
        tools, "create_product_routine", use_async, product_id=product["id"], **ROUTINE, _agno_run_context=context()
    )
    assert routine["enabled"] and routine["name"] == product["id"] + ".intake"
    assert (await _call(db, "get_product", product["id"]))["metadata"]["routine_ids"] == [routine["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_failed_routine_write_discards_the_partial_product(db, use_async, monkeypatch):
    from agno.company.execution import _call

    tools = CompanyTools(db, registry=Registry(agents=[Agent(id="reader")]))
    calls: list = []
    monkeypatch.setattr(type(db), "add_product_routine", _failing_link(db, calls, RuntimeError("link failed")))
    with pytest.raises(RuntimeError, match="link failed"):
        await invoke(
            tools,
            "create_company_product",
            use_async,
            name="Partial",
            sources=[SOURCE],
            routines=[ROUTINE],
            _agno_agent=Agent(id="chat"),
            _agno_run_context=context(),
        )
    assert calls
    assert (await _call(db, "get_products"))[1] == 0
    assert (await _call(db, "get_sources"))[1] == 0
    assert (await _call(db, "get_schedules"))[1] == 0


from tests.integration.db.test_company_execution_parity import OfflineModel  # noqa: E402
from tests.integration.db.test_company_execution_parity import system as execution_system  # noqa: E402

system = execution_system


class CreationModel(OfflineModel):
    def invoke(self, messages, *args, **kwargs):
        from agno.models.message import MessageMetrics
        from agno.models.response import ModelResponse

        if not any(message.role == "tool" for message in messages):
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    dict(
                        id="create",
                        type="function",
                        function=dict(
                            name="create_company_product",
                            arguments=json.dumps(
                                dict(
                                    name="Chat-created",
                                    purpose="Serve our docs",
                                    sources=[SOURCE],
                                    routines=[{**ROUTINE, "executor_id": "writer"}],
                                )
                            ),
                        ),
                    )
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="Done", response_usage=MessageMetrics())


@pytest.mark.asyncio
async def test_company_manager_runtime_injects_caller_and_parses_declarations(db):
    from agno.run.authorization import authorization_scope

    os = AgentOS(
        db=db,
        agents=[Agent(id="writer", model=OfflineModel())],
        company=CompanyConfig(model=CreationModel()),
        telemetry=False,
    )
    with authorization_scope(lambda: context().authorization):
        output = await os.company_manager.arun("Set up a Product for our docs site", user_id="ana")
    assert output.tools and not output.tools[0].tool_call_error, output
    async with AsyncClient(transport=ASGITransport(app=os.get_app()), base_url="http://test") as client:
        products = (await client.get("/company/products")).json()["data"]
        assert len(products) == 1 and products[0]["user_id"] == "ana"
        assert len((await client.get("/company/sources")).json()["data"]) == 1
        assert len((await client.get("/company/routines")).json()["data"]) == 1


@pytest.mark.asyncio
async def test_real_routine_run_cannot_create_product(system):
    client, db, worker, os, components = system
    components["writer"].model = CreationModel()
    components["writer"].tools = [CompanyTools(db)]
    os.resync(worker.authorization_app)
    product = (await client.post("/company/products", json={"name": "Original"})).json()
    routine = (
        await client.post(
            "/company/routines",
            json=dict(
                product_id=product["id"],
                **{**ROUTINE, "executor_id": "writer"},
            ),
        )
    ).json()
    from unittest.mock import AsyncMock

    from agno.scheduler.executor import ScheduleExecutor
    from tests.integration.db.test_company_execution_parity import SimpleClient, execute

    worker.config.max_attempts = 1
    worker.authorization_app.state.internal_service_token = "contract-internal"

    async def request_and_work(method, url, **kwargs):
        response = await client.request(method, url, **kwargs)
        if method == "POST" and response.status_code == 202:
            job = await execute(worker)
            assert job["status"] == "failed", job
        return response

    executor = ScheduleExecutor(base_url="http://test", internal_service_token="contract-internal", poll_interval=0)
    executor._get_client = AsyncMock(return_value=SimpleClient(request_and_work))
    worker.authorization_app.state.scheduler_executor = executor
    response = await client.post("/company/routines/" + routine["id"] + "/trigger")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed", response.text
    assert "automated" in response.json()["error"]
    assert [p["id"] for p in (await client.get("/company/products")).json()["data"]] == [product["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_provider_decides_permissions_and_records_human(db, use_async):
    class HumanGrants(ScopeAuthorizationProvider):
        enforces_token_scopes = False

        def authorize_route(self, ctx, required_scopes):
            # This plane ignores token scopes, including a claimed admin scope.
            return ctx.principal_id == "ana" and set(required_scopes) <= {*WRITE_SCOPES, "agents:run"}

    ctx = context([])
    ctx.authorization.provider = HumanGrants()
    tools = CompanyTools(db, user_isolation=True, registry=Registry(agents=[Agent(id="reader")]))
    product = await invoke(
        tools, "create_company_product", use_async, name="Human grants", routines=[ROUTINE], _agno_run_context=ctx
    )
    assert product["user_id"] == "ana" and len(product["metadata"]["routine_ids"]) == 1
    ctx.authorization.context.principal_id = "dev"
    ctx.authorization.context.scopes = ["agent_os:admin"]
    with pytest.raises(PermissionError, match="products:write"):
        await invoke(tools, "create_company_product", use_async, name="Denied", _agno_run_context=ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_automatic_dispatch_context_overrides_human_grants(db, use_async):
    from agno.company.execution import _automatic_task

    tools = CompanyTools(db)
    token = _automatic_task.set({"id": "automatically-dispatched"})
    try:
        with pytest.raises(PermissionError, match="automated"):
            await invoke(tools, "create_company_product", use_async, name="Denied", _agno_run_context=context())
    finally:
        _automatic_task.reset(token)
