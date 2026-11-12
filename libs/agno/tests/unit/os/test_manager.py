"""Only the manager team is public; its private members never enter the build palette."""

import asyncio
import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
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
from agno.registry._reserved import (
    BUILDER_ID,
    FORMER_MANAGER_IDS,
    LEGACY_PRODUCT_MANAGER_ID,
    MANAGER_TEAM_ID,
    MINI_AGENT_ID,
    _reserved_manager_id_message,
)
from agno.run import RunContext
from agno.tools.agentos import AgentOSTools
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

# A reserved specialist id that no served component uses.
FORMER_SPECIALIST_ID = "platform-manager-internal"


def test_routines_run_on_mini_agent_and_no_other_framework_agent(db):
    from agno.company.routines import _routine_executor_endpoint
    from agno.os import CompanyConfig

    os = AgentOS(
        db=db,
        manager=OSManager(model=OfflineModel(), access_docs=False),
        company=CompanyConfig(model=OfflineModel()),
        telemetry=False,
    )
    assert (
        _routine_executor_endpoint("agent", MINI_AGENT_ID, os.registry, agent_os=os) == f"/agents/{MINI_AGENT_ID}/runs"
    )
    for kind, target in [
        ("team", MANAGER_TEAM_ID),
        ("agent", BUILDER_ID),
        ("team", "os-manager-internal"),
        ("agent", "company-manager-internal"),
        ("agent", "platform-builder-internal"),
        ("agent", "platform-manager-internal"),
    ]:
        with pytest.raises(ValueError, match="only Mini Agent runs Routines"):
            _routine_executor_endpoint(kind, target, os.registry, agent_os=os)


@pytest.mark.parametrize("identity", ["jwt", "managed_role", "service_account", "service_account_open"])
@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("target", [MANAGER_TEAM_ID, BUILDER_ID])
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
            "scopes": ["teams:superagent:run"],
            "exp": int(time.time()) + 300,
        },
        secret,
        algorithm="HS256",
    )
    client = TestClient(os.get_app())
    headers = {"Authorization": f"Bearer {token}"}
    denied = client.post("/agents/restricted/runs", headers=headers, data={"message": "test", "stream": "false"})
    assert denied.status_code == 403
    response = client.post("/teams/superagent/runs", headers=headers, data={"message": "test", "stream": "false"})
    assert response.status_code == 200, response.text
    assert "Permission required: agents:restricted:run" in response.text
    assert model.calls > 0
    assert all(getattr(session, "agent_id", None) != "restricted" for session in db.get_sessions())


@pytest.mark.parametrize("subclass", [False, True])
def test_slack_serving_the_manager_requires_identity_mapping_under_authorization(db, subclass):
    pytest.importorskip("slack_bolt")
    from agno.os import Authorization
    from agno.os.interfaces.slack import Slack

    class CustomSlack(Slack):
        pass

    interface_class = CustomSlack if subclass else Slack

    secret = "manager-test-signing-key-at-least-32-characters"
    os = AgentOS(
        id="manager-test",
        db=db,
        telemetry=False,
        authorization=Authorization(verification_keys=[secret], algorithm="HS256", audience="manager-test"),
        manager=OSManager(model=OfflineModel()),
    )
    # Without users=, every member of the workspace would run Super Agent with no permission checks
    os.interfaces.append(interface_class(team=os.manager, token="xoxb-test", signing_secret="slack-secret"))
    with pytest.raises(ValueError, match="requires Slack identity mapping"):
        os.get_app()


def test_slack_serving_the_manager_requires_identity_mapping_under_a_base_app_jwt_middleware(db):
    pytest.importorskip("slack_bolt")
    from fastapi import FastAPI

    from agno.os.interfaces.slack import Slack
    from agno.os.middleware.jwt import JWTMiddleware

    secret = "manager-test-signing-key-at-least-32-characters"
    base_app = FastAPI()
    base_app.add_middleware(JWTMiddleware, verification_keys=[secret], algorithm="HS256", authorization=True)
    os = AgentOS(id="manager-test", db=db, telemetry=False, base_app=base_app, manager=OSManager(model=OfflineModel()))
    # The middleware on the base_app checks roles though AgentOS(authorization=...) is unset
    os.interfaces.append(Slack(team=os.manager, token="xoxb-test", signing_secret="slack-secret"))
    with pytest.raises(ValueError, match="requires Slack identity mapping"):
        os.get_app()


@pytest.mark.asyncio
async def test_slack_interfaces_sharing_a_bot_token_post_task_results_once_per_identity_setup(db):
    pytest.importorskip("slack_bolt")
    from agno.os.interfaces.slack import Slack
    from agno.os.interfaces.slack.company import CompanyBridge

    os = AgentOS(id="manager-test", db=db, telemetry=False, manager=OSManager(model=OfflineModel()))
    first = Slack(team=os.manager, token="xoxb-test", signing_secret="slack-secret")
    second = Slack(team=os.manager, token="xoxb-test", signing_secret="slack-secret", prefix="/slack2")
    other_bot = Slack(team=os.manager, token="xoxb-other", signing_secret="slack-secret", prefix="/slack3")
    os.interfaces.extend([first, second, other_bot])
    os.get_app()
    # Every interface keeps the Company bridge that authorizes Super Agent runs
    assert all(isinstance(interface.company, CompanyBridge) for interface in (first, second, other_bot))
    for interface in (first, second, other_bot):
        await interface.astart()
    try:
        assert first._task_delivery is not None and other_bot._task_delivery is not None
        assert second._task_delivery is None
    finally:
        for interface in (first, second, other_bot):
            await interface.aclose()

    # An interface added before get_app runs again joins a token that already delivers
    late = Slack(team=os.manager, token="xoxb-test", signing_secret="slack-secret", prefix="/slack4")
    os.interfaces.insert(0, late)
    os.get_app()
    assert isinstance(late.company, CompanyBridge) and not late.company.deliver
    assert [interface.company.deliver for interface in (first, second, other_bot)] == [True, False, True]

    # Interfaces sharing a token with different users= maps own different Tasks, so each posts its own
    mapped = Slack(
        team=os.manager, token="xoxb-test", signing_secret="slack-secret", prefix="/slack5", users={"U1": "a"}
    )
    remapped = Slack(
        team=os.manager, token="xoxb-test", signing_secret="slack-secret", prefix="/slack6", users={"U1": "b"}
    )
    # The same users= map with resolve_user_identity on also owns different Tasks
    resolved = Slack(
        team=os.manager,
        token="xoxb-test",
        signing_secret="slack-secret",
        prefix="/slack7",
        users={"U1": "a"},
        resolve_user_identity=True,
    )
    os.interfaces.extend([mapped, remapped, resolved])
    os.get_app()
    assert mapped.company.deliver and remapped.company.deliver and resolved.company.deliver


@pytest.mark.parametrize("service_account", [False, True])
@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("path", ["/teams/superagent/runs", "/agents/platform-builder/runs"])
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
    # Source access does not change the one-member composition.
    assert os.agents == []
    assert [a.id for a in os.manager.members] == [BUILDER_ID]
    assert [t.id for t in os.teams] == [MANAGER_TEAM_ID]
    assert os.manager is not None and os.manager.name == MANAGER_TEAM_NAME == "Super Agent"
    assert os.manager.id == MANAGER_TEAM_ID == "superagent"
    assert os.manager.model is model and manager_member(os, BUILDER_ID).model is model
    assert not any("read_file" in getattr(t, "functions", {}) for t in os.manager.tools)

    os = AgentOS(db=db, manager=OSManager(model=model, root=workspace), telemetry=False)
    assert os.agents == []
    assert [a.id for a in os.manager.members] == [BUILDER_ID]
    assert any("read_file" in getattr(t, "functions", {}) for t in os.manager.tools)


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


@pytest.mark.parametrize("company_enabled", [False, True])
@pytest.mark.parametrize("with_root", [False, True])
@pytest.mark.parametrize("access_docs", [False, True])
def test_builder_and_lead_carry_the_framework_toolkits(db, workspace, company_enabled, with_root, access_docs):
    from agno.os import CompanyConfig
    from agno.tools.company import CompanyTools
    from agno.tools.mcp import MCPTools

    def attached() -> str:
        """Application tool."""
        return "x"

    os = AgentOS(
        db=db,
        manager=OSManager(
            model=OfflineModel(),
            tools=[attached],
            root=workspace if with_root else None,
            access_docs=access_docs,
        ),
        company=CompanyConfig(model=OfflineModel()) if company_enabled else None,
        telemetry=False,
    )
    assert [member.id for member in os.manager.members] == [BUILDER_ID]
    builder = manager_member(os, BUILDER_ID)
    assert [type(t) for t in builder.tools] == [StudioTools]
    studio = builder.tools[0]
    assert studio.registry is os.registry and studio.db is db
    assert set(studio.requires_confirmation_tools) >= {"archive_component", "delete_version", "delete_schedule"}

    # The lead holds the platform tools itself, in this order.
    tools = list(os.manager.tools)
    assert tools[0] is attached
    runner, agentos, diagnostics, *rest = tools[1:]
    assert isinstance(runner, StudioRunnerTools)
    assert runner.include_all_components and runner.self_dispatch == "once"
    assert set(runner.functions) == {
        "list_agents",
        "run_agent",
        "list_teams",
        "run_team",
        "list_workflows",
        "run_workflow",
    }
    assert isinstance(agentos, AgentOSTools) and set(agentos.functions) == {"get_run_activity", "list_schedules"}
    assert diagnostics.name == "manager_diagnostics" and set(diagnostics.functions) == {"run_diagnostics"}
    if access_docs:
        docs = rest.pop(0)
        assert isinstance(docs, MCPTools) and docs.url == "https://docs.agno.com/mcp"
    if with_root:
        workspace_tools = rest.pop(0)
        assert set(workspace_tools.functions) == {"list_files", "read_file", "search_content"}
    if company_enabled:
        company = rest.pop(0)
        assert isinstance(company, CompanyTools)
        assert "create_company_product" in company.functions
        assert not {"summarize_company_product", "refresh_company_product"} & set(company.functions)
        task_runs = rest.pop(0)
        assert set(task_runs.functions) == {
            "start_company_task",
            "get_company_task_status",
            "approve_company_project",
            "accept_company_task",
            "review_company_task",
            "turn_on_routine_auto_accept",
            "turn_off_routine_auto_accept",
        }
        assert not {"list_company_wiki", "read_company_wiki", "update_product_status"} & set(company.functions)
    # notes/ comes with Super Agent. The wiki, Products and Tasks join the tree with Company.
    files = rest.pop(0)
    assert files.name == "company_files"
    assert set(files.functions) == {
        "list_company_files",
        "read_company_file",
        "search_company_files",
        "write_company_file",
        "delete_company_file",
    } | ({"save_company_page"} if company_enabled else set())
    assert rest == []

    names = set()
    for tool in tools:
        names |= set(getattr(tool, "functions", {})) if hasattr(tool, "functions") else {tool.__name__}
    assert not names & {
        "get_platform_metrics",
        "get_tool_activity",
        "get_eval_history",
        "get_schedule_history",
        "list_platform_components",
        "list_pending_approvals",
    }


def test_manager_reads_the_workspace_but_not_env_files(db, workspace):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=workspace), telemetry=False)
    tool = next(t for t in os.manager.tools if "read_file" in getattr(t, "functions", {}))
    tools = tool.functions
    assert {"list_files", "read_file"} <= tools.keys()
    assert "print" in tools["read_file"].entrypoint(path="main.py")
    assert "secret" not in tools["read_file"].entrypoint(path=".env")


def test_manifest_defaults_yield_to_the_application_config(db):
    config = AgentOSConfig(
        manifest={
            MANAGER_TEAM_ID: Manifest(description="Our lead", quick_prompts=["Hi"]),
            BUILDER_ID: Manifest(description="Old builder card"),
            FORMER_SPECIALIST_ID: Manifest(description="Old operator card"),
        }
    )
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()), config=config, telemetry=False)
    assert os.config.manifest[MANAGER_TEAM_ID].description == "Our lead"
    assert BUILDER_ID not in os.config.manifest and FORMER_SPECIALIST_ID not in os.config.manifest
    assert "platform-engineer" not in os.config.manifest


@pytest.mark.parametrize("use_async", [False, True])
def test_manager_discovery_uses_manifest_without_changing_agent_prompts(db, tmp_path, use_async):
    from agno.os import CompanyConfig

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "manifest:\n"
        "  daily-brief:\n    description: Daily news and when it matters.\n"
        "  claude-engineer:\n    description: Review code with Claude.\n"
        "  codex-engineer:\n    description: Investigate bugs with Codex.\n"
        "  explicit:\n    description: UI description.\n"
        "  manifest-only:\n    description: This must not create a runnable agent.\n"
    )
    daily_brief = Agent(id="daily-brief", model=OfflineModel())
    claude = ClaudeAgent(id="claude-engineer")
    codex = CodexAgent(id="codex-engineer")
    explicit = Agent(id="explicit", model=OfflineModel(), description="Agent description.")
    undescribed = Agent(id="undescribed", model=OfflineModel())
    os = AgentOS(
        db=db,
        agents=[daily_brief, claude, codex, explicit, undescribed],
        manager=OSManager(model=OfflineModel()),
        company=CompanyConfig(model=OfflineModel()),
        config=str(config_file),
        telemetry=False,
    )
    # Runs copy the manager; late-created Company metadata must remain visible there.
    runner = next(t for t in os.manager.deep_copy().tools if isinstance(t, StudioRunnerTools))

    def descriptions():
        payload = asyncio.run(runner.alist_agents()) if use_async else runner.list_agents()
        return {row["id"]: row["description"] for row in json.loads(payload)["agents"]}

    assert descriptions() == {
        "daily-brief": "Daily news and when it matters.",
        "claude-engineer": "Review code with Claude.",
        "codex-engineer": "Investigate bugs with Codex.",
        "explicit": "Agent description.",
        "undescribed": None,
    }
    assert daily_brief.description is claude.description is codex.description is None
    assert os._mini_agent.description is None
    assert explicit.description == "Agent description."
    os.config = AgentOSConfig(manifest={"daily-brief": Manifest(description="Updated description.")})
    assert descriptions()["daily-brief"] == "Updated description."
    assert descriptions()["claude-engineer"] is None
    os.config = None
    assert descriptions()["daily-brief"] is None


@pytest.mark.parametrize("use_async", [False, True])
def test_manager_discovery_describes_teams_workflows_and_default_managers(db, use_async):
    from agno.os import CompanyConfig
    from agno.team import Team
    from agno.workflow import Workflow

    team = Team(id="research", members=[], model=OfflineModel())
    workflow = Workflow(id="digest", steps=[])
    os = AgentOS(
        db=db,
        teams=[team],
        workflows=[workflow],
        manager=OSManager(model=OfflineModel()),
        company=CompanyConfig(model=OfflineModel()),
        config=AgentOSConfig(
            manifest={"research": Manifest(description="Research team."), "digest": Manifest(description="Digest.")}
        ),
        telemetry=False,
    )
    runner = next(t for t in os.manager.deep_copy().tools if isinstance(t, StudioRunnerTools))
    agents = json.loads(asyncio.run(runner.alist_agents()) if use_async else runner.list_agents())["agents"]
    teams = json.loads(asyncio.run(runner.alist_teams()) if use_async else runner.list_teams())["teams"]
    workflows = json.loads(asyncio.run(runner.alist_workflows()) if use_async else runner.list_workflows())["workflows"]
    # Mini Agent is served for the scheduler only and is never offered as a run target.
    assert agents == []
    assert {row["id"]: row["description"] for row in teams} == {
        "research": "Research team.",
        MANAGER_TEAM_ID: os.config.manifest[MANAGER_TEAM_ID].description,
    }
    assert workflows[0]["description"] == "Digest."
    assert team.description is workflow.description is os.manager.description is None


@pytest.mark.parametrize("with_manager", [False, True])
def test_company_chat_card_belongs_to_super_agent_only(db, with_manager):
    from agno.os import CompanyConfig

    manager = OSManager(model=OfflineModel()) if with_manager else None
    os = AgentOS(db=db, manager=manager, company=CompanyConfig(model=OfflineModel()), telemetry=False)
    config = TestClient(os.get_app()).get("/config").json()
    manifest = config.get("manifest") or {}
    assert MINI_AGENT_ID not in manifest and "company-manager" not in manifest
    assert MINI_AGENT_ID not in {agent["id"] for agent in config["agents"]}
    assert bool(manifest.get(MANAGER_TEAM_ID, {}).get("quick_prompts")) is with_manager

    custom = AgentOSConfig(manifest={MANAGER_TEAM_ID: Manifest(quick_prompts=["Ours"])})
    os = AgentOS(db=db, manager=manager, company=CompanyConfig(model=OfflineModel()), config=custom, telemetry=False)
    assert os.config.manifest[MANAGER_TEAM_ID].quick_prompts == ["Ours"]


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
    member = client.post(f"/agents/{BUILDER_ID}/runs", data={"message": "status", "stream": "false"})
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
        id="wrapper", name="Wrapper", model=OfflineModel(), members=[manager_member(os, BUILDER_ID).deep_copy()]
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
def test_manager_normalizes_workspace_and_confines_all_read_tools(db, workspace, tmp_path, provider_kind):
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
    tool = next(t for t in os.manager.tools if "read_file" in getattr(t, "functions", {}))
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
def test_manager_refuses_workspace_exclusion_overrides(db, workspace, kwargs):
    from agno.context.workspace import WorkspaceContextProvider

    with pytest.raises(ValueError, match="cannot override exclusions"):
        AgentOS(
            db=db,
            manager=OSManager(model=OfflineModel(), root=WorkspaceContextProvider(root=workspace, **kwargs)),
            telemetry=False,
        )


def test_manager_rejects_an_arbitrary_tool_provider(db):
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
def test_manager_executes_diagnostics_in_both_run_modes(db, use_async):
    model = ToolCallingModel("run_diagnostics", {})
    os = AgentOS(db=db, manager=OSManager(model=model), telemetry=False)
    result = asyncio.run(os.manager.arun("Diagnose")) if use_async else os.manager.run("Diagnose")
    report = json.loads(result.content)
    assert next(c for c in report["checks"] if c["name"] == "database")["status"] == "PASS"
    assert model.calls == 2


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("target_id", [MANAGER_TEAM_ID])
def test_manager_self_dispatch_terminates_after_one_nested_run(db, use_async, target_id):
    model = ToolCallingModel("run_team", {"team_id": target_id, "message": "Fresh context"})
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
    kwargs["agent_id"] = BUILDER_ID
    result = asyncio.run(runner.arun_agent(**kwargs)) if use_async else runner.run_agent(**kwargs)
    assert "error" in json.loads(result)


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("agent_class", [ClaudeAgent, CodexAgent])
def test_manager_discovers_and_runs_external_agents(db, monkeypatch, agent_class, use_async):
    from agno.os.authz.provider import AuthorizationContext
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider
    from agno.run.authorization import RunAuthorization

    calls = []

    async def adapter(self, message, **kwargs):
        calls.append((self, message, kwargs))
        return f"done: {message}"

    monkeypatch.setattr(agent_class, "_arun_adapter", adapter)
    claude = ClaudeAgent(id="claude-engineer", name="Claude Engineer")
    codex = CodexAgent(id="codex-engineer", name="Codex Engineer")
    agent = claude if agent_class is ClaudeAgent else codex
    os = AgentOS(db=db, agents=[claude, codex], manager=OSManager(model=OfflineModel()), telemetry=False)
    runner = next(t for t in os.manager.deep_copy().tools if isinstance(t, StudioRunnerTools))
    listing = json.loads(asyncio.run(runner.alist_agents()) if use_async else runner.list_agents())
    assert {row["id"] for row in listing["agents"]} == {"claude-engineer", "codex-engineer"}
    assert runner._iter_agents() == []  # External adapters are not Studio build/edit targets.
    assert runner._find_agent(agent.id) is None
    context = RunContext(run_id="manager-run", session_id="conversation", user_id="alice")

    def run(reference, message, caller=context):
        kwargs = dict(agent_id=reference, message=message, _agno_run_context=caller, _agno_team=os.manager)
        return json.loads(asyncio.run(runner.arun_agent(**kwargs)) if use_async else runner.run_agent(**kwargs))

    first = run(agent.id, "first")
    second = run(agent.name, "follow-up")
    other = run(agent.id, "other user", RunContext(run_id="bob-run", session_id="conversation", user_id="bob"))
    assert first["content"] == "done: first"
    assert second["content"] == "done: follow-up"
    assert other["content"] == "done: other user"
    assert first["status"] == second["status"] == other["status"] == "COMPLETED"
    assert first["session_id"] == second["session_id"] != context.session_id
    assert other["session_id"] != first["session_id"]
    assert all(call[0] is agent for call in calls)
    assert calls[1][2]["history"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "done: first"},
    ]
    assert not calls[2][2]["history"]
    assert calls[0][2]["metadata"]["agno_dispatch_chain"] == [f"team:{MANAGER_TEAM_ID}", f"agent:{agent.id}"]
    assert calls[0][2]["metadata"]["agno_dispatch_depth"] == 1
    saved = db.get_runs(session_id=first["session_id"])
    assert {row.run_id for row in saved} == {first["run_id"], second["run_id"]}
    assert all(row.user_id == "alice" for row in saved)
    # The adapter's original admission guard must still prevent overlapping turns.
    agent._sessions_in_flight[first["session_id"]] = "active-run"
    try:
        refused = run(agent.id, "overlap")
        assert "already has run active-run in flight" in refused["error"]
        assert len(calls) == 3
    finally:
        agent._sessions_in_flight.clear()
    context.authorization = RunAuthorization(
        provider=ScopeAuthorizationProvider(),
        context=AuthorizationContext(principal_id="alice", scopes=["teams:superagent:run"]),
    )
    hidden = json.loads(asyncio.run(runner.alist_agents(context)) if use_async else runner.list_agents(context))
    assert hidden["agents"] == []
    with pytest.raises(PermissionError, match=f"agents:{agent.id}:run"):
        run(agent.id, "denied")
    assert len(calls) == 3
    context.authorization = None
    # The live allowlist must follow replacement, including on a copied manager.
    os.agents = []
    assert "error" in run(agent.id, "removed")
    assert len(calls) == 3


@pytest.mark.parametrize("use_async", [False, True])
def test_registry_runners_do_not_dispatch_external_agents(db, monkeypatch, use_async):
    calls = []

    async def adapter(self, message, **kwargs):
        calls.append(message)
        return f"done: {message}"

    monkeypatch.setattr(ClaudeAgent, "_arun_adapter", adapter)
    claude = ClaudeAgent(id="claude-engineer", name="Claude Engineer")
    os = AgentOS(db=db, agents=[claude], manager=OSManager(model=OfflineModel()), telemetry=False)
    assert claude in os.registry.agents
    builder_studio = next(t for t in manager_member(os, BUILDER_ID).tools if isinstance(t, StudioTools))
    registry_runner = StudioRunnerTools(registry=os.registry, db=db, include_all_components=True)
    context = RunContext(run_id="run", session_id="conversation", user_id="alice")
    for tools in (builder_studio, registry_runner):
        if use_async:
            result = asyncio.run(tools.arun_agent(claude.id, "hi", _agno_run_context=context))
        else:
            result = tools.run_agent(claude.id, "hi", _agno_run_context=context)
        assert json.loads(result)["error"] == f"Agent not found: {claude.id}"
    listing = asyncio.run(registry_runner.alist_agents(context)) if use_async else registry_runner.list_agents(context)
    assert json.loads(listing)["agents"] == []
    assert calls == []


@pytest.mark.parametrize("component_id", [BUILDER_ID, FORMER_SPECIALIST_ID, MANAGER_TEAM_ID])
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
    os.agents.append(Agent(id=FORMER_SPECIALIST_ID, model=OfflineModel()))
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
        registry=foreign, db=db, include_agents=agents, include_teams=[team], allowed_tools=[BUILDER_ID]
    )
    assert foreign.agents == [] and foreign.teams == []
    result = json.loads(
        studio.create_team(name="Wrapper", instructions="Read", member_ids=["Platform Builder"], publish=True)
    )
    assert result["error"]["code"] == "component_not_found"


@pytest.mark.parametrize("component_id", [BUILDER_ID, FORMER_SPECIALIST_ID, MANAGER_TEAM_ID])
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
    assert os.registry.excluded_component_ids == {
        MANAGER_TEAM_ID,
        BUILDER_ID,
        MINI_AGENT_ID,
        LEGACY_PRODUCT_MANAGER_ID,
        *FORMER_MANAGER_IDS,
    }


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
        {
            "reserved-id",
            MANAGER_TEAM_ID,
            BUILDER_ID,
            MINI_AGENT_ID,
            LEGACY_PRODUCT_MANAGER_ID,
            *FORMER_MANAGER_IDS,
        }
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
@pytest.mark.parametrize("target", ["delegation", MANAGER_TEAM_ID, BUILDER_ID])
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

    if target == "delegation":
        owner = os.manager
        member = manager_member(os, BUILDER_ID)
        member.model = ManagerAnswerModel(payload)
        owner.model = ManagerToolModel(
            "delegate_task_to_member", {"member_id": BUILDER_ID, "task": "Return the report"}
        )
    else:
        owner = os.manager if target == MANAGER_TEAM_ID else manager_member(os, target)

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
    if target == "delegation":
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
@pytest.mark.parametrize("component_id", [MANAGER_TEAM_ID, MINI_AGENT_ID, BUILDER_ID, FORMER_SPECIALIST_ID])
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


@pytest.mark.parametrize("component_id", [MANAGER_TEAM_ID, MINI_AGENT_ID, BUILDER_ID, FORMER_SPECIALIST_ID])
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
        assert [member["id"] for member in team["members"]] == [BUILDER_ID]
        rows.extend(team["members"])
        assert [agent["id"] for agent in config["agents"]] == ["ordinary"]
        assert [agent["id"] for agent in client.get("/agents").json()] == ["ordinary"]
        assert BUILDER_ID not in config["manifest"]
        for row in rows:
            if row["id"] == "ordinary":
                assert row.get("metadata") in (None, ordinary_metadata)
            else:
                assert row["metadata"]["_agno"] == {"internal": True, "id": row["id"]}
                assert "is_manager" not in row
        assert [member.id for member in os.manager.members] == [BUILDER_ID]
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
    docs = [tool for tool in os.manager.tools if isinstance(tool, MCPTools)]
    assert len(docs) == int(enabled)
    assert not any(isinstance(tool, MCPTools) for tool in manager_member(os, BUILDER_ID).tools)
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


@pytest.mark.parametrize("async_mode", [False, True])
def test_manager_can_answer_framework_question_using_docs_without_delegation(db, monkeypatch, async_mode):
    from agno.tools.function import Function
    from agno.tools.mcp import MCPTools

    queries = []

    def search_docs(query: str) -> str:
        queries.append(query)
        return "Agentic learning saves and recalls user context through tools."

    async def connect(tool, force=False):
        tool.functions["search_docs"] = Function(name="search_docs", entrypoint=search_docs)
        tool._initialized = True

    monkeypatch.setattr(MCPTools, "connect", connect)
    model = ManagerToolModel("search_docs", {"query": "How does learning work?"})
    os = AgentOS(db=db, manager=OSManager(model=model), telemetry=False)
    # The fake model selects a docs call; this verifies the execution path and
    # persistence, not a real model's ability to choose the narrower route.
    with TestClient(os.get_app()):
        manager = os.manager.deep_copy()
        run = (
            asyncio.run(manager.arun("How does learning work?"))
            if async_mode
            else manager.run("How does learning work?")
        )
    assert queries == ["How does learning work?"]
    assert [tool.tool_name for tool in run.tools] == ["search_docs"]
    assert not run.member_responses
    assert model.calls == 2


@pytest.mark.parametrize("custom_provider", [False, True])
def test_manager_can_inspect_requested_tmp_artifacts(db, workspace, custom_provider):
    from agno.context.workspace import WorkspaceContextProvider

    (workspace / "tmp").mkdir()
    (workspace / "tmp" / "evidence.json").write_text('{"learning": "irrelevant run dump"}')
    (workspace / "learning.py").write_text("learning = True")
    root = WorkspaceContextProvider(root=workspace, exclude_patterns=[]) if custom_provider else workspace
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=root), telemetry=False)
    tool = next(t for t in os.manager.tools if "search_content" in getattr(t, "functions", {}))
    result = json.loads(tool.search_content("learning"))
    assert result["matches_found"] == 2
    assert {file["file"] for file in result["files"]} == {"learning.py", "tmp/evidence.json"}
    assert "evidence.json" in tool.list_files(recursive=True)
    assert "irrelevant run dump" in tool.read_file("tmp/evidence.json")


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("location", ["registry", "nested"])
def test_reserved_ids_rejected_on_resync_before_mirror_filtering(db, enabled, location):
    from agno.team import Team

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel()) if enabled else None, telemetry=False)
    app = os.get_app()
    imposter = Agent(id=FORMER_SPECIALIST_ID, model=OfflineModel())
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
    manager = os.manager
    with TestClient(os.get_app()) as client:
        # Startup succeeds even after a partially established connection fails.
        assert attempts == ["https://docs.agno.com/mcp"]
        assert not docs.initialized and docs.session is None
        assert docs._session_context is None
        assert asyncio.run(manager.arun("Hi")).content == "local answer"
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
        assert any(isinstance(tool, AgentOSTools) for tool in manager.tools)

        # A later async run reconnects without restarting AgentOS.
        available = True
        asyncio.run(manager.arun("Hi"))
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
    builder = manager_member(os, BUILDER_ID)
    builder.model = ManagerToolModel("list_models", {})
    os.manager.model = ManagerToolModel(
        "delegate_task_to_member", {"member_id": BUILDER_ID, "task": "Report the available models"}
    )

    def model_ids(result):
        return [model["id"] for model in json.loads(result)["data"]["models"]]

    client = TestClient(os.get_app())
    response = client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        data={"message": "Report models", "session_id": "reports", "stream": str(stream).lower()},
    )
    assert response.status_code == 200, response.text
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        reports = [
            event["tool"]["result"]
            for event in events
            if event.get("agent_id") == BUILDER_ID
            and event.get("event") == "ToolCallCompleted"
            and event.get("tool", {}).get("tool_name") == "list_models"
        ]
        assert reports and model_ids(reports[0]) == ["fixture"]
    else:
        assert response.json()["content"] == "local answer"
    # Persisted child runs remain available inside the manager's session for replay/diagnostics.
    from agno.db.base import SessionType

    session = db.get_session("reports", session_type=SessionType.TEAM)
    child = next(run for run in session.runs if getattr(run, "agent_id", None) == BUILDER_ID)
    assert child.agent_id == BUILDER_ID
    assert model_ids(child.tools[0].result) == ["fixture"]
    assert builder.store_events
    replay = client.get("/sessions/reports/runs")
    assert replay.status_code == 200, replay.text
    child_data = next(run for run in replay.json() if run.get("agent_id") == BUILDER_ID)
    assert model_ids(child_data["tools"][0]["result"]) == ["fixture"]


@pytest.mark.asyncio
@pytest.mark.parametrize("target_id", [MANAGER_TEAM_ID])
async def test_mcp_config_hides_specialists_but_manager_delegates(db, target_id):
    from fastmcp import Client

    from agno.os.mcp import build_mcp_server

    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    os.manager.model = ManagerToolModel("delegate_task_to_member", {"member_id": BUILDER_ID, "task": "Answer"})
    os.get_app()
    async with Client(build_mcp_server(os)) as client:
        config = await client.call_tool("get_agentos_config", {})
        text = " ".join(block.text for block in config.content if hasattr(block, "text"))
        assert MANAGER_TEAM_ID in text
        assert BUILDER_ID not in text and FORMER_SPECIALIST_ID not in text
        result = await client.call_tool("run_team", {"team_id": target_id, "message": "Answer"})
        assert not result.is_error
        for member_id in (BUILDER_ID, FORMER_SPECIALIST_ID):
            with pytest.raises(Exception, match=re.escape(_reserved_manager_id_message(member_id))):
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
    for component_id in (BUILDER_ID, FORMER_SPECIALIST_ID, "stored-ordinary"):
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
        assert BUILDER_ID not in text and FORMER_SPECIALIST_ID not in text


@pytest.mark.parametrize("member_id", [BUILDER_ID, "platform-builder-internal", FORMER_SPECIALIST_ID])
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
    for component_id in (BUILDER_ID, FORMER_SPECIALIST_ID):
        _store_manager_test_component(db, "agent", component_id, "Legacy " + component_id)
    _store_manager_test_component(db, "team", MANAGER_TEAM_ID)
    _store_manager_test_component(db, "agent", "ordinary")
    runner = (
        os.manager.tools[0] if enabled else StudioRunnerTools(db=db, registry=registry, include_all_components=True)
    )
    for component_id in (BUILDER_ID, FORMER_SPECIALIST_ID):
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
                assert str(exc.value) == _reserved_manager_id_message(component_id)
            assert loader(db=db, id="missing", registry=registry, strict=strict) is None
        assert db.get_component(component_id) is not None  # No implicit migration/deletion.
    _store_manager_test_component(db, kind, "ordinary")
    assert [c.id for c in getattr(module, f"get_{kind}s")(db=db, registry=registry)] == ["ordinary"]


@pytest.mark.parametrize("use_async", [False, True])
def test_scheduler_tools_refuse_legacy_manager_targets(db, use_async):
    from agno.tools.scheduler import SchedulerTools

    scheduler = SchedulerTools(db=db)
    args = dict(name="invalid", cron="0 0 * * *", endpoint=f"/agents/{FORMER_SPECIALIST_ID}/runs")
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
        f"/agents/{BUILDER_ID}/runs",
        "/agents/%70latform-manager-internal/runs?source=schedule",
        f"/agents/public/../{BUILDER_ID}/runs",
        f"/agents/{FORMER_SPECIALIST_ID}/runs/old/continue",
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
        endpoint=f"/agents/{FORMER_SPECIALIST_ID}/runs",
        provenance={"managed_by": "studio", "target_type": "agent", "target_id": FORMER_SPECIALIST_ID},
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
        assert "provenance target agent:" + FORMER_SPECIALIST_ID in result["error"]
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
    _store_manager_test_component(db, "agent", BUILDER_ID)
    links = [{"link_kind": "member", "child_component_id": BUILDER_ID, "child_version": version}]
    with pytest.raises(ComponentRehydrationError):
        Team.from_dict(
            {"name": "stored", "members": [{"type": "agent", "agent_id": BUILDER_ID}]},
            db=db,
            registry=registry,
            links=links,
            strict=True,
        )
    with pytest.raises(ComponentRehydrationError):
        Step.from_dict({"name": "stored-step", "agent_id": BUILDER_ID}, db=db, registry=registry, strict=True)


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
        for component_id in (BUILDER_ID, "platform-builder-internal", FORMER_SPECIALIST_ID):
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
@pytest.mark.parametrize("continue_id", [MANAGER_TEAM_ID])
def test_manager_member_confirmation_continues_through_manager(db, stream, continue_id):
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)
    _store_manager_test_component(db, "agent", "retired")
    member = manager_member(os, BUILDER_ID)
    member.model = ManagerToolModel("archive_component", {"component_id": "retired"})
    os.manager.model = ManagerToolModel(
        "delegate_task_to_member", {"member_id": BUILDER_ID, "task": "Archive the retired agent"}
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
    assert db.get_component("retired") is not None
    requirements = data["requirements"]
    assert [req["tool_execution"]["tool_name"] for req in requirements] == ["archive_component"]
    for req in requirements:
        req["confirmation"] = True
        req["tool_execution"]["confirmed"] = True
    assert (
        client.post(f"/agents/{BUILDER_ID}/runs/{data['run_id']}/continue", data={"stream": "false"}).status_code == 422
    )
    resumed = client.post(
        f"/teams/{continue_id}/runs/{data['run_id']}/continue",
        data={"session_id": data["session_id"], "requirements": json.dumps(requirements), "stream": "false"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "COMPLETED"
    assert db.get_component("retired") is None
    assert db.get_component("retired", include_deleted=True) is not None
    history = client.get(f"/sessions/{data['session_id']}/runs").json()
    assert any(run.get("agent_id") == BUILDER_ID for run in history)


@pytest.mark.parametrize("company_enabled", [False, True])
def test_manager_details_show_members_without_exposing_them_in_registry(db, company_enabled):
    from agno.company import CompanyConfig

    ordinary = Agent(id="ordinary", model=OfflineModel())
    registry = Registry(models=[OfflineModel()])
    os = AgentOS(
        db=db,
        agents=[ordinary],
        registry=registry,
        manager=OSManager(access_docs=False),
        company=CompanyConfig() if company_enabled else None,
        telemetry=False,
    )
    app = os.get_app()
    client = TestClient(app)
    # Mini Agent is not a member, with or without Company.
    expected_ids = [BUILDER_ID]
    expected_names = ["Platform Builder"]

    for resync in (False, True):
        if resync:
            os.resync(app)
        detail = client.get(f"/teams/{MANAGER_TEAM_ID}")
        assert detail.status_code == 200, detail.text
        listing = client.get("/teams")
        assert listing.status_code == 200, listing.text
        listed_manager = next(team for team in listing.json() if team["id"] == MANAGER_TEAM_ID)
        for team in (detail.json(), listed_manager):
            assert [member["id"] for member in team["members"]] == expected_ids
            assert [member["name"] for member in team["members"]] == expected_names

        assert [agent.id for agent in registry.agents] == ["ordinary"]
        assert registry.teams == []
        assert all(registry.is_component_excluded(member) for member in os.manager.members)
        # Mini Agent is served for the scheduler but never listed; Platform Builder is never served.
        assert [agent.id for agent in os.agents] == ["ordinary", *([MINI_AGENT_ID] if company_enabled else [])]
        assert [agent["id"] for agent in client.get("/agents").json()] == ["ordinary"]
        assert [agent["id"] for agent in client.get("/config").json()["agents"]] == ["ordinary"]
        assert client.get(f"/agents/{BUILDER_ID}").status_code == 422


@pytest.mark.parametrize("company_enabled", [False, True])
def test_manager_member_details_show_tools_without_instructions_or_source_root(db, workspace, company_enabled):
    from agno.company import CompanyConfig

    os = AgentOS(
        db=db,
        registry=Registry(models=[OfflineModel()]),
        manager=OSManager(root=workspace, access_docs=False),
        company=CompanyConfig() if company_enabled else None,
        telemetry=False,
    )
    client = TestClient(os.get_app())
    for path in ("/teams", f"/teams/{MANAGER_TEAM_ID}"):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert str(workspace) not in response.text
    members = client.get(f"/teams/{MANAGER_TEAM_ID}").json()["members"]
    assert [member["id"] for member in members] == [BUILDER_ID]
    for member in members:
        assert member["name"] and member["model"]
        assert member["metadata"]["_agno"] == {"internal": True, "id": member["id"]}
        assert member["tools"]["tools"]
        assert member.get("system_message") is None


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
            assert response.json()["detail"] == _reserved_manager_id_message(component_id)
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


@pytest.mark.parametrize("field", ["tool_call_limit", "member_tool_call_limit"])
@pytest.mark.parametrize("value", [-1, 1.5, True, "8"])
def test_manager_rejects_invalid_tool_limits(field, value):
    with pytest.raises(ValueError, match=field):
        OSManager(**{field: value})


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"tool_call_limit": 2, "member_tool_call_limit": 3},
        {"tool_call_limit": None, "member_tool_call_limit": None},
        {"tool_call_limit": 0, "member_tool_call_limit": 0},
    ],
)
def test_manager_limits_cover_the_lead_and_builder_without_changing_application_agents(db, limits):
    from agno.os import CompanyConfig

    config = OSManager(model=OfflineModel(), instructions="Application context", **limits)
    application_agent = Agent(id="application", model=OfflineModel())
    os = AgentOS(
        db=db, agents=[application_agent], manager=config, company=CompanyConfig(model=OfflineModel()), telemetry=False
    )
    assert os.manager.tool_call_limit == limits.get("tool_call_limit", 24)
    assert [member.id for member in os.manager.members] == [BUILDER_ID]
    assert all(member.tool_call_limit == limits.get("member_tool_call_limit", 24) for member in os.manager.members)
    assert application_agent.tool_call_limit is None
    assert "Application context" in os.manager.instructions()
    assert all(
        "Application context" not in (member.instructions() if callable(member.instructions) else member.instructions)
        for member in os.manager.members
    )
    os.resync(os.get_app())
    assert all(member.tool_call_limit == config.member_tool_call_limit for member in os.manager.members)
    assert application_agent.tool_call_limit is None


class BudgetProbeModel(OfflineModel):
    """Request more tools than allowed, then expose the refused call in the answer."""

    def __init__(self, tool_name, arguments, calls_per_turn=1, expected_instructions=None):
        from agno.os.manager.prompts import FOCUSED_EXECUTION_INSTRUCTIONS

        super().__init__()
        self.tool_name = tool_name
        self.arguments = arguments
        self.calls_per_turn = calls_per_turn
        # The call-limit guidance this role's system message must carry.
        self.expected_instructions = expected_instructions or FOCUSED_EXECUTION_INSTRUCTIONS
        self.calls = 0

    def invoke(self, messages, *args, **kwargs):
        system = "\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        assert self.expected_instructions in system
        self.calls += 1
        assert self.calls <= 5, "Budget refusal must reach the model"
        if any(m.role == "tool" and "Tool call limit reached" in str(m.content) for m in messages):
            return ModelResponse(
                content="Investigation limit reached; reporting verified evidence only.",
                role="assistant",
                response_usage=MessageMetrics(),
            )
        return ModelResponse(
            role="assistant",
            response_usage=MessageMetrics(),
            tool_calls=[
                {
                    "id": f"probe-{self.calls}-{i}",
                    "type": "function",
                    "function": {"name": self.tool_name, "arguments": json.dumps(self.arguments)},
                }
                for i in range(self.calls_per_turn)
            ],
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("calls_per_turn", [1, 4])
@pytest.mark.parametrize("target", [MANAGER_TEAM_ID, BUILDER_ID])
async def test_manager_executes_no_more_than_configured_limit(db, use_async, stream, calls_per_turn, target):
    from agno.os import CompanyConfig
    from agno.os.manager.prompts import FOCUSED_EXECUTION_INSTRUCTIONS, MANAGER_INSTRUCTIONS

    os = AgentOS(
        db=db,
        manager=OSManager(model=OfflineModel(), tool_call_limit=2, member_tool_call_limit=2),
        company=CompanyConfig(model=OfflineModel()),
        telemetry=False,
    )
    owner = os.manager if target == MANAGER_TEAM_ID else manager_member(os, target)
    calls = []

    def focused_lookup() -> str:
        """Look up the requested concept."""
        calls.append("lookup")
        return "Learning stores information for later retrieval; it does not retrain model weights."

    owner.tools.append(focused_lookup)
    expected = MANAGER_INSTRUCTIONS if target == MANAGER_TEAM_ID else FOCUSED_EXECUTION_INSTRUCTIONS
    owner.model = BudgetProbeModel("focused_lookup", {}, calls_per_turn, expected)
    # Reuse the same manager: limits must reset between user turns.
    for turn in range(2):
        owner.model.calls = 0
        kwargs = dict(session_id=f"budget-{turn}", user_id="alice", stream=stream)
        if use_async:
            if stream:
                result = [event async for event in owner.arun("How does learning work?", **kwargs)]
            else:
                result = await owner.arun("How does learning work?", **kwargs)
        elif stream:
            result = list(owner.run("How does learning work?", **kwargs))
        else:
            result = owner.run("How does learning work?", **kwargs)
        assert result
        assert len(calls) == 2 * (turn + 1)
        assert owner.model.calls == (4 if calls_per_turn == 1 else 2)


@pytest.mark.parametrize("use_async", [False, True])
async def test_manager_limits_apply_on_both_sides_of_delegation(db, use_async):
    from agno.os.manager.prompts import MANAGER_INSTRUCTIONS

    os = AgentOS(
        db=db, manager=OSManager(model=OfflineModel(), tool_call_limit=1, member_tool_call_limit=2), telemetry=False
    )
    member = manager_member(os, BUILDER_ID)
    calls = []

    def focused_lookup() -> str:
        """Read the relevant configuration."""
        calls.append("lookup")
        return "Verified configuration"

    member.tools.append(focused_lookup)
    member.model = BudgetProbeModel("focused_lookup", {})
    os.manager.model = BudgetProbeModel(
        "delegate_task_to_member",
        {
            "member_id": BUILDER_ID,
            "task": "Read the learning configuration; at most two lookups, then report evidence.",
        },
        expected_instructions=MANAGER_INSTRUCTIONS,
    )
    result = (
        await os.manager.arun("Explain this configuration")
        if use_async
        else os.manager.run("Explain this configuration")
    )
    assert result.content
    assert calls == ["lookup", "lookup"]
    assert member.model.calls == 4  # One delegation, two executions, one refusal, then an answer.
    assert os.manager.model.calls == 3  # The second delegation is refused.


@pytest.mark.parametrize("company_enabled", [False, True])
@pytest.mark.parametrize("access_docs", [False, True])
def test_instruction_sections_follow_the_attached_tools(db, company_enabled, access_docs):
    from agno.os import CompanyConfig
    from agno.os.manager.prompts import (
        COMPANY_INSTRUCTIONS,
        DOCS_INSTRUCTIONS,
        FOCUSED_EXECUTION_INSTRUCTIONS,
        MANAGER_INSTRUCTIONS,
    )

    os = AgentOS(
        db=db,
        manager=OSManager(model=OfflineModel(), access_docs=access_docs),
        company=CompanyConfig(model=OfflineModel()) if company_enabled else None,
        telemetry=False,
    )
    lead = os.manager.instructions()
    assert MANAGER_INSTRUCTIONS in lead
    assert (DOCS_INSTRUCTIONS in lead) is access_docs
    assert (COMPANY_INSTRUCTIONS in lead) is company_enabled
    assert FOCUSED_EXECUTION_INSTRUCTIONS not in lead
    builder = manager_member(os, BUILDER_ID).instructions
    assert FOCUSED_EXECUTION_INSTRUCTIONS in builder
    assert not {MANAGER_INSTRUCTIONS, DOCS_INSTRUCTIONS, COMPANY_INSTRUCTIONS} & set(builder)


@pytest.mark.parametrize("with_manager", [False, True])
def test_mini_agent_keeps_its_own_execution_policy(db, with_manager):
    from agno.os import CompanyConfig
    from agno.os.manager.prompts import FOCUSED_EXECUTION_INSTRUCTIONS

    os = AgentOS(
        db=db,
        company=CompanyConfig(model=OfflineModel()),
        manager=OSManager(model=OfflineModel(), member_tool_call_limit=7) if with_manager else None,
        telemetry=False,
    )
    # Mini Agent keeps its own limit; the manager's member limits do not bound it.
    assert os._mini_agent.tool_call_limit == 30
    assert FOCUSED_EXECUTION_INSTRUCTIONS not in os._mini_agent.instructions()
    if with_manager:
        assert manager_member(os, MINI_AGENT_ID) is None
        assert manager_member(os, BUILDER_ID).tool_call_limit == 7
        os.resync(os.get_app())
        assert os._mini_agent.tool_call_limit == 30
        assert FOCUSED_EXECUTION_INSTRUCTIONS not in os._mini_agent.instructions()


@pytest.mark.parametrize("component_id", ["superagent", "miniagent", "platform-builder"])
def test_preexisting_public_catalog_collision_is_explicit(db, component_id):
    _store_manager_test_component(db, "team" if component_id == "superagent" else "agent", component_id)
    with pytest.raises(ValueError, match="Rename or migrate"):
        AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), telemetry=False)


def test_separate_company_database_checks_os_catalog_collision(db, tmp_path):
    from agno.company import CompanyConfig

    _store_manager_test_component(db, "agent", MINI_AGENT_ID)
    company_db = SqliteDb(db_file=str(tmp_path / "separate-company.db"))
    with pytest.raises(ValueError, match="Rename or migrate"):
        AgentOS(db=db, manager=False, company=CompanyConfig(db=company_db, model=OfflineModel()), telemetry=False)


def test_manager_without_component_catalog_still_constructs():
    from agno.db.in_memory import InMemoryDb

    os = AgentOS(
        db=InMemoryDb(),
        manager=OSManager(model=OfflineModel(), access_docs=False, offload_tool_results=False),
        telemetry=False,
    )
    assert os.manager.id == "superagent"


@pytest.mark.parametrize(
    "component_id",
    [
        "super-agent",
        "company-manager",
        "my-company-manager",
        "my-platform-builder",
        "my-platform-manager",
        "platform-manager",
    ],
)
def test_nonreserved_names_are_user_owned(db, component_id):
    from agno.os import CompanyConfig
    from agno.registry._reserved import RESERVED_MANAGER_IDS
    from agno.team import Team
    from agno.utils.team import get_member_id

    custom_agent = Agent(id=component_id, model=OfflineModel())
    custom_team = Team(id=component_id, members=[custom_agent], model=OfflineModel())
    host = AgentOS(
        db=db,
        agents=[custom_agent],
        teams=[custom_team],
        manager=OSManager(model=OfflineModel(), access_docs=False),
        company=CompanyConfig(model=OfflineModel()),
    )
    assert component_id not in RESERVED_MANAGER_IDS
    assert host.registry.get_agent(component_id) is custom_agent
    assert host.registry.get_team(component_id) is custom_team
    assert get_member_id(custom_agent) == component_id
    assert get_member_id(host.manager) == "superagent"
    _store_manager_test_component(db, "agent", component_id)
    # Enabling built-ins cannot shadow a previously stored user component.
    AgentOS(
        db=db, manager=OSManager(model=OfflineModel(), access_docs=False), company=CompanyConfig(model=OfflineModel())
    ).get_app()


@pytest.mark.parametrize("managed", [False, True])
def test_user_super_agent_grant_and_history_are_separate_from_builtin(db, managed):
    import jwt

    from agno.os import Authorization
    from agno.team import Team

    secret = "public-manager-test-key-at-least-32-characters"
    user_team = Team(id="super-agent", db=db, members=[Agent(id="helper", model=OfflineModel())], model=OfflineModel())
    auth = Authorization(verification_keys=[secret], algorithm="HS256", audience="ids")
    scopes = ["teams:super-agent:run", "teams:super-agent:read", "sessions:read"]
    if managed:
        auth.define_role("user", scopes).assign("alice", "user")
    host = AgentOS(
        db=db,
        teams=[user_team],
        authorization=auth,
        user_isolation=True,
        manager=OSManager(model=OfflineModel(), access_docs=False),
    )
    client = TestClient(host.get_app())
    token = jwt.encode(
        {"sub": "alice", "aud": "ids", "exp": int(time.time()) + 300, "scopes": [] if managed else scopes},
        secret,
        algorithm="HS256",
    )
    headers = {"Authorization": "Bearer " + token}
    response = client.post(
        "/teams/super-agent/runs",
        headers=headers,
        data={"message": "hello", "stream": "false", "session_id": "custom-session"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["team_id"] == "super-agent"
    for builtin in ("superagent", "os-manager-internal"):
        response = client.post(f"/teams/{builtin}/runs", headers=headers, data={"message": "hello", "stream": "false"})
        assert response.status_code == 403, response.text
    builtin_scopes = ["teams:superagent:run", "teams:superagent:read", "sessions:read"]
    if managed:
        auth.set_role_scopes("user", builtin_scopes)
    else:
        token = jwt.encode(
            {"sub": "alice", "aud": "ids", "exp": int(time.time()) + 300, "scopes": builtin_scopes},
            secret,
            algorithm="HS256",
        )
        headers = {"Authorization": "Bearer " + token}
    response = client.post(
        "/teams/superagent/runs",
        headers=headers,
        data={"message": "hello", "stream": "false", "session_id": "builtin-session"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["team_id"] == "superagent"
    response = client.post("/teams/super-agent/runs", headers=headers, data={"message": "hello", "stream": "false"})
    assert response.status_code == 403, response.text
    sessions = client.get("/sessions", headers=headers, params={"type": "team", "component_id": "superagent"})
    assert [row["session_id"] for row in sessions.json()["data"]] == ["builtin-session"]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize(
    "family,user_id,internal_id",
    [
        ("teams", "super-agent", "superagent"),
        ("agents", "company-manager", MINI_AGENT_ID),
        ("agents", "my-platform-builder", "platform-builder"),
        ("agents", "platform-manager", FORMER_SPECIALIST_ID),
    ],
)
def test_user_and_internal_id_denies_do_not_cross(db, async_mode, family, user_id, internal_id):
    from agno.os.authz.native_engine import NativePolicyEngine

    engine = NativePolicyEngine(db=db)

    def check(component):
        scope = f"{family}:{component}:run"
        return (
            asyncio.run(engine.acheck_scope(scope, roles=["member"]))
            if async_mode
            else engine.check_scope(scope, roles=["member"])
        )

    db.set_authz_role_policies("member", [(f"{family}/*", "run", "allow"), (f"{family}/{internal_id}", "run", "deny")])
    assert check(user_id)
    assert not check(internal_id)
    db.set_authz_role_policies("member", [(f"{family}/*", "run", "allow"), (f"{family}/{user_id}", "run", "deny")])
    assert not check(user_id)
    assert check(internal_id)


def test_manager_catalog_is_checked_once_per_database(tmp_path):
    from agno.os import CompanyConfig

    calls = []

    class CountingDb(SqliteDb):
        def get_component(self, component_id, *args, **kwargs):
            calls.append(component_id)
            return super().get_component(component_id, *args, **kwargs)

    AgentOS(
        db=CountingDb(db_file=str(tmp_path / "os.db")),
        manager=OSManager(model=OfflineModel(), access_docs=False),
        company=CompanyConfig(model=OfflineModel()),
        telemetry=False,
    )
    assert sorted(calls) == sorted({MANAGER_TEAM_ID, MINI_AGENT_ID, BUILDER_ID})


@pytest.mark.parametrize(
    "family,former,current_family,current",
    [
        ("teams", "os-manager-internal", "teams", MANAGER_TEAM_ID),
        ("agents", "company-manager-internal", "teams", MANAGER_TEAM_ID),
        ("agents", FORMER_SPECIALIST_ID, "teams", MANAGER_TEAM_ID),
    ],
)
def test_former_manager_ids_no_longer_resolve_and_name_the_new_id(db, family, former, current_family, current):
    from agno.os import CompanyConfig

    os = AgentOS(
        db=db,
        manager=OSManager(model=OfflineModel(), access_docs=False),
        company=CompanyConfig(model=OfflineModel()),
        telemetry=False,
    )
    client = TestClient(os.get_app())
    response = client.get(f"/{family}/{former}")
    assert response.status_code == 422 and f"replaced by '{current}'" in response.text
    response = client.post(f"/{family}/{former}/runs", data={"message": "hello", "stream": "false"})
    assert response.status_code == 422 and f"replaced by '{current}'" in response.text
    # Routines ran on the former Company manager as well, and Mini Agent runs them now.
    assert (f"or '{MINI_AGENT_ID}' for a Routine executor" in response.text) == (former == "company-manager-internal")
    assert client.get(f"/{current_family}/{current}").status_code == 200


def test_grant_on_a_former_manager_id_does_not_authorize_the_new_one(db):
    import jwt

    from agno.os import Authorization

    secret = "former-manager-id-test-key-at-least-32-characters"
    auth = Authorization(verification_keys=[secret], algorithm="HS256", audience="former")
    os = AgentOS(db=db, manager=OSManager(model=OfflineModel(), access_docs=False), authorization=auth, telemetry=False)
    token = jwt.encode(
        {"sub": "alice", "aud": "former", "exp": int(time.time()) + 300, "scopes": ["teams:os-manager-internal:run"]},
        secret,
        algorithm="HS256",
    )
    response = TestClient(os.get_app()).post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        headers={"Authorization": "Bearer " + token},
        data={"message": "hello", "stream": "false"},
    )
    assert response.status_code == 403


def test_sessions_stored_under_a_former_id_are_not_listed_under_the_new_one(db):
    from agno.db.base import SessionType
    from agno.session.team import TeamSession

    db.upsert_session(TeamSession(session_id="old", team_id="os-manager-internal", user_id="alice"))
    db.upsert_session(TeamSession(session_id="new", team_id=MANAGER_TEAM_ID, user_id="alice"))
    rows = db.get_sessions(session_type=SessionType.TEAM, component_id=MANAGER_TEAM_ID)
    assert [session.session_id for session in rows] == ["new"]


@pytest.mark.parametrize("name", ["Superagent", "Miniagent", "Platform Builder"])
@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_name_derived_public_manager_ids_are_reserved(db, name, kind):
    from agno.team import Team
    from agno.workflow import Workflow

    component = (
        Agent(name=name, model=OfflineModel())
        if kind == "agent"
        else Team(name=name, members=[], model=OfflineModel())
        if kind == "team"
        else Workflow(name=name, steps=[])
    )
    with pytest.raises(ValueError, match="reserved for the manager"):
        AgentOS(db=db, **{kind + "s": [component]}, manager=False, telemetry=False)


@pytest.mark.parametrize("name", ["list_files", "read_file", "search_content"])
def test_application_tool_named_like_a_source_tool_is_refused_with_root(db, workspace, name):
    from agno.fs import FileSystem

    def tool() -> str:
        """Application tool."""
        return "x"

    tool.__name__ = name
    with pytest.raises(ValueError, match=f"OSManager.tools defines {name}, which OSManager.root also adds"):
        AgentOS(db=db, manager=OSManager(model=OfflineModel(), tools=[tool], root=workspace), telemetry=False)
    notes = FileSystem(db=db, namespace="notes")
    with pytest.raises(ValueError, match="OSManager.tools defines .*read_file"):
        AgentOS(db=db, manager=OSManager(model=OfflineModel(), tools=[notes.tools()], root=workspace), telemetry=False)
    # Either one alone is a working configuration.
    AgentOS(db=db, manager=OSManager(model=OfflineModel(), tools=[tool, notes.tools()]), telemetry=False)
    AgentOS(db=db, manager=OSManager(model=OfflineModel(), root=workspace), telemetry=False)
