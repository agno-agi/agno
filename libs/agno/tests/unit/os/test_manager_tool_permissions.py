"""Every tool Super Agent holds directly checks the caller's own permission, in sync and async runs."""

import asyncio
import json

import pytest

from agno.agent import Agent
from agno.company.manager import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.os.authz.provider import AuthorizationContext
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID
from agno.run.authorization import RunAuthorization, authorization_scope
from agno.tools.agentos import AgentOSTools
from agno.tools.company import CompanyTools
from agno.tools.studio_runner import StudioRunnerTools

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

RUN_ONLY = [f"teams:{MANAGER_TEAM_ID}:run"]

# One call per tool, with the permission its first check asks for. Ids in braces are filled from the
# seeded records.
MOVED_TOOLS = {
    "get_run_activity": ({}, "agent_os:admin"),
    "list_schedules": ({}, "agent_os:admin"),
    "run_diagnostics": ({}, "config:read"),
    "list_files": ({}, "filesystem:read"),
    "read_file": ({"path": "example.py"}, "filesystem:read"),
    "search_content": ({"query": "SENTINEL"}, "filesystem:read"),
    "update_company_details": ({"description": "Makes robots"}, "company:write"),
    "list_company_products": ({}, "products:read"),
    "get_company_product": ({"product_id": "{product}"}, "products:read"),
    "create_company_product": ({"name": "Second"}, "products:write"),
    "create_product_routine": (
        {
            "product_id": "{product}",
            "name": "review",
            "executor_type": "agent",
            "executor_id": "reader",
            "instructions": "Review the Product.",
        },
        "products:write",
    ),
    "list_company_projects": ({}, "projects:read"),
    "propose_company_project": ({"product_id": "{product}", "name": "Second project"}, "projects:write"),
    "edit_company_project": ({"project_id": "{project}", "name": "Renamed", "outcome": "Done"}, "projects:write"),
    "list_company_tasks": ({}, "tasks:read"),
    "propose_company_task": ({"product_id": "{product}", "title": "Second", "project_id": "{project}"}, "tasks:write"),
    "edit_company_task": ({"task_id": "{task}", "title": "Renamed", "brief": "New brief"}, "tasks:write"),
    "list_product_sources": ({"product_id": "{product}"}, "sources:read"),
    "add_product_source": ({"product_id": "{product}", "reference": "https://example.com/docs"}, "sources:write"),
    "read_product_source": ({"source_id": "{source}"}, "sources:read"),
    "intake_product_source": (
        {
            "source_id": "{source}",
            "title": "From source",
            "brief": "Do it",
            "proposal_key": "key",
            "evidence_links": ["notes.md"],
            "evidence_hashes": {"notes.md": "0"},
            "project_id": "{project}",
        },
        "sources:read",
    ),
    "list_company_wiki": ({}, "wiki:read"),
    "read_company_wiki": ({"path": "brief.md", "product_id": "{product}"}, "wiki:read"),
    "update_product_status": ({"product_id": "{product}", "content": "Status", "expected_version": 0}, "wiki:write"),
    "log_company_decision": ({"decision": "Drop the old API"}, "decisions:write"),
    "search_company_decisions": ({}, "decisions:read"),
}
# Pauses for the person before it runs, so its refusal is asserted after the confirmation.
CONFIRMED_TOOL = "confirm_company_details"


class OneToolModel(Model):
    """Call one tool, then return the tool result as the reply."""

    def __init__(self, tool, arguments):
        super().__init__(id="fixture", provider="test")
        self.tool = tool
        self.arguments = arguments

    def invoke(self, messages, **kwargs):
        if messages[-1].role != "tool":
            call = {
                "id": "call",
                "type": "function",
                "function": {"name": self.tool, "arguments": json.dumps(self.arguments)},
            }
            return ModelResponse(role="assistant", tool_calls=[call], response_usage=MessageMetrics())
        return ModelResponse(role="assistant", content=str(messages[-1].content), response_usage=MessageMetrics())

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


def authority(scopes):
    # The shape an HTTP caller has: operation checks start only inside a framework-owned component.
    return RunAuthorization(
        ScopeAuthorizationProvider(),
        AuthorizationContext(principal_id="alice", scopes=scopes, claims={"sub": "alice"}),
        enforce_tools=False,
    )


@pytest.fixture
def platform(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "example.py").write_text("READABLE_SOURCE_SENTINEL = 42\n")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "notes.md").write_text("Notes\n")
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    model = OneToolModel("list_agents", {})
    os = AgentOS(
        db=db,
        agents=[Agent(id="reader", model=model, db=db)],
        manager=OSManager(model=model, root=root),
        company=CompanyConfig(model=model),
        telemetry=False,
    )
    db.initialize_company("Acme", "Makes things")
    company = CompanyManager(db)
    product = company.create(name="SDK")
    project = company.create_project(product_id=product["id"], name="Release")
    task = company.create_task(product_id=product["id"], title="First", project_id=project["id"])
    source = company.create_source(product_id=product["id"], type="markdown", reference=str(notes))
    ids = {"product": product["id"], "project": project["id"], "task": task["id"], "source": source["id"]}
    return os, ids


def held_tools(os):
    """Function names on Super Agent, without the run tools and the application's own tools."""
    names = set()
    for tool in os.manager.tools:
        if not isinstance(tool, StudioRunnerTools):
            names |= set(getattr(tool, "functions", {}))
    return names


def run_tool(os, ids, tool, arguments, scopes, use_async):
    filled = {
        key: value.format(**ids) if isinstance(value, str) and value.startswith("{") else value
        for key, value in arguments.items()
    }
    os.manager.model = OneToolModel(tool, filled)
    with authorization_scope(lambda: authority(scopes)):
        if use_async:
            return asyncio.run(os.manager.arun("Execute", user_id="alice", session_id=f"s-{tool}-{use_async}"))
        return os.manager.run("Execute", user_id="alice", session_id=f"s-{tool}-{use_async}")


def company_records(os):
    company = CompanyManager(os.db)
    products, product_count = company.list()
    return (
        product_count,
        company.list_projects()[1],
        company.list_tasks()[1],
        sum(company.list_sources(product_id=product["id"])[1] for product in products),
        os.db.get_company()["description"],
    )


def test_matrix_covers_every_tool_super_agent_holds(platform):
    os, _ = platform
    assert held_tools(os) == set(MOVED_TOOLS) | {CONFIRMED_TOOL}
    assert [member.id for member in os.manager.members] == [BUILDER_ID]
    # The platform read tools left off Super Agent stay in the toolkit.
    left_off = set(AgentOSTools(db=os.db).functions) - held_tools(os)
    assert left_off == {
        "get_platform_metrics",
        "get_tool_activity",
        "get_eval_history",
        "get_schedule_history",
        "list_platform_components",
        "list_pending_approvals",
    }
    company = next(tool for tool in os.manager.tools if isinstance(tool, CompanyTools))
    assert not {"refresh_company_product", "summarize_company_product"} & set(company.functions)


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("tool", sorted(MOVED_TOOLS))
def test_tool_is_refused_without_its_permission(platform, tool, use_async):
    os, ids = platform
    arguments, permission = MOVED_TOOLS[tool]
    before = company_records(os)
    result = run_tool(os, ids, tool, arguments, RUN_ONLY, use_async)
    assert "Permission required: " + permission in str(result.content), result.content
    assert company_records(os) == before


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize("tool", sorted(MOVED_TOOLS))
def test_tool_runs_with_its_permission(platform, tool, use_async):
    os, ids = platform
    arguments, _ = MOVED_TOOLS[tool]
    result = run_tool(os, ids, tool, arguments, [*RUN_ONLY, "agent_os:admin"], use_async)
    assert "Permission required" not in str(result.content), result.content


@pytest.mark.parametrize("use_async", [False, True])
def test_confirmed_company_edit_is_refused_without_its_permission(platform, use_async):
    os, ids = platform
    arguments = {"expected_updated_at": os.db.get_company()["updated_at"], "description": "Replaced"}
    before = company_records(os)
    paused = run_tool(os, ids, CONFIRMED_TOOL, arguments, RUN_ONLY, use_async)
    assert paused.is_paused and company_records(os) == before
    for requirement in paused.requirements:
        requirement.confirm()
    with authorization_scope(lambda: authority(RUN_ONLY)):
        if use_async:
            result = asyncio.run(os.manager.acontinue_run(run_response=paused, user_id="alice"))
        else:
            result = os.manager.continue_run(run_response=paused, user_id="alice")
    assert "Permission required: company:write" in str(result.content), result.content
    assert company_records(os) == before
