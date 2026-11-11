"""Super Agent's context lists the components the caller can run."""

import asyncio
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, Authorization, CompanyConfig, OSManager
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.manager.manager import _CATALOG_LIMIT
from agno.registry._reserved import MANAGER_TEAM_ID
from agno.run.authorization import RunAuthorization, authorization_scope
from agno.team import Team
from agno.tools.studio_runner import StudioRunnerTools
from agno.workflow import Workflow

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

SECRET = "manager-catalog-test-key-at-least-32-characters"


class RecordingModel(Model):
    """Answer once and keep the system message it was given."""

    def __init__(self, tool=None, arguments=None):
        super().__init__(id="fixture", provider="test")
        self.tool = tool
        self.arguments = arguments or {}
        self.system = []

    def invoke(self, messages, **kwargs):
        self.system.append(str(messages[0].content))
        if self.tool and messages[-1].role != "tool":
            call = {
                "id": "call",
                "type": "function",
                "function": {"name": self.tool, "arguments": json.dumps(self.arguments)},
            }
            return ModelResponse(role="assistant", tool_calls=[call], response_usage=MessageMetrics())
        content = str(messages[-1].content) if self.tool else "answer"
        return ModelResponse(role="assistant", content=content, response_usage=MessageMetrics())

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


def catalog(system):
    """The catalog section of a system message, as its lines."""
    _, found, rest = system.partition("Components you can run:\n")
    return [line for line in rest.split("\n\n")[0].splitlines() if line] if found else []


def build(tmp_path, agents=None, company=False, **kwargs):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    model = RecordingModel()
    os = AgentOS(
        db=db,
        agents=agents if agents is not None else [],
        manager=OSManager(model=model),
        company=CompanyConfig(model=RecordingModel()) if company else None,
        telemetry=False,
        **kwargs,
    )
    return os, model


@pytest.mark.parametrize("use_async", [False, True])
def test_catalog_lists_runnable_components_without_the_framework_ones(tmp_path, use_async):
    agents = [
        Agent(
            id="notes",
            name="Meeting Notes",
            description="Turns notes into decisions.\nSecond line.",
            model=RecordingModel(),
        ),
        Agent(id="plain", model=RecordingModel()),
    ]
    os, model = build(
        tmp_path,
        agents=agents,
        company=True,
        teams=[Team(id="research", name="Research", members=[], model=RecordingModel())],
        workflows=[Workflow(id="digest", name="Digest", steps=[])],
    )
    if use_async:
        asyncio.run(os.manager.arun("hello"))
    else:
        os.manager.run("hello")
    assert catalog(model.system[0]) == [
        "- Meeting Notes (agent, id notes): Turns notes into decisions.",
        "- plain (agent, id plain)",
        "- Research (team, id research)",
        "- Digest (workflow, id digest)",
    ]


@pytest.mark.parametrize("use_async", [False, True])
def test_catalog_is_capped_and_points_to_the_list_tools(tmp_path, use_async):
    agents = [Agent(id=f"agent-{n:02}", model=RecordingModel()) for n in range(_CATALOG_LIMIT + 3)]
    os, model = build(tmp_path, agents=agents)
    if use_async:
        asyncio.run(os.manager.arun("hello"))
    else:
        os.manager.run("hello")
    lines = catalog(model.system[0])
    assert len(lines) == _CATALOG_LIMIT + 1
    assert lines[-1] == "More exist: call list_agents, list_teams or list_workflows."
    assert lines[0] == "- agent-00 (agent, id agent-00)"


def test_catalog_is_absent_when_nothing_can_be_run(tmp_path):
    os, model = build(tmp_path)
    os.manager.run("hello")
    assert catalog(model.system[0]) == []


@pytest.mark.parametrize("use_async", [False, True])
def test_catalog_shows_only_what_the_caller_may_read(tmp_path, use_async):
    agents = [Agent(id="allowed", model=RecordingModel()), Agent(id="hidden", model=RecordingModel())]
    os, model = build(tmp_path, agents=agents)
    scopes = [f"teams:{MANAGER_TEAM_ID}:run", "agents:allowed:read"]
    # The shape an HTTP caller has: operation checks are not yet active outside a tool call.
    caller = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"}),
        enforce_tools=False,
    )
    with authorization_scope(lambda: caller):
        if use_async:
            asyncio.run(os.manager.arun("hello", user_id="alice"))
        else:
            os.manager.run("hello", user_id="alice")
    assert catalog(model.system[0]) == ["- allowed (agent, id allowed)"]


HINT = "More exist: call list_agents, list_teams or list_workflows."


def store_agent(db, component_id, stage):
    from agno.db.base import ComponentType

    db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config={"id": component_id, "name": component_id},
        stage=stage,
    )


@pytest.mark.parametrize("use_async", [False, True])
def test_catalog_says_more_exist_when_drafts_fill_the_page(tmp_path, use_async):
    # Drafts are filtered after the query, so a page of newer drafts hides an older published agent.
    os, model = build(tmp_path)
    store_agent(os.db, "zz-published", "published")
    for n in range(_CATALOG_LIMIT + 1):
        store_agent(os.db, f"draft-{n:02}", "draft")
    if use_async:
        asyncio.run(os.manager.arun("hello"))
    else:
        os.manager.run("hello")
    assert catalog(model.system[0]) == [HINT]


@pytest.mark.parametrize("use_async", [False, True])
def test_catalog_says_more_exist_when_unreadable_components_fill_the_page(tmp_path, use_async):
    os, model = build(tmp_path)
    store_agent(os.db, "zz-readable", "published")
    for n in range(_CATALOG_LIMIT + 1):
        store_agent(os.db, f"hidden-{n:02}", "published")
    scopes = [f"teams:{MANAGER_TEAM_ID}:run", "agents:zz-readable:read"]
    caller = RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"}),
        enforce_tools=False,
    )
    with authorization_scope(lambda: caller):
        if use_async:
            asyncio.run(os.manager.arun("hello", user_id="alice"))
        else:
            os.manager.run("hello", user_id="alice")
    lines = catalog(model.system[0])
    assert lines == [HINT]
    assert "hidden-" not in model.system[0]


def test_catalog_has_no_hint_when_the_page_is_not_full(tmp_path):
    os, model = build(tmp_path)
    store_agent(os.db, "published", "published")
    for n in range(_CATALOG_LIMIT - 1):
        store_agent(os.db, f"draft-{n:02}", "draft")
    os.manager.run("hello")
    assert catalog(model.system[0]) == ["- published (agent, id published)"]


class CountingProvider(ScopeAuthorizationProvider):
    """Allow every read and count the checks."""

    def __init__(self):
        super().__init__()
        self.reads = []

    def check(self, ctx):
        if ctx.action == "read":
            self.reads.append(ctx.resource_id)
            return True
        return super().check(ctx)

    async def acheck(self, ctx):
        return self.check(ctx)


@pytest.mark.parametrize("use_async", [False, True])
def test_catalog_stops_checking_once_it_is_full(tmp_path, use_async):
    agents = [Agent(id=f"agent-{n:02}", model=RecordingModel()) for n in range(_CATALOG_LIMIT * 3)]
    os, model = build(
        tmp_path, agents=agents, teams=[Team(id="research", name="Research", members=[], model=RecordingModel())]
    )
    provider = CountingProvider()
    caller = RunAuthorization(
        provider,
        AuthorizationContext(principal_id="alice", scopes=[f"teams:{MANAGER_TEAM_ID}:run"], claims={"sub": "alice"}),
        enforce_tools=False,
    )
    with authorization_scope(lambda: caller):
        if use_async:
            asyncio.run(os.manager.arun("hello", user_id="alice"))
        else:
            os.manager.run("hello", user_id="alice")
    lines = catalog(model.system[0])
    assert len(lines) == _CATALOG_LIMIT + 1 and lines[-1].startswith("More exist")
    # Twenty entries and the one that shows more exist. Teams and workflows are not read at all.
    assert provider.reads == [f"agent-{n:02}" for n in range(_CATALOG_LIMIT + 1)]


def test_catalog_over_http_matches_what_list_agents_returns(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    model = RecordingModel("list_agents")
    os = AgentOS(
        id="catalog-test",
        db=db,
        agents=[Agent(id="allowed", model=RecordingModel()), Agent(id="hidden", model=RecordingModel())],
        manager=OSManager(model=model),
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", audience="catalog-test"),
        user_isolation=True,
        telemetry=False,
    )
    token = jwt.encode(
        {
            "sub": "alice",
            "aud": "catalog-test",
            "exp": int(time.time()) + 300,
            "scopes": [f"teams:{MANAGER_TEAM_ID}:run", "agents:allowed:read"],
        },
        SECRET,
        algorithm="HS256",
    )
    response = TestClient(os.get_app()).post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        headers={"Authorization": f"Bearer {token}"},
        data={"message": "hello", "stream": "false"},
    )
    assert response.status_code == 200, response.text
    assert catalog(model.system[0]) == ["- allowed (agent, id allowed)"]
    listed = json.loads(response.json()["content"])
    assert [row["id"] for row in listed["agents"]] == ["allowed"]


@pytest.mark.parametrize("company", [False, True])
def test_super_agent_can_run_itself_once(tmp_path, company):
    os, _ = build(tmp_path, company=company)
    assert not StudioRunnerTools._copy_lost_identity(os.manager, os.manager.deep_copy())
    os.manager.model = RecordingModel("run_team", {"team_id": MANAGER_TEAM_ID, "message": "investigate"})
    result = os.manager.run("look into it", session_id="self", user_id="alice")
    # The nested run starts and its own attempt to run itself again is refused.
    assert "already running" in str(result.content), result.content


def test_context_settings(tmp_path):
    os, _ = build(tmp_path)
    manager = os.manager
    assert manager.add_history_to_context and manager.num_history_runs == 5
    assert manager.read_chat_history and manager.search_past_sessions
    assert manager.tool_call_limit == 24
    assert not manager.compress_tool_results and not manager.enable_session_summaries
    assert OSManager().num_history_runs == 5 and OSManager().tool_call_limit == 24
