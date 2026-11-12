"""Framework-owned Routine executors use normal routes and caller authority."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from agno.agent import Agent
from agno.company import Product, Routine
from agno.company.bootstrap import arehydrate_product, rehydrate_product
from agno.company.execution import _call, _executor
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _routine_executor_endpoint, _routine_failure, _RoutineAuthorization
from agno.company.scheduler import CompanyScheduleExecutor
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.registry import Registry
from agno.registry._reserved import (
    BUILDER_ID,
    LEGACY_PRODUCT_MANAGER_ID,
    MANAGER_TEAM_ID,
    MINI_AGENT_ID,
    RESERVED_MANAGER_IDS,
)
from agno.run import RunContext
from agno.run.authorization import AUTHORIZATION_KEY, current_authorization
from agno.scheduler import ScheduleManager
from agno.tools.scheduler import SchedulerTools
from agno.tools.studio import StudioTools

SECRET = "company-manager-routines-offline-key-32-characters"
SCOPES = [
    "products:read",
    "products:write",
    "projects:read",
    "projects:write",
    "tasks:read",
    "tasks:write",
    "sources:read",
    "sources:write",
    "wiki:read",
    "wiki:write",
    "decisions:read",
    "routines:read",
    "routines:write",
    "schedules:read",
    "schedules:write",
    "sessions:read",
    "agents:miniagent:read",
    "teams:superagent:read",
    "agents:miniagent:run",
    "teams:superagent:run",
]


class ScriptedModel(Model):
    """Choose calls from current-run tool results, without shared turn counters."""

    def __init__(self, steps=()):
        super().__init__(id="offline-company-review", provider="test")
        self.steps = steps

    def invoke(self, messages, *args, **kwargs):
        start = max((i for i, message in enumerate(messages) if message.role == "user"), default=-1)
        results = [message for message in messages[start + 1 :] if message.role == "tool"]
        if len(results) < len(self.steps):
            name, arguments = self.steps[len(results)]
            if callable(arguments):
                arguments = arguments(results)
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-" + str(len(results)),
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(role="assistant", content="Review complete", response_usage=MessageMetrics())

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


def headers(user="alice", scopes=None):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": user,
                "aud": "routine-test",
                "scopes": SCOPES if scopes is None else scopes,
                "exp": time.time() + 600,
            },
            SECRET,
            algorithm="HS256",
        )
    }


def declaration(kind="agent", component_id=MINI_AGENT_ID, **kwargs):
    return Routine(
        name="weekly-review",
        executor_type=kind,
        executor_id=component_id,
        instructions="Review Sources and existing work. Propose useful work and update status without accepting Tasks.",
        cron_expr="0 9 * * 1",
        timezone="Europe/London",
        **kwargs,
    )


RUNNER_ENDPOINT = "/agents/" + MINI_AGENT_ID + "/runs"


def make_os(db, *, manager=False, model=None, authorization=False, isolation=False, products=()):
    return AgentOS(
        id="routine-test",
        db=db,
        company=CompanyConfig(model=model or ScriptedModel(), products=list(products)),
        manager=OSManager(model=ScriptedModel(), access_docs=False, offload_tool_results=False) if manager else None,
        authorization=authorization,
        user_isolation=isolation,
        telemetry=False,
    )


@asynccontextmanager
async def system(tmp_path, *, mode="standalone", identity="scope", isolation=True, scopes=None):
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="routine-test")
    scopes = SCOPES if scopes is None else scopes
    if identity == "managed":
        auth.define_role("reviewer", scopes)
        auth.assign("alice", "reviewer")
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    os = make_os(db, manager=mode != "standalone", authorization=auth, isolation=isolation)
    app = os.get_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        executor = CompanyScheduleExecutor(
            company_db=db,
            schedule_db=db,
            base_url="http://test",
            internal_service_token=os._internal_service_token,
            poll_interval=0.01,
            timeout=10,
        )
        executor._client = client
        app.state.scheduler_executor = executor
        yield SimpleNamespace(
            os=os,
            auth=auth,
            app=app,
            db=db,
            client=client,
            executor=executor,
            headers=headers(scopes=["agent_os:admin"] if identity == "managed" else scopes),
        )
    db.close()


async def create_routine(s, product_id, *, kind="agent", component_id=MINI_AGENT_ID):
    response = await s.client.post(
        "/company/routines",
        headers=s.headers,
        json={"product_id": product_id, **declaration(kind, component_id).model_dump()},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("enabled", [False, True])
def test_owned_resolution_serving_and_resync(tmp_path, enabled):
    db = SqliteDb(db_file=str(tmp_path / "assembly.db"))
    os = make_os(db, manager=enabled)
    for _ in range(2):
        os.resync(os.get_app())
    runner = os._mini_agent
    assert runner.id == MINI_AGENT_ID and runner.name == "Mini Agent"
    assert sum(agent is runner for agent in os._agents) == 1
    assert os.registry.get_agent(MINI_AGENT_ID) is None
    assert os.registry.get_team(MANAGER_TEAM_ID) is None
    assert not os.registry.tools
    assert _routine_executor_endpoint("agent", MINI_AGENT_ID, os.registry, agent_os=os) == RUNNER_ENDPOINT
    if enabled:
        assert all(member.id != MINI_AGENT_ID for member in os.manager.members)
    assert all(agent.id != BUILDER_ID for agent in os._agents)
    # Among framework components only Mini Agent executes Tasks.
    assert _executor(os.registry, "agent", MINI_AGENT_ID) is runner
    for kind, cid in (("team", MINI_AGENT_ID), ("team", MANAGER_TEAM_ID), ("agent", BUILDER_ID)):
        with pytest.raises(ValueError):
            _executor(os.registry, kind, cid)
    db.close()


def test_wrong_type_and_reserved_registry_fallback_are_refused(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "reserved.db"))
    os = make_os(db, manager=True)
    with pytest.raises(ValueError, match="executor_type"):
        _routine_executor_endpoint("team", MINI_AGENT_ID, os.registry, agent_os=os)
    # Even a corrupted registry cannot substitute for the owning AgentOS.
    registry = SimpleNamespace(get_agent=lambda _: os._mini_agent, get_team=lambda _: os.manager)
    with pytest.raises(ValueError, match="Mini Agent unavailable"):
        _routine_executor_endpoint("agent", MINI_AGENT_ID, registry)
    db.close()


@pytest.mark.parametrize(
    "kind,cid",
    [
        ("team", MANAGER_TEAM_ID),
        ("agent", MANAGER_TEAM_ID),
        ("agent", BUILDER_ID),
        ("agent", "platform-manager-internal"),
        ("agent", "company-manager-internal"),
        ("agent", LEGACY_PRODUCT_MANAGER_ID),
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_only_mini_agent_runs_routines_among_framework_agents(tmp_path, kind, cid, enabled):
    db = SqliteDb(db_file=str(tmp_path / "only.db"))
    os = make_os(db, manager=enabled)
    # A registry that would hand back the live Mini Agent or team must not be consulted for reserved IDs.
    registry = SimpleNamespace(get_agent=lambda _: os._mini_agent, get_team=lambda _: os.manager)
    for candidate in (os.registry, registry):
        with pytest.raises(ValueError, match="only Mini Agent runs Routines"):
            _routine_executor_endpoint(kind, cid, candidate, agent_os=os)
    with pytest.raises(ValueError, match="only Mini Agent runs Routines"):
        rehydrate_product(db, Product(name="Docs", routines=[declaration(kind, cid)]), os.registry, agent_os=os)
    assert db.get_products()[1] == 0
    db.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_company_manager_id_is_an_ordinary_executor(tmp_path, enabled):
    assert "company-manager" not in RESERVED_MANAGER_IDS
    db = SqliteDb(db_file=str(tmp_path / "ordinary.db"))
    os = make_os(db, manager=enabled)
    # Unregistered, it fails as any missing component does, not as a framework manager.
    with pytest.raises(ValueError, match="missing from the registry") as refused:
        rehydrate_product(
            db, Product(name="Docs", routines=[declaration("agent", "company-manager")]), os.registry, agent_os=os
        )
    assert "Only Super Agent" not in str(refused.value)
    assert "Product 'Docs', Routine 'weekly-review', executor agent 'company-manager'" in str(refused.value)
    assert db.get_products()[1] == 0
    user = Agent(id="company-manager", model=ScriptedModel())
    registered = AgentOS(
        db=db,
        agents=[user],
        company=CompanyConfig(model=ScriptedModel()),
        registry=Registry(agents=[user]),
        telemetry=False,
    )
    assert _routine_executor_endpoint("agent", "company-manager", registered.registry, agent_os=registered) == (
        "/agents/company-manager/runs"
    )
    db.close()


@pytest.mark.parametrize("mode", ["sync", "async", "lifespan", "yaml"])
@pytest.mark.parametrize("enabled", [True, False])
def test_declarations_bootstrap_and_restart(tmp_path, mode, enabled):
    kind, cid = "agent", MINI_AGENT_ID
    db = SqliteDb(db_file=str(tmp_path / "bootstrap.db"))
    product = Product(id="docs", name="Docs", user_id="alice", routines=[declaration(kind, cid, enabled=enabled)])
    os = make_os(db, manager=True, products=[product] if mode == "lifespan" else [])
    if mode == "sync":
        rehydrate_product(db, product, os.registry, agent_os=os)
    elif mode == "async":
        import asyncio

        asyncio.run(arehydrate_product(db, product, os.registry, agent_os=os))
    elif mode == "yaml":
        import yaml

        path = tmp_path / "company.yaml"
        path.write_text(yaml.safe_dump({"company": {"products": [product.model_dump()]}}))
        os = AgentOS(
            db=db,
            config=str(path),
            company=CompanyConfig(model=ScriptedModel()),
            manager=OSManager(model=ScriptedModel(), access_docs=False),
            telemetry=False,
        )
        with TestClient(os.get_app()):
            pass
    else:
        with TestClient(os.get_app()):
            pass
    row = db.get_schedule_by_name("docs.weekly-review", user_id="alice")
    assert row["endpoint"] == RUNNER_ENDPOINT
    # The stored row names the component that runs; the Routine API shows the executor the person named.
    assert row["managed_by"] == "company" and row["target_type"] == "agent" and row["target_id"] == MINI_AGENT_ID
    assert AUTHORIZATION_KEY not in row["payload"]
    assert row["enabled"] is enabled
    db.update_schedule(row["id"], enabled=not enabled, payload={**row["payload"], "message": "Human edit"})
    rehydrate_product(db, product, os.registry, agent_os=os)
    saved = db.get_schedule(row["id"])
    assert saved["enabled"] is not enabled and saved["payload"]["message"] == "Human edit"
    db.close()


def test_unavailable_bootstrap_has_no_partial_product(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "missing.db"))
    os = AgentOS(db=db, company=CompanyConfig(), telemetry=False)
    with pytest.raises(ValueError, match="configure CompanyConfig"):
        rehydrate_product(db, Product(name="Docs", routines=[declaration()]), os.registry, agent_os=os)
    assert db.get_products()[1] == 0
    db.close()


async def test_api_create_patch_resume_and_unavailable_manager(tmp_path):
    async with system(tmp_path, mode="member") as s:
        product = CompanyManager(s.db).create(name="Docs", user_id="alice")
        row = await create_routine(s, product["id"])
        path = "/company/routines/" + row["id"]
        assert row["endpoint"] == RUNNER_ENDPOINT
        assert row["target_type"] == "agent" and row["target_id"] == MINI_AGENT_ID
        before = s.db.get_schedule(row["id"])
        for kind, cid in (("team", MANAGER_TEAM_ID), ("agent", BUILDER_ID)):
            response = await s.client.patch(path, headers=s.headers, json={"executor_type": kind, "executor_id": cid})
            assert response.status_code == 422 and "only Mini Agent runs Routines" in response.text
        response = await s.client.patch(path, headers=s.headers, json={"executor_type": "team"})
        assert response.status_code == 422 and "executor_type" in response.text
        assert s.db.get_schedule(row["id"]) == before
        assert (await s.client.post(path + "/pause", headers=s.headers)).status_code == 200
        s.os._mini_agent = None
        response = await s.client.post(path + "/resume", headers=s.headers)
        assert response.status_code == 422 and "Mini Agent unavailable" in response.text
        assert not s.db.get_schedule(row["id"])["enabled"]
        response = await s.client.post(
            "/company/routines",
            headers=s.headers,
            json={"product_id": product["id"], **declaration("agent", BUILDER_ID).model_dump()},
        )
        assert response.status_code == 422
        assert len(s.db.get_product(product["id"])["metadata"]["routine_ids"]) == 1


async def test_setup_captures_authority_and_retry_retains_it(tmp_path):
    async with system(tmp_path) as s:
        body = {"name": "Docs", "routines": [declaration().model_dump()]}
        response = await s.client.post("/company/setup", headers=s.headers, json=body)
        assert response.status_code == 201, response.text
        row = s.db.get_schedule(response.json()["metadata"]["routine_ids"][0])
        assert row["payload"][AUTHORIZATION_KEY]["context"]["principal_id"] == "alice"
        assert row["payload"][AUTHORIZATION_KEY]["context"]["scopes"] == SCOPES
        retry = await s.client.post("/company/setup", headers=headers(scopes=SCOPES + ["config:read"]), json=body)
        assert retry.status_code == 200, retry.text
        assert s.db.get_schedule(row["id"])["payload"] == row["payload"]


def review_steps(product, project, source, path):
    return [
        ("list_company_tasks", {"product_id": product["id"]}),
        ("read_product_source", {"source_id": source["id"], "path": path.name}),
        (
            "intake_product_source",
            lambda results: {
                "source_id": source["id"],
                "project_id": project["id"],
                "title": "Document API",
                "brief": "Write the missing guide",
                "proposal_key": "api-guide",
                "evidence_links": [path.as_uri()],
                "evidence_hashes": {path.as_uri(): json.loads(results[-1].content)["content_hash"]},
            },
        ),
        ("read_company_wiki", {"product_id": product["id"], "path": "status.md"}),
        (
            "update_product_status",
            lambda results: {
                "product_id": product["id"],
                "content": "Reviewed Sources; API guide proposed for human review.",
                "expected_version": json.loads(results[-1].content)["metadata"]["version"],
            },
        ),
    ]


@pytest.mark.parametrize("mode", ["standalone", "member"])
@pytest.mark.parametrize("identity", ["scope", "managed"])
@pytest.mark.parametrize("isolation", [False, True])
async def test_scheduled_review_persists_evidence_and_caller_authority(tmp_path, mode, identity, isolation):
    async with system(tmp_path, mode=mode, identity=identity, isolation=isolation) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Docs", user_id="alice")
        project = manager.create_project(product_id=product["id"], name="Guides", user_id="alice")
        manager.transition_project(project_id=project["id"], target="active", reason="Approved")
        path = tmp_path / "source.md"
        path.write_text("The released API needs a guide.")
        source = manager.create_source(product_id=product["id"], type="markdown", reference=str(path))
        observed = []

        def observe_authority(_agno_run_context: RunContext) -> str:
            authority = current_authorization()
            assert isinstance(authority, _RoutineAuthorization)
            observed.append(
                (
                    _agno_run_context.user_id,
                    authority.context.principal_id,
                    authority.routine_id,
                    authority.product_id,
                    authority.enforce_tools,
                )
            )
            return "Observed injected authority"

        s.os._mini_agent.tools.routine.append(observe_authority)
        s.os._mini_agent.model = ScriptedModel(
            [("observe_authority", {"_agno_run_context": {"user_id": "mallory"}})]
            + review_steps(product, project, source, path)
        )
        row = await create_routine(s, product["id"])
        for _ in range(2):
            response = await s.client.post("/company/routines/" + row["id"] + "/trigger", headers=s.headers)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["status"] == "success", json.dumps(result)
            assert result["run_id"] and result["session_id"]
        assert observed == [("alice", "alice", row["id"], product["id"], True)] * 2
        tasks, total = s.db.get_tasks(product_id=product["id"])
        assert total == 1
        task = tasks[0]
        assert task["status"] == "backlog" and task["user_id"] == "alice"
        assert task["origin"] == "routine" and task["routine_id"] == row["id"]
        assert task["evidence"][0]["link"] == path.as_uri()
        assert task["evidence"][0]["content_hash"]
        assert not task.get("accepted_by") and not task.get("job_id")
        assert "API guide proposed" in manager.read_wiki(product["id"], "status.md").content
        runs = await ScheduleManager(s.db).aget_runs(row["id"])
        assert len(runs) == 2 and all(run.status == "success" for run in runs)


def test_recursive_scheduler_tools_validation_is_preserved(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "tools.db"))
    os = make_os(db, manager=True)
    os._mini_agent.tools.routine.append(SchedulerTools(db=db))
    with pytest.raises(ValueError, match="cannot hold SchedulerTools"):
        _routine_executor_endpoint("agent", MINI_AGENT_ID, os.registry, agent_os=os)
    db.close()


@pytest.mark.parametrize("mode", ["standalone", "member"])
@pytest.mark.parametrize("identity", ["scope", "managed"])
@pytest.mark.parametrize("isolation", [False, True])
async def test_routine_status_write_never_gains_permission(tmp_path, mode, identity, isolation):
    scopes = [scope for scope in SCOPES if scope != "wiki:write"]
    async with system(tmp_path, mode=mode, identity=identity, isolation=isolation, scopes=scopes) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Docs", user_id="alice")
        before = manager.read_wiki(product["id"], "status.md")
        s.os._mini_agent.model = ScriptedModel(
            [("update_product_status", {"product_id": product["id"], "content": "Unauthorized", "expected_version": 1})]
        )
        row = await create_routine(s, product["id"])
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert manager.read_wiki(product["id"], "status.md") == before
        assert result["status"] == "failed", json.dumps(result)
        # The refusal comes from inside the run, not from the schedule being refused before it starts.
        assert result["run_id"], json.dumps(result)


@pytest.mark.parametrize("mode", ["standalone", "member"])
async def test_routine_mutation_fence_holds_even_for_admin(tmp_path, mode):
    async with system(tmp_path, mode=mode, scopes=["agent_os:admin"]) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Docs", user_id="alice")
        project = manager.create_project(product_id=product["id"], name="Guides", user_id="alice")
        project = manager.transition_project(project_id=project["id"], target="active", reason="Approved")
        task = manager.create_task(product_id=product["id"], project_id=project["id"], title="Guide", user_id="alice")
        observed = []

        def check_forbidden_mutations(_agno_run_context: RunContext) -> str:
            assert isinstance(current_authorization(), _RoutineAuthorization)
            actions = [
                lambda: manager.transition_task(task_id=task["id"], target="ready", reason="Routine"),
                lambda: manager.transition_task(task_id=task["id"], target="done", reason="Routine"),
                lambda: manager.transition_project(project_id=project["id"], target="done", reason="Routine"),
                lambda: StudioTools(registry=s.os.registry, db=s.db, schedules=True).create_schedule(
                    name="forbidden",
                    cron="0 0 * * *",
                    target_type="agent",
                    target_id=MINI_AGENT_ID,
                    message="Run again",
                    _agno_run_context=_agno_run_context,
                ),
            ]
            for action in actions:
                try:
                    action()
                except PermissionError:
                    observed.append(_agno_run_context.user_id)
                else:
                    raise RuntimeError("An exposed mutation unexpectedly succeeded")
            return "All unauthorized mutations refused"

        s.os._mini_agent.tools.routine.append(check_forbidden_mutations)
        s.os._mini_agent.model = ScriptedModel([("check_forbidden_mutations", {})])
        row = await create_routine(s, product["id"])
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert result["status"] == "success", result
        assert observed == ["alice"] * 4
        assert manager.get_task(task["id"]) == task
        assert s.db.get_project(project["id"]) == project
        assert s.db.get_schedule_by_name("forbidden") is None


@pytest.mark.parametrize("owner", ["alice", "bob"])
async def test_other_product_source_and_status_are_refused(tmp_path, owner):
    async with system(tmp_path) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Docs", user_id="alice")
        other = manager.create(name="Other", user_id=owner)
        path = tmp_path / "other.md"
        path.write_text("Other Product source")
        source = manager.create_source(product_id=other["id"], type="markdown", reference=str(path))
        before = manager.read_wiki(other["id"], "status.md")
        s.os._mini_agent.model = ScriptedModel(
            [
                ("read_product_source", {"source_id": source["id"], "path": path.name}),
                (
                    "update_product_status",
                    {"product_id": other["id"], "content": "Wrong Product", "expected_version": 1},
                ),
            ]
        )
        row = await create_routine(s, product["id"])
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert result["status"] == "failed", result
        assert manager.read_wiki(other["id"], "status.md") == before
        output = await s.os._mini_agent.aget_run_output(
            result["run_id"], session_id=result["session_id"], user_id="alice"
        )
        assert "Routine authority is restricted to its configured Product" in json.dumps(output.to_dict())
        assert manager.list_tasks()[1] == 0


@pytest.mark.parametrize(
    "run_scope,allowed",
    [
        (None, False),
        # Running Super Agent in chat does not grant Mini Agent, which executes its Routines.
        ("teams:" + MANAGER_TEAM_ID + ":run", False),
        ("agents:" + MINI_AGENT_ID + ":run", True),
    ],
)
@pytest.mark.parametrize("identity", ["scope", "managed"])
async def test_configuration_requires_target_run_permission(tmp_path, identity, run_scope, allowed):
    scopes = [scope for scope in SCOPES if not scope.endswith(":run")]
    if run_scope is not None:
        scopes.append(run_scope)
    async with system(tmp_path, identity=identity, mode="member", scopes=scopes) as s:
        product = CompanyManager(s.db).create(name="Docs", user_id="alice")
        response = await s.client.post(
            "/company/routines",
            headers=s.headers,
            json={"product_id": product["id"], **declaration().model_dump()},
        )
        routine_ids = (s.db.get_product(product["id"]).get("metadata") or {}).get("routine_ids")
        if allowed:
            assert response.status_code == 201, response.text
            assert response.json()["target_type"] == "agent" and response.json()["target_id"] == MINI_AGENT_ID
            assert routine_ids == [response.json()["id"]]
        else:
            assert response.status_code == 403, response.text
            assert not routine_ids


@pytest.mark.parametrize("stage", ["draft", "published", "archived"])
async def test_legacy_catalog_cannot_replace_owned_or_unavailable_manager(tmp_path, stage):
    from agno.db.base import ComponentType

    kind, cid = "agent", MINI_AGENT_ID

    async with system(tmp_path, mode="member") as s:
        s.db.upsert_component(component_id=cid, component_type=ComponentType(kind), user_id="alice")
        s.db.upsert_config(
            component_id=cid, config={"id": cid, "name": "Impostor"}, stage="draft" if stage == "archived" else stage
        )
        if stage == "archived":
            s.db.delete_component(cid)
        product = CompanyManager(s.db).create(name="Docs", user_id="alice")
        row = await create_routine(s, product["id"])
        assert row["endpoint"] == "/agents/" + cid + "/runs"
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert result["status"] == "success", json.dumps(result)
        if stage == "archived":
            assert s.db.get_component(cid, include_deleted=True)["deleted_at"] is not None
        # A new process with Company/manager configuration removed must not rehydrate
        # a legacy reserved component, even if its saved version is published.
        restarted = AgentOS(
            id="routine-test",
            db=s.db,
            company=CompanyConfig(),
            authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="routine-test"),
            telemetry=False,
            internal_service_token=s.os._internal_service_token,
        )
        async with AsyncClient(transport=ASGITransport(app=restarted.get_app()), base_url="http://test") as client:
            s.executor._client = client
            result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
            assert result["status"] == "failed", result
        assert CompanyManager(s.db).list_tasks()[1] == 0


async def test_poller_quiet_review_and_bootstrap_grant_update(tmp_path):
    import asyncio

    from agno.scheduler.poller import SchedulePoller

    async with system(tmp_path) as s:
        product = Product(id="docs", name="Docs", user_id="alice", routines=[declaration()])
        await arehydrate_product(s.db, product, s.os.registry, agent_os=s.os)
        row = s.db.get_schedule_by_name("docs.weekly-review", user_id="alice")
        # Code configuration names an owner but cannot manufacture a saved caller grant.
        assert AUTHORIZATION_KEY not in row["payload"]
        denied = await s.executor.execute(row, s.db, release_schedule=False)
        assert denied["status"] == "failed"
        updated = await s.client.patch(
            "/company/routines/" + row["id"],
            headers=s.headers,
            json={"instructions": "Read existing work; quiet review"},
        )
        assert updated.status_code == 200, updated.text
        assert s.db.get_schedule(row["id"])["payload"][AUTHORIZATION_KEY]["context"]["principal_id"] == "alice"
        s.db.update_schedule(row["id"], next_run_at=int(time.time()) - 1)
        poller = SchedulePoller(s.db, s.executor)
        poller._running = True
        try:
            await poller._poll_once()
            await asyncio.gather(*list(poller._in_flight))
        finally:
            await poller.stop()
        runs = await ScheduleManager(s.db).aget_runs(row["id"])
        assert len(runs) == 2 and {run.status for run in runs} == {"failed", "success"}
        assert CompanyManager(s.db).list_tasks()[1] == 0


@pytest.mark.parametrize("isolation", [False, True])
async def test_managed_grant_revocation_is_rechecked_at_fire_time(tmp_path, isolation):
    async with system(tmp_path, identity="managed", isolation=isolation) as s:
        product = CompanyManager(s.db).create(name="Docs", user_id="alice")
        row = await create_routine(s, product["id"])
        s.auth.define_role("viewer", [scope for scope in SCOPES if not scope.endswith(":run")])
        s.auth.set_role("alice", "viewer")
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert result["status"] == "failed" and result["status_code"] == 403
        assert result["run_id"] is None


async def test_concurrent_reviews_keep_private_sessions_and_owners_separate(tmp_path):
    import asyncio

    async with system(tmp_path) as s:
        manager = CompanyManager(s.db)
        products = {user: manager.create(name=user, user_id=user) for user in ("alice", "bob")}
        observed = []

        def observe_caller(_agno_run_context: RunContext) -> str:
            authority = current_authorization()
            observed.append((_agno_run_context.user_id, authority.context.principal_id, authority.product_id))
            return "Caller observed"

        s.os._mini_agent.tools.routine.append(observe_caller)
        s.os._mini_agent.model = ScriptedModel([("observe_caller", {})])
        schedules = []
        for user, product in products.items():
            response = await s.client.post(
                "/company/routines",
                headers=headers(user),
                json={"product_id": product["id"], **declaration().model_dump()},
            )
            assert response.status_code == 201, response.text
            schedules.append(s.db.get_schedule(response.json()["id"]))
        results = await asyncio.gather(*(s.executor.execute(row, s.db, release_schedule=False) for row in schedules))
        assert all(result["status"] == "success" for result in results), results
        assert sorted(observed) == [(user, user, products[user]["id"]) for user in ("alice", "bob")]
        assert results[0]["session_id"] != results[1]["session_id"]
        alice = results[0]
        route = RUNNER_ENDPOINT + "/" + alice["run_id"]
        params = {"session_id": alice["session_id"]}
        assert (await s.client.get(route, headers=headers("alice"), params=params)).status_code == 200
        assert (await s.client.get(route, headers=headers("bob"), params=params)).status_code == 404


async def test_status_conflict_is_failed_without_overwriting_human_edit(tmp_path):
    async with system(tmp_path) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Docs", user_id="alice")
        manager.read_wiki(product["id"], "status.md")
        manager.write_wiki(
            product_id=product["id"], path="status.md", content="Human edit", expected_version=1, user_id="alice"
        )
        s.os._mini_agent.model = ScriptedModel(
            [("update_product_status", {"product_id": product["id"], "content": "Stale review", "expected_version": 1})]
        )
        row = await create_routine(s, product["id"])
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert result["status"] == "failed" and result["run_id"], result
        assert manager.read_wiki(product["id"], "status.md").content == "Human edit"


@pytest.mark.parametrize("mode", ["standalone", "member"])
async def test_recovered_status_conflict_succeeds(tmp_path, mode):
    async with system(tmp_path, mode=mode) as s:
        manager = CompanyManager(s.db)
        product = manager.create(name="Docs", user_id="alice")
        manager.read_wiki(product["id"], "status.md")
        manager.write_wiki(
            product_id=product["id"], path="status.md", content="Human edit", expected_version=1, user_id="alice"
        )
        s.os._mini_agent.model = ScriptedModel(
            [
                ("update_product_status", {"product_id": product["id"], "content": "Stale", "expected_version": 1}),
                ("read_company_wiki", {"product_id": product["id"], "path": "status.md"}),
                (
                    "update_product_status",
                    lambda results: {
                        "product_id": product["id"],
                        "content": json.loads(results[-1].content)["content"] + "\nReview complete",
                        "expected_version": json.loads(results[-1].content)["metadata"]["version"],
                    },
                ),
            ]
        )
        row = await create_routine(s, product["id"])
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        page = manager.read_wiki(product["id"], "status.md")
        assert page.content == "Human edit\nReview complete"
        assert page.metadata.version == 3
        assert result["status"] == "success", result
        assert (await ScheduleManager(s.db).aget_runs(row["id"]))[0].status == "success"


@pytest.mark.parametrize("mode", ["standalone", "member"])
async def test_superagent_routine_reports_provider_failure(tmp_path, mode):
    class FailingModel(ScriptedModel):
        def invoke(self, *args, **kwargs):
            raise RuntimeError("Provider unavailable during product review")

    async with system(tmp_path, mode=mode) as s:
        product = CompanyManager(s.db).create(name="Docs", user_id="alice")
        s.os._mini_agent.model = FailingModel()
        row = await create_routine(s, product["id"])
        result = await s.executor.execute(s.db.get_schedule(row["id"]), s.db, release_schedule=False)
        assert result["status"] == "failed", result
        assert "Provider unavailable during product review" in result["error"]
        assert (await ScheduleManager(s.db).aget_runs(row["id"]))[0].status == "failed"


@pytest.mark.parametrize("status", ["ERROR", "FAILED", "CANCELLED"])
def test_nested_member_terminal_failure_is_not_success(status):
    output = {"status": "COMPLETED", "member_responses": [{"member_responses": [{"status": status}]}]}
    assert _routine_failure(output) is not None


@pytest.mark.parametrize("case", ["denied", "other_product", "earlier_success", "failed_retry", "invalid_result"])
def test_status_success_does_not_hide_unrecovered_failure(case):
    failed = {
        "tool_name": "update_product_status",
        "tool_args": {"product_id": "docs", "expected_version": 1},
        "tool_call_error": True,
        "result": "version conflict on status.md: expected 1, actual 2",
    }
    success = {
        "tool_name": "update_product_status",
        "tool_args": {"product_id": "docs", "expected_version": 2},
        "tool_call_error": False,
        "result": json.dumps({"path": "status.md", "version": 3}),
    }
    if case == "denied":
        failed["result"] = "Missing permission: wiki:write"
    elif case == "other_product":
        success["tool_args"]["product_id"] = "other"
    elif case == "failed_retry":
        success["tool_call_error"] = True
    elif case == "invalid_result":
        success["result"] = "Update failed"
    tools = [success, failed] if case == "earlier_success" else [failed, success]
    assert _routine_failure({"tools": tools}) is not None


async def test_no_auth_declared_review_can_run_locally(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "local.db"))
    os = make_os(db)
    product = Product(id="docs", name="Docs", routines=[declaration()])
    await arehydrate_product(db, product, os.registry, agent_os=os)
    async with AsyncClient(transport=ASGITransport(app=os.get_app()), base_url="http://test") as client:
        executor = CompanyScheduleExecutor(
            company_db=db,
            schedule_db=db,
            base_url="http://test",
            internal_service_token=os._internal_service_token,
            poll_interval=0.01,
            timeout=10,
        )
        executor._client = client
        result = await executor.execute(db.get_schedule_by_name("docs.weekly-review"), db)
        assert result["status"] == "success", result
    db.close()


@pytest.mark.parametrize("component_id", [MINI_AGENT_ID, LEGACY_PRODUCT_MANAGER_ID, MANAGER_TEAM_ID])
def test_user_components_cannot_claim_manager_ids(component_id):
    component = Agent(id=component_id, model=ScriptedModel())
    with pytest.raises(ValueError, match="reserved"):
        Registry(agents=[component])
    with pytest.raises(ValueError, match="reserved"):
        AgentOS(agents=[component], telemetry=False)


@pytest.mark.parametrize("tool", ["create_company_product", "create_product_routine"])
@pytest.mark.parametrize("enabled", [True, False])
async def test_human_chat_configures_superagent_routine(tmp_path, tool, enabled):
    async with system(tmp_path, mode="member") as s:
        kwargs = {"name": "Docs", "routines": [declaration(enabled=enabled).model_dump()]}
        if tool == "create_product_routine":
            product = CompanyManager(s.db).create(name="Docs", user_id="alice")
            kwargs = {"product_id": product["id"], **declaration(enabled=enabled).model_dump(exclude={"auto_accept"})}
        s.os.manager.model = ScriptedModel([(tool, kwargs)])
        response = await s.client.post(
            "/teams/" + MANAGER_TEAM_ID + "/runs", headers=s.headers, data={"message": "Set up a weekly review"}
        )
        assert response.status_code == 200, response.text
        products, total = s.db.get_products()
        assert total == 1
        row = s.db.get_schedule(products[0]["metadata"]["routine_ids"][0])
        assert row["endpoint"] == RUNNER_ENDPOINT
        assert row["target_type"] == "agent" and row["target_id"] == MINI_AGENT_ID and row["user_id"] == "alice"
        assert row["payload"][AUTHORIZATION_KEY]["context"]["principal_id"] == "alice"
        assert row["payload"]["metadata"]["auto_accept"] is False
        assert row["enabled"] is enabled


@pytest.mark.parametrize("tool", ["create_company_product", "create_product_routine"])
async def test_human_chat_routine_needs_runner_permission(tmp_path, tool):
    # Talking to Super Agent does not grant Mini Agent, which executes its Routines.
    scopes = [scope for scope in SCOPES if scope != "agents:" + MINI_AGENT_ID + ":run"]
    async with system(tmp_path, mode="member", scopes=scopes) as s:
        kwargs = {"name": "Docs", "routines": [declaration().model_dump()]}
        if tool == "create_product_routine":
            product = CompanyManager(s.db).create(name="Docs", user_id="alice")
            kwargs = {"product_id": product["id"], **declaration().model_dump(exclude={"auto_accept"})}
        s.os.manager.model = ScriptedModel([(tool, kwargs)])
        response = await s.client.post(
            "/teams/" + MANAGER_TEAM_ID + "/runs", headers=s.headers, data={"message": "Set up a weekly review"}
        )
        assert response.status_code == 200, response.text
        assert "Permission required: agents:" + MINI_AGENT_ID + ":run" in response.text
        products, _ = s.db.get_products()
        assert all(not (product.get("metadata") or {}).get("routine_ids") for product in products)
        assert s.db.get_schedules()[1] == 0


@pytest.mark.parametrize("mode", ["standalone", "member"])
async def test_person_cannot_chat_with_mini_agent(tmp_path, mode):
    class UncalledModel(ScriptedModel):
        def invoke(self, *args, **kwargs):
            raise AssertionError("Mini Agent called its model outside a Routine")

    async with system(tmp_path, mode=mode, scopes=SCOPES + ["agents:read"]) as s:
        product = CompanyManager(s.db).create(name="Docs", user_id="alice")
        s.os._mini_agent.model = UncalledModel()
        response = await s.client.post(
            RUNNER_ENDPOINT,
            headers=s.headers,
            data={"message": "Create a Routine for product " + product["id"], "stream": "false"},
        )
        assert "Mini Agent runs Company Routines and Tasks only" in response.text, response.text
        assert s.db.get_product(product["id"]).get("metadata", {}).get("routine_ids") in (None, [])
        listed = (await s.client.get("/agents", headers=s.headers)).json()
        assert all(agent["id"] != MINI_AGENT_ID for agent in listed)


@pytest.mark.parametrize("tool", ["run_agent", "run_team", "run_workflow"])
@pytest.mark.parametrize(
    "result,failed",
    [
        ({"error": "Agent 'missing' not found"}, True),
        ({"agent_id": "child", "status": "ERROR", "content": "boom"}, True),
        ({"agent_id": "child", "status": "CANCELLED", "content": None}, True),
        ({"agent_id": "child", "status": "COMPLETED", "content": "done"}, False),
        ("not json", False),
    ],
)
def test_studio_dispatch_failures_fail_the_routine(tool, result, failed):
    payload = result if isinstance(result, str) else json.dumps(result)
    output = {"tools": [{"tool_name": tool, "result": payload}]}
    assert bool(_routine_failure(output)) is failed
    assert bool(_routine_failure({"member_responses": [output]})) is failed
    assert _routine_failure({"tools": [{"tool_name": tool, "tool_call_error": True, "result": "raised"}]})


@pytest.mark.parametrize("async_db", [False, True])
@pytest.mark.parametrize("creation", ["manager", "bootstrap"])
async def test_disabled_routine_is_inserted_disabled(tmp_path, monkeypatch, async_db, creation):
    db = (AsyncSqliteDb if async_db else SqliteDb)(db_file=str(tmp_path / "disabled.db"))
    os = make_os(db)
    product = Product(id="docs", name="Docs", routines=[declaration(enabled=False)])
    inserted = []
    create = db.create_schedule

    def observe(row):
        assert row["enabled"] is False
        inserted.append(row["id"])

    if async_db:

        async def create_disabled(row):
            observe(row)
            return await create(row)
    else:

        def create_disabled(row):
            observe(row)
            return create(row)

    monkeypatch.setattr(db, "create_schedule", create_disabled)
    try:
        if creation == "bootstrap":
            await arehydrate_product(db, product, os.registry, agent_os=os)
        else:
            manager = AsyncCompanyManager(db) if async_db else CompanyManager(db)
            await _call(manager, "create", id="docs", name="Docs")
            row = await _call(manager, "create_routine", product_id="docs", routine=product.routines[0], agent_os=os)
            assert row["enabled"] is False
        assert len(inserted) == 1
        row = await _call(db, "get_schedule", inserted[0])
        assert row["enabled"] is False
        assert (await _call(db, "get_product", "docs"))["metadata"]["routine_ids"] == inserted
        await _call(db, "update_schedule", row["id"], next_run_at=int(time.time()) - 60)
        assert await _call(db, "claim_due_schedule", worker_id="test") is None
    finally:
        await _call(db, "close")


@pytest.mark.parametrize("creation", ["api", "setup", "declaration"])
@pytest.mark.parametrize("on_demand", [False, True])
async def test_disabled_routine_visible_and_resume_survives_restart(tmp_path, creation, on_demand):
    async with system(tmp_path) as s:
        routine = declaration(enabled=False)
        if on_demand:
            routine.cron_expr = None
        product = Product(id="docs", name="Docs", user_id="alice", routines=[routine])
        if creation == "setup":
            response = await s.client.post(
                "/company/setup", headers=s.headers, json={"name": "Docs", "routines": [routine.model_dump()]}
            )
            assert response.status_code == 201, response.text
            product.id = response.json()["id"]
        elif creation == "api":
            CompanyManager(s.db).create(id="docs", name="Docs", user_id="alice")
            response = await s.client.post(
                "/company/routines", headers=s.headers, json={"product_id": "docs", **routine.model_dump()}
            )
            assert response.status_code == 201, response.text
            assert response.json()["enabled"] is False
        else:
            await arehydrate_product(s.db, product, s.os.registry, agent_os=s.os)
        rows = (await s.client.get("/company/routines", headers=s.headers)).json()["data"]
        assert len(rows) == 1 and rows[0]["enabled"] is False
        path = "/company/routines/" + rows[0]["id"]
        assert (await s.client.post(path + "/trigger", headers=s.headers)).status_code == 409
        resumed = await s.client.post(path + "/resume", headers=s.headers)
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["enabled"] is True
        await arehydrate_product(s.db, product, s.os.registry, agent_os=s.os)
        saved = (await s.client.get(path, headers=s.headers)).json()
        assert saved["enabled"] is True and saved["id"] == rows[0]["id"]
        assert (await s.client.get("/company/routines", headers=s.headers)).json()["meta"]["total_count"] == 1


@pytest.mark.parametrize("async_db", [False, True])
@pytest.mark.parametrize("on_demand", [False, True])
async def test_completed_disabled_routine_cannot_be_recovered_as_pending(tmp_path, async_db, on_demand):
    db = (AsyncSqliteDb if async_db else SqliteDb)(db_file=str(tmp_path / "disabled-creation.db"))
    os = make_os(db)
    routine = declaration(enabled=False)
    if on_demand:
        routine.cron_expr = None
    try:
        async with AsyncClient(transport=ASGITransport(app=os.get_app()), base_url="http://test") as client:
            product = await client.post("/company/products", json={"name": "Docs"})
            assert product.status_code == 201, product.text
            body = {"product_id": product.json()["id"], **routine.model_dump()}
            response = await client.post("/company/routines", json=body)
            assert response.status_code == 201, response.text
            row = response.json()
            assert row["enabled"] is False
            assert "_agno_pending_creation" not in row["payload"]
            for duplicate in (body, {**body, "enabled": True}, {k: v for k, v in body.items() if k != "enabled"}):
                response = await client.post("/company/routines", json=duplicate)
                assert response.status_code == 409, response.text
                saved = await _call(db, "get_schedule", row["id"])
                assert saved["enabled"] is False
                assert "_agno_pending_creation" not in saved["payload"]
            rows = (await client.get("/company/routines")).json()["data"]
            assert [item["id"] for item in rows] == [row["id"]]
            response = await client.post("/company/routines/" + row["id"] + "/resume")
            assert response.status_code == 200, response.text
            assert response.json()["enabled"] is True
    finally:
        await _call(db, "close")


@pytest.mark.parametrize("async_db", [False, True])
@pytest.mark.parametrize("on_demand", [False, True])
async def test_pending_disabled_routine_rejects_overlapping_activation(tmp_path, monkeypatch, async_db, on_demand):
    db = (AsyncSqliteDb if async_db else SqliteDb)(db_file=str(tmp_path / "overlapping-creation.db"))
    os = make_os(db)
    routine = declaration(enabled=False)
    if on_demand:
        routine.cron_expr = None
    linked = asyncio.Event()
    finish = asyncio.Event()
    original = db.add_product_routine

    async def pause_after_link(*args, **kwargs):
        row = await original(*args, **kwargs) if async_db else await asyncio.to_thread(original, *args, **kwargs)
        if not linked.is_set():
            linked.set()
            await asyncio.wait_for(finish.wait(), 10)
        return row

    monkeypatch.setattr(db, "add_product_routine", pause_after_link)
    try:
        async with AsyncClient(transport=ASGITransport(app=os.get_app()), base_url="http://test") as client:
            product = await client.post("/company/products", json={"name": "Docs"})
            assert product.status_code == 201, product.text
            body = {"product_id": product.json()["id"], **routine.model_dump()}
            first = asyncio.create_task(client.post("/company/routines", json=body))
            try:
                await asyncio.wait_for(linked.wait(), 10)
                duplicate = await client.post("/company/routines", json={**body, "enabled": True})
                assert duplicate.status_code == 409, duplicate.text
            finally:
                finish.set()
                created = await first
            assert created.status_code == 201, created.text
            row = created.json()
            assert row["enabled"] is False
            assert (await _call(db, "get_schedule", row["id"]))["enabled"] is False
            duplicate = await client.post("/company/routines", json={**body, "enabled": True})
            assert duplicate.status_code == 409, duplicate.text
            assert (await _call(db, "get_schedule", row["id"]))["enabled"] is False
    finally:
        await _call(db, "close")
