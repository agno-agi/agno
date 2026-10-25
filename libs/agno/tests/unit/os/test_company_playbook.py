"""Company playbook, bounded tools and framework Company Manager contracts."""

import inspect
import json

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.registry import Registry
from agno.registry._reserved import COMPANY_MANAGER_ID
from agno.run import RunContext
from agno.tools.company import CompanyTools


@pytest.mark.parametrize("manager", [False, True])
def test_company_manager_assembly_and_model_precedence(tmp_path, manager):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    first, override = OpenAIResponses(id="first"), OpenAIResponses(id="override")
    registry = Registry(models=[first])
    os = AgentOS(
        db=db,
        registry=registry,
        company=CompanyConfig(model=override),
        manager=OSManager(access_docs=False) if manager else None,
        telemetry=False,
    )
    pm = os.company_manager
    assert pm.id == COMPANY_MANAGER_ID and pm.model is override
    assert pm.learning.decision_log.db is db
    assert pm not in registry.agents and not registry.tools
    assert sum(agent is pm for agent in os._agents) == 1
    if manager:
        member = next(m for m in os.manager.members if m.id == COMPANY_MANAGER_ID)
        assert member is not pm and member not in os._agents and member not in registry.agents
        assert member.model is override and member.tools[0] is not pm.tools[0]
        delegation = os.manager.instructions[-1]
        assert "Routines" in delegation and "Tasks" in delegation and "not Platform Builder" in delegation
    os.resync(os.get_app())
    assert pm not in registry.agents and not registry.tools
    tools = pm.tools[0]
    assert {"create_company_product", "create_product_routine"} <= tools.functions.keys()
    assert tools.registry is registry
    assert not any("schedule" in name or "transition" in name for name in tools.functions)
    assert "log_company_decision" not in tools.functions
    assert "summarize_company_product" not in tools.functions
    assert "refresh_company_product" not in tools.functions
    assert "summarize_company_product" in CompanyTools(db, summary_tools=True).functions
    assert {fn.__name__ for fn in pm.learning.decision_log.get_tools()} == {
        "log_company_decision",
        "search_company_decisions",
    }
    inherited = AgentOS(db=db, registry=Registry(models=[first, override]), company=CompanyConfig(), telemetry=False)
    assert inherited.company_manager.model is first
    with pytest.raises(ValueError, match="cron_expr"):
        CompanyConfig(cron_expr="")


def test_company_tools_published_only_over_mcp_are_bound(tmp_path):
    from agno.os import MCPConfig

    db = SqliteDb(db_file=str(tmp_path / "mcp.db"))
    registry = Registry(agents=[Agent(id="reader")])
    exposed, explicit = CompanyTools(db), CompanyTools(db, registry=Registry())
    AgentOS(
        db=db,
        registry=registry,
        company=CompanyConfig(automation_history_retention_days=7),
        mcp=MCPConfig(tools=[exposed, explicit]),
        telemetry=False,
    )
    assert exposed.registry is registry and exposed._schedule_db is db
    assert exposed._automation_history_retention_days == 7
    assert explicit.registry is not registry


def test_no_model_manual_api_and_disabled_company(tmp_path, caplog):
    db = SqliteDb(db_file=str(tmp_path / "no-model.db"))
    os = AgentOS(db=db, company=CompanyConfig(), telemetry=False)
    assert not any("Company Manager unavailable" in record.message for record in caplog.records)
    assert os.company_manager is None and "CompanyConfig(model=" in os.company_manager_unavailable_reason
    assert any(c.name == "company" and c.status == "WARN" for c in os.run_diagnostics().checks)
    assert TestClient(os.get_app()).post("/company/decisions", json={"decision": "manual"}).status_code == 201
    disabled = AgentOS(db=db, telemetry=False)
    assert not any(getattr(route, "path", "").startswith("/company") for route in disabled.get_app().routes)
    with pytest.raises(ValueError, match="reserved"):
        AgentOS(db=db, agents=[Agent(id=COMPANY_MANAGER_ID)], telemetry=False)
    with pytest.raises(ValueError, match="reserved"):
        Registry(agents=[Agent(id=COMPANY_MANAGER_ID)])


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_tools_identity_fence_and_learning(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "tools.db"))
    from agno.agent import Agent

    manager = CompanyManager(db, registry=Registry(agents=[Agent(id="writer")]))
    product = manager.create(name="SDK", user_id="alice")
    project = manager.create_project(product_id=product["id"], name="Release", user_id="alice")
    tools = CompanyTools(db, user_isolation=True)
    alice = RunContext(run_id="r", session_id="s", user_id="alice")
    bob = RunContext(run_id="r2", session_id="s2", user_id="bob")

    async def invoke(name, *args, **kwargs):
        fn = getattr(tools, ("a" if use_async else "") + name)
        return await fn(*args, **kwargs) if use_async else fn(*args, **kwargs)

    task = json.loads(
        await invoke("propose_company_task", product["id"], "Draft", project_id=project["id"], _agno_run_context=alice)
    )
    assert task["status"] == "backlog" and task["user_id"] == "alice"
    assert json.loads(await invoke("list_company_tasks", _agno_run_context=bob))["meta"]["total_count"] == 1
    # Edits are collaborative, as on PATCH /company/tasks; ownership does not move.
    edited = json.loads(await invoke("edit_company_task", task["id"], "Draft v2", "bob's", _agno_run_context=bob))
    assert edited["title"] == "Draft v2" and edited["user_id"] == "alice"
    await invoke("edit_company_task", task["id"], "Draft", "better", _agno_run_context=alice)
    renamed = json.loads(await invoke("edit_company_project", project["id"], "Launch", "Ship", _agno_run_context=bob))
    assert renamed["name"] == "Launch" and renamed["user_id"] == "alice"
    manager.transition_task(
        task_id=task["id"],
        target="ready",
        reason="approved",
        executor_type="agent",
        executor_id="writer",
        accepted_by="alice",
    )
    with pytest.raises(ValueError, match="Backlog"):
        await invoke("edit_company_task", task["id"], "changed", "no", _agno_run_context=alice)
    await invoke("update_product_status", product["id"], "draft ready", 1, _agno_run_context=alice)
    entry = json.loads(
        await invoke("log_company_decision", "Draft first", reasoning="review needed", _agno_run_context=alice)
    )
    assert entry["user_id"] == "alice" and entry["session_id"] == "s"
    assert entry["agent_id"] is None
    assert manager.list_decisions(agent_id=COMPANY_MANAGER_ID, session_id="s")[1] == 0
    for function in tools.get_async_functions().values():
        function.process_entrypoint()
        properties = function.parameters.get("properties", {})
        if function.name == "log_company_decision":
            assert "agent_id" not in properties
        assert not {"user_id", "_agno_run_context", "owner", "auto_accept", "accepted_by"} & set(properties)
        if function.name != "create_company_product":
            assert "sources" not in properties
    with pytest.raises(PermissionError):
        await invoke("propose_company_task", product["id"], "anonymous", project_id=project["id"])


@pytest.mark.asyncio
async def test_direct_mcp_has_only_bounded_tools(tmp_path):
    from fastmcp import Client

    from agno.os import MCPConfig
    from agno.os.mcp import build_mcp_server

    db = SqliteDb(db_file=str(tmp_path / "mcp.db"))
    product = CompanyManager(db).create(name="SDK")
    project = CompanyManager(db).create_project(product_id=product["id"], name="Release")
    tools = CompanyTools(db)
    os = AgentOS(db=db, company=CompanyConfig(), mcp=MCPConfig(tools=[tools], default_tools=False), telemetry=False)
    async with Client(build_mcp_server(os)) as client:
        surface = await client.list_tools()
        assert {tool.name for tool in surface} == set(tools.functions)
        for tool in surface:
            assert "_agno_run_context" not in tool.inputSchema.get("properties", {})
            assert "user_id" not in tool.inputSchema.get("properties", {})
        result = await client.call_tool(
            "propose_company_task", {"product_id": product["id"], "title": "MCP proposal", "project_id": project["id"]}
        )
        assert not result.is_error
        rows, _ = CompanyManager(db).list_tasks()
        assert rows[0]["status"] == "backlog" and rows[0]["user_id"] is None
        result = await client.call_tool("log_company_decision", {"decision": "MCP decision"})
        assert not result.is_error
        decisions, _ = CompanyManager(db).list_decisions()
        assert decisions[0].agent_id is None
        for forbidden in ["transition_company_task", "accept_company_task", "complete_company_task"]:
            result = await client.call_tool(forbidden, {"task_id": rows[0]["id"]}, raise_on_error=False)
            assert result.is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async", "http"])
async def test_company_manager_runs_tools_with_injected_identity(tmp_path, mode):
    from agno.models.base import Model
    from agno.models.message import MessageMetrics
    from agno.models.response import ModelResponse

    db = SqliteDb(db_file=str(tmp_path / "runtime.db"))
    product = CompanyManager(db).create(name="SDK", user_id="alice")
    project = CompanyManager(db).create_project(product_id=product["id"], name="Release", user_id="alice")

    class PlanningModel(Model):
        def __init__(self):
            super().__init__(id="offline-planner", provider="test")
            self.calls = 0

        def invoke(self, messages, *args, **kwargs):
            prompt = "\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
            assert "Human review decision" in prompt
            assert "`log_company_decision`" in prompt and "`search_company_decisions`" in prompt
            assert not any(name in prompt for name in ("`log_decision`", "`search_decisions`", "`record_outcome`"))
            assert "append-only" in prompt
            self.calls += 1
            if self.calls == 1:
                calls = [
                    (
                        "propose_company_task",
                        {
                            "product_id": product["id"],
                            "title": "Draft notes",
                            "project_id": project["id"],
                            "_agno_run_context": {"user_id": "mallory"},
                        },
                    ),
                    (
                        "update_product_status",
                        {"product_id": product["id"], "content": "Draft proposed", "expected_version": 1},
                    ),
                    ("log_company_decision", {"decision": "Review first", "reasoning": "Approval required"}),
                ]
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": str(i),
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                        for i, (name, arguments) in enumerate(calls)
                    ],
                    response_usage=MessageMetrics(),
                )
            return ModelResponse(role="assistant", content="Proposal recorded", response_usage=MessageMetrics())

        async def ainvoke(self, *args, **kwargs):
            return self.invoke(*args, **kwargs)

        def invoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

        async def ainvoke_stream(self, *args, **kwargs):
            yield self.invoke(*args, **kwargs)

        def parse_args(self, *args, **kwargs):
            return {}

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response):
            return response

    os = AgentOS(db=db, company=CompanyConfig(model=PlanningModel()), user_isolation=True, telemetry=False)
    with TestClient(os.get_app()) as client:
        response = client.post("/company/decisions", json={"decision": "Human review decision"})
        assert response.status_code == 201 and response.json()["agent_id"] is None
    if mode == "http":
        with TestClient(os.get_app()) as client:
            route = "/agents/" + COMPANY_MANAGER_ID
            assert client.get(route).status_code == 200
            response = client.post(
                route + "/runs",
                data={"message": "Plan the release", "user_id": "alice", "session_id": "planning", "stream": "false"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["content"] == "Proposal recorded"
            created = client.post(
                "/components",
                json={"component_id": COMPANY_MANAGER_ID, "component_type": "agent", "name": "Impersonator"},
            )
            assert created.status_code == 409, created.text
            assert client.patch("/components/" + COMPANY_MANAGER_ID, json={"name": "Changed"}).status_code == 404
            assert client.delete("/components/" + COMPANY_MANAGER_ID).status_code == 404
            assert db.get_component(COMPANY_MANAGER_ID) is None
            assert client.get(route).status_code == 200
    elif mode == "async":
        await os.company_manager.arun("Plan the release", user_id="alice", session_id="planning")
    else:
        os.company_manager.run("Plan the release", user_id="alice", session_id="planning")
    m = CompanyManager(db)
    tasks, total = m.list_tasks()
    assert total == 1 and tasks[0]["user_id"] == "alice" and tasks[0]["status"] == "backlog"
    assert m.read_wiki(product["id"], "status.md").content == "Draft proposed"
    decisions, total = m.list_decisions()
    assert total == 2
    own = next(decision for decision in decisions if decision.decision == "Review first")
    assert own.user_id == "alice" and own.session_id == "planning" and own.agent_id == COMPANY_MANAGER_ID
    assert m.list_decisions(agent_id=COMPANY_MANAGER_ID)[1] == 1


@pytest.mark.asyncio
async def test_tools_and_automatic_recall_require_scopes(tmp_path):
    from agno.company.decisions import CompanyDecisionLogStore
    from agno.os.authz.provider import AuthorizationContext
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider
    from agno.run.authorization import RunAuthorization, authorization_scope

    db = SqliteDb(db_file=str(tmp_path / "permission.db"))
    authority = RunAuthorization(
        provider=ScopeAuthorizationProvider(),
        context=AuthorizationContext(principal_id="alice", scopes=["agents:run"]),
        enforce_tools=False,
    )
    tools = CompanyTools(db, user_isolation=True)
    context = RunContext(run_id="r", session_id="s", user_id="spoofed", authorization=authority)
    with authorization_scope(lambda: authority):
        with pytest.raises(PermissionError):
            tools.list_company_products(_agno_run_context=context)
        with pytest.raises(PermissionError):
            await tools.alog_company_decision("denied", _agno_run_context=context)
        with pytest.raises(PermissionError):
            CompanyDecisionLogStore(db).recall(run_context=context)
        with pytest.raises(PermissionError):
            await CompanyDecisionLogStore(db).arecall(run_context=context)
    assert CompanyManager(db).list_decisions()[1] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [False, True])
async def test_served_company_manager_resolution_and_catalog_fence(tmp_path, fresh):
    from agno.os.utils import AgnoHTTPException, get_agent_by_id, get_agent_by_id_async

    db = SqliteDb(db_file=str(tmp_path / "resolution.db"))
    os = AgentOS(db=db, company=CompanyConfig(model=OpenAIResponses(id="offline")), telemetry=False)
    for resolver in (get_agent_by_id, get_agent_by_id_async):
        result = resolver(COMPANY_MANAGER_ID, agents=os._agents, db=db, create_fresh=fresh)
        result = await result if inspect.isawaitable(result) else result
        assert result.id == COMPANY_MANAGER_ID
        assert (result is not os.company_manager) == fresh
        with pytest.raises(AgnoHTTPException, match="reserved"):
            result = resolver(COMPANY_MANAGER_ID, agents=[], db=db)
            if inspect.isawaitable(result):
                await result
    db.close()


def _owner_less_routine_authority(product_id):
    from agno.os.authz.run_context import restore_authorization

    # The snapshot the scheduler sends for a company schedule with no owner and no stored grant.
    return restore_authorization(
        None,
        {
            "context": {"principal_id": None},
            "service_account": True,
            "enforce_tools": True,
            "company_routine": True,
            "company_routine_unscoped": True,
            "company_routine_id": "declared-intake",
            "company_product_id": product_id,
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True])
async def test_owner_less_routine_runs_unscoped_on_its_product_under_isolation(tmp_path, use_async):
    from agno.run.authorization import authorization_scope

    db = SqliteDb(db_file=str(tmp_path / "declared.db"))
    manager = CompanyManager(db)
    declared = manager.create(name="Declared")
    other = manager.create(name="Other", user_id="alice")
    tools = CompanyTools(db, user_isolation=True)
    run = RunContext(run_id="r", session_id="s")

    async def status(product_id):
        version = manager.read_wiki(product_id, "status.md").metadata.version
        if use_async:
            return await tools.aupdate_product_status(product_id, "Checked", version, _agno_run_context=run)
        return tools.update_product_status(product_id, "Checked", version, _agno_run_context=run)

    with authorization_scope(lambda: _owner_less_routine_authority(declared["id"])):
        assert json.loads(await status(declared["id"]))["path"] == "status.md"
        with pytest.raises(PermissionError, match="configured Product"):
            await status(other["id"])
    with pytest.raises(PermissionError, match="Caller identity is required"):
        await status(declared["id"])


def test_refresh_archives_every_members_finished_work(tmp_path):
    import time

    from agno.company.refresh import refresh_product

    db = SqliteDb(db_file=str(tmp_path / "refresh.db"))
    manager = CompanyManager(db)
    product = manager.create(name="SDK", user_id="alice", metadata={"archive_window_days": 0})
    project = manager.create_project(product_id=product["id"], name="Release", user_id="alice")
    tasks = {
        owner: manager.create_task(product_id=product["id"], title=owner, project_id=project["id"], user_id=owner)
        for owner in ("alice", "bob")
    }
    for task in tasks.values():
        manager.transition_task(task_id=task["id"], target="cancelled", reason="Dropped")
    time.sleep(1.1)

    # Refresh is Product housekeeping, so it archives finished work whoever created it.
    archived = refresh_product(manager, product["id"], user_id="alice")["archived_tasks"]
    assert sorted(archived) == sorted(task["id"] for task in tasks.values())


@pytest.mark.asyncio
async def test_declared_routines_belong_to_their_declarer(tmp_path):
    from agno.agent import Agent
    from agno.company import Product, Routine
    from agno.company.bootstrap import arehydrate_product

    db = SqliteDb(db_file=str(tmp_path / "setup.db"))
    registry = Registry(agents=[Agent(id="reader")])

    def declaration(user_id, routine):
        return Product(
            id="docs",
            name="Docs",
            user_id=user_id,
            routines=[Routine(name=routine, template="intake", executor_type="agent", executor_id="reader")],
        )

    await arehydrate_product(db, declaration("alice", "first"), registry)
    await arehydrate_product(db, declaration("bob", "retry"), registry)
    # A retry by another declarer reuses the existing Routine and keeps its owner.
    await arehydrate_product(db, declaration("bob", "first"), registry)
    await arehydrate_product(db, declaration(None, "code"), registry)
    rows = db.get_schedules()[0]
    assert len(rows) == 3
    owners = {row["name"]: row["user_id"] for row in rows}
    assert db.get_product("docs")["user_id"] == "alice"
    assert owners == {"docs.first": "alice", "docs.retry": "bob", "docs.code": "alice"}
