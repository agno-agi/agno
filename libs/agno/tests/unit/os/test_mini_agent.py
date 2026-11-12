"""Company Routines run on Mini Agent by default, and never on Super Agent."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company import Product, Routine
from agno.company.manager import CompanyManager
from agno.company.routines import _routine_executor_endpoint, _RoutineAuthorization, load_routine_skills
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig, OSManager
from agno.registry._reserved import BUILDER_ID, MANAGER_TEAM_ID, MINI_AGENT_ID, RESERVED_MANAGER_IDS
from agno.run.authorization import AUTHORIZATION_HEADER, authorization_scope
from agno.tools.agentos import AgentOSTools
from agno.tools.company import CompanyTools
from agno.tools.studio import StudioTools
from agno.tools.studio_runner import StudioRunnerTools

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

RUNNER_ENDPOINT = f"/agents/{MINI_AGENT_ID}/runs"
ROUTINE_SNAPSHOT = {
    "context": {"principal_id": None},
    "service_account": True,
    "enforce_tools": True,
    "company_routine": True,
    "company_routine_unscoped": True,
    "company_routine_id": "routine",
    "company_product_id": "sdk",
}


class CountingModel(Model):
    """Count model calls; optionally call one tool first and reply with its result."""

    def __init__(self, tool=None, arguments=None):
        super().__init__(id="fixture", provider="test")
        self.tool = tool
        self.arguments = arguments or {}
        self.calls = 0
        self.system = ""

    def invoke(self, messages, **kwargs):
        self.calls += 1
        self.system = str(messages[0].content)
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


def routine_authority():
    return _RoutineAuthorization(None, routine_id="routine", product_id="sdk")


def build(tmp_path, manager=True, **kwargs):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    return AgentOS(
        db=db,
        manager=OSManager(model=CountingModel()) if manager else None,
        company=CompanyConfig(model=CountingModel()),
        telemetry=False,
        **kwargs,
    )


def run(component, use_async, message="go"):
    if use_async:
        return asyncio.run(component.arun(message, user_id="alice", session_id="session"))
    return component.run(message, user_id="alice", session_id="session")


def internal_headers(os, snapshot=None):
    headers = {"Authorization": "Bearer " + os._internal_service_token}
    if snapshot is not None:
        headers[AUTHORIZATION_HEADER] = json.dumps(snapshot)
    return headers


# ----------------------------------------------------------------- the executor a Routine may name


@pytest.mark.parametrize("manager", [False, True])
def test_a_routine_naming_mini_agent_runs_on_it(tmp_path, manager):
    os = build(tmp_path, manager=manager)
    assert _routine_executor_endpoint("agent", MINI_AGENT_ID, os.registry, agent_os=os) == RUNNER_ENDPOINT
    with pytest.raises(ValueError, match="executor_type must be 'agent'"):
        _routine_executor_endpoint("team", MINI_AGENT_ID, os.registry, agent_os=os)


@pytest.mark.parametrize("executor_id", sorted(RESERVED_MANAGER_IDS - {MINI_AGENT_ID}))
def test_no_other_framework_id_can_execute_a_routine(tmp_path, executor_id):
    os = build(tmp_path)
    for executor_type in ("agent", "team"):
        with pytest.raises(ValueError, match="only Mini Agent runs Routines"):
            _routine_executor_endpoint(executor_type, executor_id, os.registry, agent_os=os)


def test_mini_agent_needs_company_and_a_model(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    os = AgentOS(db=db, manager=OSManager(model=CountingModel()), telemetry=False)
    with pytest.raises(ValueError, match="configure CompanyConfig"):
        _routine_executor_endpoint("agent", MINI_AGENT_ID, os.registry, agent_os=os)
    os = AgentOS(db=db, company=CompanyConfig(), telemetry=False)
    assert os._mini_agent is None
    with pytest.raises(ValueError, match="Mini Agent unavailable: configure CompanyConfig\\(model="):
        _routine_executor_endpoint("agent", MINI_AGENT_ID, os.registry, agent_os=os)


# ----------------------------------------------------------------- what Mini Agent holds


def test_runner_holds_company_tools_and_routine_skills_only(tmp_path):
    os = build(tmp_path)
    runner = os._mini_agent
    assert runner.id == MINI_AGENT_ID and runner.name == "Mini Agent"
    assert [type(tool) for tool in runner.tools] == [CompanyTools]
    assert not any(isinstance(tool, (StudioTools, StudioRunnerTools, AgentOSTools)) for tool in runner.tools)
    assert not getattr(runner, "members", None)
    assert {"refresh_company_product", "summarize_company_product", "intake_product_source"} <= set(
        runner.tools[0].functions
    )
    assert sorted(skill.name for skill in runner.skills.get_all_skills()) == ["intake", "refresh", "summary"]
    # Super Agent holds the platform, so it keeps the two Routine tools off.
    company = next(tool for tool in os.manager.tools if isinstance(tool, CompanyTools))
    assert not {"refresh_company_product", "summarize_company_product"} & set(company.functions)


@pytest.mark.parametrize("skill", ["intake", "refresh", "summary"])
def test_every_tool_a_packaged_skill_names_is_on_the_runner(tmp_path, skill):
    os = build(tmp_path)
    functions = set(os._mini_agent.tools[0].functions)
    text = load_routine_skills().get_skill(skill).instructions
    named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)*_(?:company|product)_[a-z_]+\b", text))
    assert named, text
    # propose_company_task is named only to say Routines do not use it.
    assert named - {"propose_company_task"} <= functions, named - functions


@pytest.mark.parametrize("use_async", [False, True])
@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("refresh_company_product", {"product_id": "{product}"}),
        ("summarize_company_product", {"product_id": "{product}", "narrative": "Nothing changed."}),
        (
            "intake_product_source",
            {
                "source_id": "{source}",
                "title": "Fix the docs",
                "brief": "The install page is wrong.",
                "proposal_key": "install-docs",
                "evidence_links": ["notes.md"],
                "evidence_hashes": {"notes.md": "{hash}"},
                "project_id": "{project}",
            },
        ),
    ],
)
def test_runner_can_call_the_tool_each_skill_names(tmp_path, tool, arguments, use_async):
    import hashlib

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "notes.md").write_text("The install page is wrong.\n")
    os = build(tmp_path)
    company = CompanyManager(os.db)
    product = company.create(name="SDK")
    project = company.create_project(product_id=product["id"], name="Docs")
    company.transition_project(project_id=project["id"], target="active", reason="Approved")
    source = company.create_source(product_id=product["id"], type="markdown", reference=str(notes))
    ids = {
        "product": product["id"],
        "project": project["id"],
        "source": source["id"],
        "hash": hashlib.sha256((notes / "notes.md").read_bytes()).hexdigest(),
    }
    filled = json.loads(json.dumps(arguments).replace("{product}", ids["product"]).replace("{source}", ids["source"]))
    filled = json.loads(json.dumps(filled).replace("{project}", ids["project"]).replace("{hash}", ids["hash"]))
    runner = os._mini_agent
    runner.model = CountingModel(tool, filled)
    authority = _RoutineAuthorization(None, routine_id="routine", product_id=product["id"])
    with authorization_scope(lambda: authority):
        result = run(runner, use_async)
    executed = [execution for execution in result.tools or [] if execution.tool_name == tool]
    assert len(executed) == 1, result.content
    reply = str(executed[0].result)
    assert "Permission required" not in reply and "requires Routine authority" not in reply, reply
    assert "not found" not in reply.lower(), reply
    if tool == "refresh_company_product":
        assert not executed[0].tool_call_error, reply


# ----------------------------------------------------------------- Mini Agent runs Routines only


@pytest.mark.parametrize("use_async", [False, True])
def test_runner_refuses_a_run_without_routine_authority(tmp_path, use_async):
    os = build(tmp_path)
    runner = os._mini_agent
    result = run(runner, use_async)
    assert "This agent runs Company Routines only" in str(result.content)
    assert runner.model.calls == 0


@pytest.mark.parametrize("use_async", [False, True])
def test_runner_prompt_opens_by_saying_what_it_is(tmp_path, use_async):
    os = build(tmp_path)
    with authorization_scope(routine_authority):
        run(os._mini_agent, use_async)
    assert os._mini_agent.model.system.startswith("You are Mini Agent, running a Routine for a Product.")


@pytest.mark.parametrize("use_async", [False, True])
def test_runner_runs_with_routine_authority(tmp_path, use_async):
    os = build(tmp_path)
    runner = os._mini_agent
    with authorization_scope(routine_authority):
        result = run(runner, use_async)
    assert result.content == "answer" and runner.model.calls == 1


def test_a_person_cannot_chat_with_the_runner_over_http(tmp_path):
    os = build(tmp_path)
    client = TestClient(os.get_app())
    response = client.post(RUNNER_ENDPOINT, data={"message": "hello", "stream": "false"})
    assert "This agent runs Company Routines only" in response.text
    assert os._mini_agent.model.calls == 0
    # The scheduler's own identity without a Routine is refused as well.
    response = client.post(RUNNER_ENDPOINT, headers=internal_headers(os), data={"message": "hello", "stream": "false"})
    assert "This agent runs Company Routines only" in response.text
    assert os._mini_agent.model.calls == 0


def test_the_scheduler_reaches_the_runner_with_a_routine(tmp_path):
    os = build(tmp_path)
    client = TestClient(os.get_app())
    response = client.post(
        RUNNER_ENDPOINT, headers=internal_headers(os, ROUTINE_SNAPSHOT), data={"message": "go", "stream": "false"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"] == "answer" and body["agent_id"] == MINI_AGENT_ID
    assert body["agent_name"] == "Mini Agent"


@pytest.mark.parametrize("use_async", [False, True])
def test_super_agent_cannot_run_the_runner(tmp_path, use_async):
    os = build(tmp_path)
    os.manager.model = CountingModel("run_agent", {"agent_id": MINI_AGENT_ID, "message": "go"})
    result = run(os.manager, use_async)
    assert "not found" in str(result.content).lower() or "reserved" in str(result.content).lower(), result.content
    assert os._mini_agent.model.calls == 0


# ----------------------------------------------------------------- Super Agent never runs a Routine


@pytest.mark.parametrize("use_async", [False, True])
def test_super_agent_refuses_a_run_with_routine_authority(tmp_path, use_async):
    os = build(tmp_path)
    with authorization_scope(routine_authority):
        result = run(os.manager, use_async)
    assert "Company Routines run on Mini Agent" in str(result.content)
    assert os.manager.model.calls == 0


@pytest.mark.parametrize("use_async", [False, True])
def test_super_agent_runs_for_a_person(tmp_path, use_async):
    os = build(tmp_path)
    assert run(os.manager, use_async).content == "answer"
    assert os.manager.model.calls == 1


def test_super_agent_refuses_a_routine_over_http(tmp_path):
    os = build(tmp_path)
    client = TestClient(os.get_app())
    response = client.post(
        f"/teams/{MANAGER_TEAM_ID}/runs",
        headers=internal_headers(os, ROUTINE_SNAPSHOT),
        data={"message": "go", "stream": "false"},
    )
    assert "Company Routines run on Mini Agent" in response.text
    assert os.manager.model.calls == 0


# ----------------------------------------------------------------- listings


def test_runner_is_served_but_listed_nowhere(tmp_path):
    os = build(tmp_path, agents=[Agent(id="reader", model=CountingModel())], a2a_interface=True, mcp=True)
    assert MINI_AGENT_ID in [agent.id for agent in os.agents]
    client = TestClient(os.get_app())
    assert [agent["id"] for agent in client.get("/agents").json()] == ["reader"]
    config = client.get("/config").json()
    assert [agent["id"] for agent in config["agents"]] == ["reader"]
    assert MINI_AGENT_ID not in config.get("manifest", {})
    assert [agent.id for agent in os._get_a2a_agents()] == ["reader"]
    assert os.registry.get_agent(MINI_AGENT_ID) is None
    runner_tools = next(tool for tool in os.manager.tools if isinstance(tool, StudioRunnerTools))
    assert [row["id"] for row in json.loads(runner_tools.list_agents())["agents"]] == ["reader"]
    assert MINI_AGENT_ID not in "\n".join(os.manager.instructions())
    assert [member.id for member in os.manager.members] == [BUILDER_ID]


@pytest.mark.asyncio
async def test_runner_is_not_in_the_mcp_listing(tmp_path):
    from fastmcp import Client

    from agno.os.mcp import build_mcp_server

    os = build(tmp_path, agents=[Agent(id="reader", model=CountingModel())], mcp=True)
    os.get_app()
    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool("get_agentos_config", {})
    listed = json.loads(result.content[0].text)
    assert [agent["id"] for agent in listed["agents"]] == ["reader"]


# ----------------------------------------------------------------- records and declarations


def test_routine_record_names_mini_agent_everywhere(tmp_path):
    product = Product(
        id="sdk",
        name="SDK",
        routines=[
            Routine(
                name="weekly",
                executor_type="agent",
                executor_id=MINI_AGENT_ID,
                cron_expr="0 9 * * 1",
                instructions="Review.",
            )
        ],
    )
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    os = AgentOS(db=db, company=CompanyConfig(model=CountingModel(), products=[product]), telemetry=False)
    with TestClient(os.get_app()) as client:
        routine = client.get("/company/routines").json()["data"][0]
    # The API, the endpoint and the stored row all name the same component.
    assert routine["endpoint"] == RUNNER_ENDPOINT
    assert (routine["target_type"], routine["target_id"]) == ("agent", MINI_AGENT_ID)
    stored = db.get_schedule_by_name("sdk.weekly")
    assert stored["endpoint"] == RUNNER_ENDPOINT
    assert (stored["target_type"], stored["target_id"]) == ("agent", MINI_AGENT_ID)


def test_declared_routine_with_a_missing_executor_names_what_is_wrong(tmp_path):
    product = Product(
        name="Docs",
        routines=[Routine(name="weekly", executor_type="agent", executor_id="company-manager", instructions="Review.")],
    )
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    os = AgentOS(db=db, company=CompanyConfig(model=CountingModel(), products=[product]), telemetry=False)
    with pytest.raises(ValueError) as raised:
        with TestClient(os.get_app()):
            pass
    message = str(raised.value)
    assert "Product 'Docs'" in message and "Routine 'weekly'" in message
    assert "executor agent 'company-manager'" in message and "missing from the registry" in message


# ----------------------------------------------------------------- a Routine with no executor runs on Mini Agent


def test_a_routine_with_no_executor_names_mini_agent():
    routine = Routine(name="weekly", instructions="Review.")
    assert (routine.executor_type, routine.executor_id) == ("agent", MINI_AGENT_ID)
    nulls = Routine(name="weekly", instructions="Review.", executor_type=None, executor_id=None)
    assert (nulls.executor_type, nulls.executor_id) == ("agent", MINI_AGENT_ID)
    named = Routine(name="weekly", instructions="Review.", executor_type="agent", executor_id="reader")
    assert (named.executor_type, named.executor_id) == ("agent", "reader")


@pytest.mark.parametrize("half", [{"executor_type": "agent"}, {"executor_id": "reader"}])
def test_a_routine_needs_both_executor_fields_or_neither(half):
    with pytest.raises(ValueError, match="Give executor_type and executor_id together"):
        Routine(name="weekly", instructions="Review.", **half)


def test_routine_api_defaults_the_executor_to_mini_agent(tmp_path):
    os = build(tmp_path)
    with TestClient(os.get_app()) as client:
        product = CompanyManager(os.db).create(name="Docs")
        body = {"product_id": product["id"], "name": "weekly", "instructions": "Review."}
        created = client.post("/company/routines", json=body)
        assert created.status_code == 201, created.text
        assert (created.json()["target_type"], created.json()["target_id"]) == ("agent", MINI_AGENT_ID)
        assert created.json()["endpoint"] == RUNNER_ENDPOINT
        half = client.post("/company/routines", json={**body, "name": "half", "executor_type": "agent"})
        assert half.status_code == 422 and "Give executor_type and executor_id together" in half.text


@pytest.mark.parametrize("use_async", [False, True])
def test_routine_tool_defaults_the_executor_to_mini_agent(tmp_path, use_async):
    os = build(tmp_path)
    product = CompanyManager(os.db).create(name="Docs")
    company = next(tool for tool in os.manager.tools if isinstance(tool, CompanyTools))
    if use_async:
        result = asyncio.run(company.acreate_product_routine(product["id"], "weekly", instructions="Review."))
    else:
        result = company.create_product_routine(product["id"], "weekly", instructions="Review.")
    # The tool result and the stored row name the same executor.
    assert (json.loads(result)["target_type"], json.loads(result)["target_id"]) == ("agent", MINI_AGENT_ID)
    stored = os.db.get_schedule_by_name(product["id"] + ".weekly")
    assert stored["endpoint"] == RUNNER_ENDPOINT and stored["target_id"] == MINI_AGENT_ID
    call = company.acreate_product_routine if use_async else company.create_product_routine
    with pytest.raises(ValueError, match="Give executor_type and executor_id together"):
        half = call(product["id"], "half", executor_id="reader", instructions="Review.")
        if use_async:
            asyncio.run(half)


@pytest.mark.parametrize("executor", [{}, {"executor_type": "agent", "executor_id": MINI_AGENT_ID}])
def test_declared_routine_fails_at_startup_when_the_runner_is_unavailable(tmp_path, executor):
    # No model for Company, so there is no Mini Agent. A defaulted executor fails like a named one.
    product = Product(name="Docs", routines=[Routine(name="weekly", instructions="Review.", **executor)])
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    os = AgentOS(db=db, company=CompanyConfig(products=[product]), telemetry=False)
    with pytest.raises(ValueError) as raised:
        with TestClient(os.get_app()):
            pass
    message = str(raised.value)
    assert "Product 'Docs'" in message and "Routine 'weekly'" in message
    assert "executor agent 'miniagent'" in message and "Mini Agent unavailable" in message


@pytest.mark.parametrize("use_async", [False, True])
def test_created_routine_fails_the_same_with_or_without_a_named_executor(tmp_path, use_async):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    os = AgentOS(db=db, company=CompanyConfig(), telemetry=False)
    named = {"executor_type": "agent", "executor_id": MINI_AGENT_ID}
    with TestClient(os.get_app()) as client:
        product = CompanyManager(db).create(name="Docs")
        body = {"product_id": product["id"], "name": "weekly", "instructions": "Review."}
        defaulted, explicit = (
            client.post("/company/routines", json=body),
            client.post("/company/routines", json={**body, **named}),
        )
    assert defaulted.status_code == explicit.status_code == 422
    assert defaulted.json() == explicit.json() and "Mini Agent unavailable" in defaulted.text
    company = CompanyTools(db)
    errors = []
    for executor in ({}, named):
        with pytest.raises(ValueError, match="Mini Agent unavailable") as raised:
            if use_async:
                asyncio.run(
                    company.acreate_product_routine(product["id"], "weekly", instructions="Review.", **executor)
                )
            else:
                company.create_product_routine(product["id"], "weekly", instructions="Review.", **executor)
        errors.append(str(raised.value))
    assert errors[0] == errors[1]
    assert db.get_schedules()[1] == 0


def test_skill_files_are_the_packaged_three():
    import agno.company

    names = sorted(path.parent.name for path in (Path(agno.company.__file__).parent / "skills").glob("*/SKILL.md"))
    assert names == ["intake", "refresh", "summary"]
