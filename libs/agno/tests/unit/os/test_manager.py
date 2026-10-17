"""Only the manager team is public; its private members never enter the build palette."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.exceptions import ComponentRehydrationError
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.offload import ResultStore
from agno.offload.tools import get_read_result_function
from agno.os import AgentOS, OSManager
from agno.os.config import AgentOSConfig, Manifest
from agno.os.manager.config import MANAGER_TEAM_NAME
from agno.os.utils import AgnoHTTPException
from agno.registry import Registry
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID, OPERATOR_ID, PRODUCT_MANAGER_ID
from agno.run import RunContext
from agno.tools.agentos import AgentOSTools
from agno.tools.platform_context import PlatformContextTools
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")


@pytest.mark.parametrize("identity", ["jwt", "managed_role", "service_account", "service_account_open"])
@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("target", [MANAGER_TEAM_ID, BUILDER_ID, OPERATOR_ID])
def test_manager_execution_accepts_ordinary_run_grants(db, workspace, identity, admin, target):
    import jwt

    from agno.db.schemas.service_accounts import ServiceAccount
    from agno.os import Authorization
    from agno.os.service_accounts import generate_token

    secret = "manager-test-signing-key-at-least-32-characters"
    # Broad pre-existing grants must not expose newly enabled manager capabilities.
    scopes = ["agent_os:admin"] if admin else ["agents:run", "teams:run", "schedules:write"]
    auth = Authorization(verification_keys=[secret], algorithm="HS256", audience="manager-test")
    if identity == "managed_role":
        auth.define_role("caller", scopes)
        auth.assign("alice", "caller")
    os = AgentOS(
        id="manager-test",
        db=db,
        telemetry=False,
        authorization=False if identity == "service_account_open" else auth,
        a2a_interface=True,
        user_isolation=True,
        agents=[Agent(id="ordinary", model=OfflineModel())],
        manager=OSManager(model=OfflineModel(), root=workspace),
    )
    if identity.startswith("service_account"):
        token, token_hash, token_prefix = generate_token()
        db.create_service_account(
            ServiceAccount(
                id="caller",
                name="caller",
                token_hash=token_hash,
                token_prefix=token_prefix,
                scopes=scopes,
            ).to_dict()
        )
    else:
        # A token's admin claim must not override a managed role's ordinary grants.
        token = jwt.encode(
            {
                "sub": "alice",
                "aud": "manager-test",
                "exp": int(time.time()) + 300,
                "scopes": ["agent_os:admin"] if identity == "managed_role" else scopes,
            },
            secret,
            algorithm="HS256",
        )
    headers = {"Authorization": f"Bearer {token}"}
    family = "teams" if target == MANAGER_TEAM_ID else "agents"
    client = TestClient(os.get_app())
    response = client.post(f"/{family}/{target}/runs", headers=headers, data={"message": "hello", "stream": "false"})
    assert response.status_code == (200 if target == MANAGER_TEAM_ID else 422), response.text
    ordinary = client.post("/agents/ordinary/runs", headers=headers, data={"message": "hello", "stream": "false"})
    assert ordinary.status_code == 200, ordinary.text
    scheduled = client.post(
        "/schedules",
        headers=headers,
        json={
            "name": "manager-job",
            "cron_expr": "0 0 * * *",
            "endpoint": f"/{family}/{target}/runs",
            "payload": {"message": "hello"},
        },
    )
    assert scheduled.status_code == (201 if target == MANAGER_TEAM_ID else 409), scheduled.text


def test_manager_cannot_dispatch_for_a_caller_with_only_its_run_scope(db):
    import jwt

    from agno.os import Authorization

    secret = "manager-test-signing-key-at-least-32-characters"
    restricted = Agent(id="restricted", model=ManagerAnswerModel("restricted ran"), db=db)
    os = AgentOS(
        id="manager-test",
        db=db,
        agents=[restricted],
        telemetry=False,
        user_isolation=True,
        authorization=Authorization(verification_keys=[secret], algorithm="HS256", audience="manager-test"),
        manager=OSManager(model=OfflineModel()),
    )
    model = ManagerToolModel("run_agent", {"agent_id": "restricted", "message": "test"})
    os.manager.model = model
    token = jwt.encode(
        {
            "sub": "alice",
            "aud": "manager-test",
            "scopes": ["teams:os-manager-internal:run"],
            "exp": int(time.time()) + 300,
        },
        secret,
        algorithm="HS256",
    )
    client = TestClient(os.get_app())
    headers = {"Authorization": f"Bearer {token}"}
    denied = client.post("/agents/restricted/runs", headers=headers, data={"message": "test", "stream": "false"})
    assert denied.status_code == 403
    response = client.post(
        "/teams/os-manager-internal/runs", headers=headers, data={"message": "test", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    assert "Permission required: agents:restricted:run" in response.text
    assert model.calls > 0
    assert all(getattr(session, "agent_id", None) != "restricted" for session in db.get_sessions())


@pytest.mark.parametrize("service_account", [False, True])
@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("path", ["/teams/os-manager-internal/runs", "/agents/platform-builder-internal/runs"])
async def test_manager_mcp_accepts_ordinary_run_grants(db, monkeypatch, service_account, admin, path):
    from types import SimpleNamespace

    from fastmcp.server import dependencies

    from agno.os.mcp import _require_tool_scopes

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), mcp=True, telemetry=False)
    os.get_app()
    request = SimpleNamespace(
        app=os._mcp_app,
        headers={},
        state=SimpleNamespace(
            authorization_enabled=True,
            user_id="alice",
            claims={},
            scopes=["agent_os:admin"] if admin else ["agents:run", "teams:run"],
            service_account_name="caller" if service_account else None,
            admin_scope="agent_os:admin",
        ),
    )
    monkeypatch.setattr(dependencies, "get_http_request", lambda: request)
    await _require_tool_scopes("POST", path)


class OfflineModel(Model):
    def __init__(self):
        super().__init__(id="fixture", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(content="local answer", role="assistant", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke()

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke()

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def manager_member(os, component_id):
    return next((member for member in os.manager.members if member.id == component_id), None)


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "os.db"))


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "README.md").write_text("# Platform\n")
    (root / "main.py").write_text("print('hi')\n")
    (root / ".env").write_text("OPENAI_API_KEY=secret\n")
    return root


def test_manager_true_uses_the_registry_model_and_serves_only_the_team(db, workspace):
    model = OfflineModel()
    os = AgentOS(db=db, registry=Registry(models=[model]), manager=True, telemetry=False)
    # Source access does not change the two-member composition.
    assert os.agents == []
    assert [a.id for a in os.manager.members] == [BUILDER_ID, OPERATOR_ID]
    assert [t.id for t in os.teams] == [MANAGER_TEAM_ID]
    assert os.manager is not None and os.manager.name == MANAGER_TEAM_NAME == "OS Manager"
    assert os.manager.id == MANAGER_TEAM_ID == "os-manager-internal"
    assert os.manager.model is model and manager_member(os, BUILDER_ID).model is model
    assert not any("read_file" in getattr(t, "functions", {}) for t in manager_member(os, OPERATOR_ID).tools)

    os = AgentOS(db=db, manager=OSManager(model=model, root=workspace), telemetry=False)
    assert os.agents == []
    assert [a.id for a in os.manager.members] == [BUILDER_ID, OPERATOR_ID]
    assert manager_member(os, OPERATOR_ID) is not None


def test_manager_needs_a_model_and_a_sync_db(db, tmp_path):
    with pytest.raises(ValueError, match="needs a model"):
        AgentOS(db=db, manager=True, telemetry=False)
    with pytest.raises(ValueError, match="needs AgentOS\\(db="):
        AgentOS(
            agents=[Agent(id="app", model=OfflineModel())], manager=OSManager(model=OfflineModel()), telemetry=False
        )
    with pytest.raises(ValueError, match="synchronous"):
        AgentOS(
            db=AsyncSqliteDb(db_file=str(tmp_path / "a.db")),
            manager=OSManager(model=OfflineModel()),
            telemetry=False,
        )


def test_manager_config_validates_name_id_and_history():
    with pytest.raises(ValueError):
        OSManager(name=" ")
    with pytest.raises(TypeError):
        OSManager(id=BUILDER_ID)
    with pytest.raises(ValueError):
        OSManager(num_history_runs=-1)


def test_manager_stays_out_of_the_registry_including_after_resync(db, workspace):
    registry = Registry(models=[OfflineModel()])
    app_agent = Agent(id="app", model=OfflineModel())
    os = AgentOS(db=db, registry=registry, agents=[app_agent], manager=OSManager(root=workspace), telemetry=False)
    app = os.get_app()
    os.resync(app)
    assert [a.id for a in registry.agents] == ["app"]
    assert registry.teams == []
    # The platform toolkits were not folded into the registry's tool palette either.
    palette = {type(tool).__name__ for tool in registry.tools}
    assert not palette & {"StudioTools", "StudioRunnerTools", "AgentOSTools"}


def test_application_component_cannot_take_a_reserved_id(db):
    with pytest.raises(ValueError, match="Duplicate IDs"):
        AgentOS(
            db=db,
            agents=[Agent(id=BUILDER_ID, model=OfflineModel())],
            manager=OSManager(model=OfflineModel()),
            telemetry=False,
        )


def test_builder_operator_and_lead_carry_the_framework_toolkits(db):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), tools=[lambda: "x"]), telemetry=False)
    studio = next(t for t in manager_member(os, BUILDER_ID).tools if isinstance(t, StudioTools))
    assert studio.registry is os.registry and studio.db is db
    assert set(studio.requires_confirmation_tools) >= {"archive_component", "delete_version", "delete_schedule"}
    assert any(isinstance(t, AgentOSTools) for t in manager_member(os, OPERATOR_ID).tools)
    assert any("run_diagnostics" in getattr(t, "functions", {}) for t in manager_member(os, OPERATOR_ID).tools)
    runner = next(t for t in os.manager.tools if isinstance(t, StudioRunnerTools))
    assert runner.include_all_components and runner.self_dispatch == "once"
    # Attached resources ride the lead.
    assert any(callable(t) and getattr(t, "__name__", "") == "<lambda>" for t in os.manager.tools)


def test_operator_reads_the_workspace_but_not_env_files(db, workspace):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=workspace), telemetry=False)
    operator = manager_member(os, OPERATOR_ID)
    tool = next(t for t in operator.tools if "read_file" in getattr(t, "functions", {}))
    tools = tool.functions
    assert {"list_files", "read_file"} <= tools.keys()
    assert "print" in tools["read_file"].entrypoint(path="main.py")
    assert "secret" not in tools["read_file"].entrypoint(path=".env")


def test_manifest_defaults_yield_to_the_application_config(db):
    config = AgentOSConfig(
        manifest={
            MANAGER_TEAM_ID: Manifest(description="Our lead", quick_prompts=["Hi"]),
            BUILDER_ID: Manifest(description="Old builder card"),
            OPERATOR_ID: Manifest(description="Old operator card"),
        }
    )
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), config=config, telemetry=False)
    assert os.config.manifest[MANAGER_TEAM_ID].description == "Our lead"
    assert BUILDER_ID not in os.config.manifest and OPERATOR_ID not in os.config.manifest
    assert "platform-engineer" not in os.config.manifest


def test_manager_serves_over_the_ordinary_planes(db):
    os = AgentOS(db=db, manager=OSManager(name="Jarvis", model=OfflineModel()), telemetry=False)
    client = TestClient(os.get_app())
    config = client.get("/config").json()
    assert [t["id"] for t in config["teams"]] == [MANAGER_TEAM_ID]
    assert not config.get("agents")
    assert config["manifest"][MANAGER_TEAM_ID]["quick_prompts"]
    run = client.post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "hello", "stream": "false"})
    assert run.status_code == 200, run.text
    assert run.json()["content"] == "local answer" and run.json()["team_name"] == "Jarvis"
    sessions = client.get("/sessions?type=team").json()["data"]
    assert [s["session_id"] for s in sessions] == [run.json()["session_id"]]
    member = client.post(f"/agents/{OPERATOR_ID}/runs", data={"message": "status", "stream": "false"})
    assert member.status_code == 422, member.text


def test_diagnostics_report_sync_async_and_required_env(db, monkeypatch):
    monkeypatch.setenv("PRESENT_KEY", "1")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    os = AgentOS(
        db=db, manager=OSManager(model=OfflineModel(), required_env=("PRESENT_KEY", "MISSING_KEY")), telemetry=False
    )
    report = os.run_diagnostics()
    by_name = {check.name: check for check in report.checks}
    assert by_name["database"].status == "PASS" and by_name["database"].evidence == "live"
    assert by_name["components"].status == "PASS"
    assert by_name["env:PRESENT_KEY"].status == "PASS" and by_name["env:MISSING_KEY"].status == "FAIL"
    assert report.status == "FAIL"
    assert "secret" not in str(report.to_dict())

    async def inside_loop():
        with pytest.raises(RuntimeError, match="arun_diagnostics"):
            os.run_diagnostics()
        return await os.arun_diagnostics(required_env=())

    clean = asyncio.run(inside_loop())
    assert clean.status == "WARN"  # authorization is off in this fixture
    assert {c.name for c in clean.checks} == {
        "database",
        "authorization",
        "components",
        "registry",
        "interfaces",
        "scheduler",
        "mcp",
    }


class CapturingModel(OfflineModel):
    def __init__(self):
        super().__init__()
        self.system_messages = []

    def invoke(self, *args, **kwargs):
        messages = kwargs.get("messages") or []
        self.system_messages.extend(m.content for m in messages if m.role == "system")
        return super().invoke()

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)


def test_manager_reads_page_context_from_run_dependencies(db):
    model = CapturingModel()
    os = AgentOS(db=db, manager=OSManager(model=model), telemetry=False)
    client = TestClient(os.get_app())
    assert any(isinstance(t, PlatformContextTools) for t in os.manager.tools)
    assert any(isinstance(t, PlatformContextTools) for t in manager_member(os, OPERATOR_ID).tools)

    dependencies = {
        "page_context": {"page": "Traces", "path": "/traces"},
        "context_refs": [{"kind": "trace", "id": "t1"}],
    }
    run = client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        data={"message": "why did this fail?", "stream": "false", "dependencies": json.dumps(dependencies)},
    )
    assert run.status_code == 200, run.text
    system = model.system_messages[-1]
    assert "'path': '/traces'" in system and "'id': 't1'" in system

    # Without page context the placeholders fall back to the team defaults.
    client.post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "hello", "stream": "false"})
    assert "AgentOS UI: not provided" in model.system_messages[-1]
    assert "{page_context}" not in model.system_messages[-1]


def test_diagnostics_without_a_manager(tmp_path):
    os = AgentOS(db=SqliteDb(db_file=str(tmp_path / "bare.db")), telemetry=False)
    assert os.manager is None
    report = os.run_diagnostics()
    assert {c.name for c in report.checks} >= {"database", "scheduler"}


def test_diagnostics_hide_exception_messages(db, monkeypatch):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)

    def boom(*args, **kwargs):
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(db, "get_sessions", boom)
    report = os.run_diagnostics(required_env=())
    database = next(c for c in report.checks if c.name == "database")
    assert database.status == "FAIL" and "hunter2" not in database.detail and "RuntimeError" in database.detail


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("by_name", [False, True])
def test_manager_cannot_be_composed_through_explicit_studio_lists(db, workspace, use_async, by_name):
    registry = Registry(models=[OfflineModel()])
    os = AgentOS(db=db, registry=registry, manager=OSManager(root=workspace), telemetry=False)
    studio = StudioTools(
        registry=registry,
        db=db,
        include_agents=os.manager.members,
        include_teams=os.teams,
        # Manager exclusion is not the overridable guard for application builders.
        allowed_tools=[c.id for c in [os.manager, *os.manager.members]],
    )
    assert registry.agents == [] and registry.teams == []
    os.resync(os.get_app())
    assert registry.agents == [] and registry.teams == []
    for component in [os.manager, *os.manager.members]:
        reference = component.name if by_name else component.id
        kwargs = dict(name="Wrapper", instructions="Delegate", member_ids=[reference], publish=True)
        result = asyncio.run(studio.acreate_team(**kwargs)) if use_async else studio.create_team(**kwargs)
        assert json.loads(result)["error"]["code"] == (
            "component_not_found" if by_name and component is not os.manager else "tool_not_allowed"
        )
        step = {"name": "Inspect", "type": "step", "team_id" if component is os.manager else "agent_id": reference}
        kwargs = dict(name="Flow", steps=[step], publish=True)
        result = asyncio.run(studio.acreate_workflow(**kwargs)) if use_async else studio.create_workflow(**kwargs)
        assert json.loads(result)["error"]["code"] == (
            "component_not_found" if by_name and component is not os.manager else "tool_not_allowed"
        )
    assert db.get_component("wrapper") is None
    assert db.get_component("flow") is None


def test_resync_repairs_manager_mirrors_and_recursive_collection_stops_at_manager(db, workspace):
    from agno.os.utils import collect_components_from_os
    from agno.team import Team

    registry = Registry(models=[OfflineModel()])
    os = AgentOS(db=db, registry=registry, manager=OSManager(root=workspace), telemetry=False)
    registry.agents.extend(os.manager.members)
    registry.teams.append(os.manager)
    wrapper = Team(
        id="wrapper", name="Wrapper", model=OfflineModel(), members=[manager_member(os, OPERATOR_ID).deep_copy()]
    )
    os.teams.append(wrapper)
    collect_components_from_os(os.agents, os.teams, os.workflows, registry)
    os.resync(os.get_app())
    assert registry.agents == []
    assert [t.id for t in registry.teams] == ["wrapper"]
    assert not registry.tools
    studio = StudioTools(registry=registry, db=db, allowed_tools=["wrapper"])
    result = json.loads(studio.create_team(name="Built", instructions="Delegate", member_ids=["Wrapper"], publish=True))
    assert result["error"]["code"] == "tool_not_allowed"


@pytest.mark.parametrize("declaration", [None, "registry", "os", "agent"])
def test_manager_knowledge_requires_an_independent_build_declaration(db, declaration):
    from agno.agent import get_agent_by_id
    from agno.knowledge import Knowledge
    from agno.learn import LearningMachine

    knowledge = Knowledge(name="lead-only", contents_db=db)
    learning = LearningMachine(name="lead-memory", db=db, model=OfflineModel())
    registry = Registry(models=[OfflineModel()], knowledge=[knowledge] if declaration == "registry" else [])
    app_agent = Agent(id="app", model=OfflineModel(), knowledge=knowledge if declaration == "agent" else None)
    os = AgentOS(
        db=db,
        registry=registry,
        agents=[app_agent],
        knowledge=[knowledge] if declaration == "os" else None,
        manager=OSManager(knowledge=knowledge, learning=learning),
        telemetry=False,
    )
    os.resync(os.get_app())
    assert knowledge in os.knowledge_instances  # still served as an ordinary team's resource
    assert (knowledge in registry.knowledge) == (declaration is not None)
    assert learning not in registry.learning
    studio = manager_member(os, BUILDER_ID).tools[0]
    result = json.loads(
        studio.create_agent(name="Consumer", instructions="Read", knowledge_name=knowledge.name, publish=True)
    )
    if declaration is None:
        assert result["ok"] is False
    else:
        assert result["ok"] is True
        restored = get_agent_by_id(db=db, id=result["data"]["id"], registry=registry, strict=True)
        assert restored.knowledge is knowledge


@pytest.mark.parametrize("provider_kind", ["path", "default", "empty_exclusions", "subclass"])
def test_operator_normalizes_workspace_and_confines_all_read_tools(db, workspace, tmp_path, provider_kind):
    from agno.context.mode import ContextMode
    from agno.context.workspace import WorkspaceContextProvider

    class CustomProvider(WorkspaceContextProvider):
        def get_tools(self):
            raise AssertionError("The manager must not use replacement platform tools")

    (workspace / "credentials.json").write_text('{"token": "synthetic-credential"}')
    (workspace / "alias.py").symlink_to(workspace / "credentials.json")
    (tmp_path / "outside.txt").write_text("synthetic-credential")
    (workspace / "escape.py").symlink_to(tmp_path / "outside.txt")
    (workspace / "extra.py").write_text("extra source")
    provider = (
        workspace
        if provider_kind == "path"
        else CustomProvider(root=workspace)
        if provider_kind == "subclass"
        else WorkspaceContextProvider(
            root=workspace, exclude_patterns=[] if provider_kind == "empty_exclusions" else None
        )
    )
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=provider), telemetry=False)
    tool = next(t for t in manager_member(os, OPERATOR_ID).tools if "read_file" in getattr(t, "functions", {}))
    assert set(tool.functions) == {"read_file", "list_files", "search_content"}
    assert "print" in tool.read_file("main.py")
    for path in (".env", "credentials.json", "alias.py", "./credentials.json", "../outside.txt", "escape.py"):
        assert tool.read_file(path).startswith("Error:")
    assert json.loads(tool.search_content("synthetic-credential"))["matches_found"] == 0
    assert "credentials.json" not in tool.list_files(recursive=True)
    if provider_kind != "path":
        assert provider.mode == ContextMode.default
        if provider_kind == "empty_exclusions":
            assert provider.exclude_patterns == []


@pytest.mark.parametrize("kwargs", [{"allow_paths": [".env"]}, {"exclude_patterns": ["!.env"]}])
def test_operator_refuses_workspace_exclusion_overrides(db, workspace, kwargs):
    from agno.context.workspace import WorkspaceContextProvider

    with pytest.raises(ValueError, match="cannot override exclusions"):
        AgentOS(
            db=db,
            manager=OSManager(model=OfflineModel(), root=WorkspaceContextProvider(root=workspace, **kwargs)),
            telemetry=False,
        )


def test_operator_rejects_an_arbitrary_tool_provider(db):
    with pytest.raises(TypeError, match="WorkspaceContextProvider"):
        AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=object()), telemetry=False)


class ToolCallingModel(OfflineModel):
    def __init__(self, tool_name, arguments):
        super().__init__()
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls = 0

    def invoke(self, messages, *args, **kwargs):
        self.calls += 1
        assert self.calls <= 6, "Dispatch must terminate"
        if messages[-1].role == "tool":
            return ModelResponse(content=str(messages[-1].content), role="assistant", response_usage=MessageMetrics())
        return ModelResponse(
            role="assistant",
            response_usage=MessageMetrics(),
            tool_calls=[
                {
                    "id": f"call-{self.calls}",
                    "type": "function",
                    "function": {"name": self.tool_name, "arguments": json.dumps(self.arguments)},
                }
            ],
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)


@pytest.mark.parametrize("use_async", [False, True])
def test_operator_executes_diagnostics_in_both_run_modes(db, use_async):
    model = ToolCallingModel("run_diagnostics", {})
    os = AgentOS(db=db, manager=OSManager(model=model), telemetry=False)
    result = (
        asyncio.run(manager_member(os, OPERATOR_ID).arun("Diagnose"))
        if use_async
        else manager_member(os, OPERATOR_ID).run("Diagnose")
    )
    report = json.loads(result.content)
    assert next(c for c in report["checks"] if c["name"] == "database")["status"] == "PASS"
    assert model.calls == 2


@pytest.mark.parametrize("use_async", [False, True])
def test_manager_self_dispatch_terminates_after_one_nested_run(db, use_async):
    model = ToolCallingModel("run_team", {"team_id": MANAGER_TEAM_ID, "message": "Fresh context"})
    os = AgentOS(db=db, manager=OSManager(model=model), telemetry=False)
    result = (
        asyncio.run(os.manager.arun("Consult yourself", user_id="alice"))
        if use_async
        else os.manager.run("Consult yourself", user_id="alice")
    )
    assert "already running" in result.content
    assert model.calls == 4
    sessions = db.get_sessions(user_id="alice")
    assert len(sessions) == 2
    assert os.registry.teams == [] and os.registry.agents == []


@pytest.mark.parametrize("use_async", [False, True])
def test_manager_runner_tracks_served_components_after_list_replacement(db, use_async):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)
    runner = next(t for t in os.manager.deep_copy().tools if isinstance(t, StudioRunnerTools))
    app_agent = Agent(id="later", model=OfflineModel(), db=db)
    os.agents = [*os.agents, app_agent]
    kwargs = dict(agent_id="later", message="Hello")
    result = asyncio.run(runner.arun_agent(**kwargs)) if use_async else runner.run_agent(**kwargs)
    assert json.loads(result)["content"] == "local answer"
    kwargs["agent_id"] = OPERATOR_ID
    result = asyncio.run(runner.arun_agent(**kwargs)) if use_async else runner.run_agent(**kwargs)
    assert "error" in json.loads(result)


@pytest.mark.parametrize("component_id", [BUILDER_ID, OPERATOR_ID, MANAGER_TEAM_ID])
@pytest.mark.parametrize("in_registry", [False, True])
def test_manager_reserves_fixed_ids(db, component_id, in_registry):
    app_agent = Agent(id=component_id, model=OfflineModel())
    with pytest.raises(ValueError, match="reserved for the manager"):
        AgentOS(
            db=db,
            agents=[] if in_registry else [app_agent],
            registry=Registry(agents=[app_agent] if in_registry else []),
            manager=OSManager(model=OfflineModel()),
            telemetry=False,
        )


def test_resync_rejects_an_application_agent_with_an_unused_reserved_id(db):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)
    app = os.get_app()
    os.agents.append(Agent(id=OPERATOR_ID, model=OfflineModel()))
    with pytest.raises(ValueError, match="reserved for the manager"):
        os.resync(app)


@pytest.mark.parametrize("copied", [False, True])
def test_manager_exclusion_survives_foreign_registry_mirrors(db, workspace, copied):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=workspace), telemetry=False)
    agents = [a.deep_copy() for a in os.manager.members] if copied else os.manager.members
    team = os.manager.deep_copy() if copied else os.manager
    foreign = Registry(models=[OfflineModel()], agents=list(agents), teams=[team])
    assert foreign.agents == [] and foreign.teams == []
    studio = StudioTools(
        registry=foreign, db=db, include_agents=agents, include_teams=[team], allowed_tools=[OPERATOR_ID]
    )
    assert foreign.agents == [] and foreign.teams == []
    result = json.loads(
        studio.create_team(name="Wrapper", instructions="Read", member_ids=["Platform Manager"], publish=True)
    )
    assert result["error"]["code"] == "component_not_found"


@pytest.mark.parametrize("component_id", [BUILDER_ID, OPERATOR_ID, MANAGER_TEAM_ID])
def test_studio_and_component_api_cannot_mint_reserved_manager_ids(db, component_id):
    registry = Registry(models=[OfflineModel()])
    os = AgentOS(db=db, registry=registry, manager=OSManager(), telemetry=False)
    studio = manager_member(os, BUILDER_ID).tools[0]
    result = json.loads(
        studio.create_agent(name="Application agent", component_id=component_id, instructions="Answer", publish=True)
    )
    assert result["error"]["code"] == "component_conflict"
    response = TestClient(os.get_app()).post(
        "/components",
        json={
            "name": "Application agent",
            "component_id": component_id,
            "component_type": "agent",
            "config": {},
        },
    )
    assert response.status_code == 409
    assert db.get_component(component_id) is None


def test_registry_exclusion_does_not_mutate_the_served_lists(db, workspace):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=workspace), telemetry=False)
    app = os.get_app()
    foreign = Registry(agents=os.agents, teams=os.teams)
    assert foreign.agents == [] and foreign.teams == []
    assert os.agents == [] and os.teams == [os.manager]
    os.registry.agents = os.agents
    os.registry.teams = os.teams
    os.resync(app)
    assert os.registry.agents == [] and os.registry.teams == []
    assert os.agents == [] and os.teams == [os.manager]


@pytest.mark.parametrize("enabled", [None, False])
def test_disabled_manager_needs_neither_a_model_nor_a_workspace(db, enabled):
    os = AgentOS(db=db, manager=enabled, telemetry=False)
    assert os.manager is None
    assert not os.agents and not os.teams
    assert os.registry.excluded_component_ids == {MANAGER_TEAM_ID, BUILDER_ID, OPERATOR_ID, PRODUCT_MANAGER_ID}


@pytest.mark.parametrize("invalid", ["true", {}, 1, 0])
def test_manager_rejects_values_outside_the_configuration_contract(db, invalid):
    with pytest.raises(TypeError, match="AgentOS.manager must be"):
        AgentOS(db=db, manager=invalid, telemetry=False)


@pytest.mark.parametrize("use_async", [False, True])
def test_manager_property_is_the_served_team_and_runs_directly(db, use_async):
    from agno.team import Team

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)
    assert type(os.manager) is Team
    assert os.manager is os.teams[0]
    result = (
        asyncio.run(os.manager.arun("Hello", user_id="alice"))
        if use_async
        else os.manager.run("Hello", user_id="alice")
    )
    assert result.content == "local answer"
    assert [s.session_id for s in db.get_sessions(user_id="alice")] == [result.session_id]
    app = os.get_app()
    manager = os.manager
    os.resync(app)
    assert os.manager is manager and os.manager is os.teams[0]
    assert not any(path.startswith("/manager") for path in app.openapi()["paths"])


def test_manager_configuration_does_not_accept_replacement_members():
    with pytest.raises(TypeError, match="members"):
        OSManager(members=[])


def test_scheduler_check_fails_on_an_unreadable_schedules_table(tmp_path):
    import sqlite3

    db_file = tmp_path / "broken.db"
    os = AgentOS(db=SqliteDb(db_file=str(db_file)), scheduler=True, telemetry=False)
    os.get_app()
    # A schedules table of the wrong shape: every real query against it fails, and the
    # adapter's default answer to that is an empty list.
    with sqlite3.connect(db_file) as conn:
        conn.execute("DROP TABLE IF EXISTS agno_schedules")
        conn.execute("CREATE TABLE agno_schedules (id TEXT PRIMARY KEY)")
    assert os.db.get_schedules(enabled=True) == ([], 0)
    scheduler = next(c for c in os.run_diagnostics(required_env=()).checks if c.name == "scheduler")
    assert scheduler.status == "FAIL" and "Error" in scheduler.detail


def test_database_check_reads_one_session_without_runs(db, monkeypatch):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)
    seen = {}
    original = db.get_sessions

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(db, "get_sessions", spy)
    database = next(c for c in os.run_diagnostics(required_env=()).checks if c.name == "database")
    assert database.status == "PASS"
    assert seen["limit"] == 1 and seen["include_runs"] is False and seen["deserialize"] is False


def test_diagnostics_pass_only_arguments_an_adapter_declares(db, monkeypatch):
    os = AgentOS(db=db, scheduler=True, telemetry=False)

    def narrow_get_sessions(limit=None, page=None, deserialize=True):
        return [], 0

    def narrow_get_schedules(enabled=None, limit=None, page=None):
        return [], 0

    monkeypatch.setattr(db, "get_sessions", narrow_get_sessions)
    monkeypatch.setattr(db, "get_schedules", narrow_get_schedules)
    checks = {c.name: c for c in os.run_diagnostics(required_env=()).checks}
    assert checks["database"].status == "PASS" and checks["scheduler"].status == "PASS"


@pytest.mark.parametrize(
    "status_code,expected",
    [(200, "PASS"), (401, "PASS"), (403, "PASS"), (404, "FAIL"), (503, "FAIL"), (500, "FAIL"), (307, "WARN")],
)
def test_mcp_probe_distinguishes_reachable_from_healthy(db, monkeypatch, status_code, expected):
    import httpx

    os = AgentOS(db=db, mcp=True, telemetry=False)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, **kwargs):
            assert url == "https://os.example.test/mcp"
            return httpx.Response(status_code)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    report = os.run_diagnostics(required_env=(), network_probe=True, public_url="https://os.example.test/")
    mcp = next(c for c in report.checks if c.name == "mcp")
    assert mcp.status == expected and mcp.evidence == "live" and str(status_code) in mcp.detail


def test_registry_exclusion_surface_is_public_and_read_only():
    registry = Registry()
    registry.reserve_component_ids(["reserved-id", ""])
    assert registry.excluded_component_ids == frozenset(
        {"reserved-id", MANAGER_TEAM_ID, BUILDER_ID, OPERATOR_ID, PRODUCT_MANAGER_ID}
    )
    with pytest.raises(AttributeError):
        registry.excluded_component_ids.add("other")  # type: ignore[attr-defined]
    agent = Agent(id="served", model=OfflineModel())
    registry.agents.append(agent)
    registry.exclude_components([agent])
    assert registry.agents == []
    assert registry.is_component_excluded(agent) and registry.is_component_excluded(agent.deep_copy())
    assert registry.is_component_excluded(Agent(id="reserved-id", model=OfflineModel()))
    assert not registry.is_component_excluded(Agent(id="free", model=OfflineModel()))


def test_manager_name_is_customizable_but_id_is_fixed(db):
    config = OSManager(name="Agno", model=OfflineModel())
    with pytest.raises(AttributeError):
        config.id = "custom"
    os = AgentOS(db=db, manager=config, telemetry=False)
    assert os.manager.id == MANAGER_TEAM_ID and os.manager.name == "Agno"
    run = TestClient(os.get_app()).post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "hello", "stream": "false"})
    assert run.status_code == 200 and run.json()["team_name"] == "Agno"


class ManagerToolModel(OfflineModel):
    """Call one tool, then finish without an external model."""

    def __init__(self, tool_name, tool_args):
        super().__init__()
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.calls = 0

    def invoke(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": "manager-tool-call",
                        "type": "function",
                        "function": {"name": self.tool_name, "arguments": json.dumps(self.tool_args)},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        return super().invoke(*args, **kwargs)


class ManagerAnswerModel(OfflineModel):
    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def invoke(self, *args, **kwargs):
        return ModelResponse(content=self.answer, role="assistant", response_usage=MessageMetrics())


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("target", [MANAGER_TEAM_ID, BUILDER_ID, OPERATOR_ID])
@pytest.mark.parametrize("setting", ["default", "disabled", "custom"])
def test_manager_offloading_and_readback(db, workspace, async_mode, target, setting):
    # The custom payload is below the default threshold, so it only offloads
    # if the supplied ResultStore settings survive manager construction.
    payload = "\n".join(f"row {i}: " + "x" * 70 for i in range(1, 301 if setting != "custom" else 101))
    config = OSManager(model=OfflineModel(), root=workspace)
    if setting == "disabled":
        config.offload_tool_results = False
    elif setting == "custom":
        config.offload_tool_results = ResultStore(threshold_chars=500, ttl_seconds=3600)
    os = AgentOS(db=db, manager=config, telemetry=False)
    assert os.manager.offload_tool_results is config.offload_tool_results
    assert all(member.offload_tool_results is config.offload_tool_results for member in os.manager.members)
    if setting == "default":
        assert config.offload_tool_results is True

    if target == MANAGER_TEAM_ID:
        owner = os.manager
        member = manager_member(os, OPERATOR_ID)
        member.model = ManagerAnswerModel(payload)
        owner.model = ManagerToolModel(
            "delegate_task_to_member", {"member_id": OPERATOR_ID, "task": "Return the report"}
        )
    else:
        owner = manager_member(os, target)

        def fetch_report() -> str:
            """Return the full report."""
            return payload

        owner.tools.append(fetch_report)
        owner.model = ManagerToolModel("fetch_report", {})

    run_args = {"session_id": "manager-report", "user_id": "alice"}
    result = (
        asyncio.run(owner.arun("Get the report", **run_args)) if async_mode else owner.run("Get the report", **run_args)
    )
    messages = [message for message in result.messages if message.role == "tool"]
    assert len(messages) == 1
    content = messages[0].content
    if setting == "disabled":
        assert content == payload
        assert owner._result_store is None
        return

    assert content.startswith('<result id="res_')
    assert payload not in content
    result_id = content.split('id="')[1].split('"')[0]
    store = owner._result_store
    assert store.threshold_chars == (500 if setting == "custom" else 16000)
    if setting == "custom":
        assert store.ttl_seconds == 3600
    if target == MANAGER_TEAM_ID:
        assert member._result_store.db is store.db

    def read(session_id, user_id):
        context = RunContext(run_id="read-back", session_id=session_id, user_id=user_id)
        tool = get_read_result_function(owner, context, async_mode=async_mode)
        args = {"result_id": result_id, "start_line": 50, "end_line": 51}
        return asyncio.run(tool.entrypoint(**args)) if async_mode else tool.entrypoint(**args)

    # Read past the preview through the actual tool, including access checks.
    assert "row 50:" not in content
    assert "row 50:" in read("manager-report", "alice")
    assert "different session" in read("another-session", "alice")
    assert "different user" in read("manager-report", "bob")


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("component_id", [MANAGER_TEAM_ID, BUILDER_ID, OPERATOR_ID])
def test_reserved_ids_cannot_be_minted_when_manager_is_disabled(db, enabled, component_id):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()) if enabled else None, telemetry=False)
    studio = StudioTools(registry=os.registry, db=db)
    result = json.loads(studio.create_agent(name="Imposter", component_id=component_id, instructions="Answer"))
    assert result["error"]["code"] == "component_conflict"
    response = TestClient(os.get_app()).post(
        "/components",
        json={"name": "Imposter", "component_id": component_id, "component_type": "agent", "config": {}},
    )
    assert response.status_code == 409
    assert db.get_component(component_id) is None


@pytest.mark.parametrize("component_id", [MANAGER_TEAM_ID, BUILDER_ID, OPERATOR_ID])
@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_reserved_ids_rejected_for_all_application_component_types(db, component_id, kind):
    from agno.team import Team
    from agno.workflow import Workflow

    component = (
        Agent(id=component_id, model=OfflineModel())
        if kind == "agent"
        else Team(id=component_id, members=[], model=OfflineModel())
        if kind == "team"
        else Workflow(id=component_id, steps=[])
    )
    with pytest.raises(ValueError, match="reserved for the manager"):
        AgentOS(db=db, **{kind + "s": [component]}, telemetry=False)
    with pytest.raises(ValueError, match="reserved for the manager"):
        Registry(**{kind + "s": [component]})


def test_internal_identity_metadata_reaches_discovery_detail_and_runs(db, workspace):
    ordinary_metadata = {"customer": "example", "_agno": {"source_url": "https://example.com"}}
    ordinary = Agent(id="ordinary", model=OfflineModel(), metadata=ordinary_metadata)
    os = AgentOS(db=db, agents=[ordinary], manager=OSManager(model=OfflineModel(), root=workspace), telemetry=False)
    client = TestClient(os.get_app())
    for resync in (False, True):
        if resync:
            os.resync(os.get_app())
        config = client.get("/config").json()
        rows = [*config["agents"], *config["teams"]]
        rows += client.get("/agents").json() + client.get("/teams").json()
        team = client.get(f"/teams/{MANAGER_TEAM_ID}").json()
        rows.append(team)
        assert not team.get("members")
        assert [agent["id"] for agent in config["agents"]] == ["ordinary"]
        assert [agent["id"] for agent in client.get("/agents").json()] == ["ordinary"]
        assert not {BUILDER_ID, OPERATOR_ID}.intersection(config["manifest"])
        for row in rows:
            if row["id"] == "ordinary":
                assert row.get("metadata") in (None, ordinary_metadata)
            else:
                assert row["metadata"]["_agno"] == {"internal": True, "id": row["id"]}
                assert "is_manager" not in row
        assert [member.id for member in os.manager.members] == [BUILDER_ID, OPERATOR_ID]
    run = client.post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "hello", "stream": "false"})
    assert run.status_code == 200
    assert run.json()["metadata"]["_agno"] == {"internal": True, "id": MANAGER_TEAM_ID}


@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
def test_manager_model_is_buildable_without_leaking_privileged_tools(db, declared, use_async):
    from agno.agent import get_agent_by_id

    model = OfflineModel()
    declared_model = OfflineModel()
    registry = Registry(models=[declared_model]) if declared else None
    os = AgentOS(db=db, registry=registry, manager=OSManager(model=model), telemetry=False)
    registry = os.registry
    assert registry.models == [declared_model if declared else model]
    assert registry.models[0] is (declared_model if declared else model)
    os.resync(os.get_app())
    assert len(registry.models) == 1
    assert not registry.tools and not registry.agents and not registry.teams
    studio = manager_member(os, BUILDER_ID).tools[0]
    listed = json.loads(studio.list_models())
    assert listed["data"]["models"][0]["id"] == model.id
    kwargs = dict(name="Basic agent", instructions="Answer plainly", model_id=model.id, publish=True)
    result = json.loads(asyncio.run(studio.acreate_agent(**kwargs)) if use_async else studio.create_agent(**kwargs))
    assert result["ok"], result
    restored = get_agent_by_id(db=db, id=result["data"]["id"], registry=registry, strict=True)
    output = asyncio.run(restored.arun("Hello")) if use_async else restored.run("Hello")
    assert output.content == "local answer"
    assert not restored.tools


@pytest.mark.parametrize("enabled", [None, False, True])
def test_docs_mcp_defaults_on_is_private_and_uses_os_lifecycle(db, monkeypatch, enabled):
    from agno.tools.mcp import MCPTools

    calls = []

    async def connect(tool, force=False):
        calls.append(("connect", tool.url))
        tool._initialized = True

    async def close(tool):
        calls.append(("close", tool.url))
        tool._initialized = False

    monkeypatch.setattr(MCPTools, "connect", connect)
    monkeypatch.setattr(MCPTools, "close", close)
    config = OSManager(model=OfflineModel(), **({} if enabled is None else {"access_docs": enabled}))
    assert config.access_docs is (enabled is not False)
    enabled = config.access_docs
    os = AgentOS(db=db, manager=config, telemetry=False)
    docs = [tool for tool in manager_member(os, OPERATOR_ID).tools if isinstance(tool, MCPTools)]
    assert len(docs) == int(enabled)
    assert not os.registry.tools
    if enabled:
        assert docs[0].url == "https://docs.agno.com/mcp"
        assert os.mcp_tools == docs
    with TestClient(os.get_app()) as client:
        assert (
            client.post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "Hi", "stream": "false"}).status_code == 200
        )
    if enabled:
        assert calls[0] == ("connect", "https://docs.agno.com/mcp")
        assert calls[-1] == ("close", "https://docs.agno.com/mcp")
        assert all(url == "https://docs.agno.com/mcp" for _, url in calls)
    else:
        assert not calls


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("location", ["registry", "nested"])
def test_reserved_ids_rejected_on_resync_before_mirror_filtering(db, enabled, location):
    from agno.team import Team

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()) if enabled else None, telemetry=False)
    app = os.get_app()
    imposter = Agent(id=OPERATOR_ID, model=OfflineModel())
    if location == "registry":
        os.registry.agents.append(imposter)
    else:
        os.teams = [*(os.teams or []), Team(id="ordinary-team", members=[imposter], model=OfflineModel())]
    with pytest.raises(ValueError, match="reserved for the manager"):
        os.resync(app)


@pytest.mark.parametrize("failure", [OSError, TimeoutError])
def test_docs_outage_is_nonfatal_cleans_up_and_recovers(db, monkeypatch, failure):
    from unittest.mock import AsyncMock

    from agno.tools.function import Function
    from agno.tools.mcp import MCPTools

    available = False
    attempts = []
    partial_sessions = []
    offered_tools = []

    class ObservingModel(OfflineModel):
        async def ainvoke(self, *args, **kwargs):
            offered_tools.append({tool.get("function", {}).get("name") for tool in kwargs.get("tools") or []})
            return self.invoke()

    async def connect(tool):
        attempts.append(tool.url)
        if not available:
            partial = AsyncMock()
            partial_sessions.append(partial)
            tool._session_context = partial
            tool.session = object()
            raise failure("Docs temporarily unavailable")
        tool.functions["search_agno_docs"] = Function(
            name="search_agno_docs", entrypoint=lambda: "Documentation result"
        )
        tool._initialized = True

    monkeypatch.setattr(MCPTools, "_connect", connect)
    os = AgentOS(db=db, manager=OSManager(model=ObservingModel()), telemetry=False)
    docs = os.mcp_tools[0]
    operator = manager_member(os, OPERATOR_ID)
    with TestClient(os.get_app()) as client:
        # Startup succeeds even after a partially established connection fails.
        assert attempts == ["https://docs.agno.com/mcp"]
        assert not docs.initialized and docs.session is None
        assert docs._session_context is None
        assert asyncio.run(operator.arun("Hi")).content == "local answer"
        for target in (f"teams/{MANAGER_TEAM_ID}",):
            response = client.post(f"/{target}/runs", data={"message": "Hi", "stream": "false"})
            assert response.status_code == 200, response.text
            assert response.json()["content"] == "local answer"
        assert len(attempts) >= 2
        assert all("search_agno_docs" not in names for names in offered_tools)
        assert "run_diagnostics" in offered_tools[0]
        for partial in partial_sessions:
            partial.__aexit__.assert_awaited_once_with(None, None, None)
        assert not docs.initialized and not docs.functions
        assert any(isinstance(tool, AgentOSTools) for tool in operator.tools)

        # A later async run reconnects without restarting AgentOS.
        available = True
        asyncio.run(operator.arun("Hi"))
        assert "search_agno_docs" in docs.functions
        assert "search_agno_docs" in offered_tools[-1]
        os.resync(os.get_app())
        assert not os.registry.tools


def test_missing_optional_mcp_dependency_does_not_prevent_manager_startup(db, monkeypatch):
    import builtins

    from agno.utils import log

    original_import = builtins.__import__
    warnings = []
    attempted = []

    def without_mcp(name, *args, **kwargs):
        if name == "agno.tools.mcp":
            attempted.append(name)
            raise ImportError("mcp is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_mcp)
    monkeypatch.setattr(log, "log_warning", warnings.append)
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)
    assert attempted == ["agno.tools.mcp"]
    assert any("install agno[mcp]" in message for message in warnings)
    assert not os.mcp_tools
    with TestClient(os.get_app()) as client:
        response = client.post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "Hi", "stream": "false"})
        assert response.status_code == 200, response.text

    attempted.clear()
    warnings.clear()
    AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    assert not attempted and not warnings


@pytest.mark.asyncio
async def test_docs_connection_does_not_swallow_cancellation(db, monkeypatch):
    from agno.tools.mcp import MCPTools

    async def cancelled(tool):
        raise asyncio.CancelledError()

    monkeypatch.setattr(MCPTools, "_connect", cancelled)
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), telemetry=False)
    with pytest.raises(asyncio.CancelledError):
        await os.mcp_tools[0].connect()


@pytest.mark.parametrize("stream", [False, True])
def test_internal_members_delegate_and_keep_structured_reports(db, stream):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    operator = manager_member(os, OPERATOR_ID)
    operator.model = ManagerToolModel("get_platform_metrics", {"days": 7})
    os.manager.model = ManagerToolModel(
        "delegate_task_to_member", {"member_id": OPERATOR_ID, "task": "Report platform usage"}
    )
    client = TestClient(os.get_app())
    response = client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        data={"message": "Report usage", "session_id": "reports", "stream": str(stream).lower()},
    )
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        reports = [
            event["tool"]["result"]
            for event in events
            if event.get("agent_id") == OPERATOR_ID
            and event.get("event") == "ToolCallCompleted"
            and event.get("tool", {}).get("tool_name") == "get_platform_metrics"
        ]
        assert reports and json.loads(reports[0])["window_days"] == 7
    else:
        assert response.json()["content"] == "local answer"
    # Persisted child runs remain available inside the manager's session for replay/diagnostics.
    from agno.db.base import SessionType

    session = db.get_session("reports", session_type=SessionType.TEAM)
    child = next(run for run in session.runs if getattr(run, "agent_id", None) == OPERATOR_ID)
    assert child.agent_id == OPERATOR_ID
    assert json.loads(child.tools[0].result)["window_days"] == 7
    assert operator.store_events
    replay = client.get("/sessions/reports/runs")
    assert replay.status_code == 200, replay.text
    child_data = next(run for run in replay.json() if run.get("agent_id") == OPERATOR_ID)
    assert json.loads(child_data["tools"][0]["result"])["window_days"] == 7


@pytest.mark.asyncio
async def test_mcp_config_hides_specialists_but_manager_delegates(db):
    from fastmcp import Client

    from agno.os.mcp import build_mcp_server

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    os.manager.model = ManagerToolModel("delegate_task_to_member", {"member_id": OPERATOR_ID, "task": "Answer"})
    os.get_app()
    async with Client(build_mcp_server(os)) as client:
        config = await client.call_tool("get_agentos_config", {})
        text = " ".join(block.text for block in config.content if hasattr(block, "text"))
        assert MANAGER_TEAM_ID in text
        assert BUILDER_ID not in text and OPERATOR_ID not in text
        result = await client.call_tool("run_team", {"team_id": MANAGER_TEAM_ID, "message": "Answer"})
        assert not result.is_error
        for member_id in (BUILDER_ID, OPERATOR_ID):
            with pytest.raises(Exception, match="is reserved"):
                await client.call_tool("run_agent", {"agent_id": member_id, "message": "Answer"})


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_enabled", [False, True])
async def test_legacy_catalog_rows_cannot_restore_public_specialists(db, manager_enabled):
    from fastmcp import Client

    from agno.db.base import ComponentType
    from agno.os.mcp import build_mcp_server

    os = AgentOS(
        db=db,
        manager=OSManager(model=OfflineModel(), access_docs=False) if manager_enabled else False,
        telemetry=False,
    )
    # Simulate rows left by an older deployment, bypassing current reservation checks.
    for component_id in (BUILDER_ID, OPERATOR_ID, "stored-ordinary"):
        db.create_component_with_config(
            component_id=component_id,
            component_type=ComponentType.AGENT,
            name=component_id,
            config={"name": component_id, "instructions": "Answer briefly"},
            stage="published",
        )
    client = TestClient(os.get_app())
    assert [agent["id"] for agent in client.get("/agents").json()] == ["stored-ordinary"]
    async with Client(build_mcp_server(os)) as mcp:
        config = await mcp.call_tool("get_agentos_config", {})
        text = " ".join(block.text for block in config.content if hasattr(block, "text"))
        assert "stored-ordinary" in text
        assert BUILDER_ID not in text and OPERATOR_ID not in text


@pytest.mark.parametrize("member_id", [BUILDER_ID, OPERATOR_ID])
def test_schedule_cannot_be_retargeted_to_a_private_specialist(db, member_id):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    client = TestClient(os.get_app())
    created = client.post(
        "/schedules",
        json={"name": "manager-job", "cron_expr": "0 0 * * *", "endpoint": f"/teams/{MANAGER_TEAM_ID}/runs"},
    )
    assert created.status_code == 201, created.text
    path = f"/schedules/{created.json()['id']}"
    response = client.patch(path, json={"endpoint": f"/agents/{member_id}/runs/"})
    assert response.status_code == 409, response.text
    assert client.get(path).json()["endpoint"] == f"/teams/{MANAGER_TEAM_ID}/runs"


def _store_manager_test_component(db, kind, component_id, name=None):
    from agno.db.base import ComponentType

    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType(kind),
        name=name or component_id,
        config={"name": name or component_id, "model": {"id": "fixture", "provider": "test"}},
        stage="published",
    )


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("use_async", [False, True])
def test_manager_runner_refuses_legacy_specialists(db, enabled, use_async):
    from agno.tools.studio_runner import StudioRunnerTools

    registry = Registry(models=[OfflineModel()])
    os = AgentOS(db=db, registry=registry, manager=OSManager(access_docs=False) if enabled else False, telemetry=False)
    for component_id in (BUILDER_ID, OPERATOR_ID):
        _store_manager_test_component(db, "agent", component_id, "Legacy " + component_id)
    _store_manager_test_component(db, "team", MANAGER_TEAM_ID)
    _store_manager_test_component(db, "agent", "ordinary")
    runner = (
        os.manager.tools[0] if enabled else StudioRunnerTools(db=db, registry=registry, include_all_components=True)
    )
    for component_id in (BUILDER_ID, OPERATOR_ID):
        for reference in (component_id, "Legacy " + component_id):
            result = asyncio.run(runner.arun_agent(reference, "hi")) if use_async else runner.run_agent(reference, "hi")
            assert "error" in json.loads(result)
    data = json.loads(runner.list_agents())
    assert data["count"] == data["total"] == 1
    assert data["agents"][0]["id"] == "ordinary"
    assert json.loads(runner.list_teams())["total"] == int(enabled)
    assert data["other_components"]["teams"] == int(enabled)


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
@pytest.mark.parametrize("strict", [False, True])
def test_catalog_cannot_restore_framework_manager_ids(db, kind, strict):
    from importlib import import_module

    from agno.registry._reserved import RESERVED_MANAGER_IDS

    registry = Registry(models=[OfflineModel()])
    module = import_module(f"agno.{kind}.{kind}")
    for component_id in RESERVED_MANAGER_IDS:
        _store_manager_test_component(db, kind, component_id)
        for loader in (getattr(module, f"get_{kind}_by_id"), getattr(module, kind.capitalize()).load):
            for version in (None, 1):
                with pytest.raises(ComponentRehydrationError) as exc:
                    loader(db=db, id=component_id, registry=registry, version=version, strict=strict)
                assert str(exc.value) == (
                    f"Component ID '{component_id}' is reserved. Please choose a different ID for your component."
                )
            assert loader(db=db, id="missing", registry=registry, strict=strict) is None
        assert db.get_component(component_id) is not None  # No implicit migration/deletion.
    _store_manager_test_component(db, kind, "ordinary")
    assert [c.id for c in getattr(module, f"get_{kind}s")(db=db, registry=registry)] == ["ordinary"]


@pytest.mark.parametrize("use_async", [False, True])
def test_scheduler_tools_refuse_legacy_manager_targets(db, use_async):
    from agno.tools.scheduler import SchedulerTools

    scheduler = SchedulerTools(db=db)
    args = dict(name="invalid", cron="0 0 * * *", endpoint=f"/agents/{OPERATOR_ID}/runs")
    result = asyncio.run(scheduler.acreate_schedule(**args)) if use_async else scheduler.create_schedule(**args)
    assert json.loads(result)["error_type"] == "target_internal"
    old = scheduler.manager.create(name="old", cron="0 0 * * *", endpoint=args["endpoint"])
    for method in ("enable_schedule", "trigger_schedule"):
        result = getattr(scheduler, ("a" if use_async else "") + method)(old.id)
        assert json.loads(asyncio.run(result) if use_async else result)["error_type"] == "target_internal"
    assert json.loads(scheduler.disable_schedule(old.id))["status"] == "disabled"
    assert json.loads(scheduler.delete_schedule(old.id))["status"] == "deleted"


@pytest.mark.parametrize(
    "target",
    [
        f"/agents/{OPERATOR_ID}/runs",
        "/agents/%70latform-manager-internal/runs?source=schedule",
        f"/agents/public/../{OPERATOR_ID}/runs",
        f"/agents/{OPERATOR_ID}/runs/old/continue",
    ],
)
def test_unmanaged_specialist_schedules_can_be_retargeted(db, target):
    from agno.tools.scheduler import SchedulerTools

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    client = TestClient(os.get_app())
    data = {"name": "job", "cron_expr": "0 0 * * *", "endpoint": target, "payload": {"message": "hi"}}
    assert client.post("/schedules", json=data).status_code == 409
    old = SchedulerTools(db=db).manager.create(name="old", cron="0 0 * * *", endpoint=target)
    path = f"/schedules/{old.id}"
    for suffix in ("enable", "trigger"):
        assert client.post(f"{path}/{suffix}").status_code == 409
    assert client.patch(path, json={"payload": {"message": "replacement"}}).status_code == 409
    assert client.post(f"{path}/disable").status_code == 200
    assert client.patch(path, json={"endpoint": f"/teams/{MANAGER_TEAM_ID}/runs"}).status_code == 200
    assert client.post(f"{path}/enable").status_code == 200
    assert client.delete(path).status_code == 204


@pytest.mark.asyncio
async def test_managed_specialist_schedule_requires_replacement(db):
    from unittest.mock import AsyncMock, patch

    from agno.scheduler.executor import ScheduleExecutor
    from agno.tools.scheduler import SchedulerTools

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    client = TestClient(os.get_app())
    old = SchedulerTools(db=db).manager.create(
        name="legacy-managed",
        cron="0 0 * * *",
        endpoint=f"/agents/{OPERATOR_ID}/runs",
        provenance={"managed_by": "studio", "target_type": "agent", "target_id": OPERATOR_ID},
    )
    path = f"/schedules/{old.id}"
    assert client.post(f"{path}/disable").status_code == 200
    assert client.patch(path, json={"endpoint": f"/teams/{MANAGER_TEAM_ID}/runs"}).status_code == 200
    executor = ScheduleExecutor(base_url="http://localhost:9", internal_service_token="fixture")
    try:
        with patch.object(executor, "_call_endpoint", new=AsyncMock()) as call:
            result = await executor.execute(db.get_schedule(old.id), db, release_schedule=False)
        call.assert_not_awaited()
        assert result["status"] == "failed"
        assert "provenance target agent:" + OPERATOR_ID in result["error"]
        assert client.post(f"{path}/enable").status_code == 409
    finally:
        await executor.close()
    replacement = client.post(
        "/schedules",
        json={"name": "replacement", "cron_expr": "0 0 * * *", "endpoint": f"/teams/{MANAGER_TEAM_ID}/runs"},
    )
    assert replacement.status_code == 201, replacement.text
    assert client.delete(path).status_code == 204


@pytest.mark.parametrize("version", [None, 1])
def test_stored_composition_cannot_restore_manager_member(db, version):
    from agno.exceptions import ComponentRehydrationError
    from agno.team import Team
    from agno.workflow.step import Step

    registry = Registry(models=[OfflineModel()])
    _store_manager_test_component(db, "agent", OPERATOR_ID)
    links = [{"link_kind": "member", "child_component_id": OPERATOR_ID, "child_version": version}]
    with pytest.raises(ComponentRehydrationError):
        Team.from_dict(
            {"name": "stored", "members": [{"type": "agent", "agent_id": OPERATOR_ID}]},
            db=db,
            registry=registry,
            links=links,
            strict=True,
        )
    with pytest.raises(ComponentRehydrationError):
        Step.from_dict({"name": "stored-step", "agent_id": OPERATOR_ID}, db=db, registry=registry, strict=True)


@pytest.mark.asyncio
async def test_queue_cannot_replay_standalone_manager_members(db):
    from types import SimpleNamespace

    from agno.job_queue.config import QueueConfig
    from agno.job_queue.store import InMemoryQueueStore
    from agno.os.job_queue import get_active_queue_worker, queue_lifespan

    # A worker holding an old roster must still refuse a pre-existing direct job.
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    host = SimpleNamespace(
        db=db,
        registry=os.registry,
        agents=os.manager.members,
        teams=[],
        workflows=[],
        queue=QueueConfig(durable=True, db=InMemoryQueueStore()),
    )
    async with queue_lifespan(SimpleNamespace(state=SimpleNamespace()), host):
        worker = get_active_queue_worker()
        for component_id in (BUILDER_ID, OPERATOR_ID):
            for source in ("registry", "db", "factory"):
                assert (
                    await worker._aresolve_job_component(
                        {
                            "component_type": "agent",
                            "component_id": component_id,
                            "payload": {"scope": {"source": source, "version": 1}},
                        }
                    )
                    is None
                )


@pytest.mark.parametrize("stream", [False, True])
def test_manager_member_confirmation_continues_through_manager(db, stream):
    from agno.tools import tool

    calls = []

    @tool(requires_confirmation=True)
    def approved_action() -> str:
        """Execute the local fixture action."""
        calls.append(True)
        return "action complete"

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    member = manager_member(os, OPERATOR_ID)
    member.model = ManagerToolModel("approved_action", {})
    member.tools.append(approved_action)
    os.manager.model = ManagerToolModel(
        "delegate_task_to_member", {"member_id": OPERATOR_ID, "task": "Perform the action"}
    )
    client = TestClient(os.get_app())
    response = client.post(f"/teams/{MANAGER_TEAM_ID}/runs", data={"message": "act", "stream": str(stream).lower()})
    assert response.status_code == 200
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        data = next(event for event in events if event.get("event") == "TeamRunPaused")
    else:
        data = response.json()
        assert data["status"] == "PAUSED"
    assert calls == []
    requirements = data["requirements"]
    for req in requirements:
        req["confirmation"] = True
        req["tool_execution"]["confirmed"] = True
    assert (
        client.post(f"/agents/{OPERATOR_ID}/runs/{data['run_id']}/continue", data={"stream": "false"}).status_code
        == 422
    )
    resumed = client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs/{data['run_id']}/continue",
        data={"session_id": data["session_id"], "requirements": json.dumps(requirements), "stream": "false"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "COMPLETED"
    assert calls == [True]
    history = client.get(f"/sessions/{data['session_id']}/runs").json()
    assert any(run.get("agent_id") == OPERATOR_ID for run in history)


@pytest.mark.asyncio
async def test_team_detail_hides_only_framework_owned_members():
    from agno.os.routers.teams.schema import TeamResponse
    from agno.team import Team

    member = Agent(id=OPERATOR_ID, model=OfflineModel())
    team = Team(id="ordinary", members=[member], model=OfflineModel())
    assert (await TeamResponse.from_team(team)).members
    member._registry_excluded = True
    assert not (await TeamResponse.from_team(team)).members


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
@pytest.mark.parametrize("deployment", ["manager", "catalog", "no_db", "async_db", "base_app"])
def test_reserved_ids_have_clear_rest_errors(db, tmp_path, kind, deployment):
    from fastapi import FastAPI

    from agno.registry._reserved import RESERVED_MANAGER_IDS

    os_db = None if deployment == "no_db" else db
    if deployment == "async_db":
        os_db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))
    os = AgentOS(
        agents=[Agent(id="ordinary", model=OfflineModel())],
        db=os_db,
        manager=OSManager(model=OfflineModel(), access_docs=False) if deployment == "manager" else False,
        base_app=FastAPI() if deployment == "base_app" else None,
        telemetry=False,
    )
    client = TestClient(os.get_app())
    os.resync(os.get_app())
    for component_id in RESERVED_MANAGER_IDS:
        if deployment == "catalog":
            _store_manager_test_component(db, kind, component_id)
        if kind == "team" and component_id == MANAGER_TEAM_ID and deployment == "manager":
            assert client.get(f"/teams/{component_id}").status_code == 200
            continue
        path = f"/{kind}s/{component_id}"
        # Detail, start, continuation and run management use different exception boundaries.
        responses = [
            client.get(path),
            client.get(f"{path}/runs/missing", params={"session_id": "missing"}),
            client.post(f"{path}/runs/missing/cancel"),
            client.post(f"{path}/runs", data={"message": "run", "stream": "false"}),
            client.post(f"{path}/runs", data={"message": "run", "stream": "true"}),
        ]
        if kind != "workflow":
            responses.append(client.post(f"{path}/runs/missing/continue", data={"stream": "false"}))
        for response in responses:
            assert response.status_code == 422, response.text
            assert response.json()["detail"] == (
                f"Component ID '{component_id}' is reserved. Please choose a different ID for your component."
            )
    assert client.get(f"/{kind}s/missing").status_code == 404
    assert client.post("/agents/ordinary/runs", data={"message": "Hi", "stream": "false"}).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
@pytest.mark.parametrize("database", ["sync", "async", "none"])
async def test_reserved_errors_match_sync_and_async_os_lookup(db, tmp_path, kind, database):
    from agno.os import utils
    from agno.registry._reserved import RESERVED_MANAGER_IDS

    os_db = None if database == "none" else db
    if database == "async":
        os_db = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))
    for component_id in RESERVED_MANAGER_IDS:
        with pytest.raises(AgnoHTTPException) as sync_error:
            getattr(utils, f"get_{kind}_by_id")(component_id, db=os_db)
        with pytest.raises(AgnoHTTPException) as async_error:
            await getattr(utils, f"get_{kind}_by_id_async")(component_id, db=os_db)
        assert sync_error.value.status_code == async_error.value.status_code == 422
        assert sync_error.value.detail == async_error.value.detail
    assert getattr(utils, f"get_{kind}_by_id")("missing", db=os_db) is None
    assert await getattr(utils, f"get_{kind}_by_id_async")("missing", db=os_db) is None
