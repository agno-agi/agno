"""A component whose references cannot be rehydrated answers 422 over HTTP.

Covers both deployment shapes: an AgentOS that owns its FastAPI app, and one
mounted on an app the caller supplied, where AgentOS registers no exception
handlers of its own.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.registry import Registry
from agno.team.team import Team


def _search(query: str) -> str:
    """Search for a query."""
    return f"results for {query}"


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "rehydration_status.db"))


@pytest.fixture
def toolless_os(db):
    """An AgentOS whose registry lacks the tool its stored components reference."""
    # Tools reach the stored config only when the component carries a model.
    model = OpenAIChat(id="gpt-4o-mini")
    Agent(id="broken-agent", name="Broken", model=model, tools=[_search]).save(db=db)
    Agent(id="clean-agent", name="Clean", model=model).save(db=db)
    Team(id="broken-team", name="BrokenTeam", model=model, members=[], tools=[_search]).save(db=db)
    return AgentOS(id="status-os", db=db, registry=Registry(dbs=[db]))


def _client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestRehydrationHttpStatus:
    def test_detail_read_of_a_broken_component_is_422(self, toolless_os):
        client = _client(toolless_os.get_app())

        response = client.get("/agents/broken-agent")

        assert response.status_code == 422
        assert "search" in response.json()["detail"]

    def test_broken_team_detail_read_is_422(self, toolless_os):
        client = _client(toolless_os.get_app())

        assert client.get("/teams/broken-team").status_code == 422

    def test_dispatch_of_a_broken_component_is_422(self, toolless_os):
        client = _client(toolless_os.get_app())

        response = client.post("/agents/broken-agent/runs", data={"message": "hi", "stream": "false"})

        assert response.status_code == 422

    def test_intact_component_and_missing_component_are_unaffected(self, toolless_os):
        client = _client(toolless_os.get_app())

        assert client.get("/agents/clean-agent").status_code == 200
        assert client.get("/agents/does-not-exist").status_code == 404
        # Listings stay readable so a broken component remains discoverable.
        assert client.get("/agents").status_code == 200

    def test_422_survives_a_caller_supplied_app(self, db):
        """AgentOS registers its exception handlers only when it owns the app,
        so the status has to come from the router rather than a handler."""
        model = OpenAIChat(id="gpt-4o-mini")
        Agent(id="broken-agent", name="Broken", model=model, tools=[_search]).save(db=db)
        mounted = AgentOS(id="mounted-os", db=db, registry=Registry(dbs=[db]), base_app=FastAPI())
        client = _client(mounted.get_app())

        response = client.get("/agents/broken-agent")

        assert response.status_code == 422
        assert "search" in response.json()["detail"]

    def test_dispatch_of_broken_components_is_422_on_caller_supplied_app(self, db):
        """The run endpoints resolve through resolve_agent/team/workflow, which
        must convert the refusal themselves: a caller-supplied app has no
        AgentOS exception handlers to fall back on."""
        from agno.workflow.step import Step
        from agno.workflow.workflow import Workflow

        model = OpenAIChat(id="gpt-4o-mini")
        agent = Agent(id="broken-agent", name="Broken", model=model, tools=[_search])
        agent.save(db=db)
        Team(id="broken-team", name="BrokenTeam", model=model, members=[], tools=[_search]).save(db=db)
        Workflow(id="broken-workflow", name="BrokenWF", steps=[Step(name="s1", agent=agent)]).save(db=db)
        mounted = AgentOS(id="mounted-dispatch-os", db=db, registry=Registry(dbs=[db]), base_app=FastAPI())
        client = _client(mounted.get_app())

        for path in (
            "/agents/broken-agent/runs",
            "/teams/broken-team/runs",
            "/workflows/broken-workflow/runs",
        ):
            response = client.post(path, data={"message": "hi", "stream": "false"})
            assert response.status_code == 422, path
            assert "registry" in response.json()["detail"], path

    def test_cancel_of_a_broken_component_is_not_blocked(self, toolless_os):
        """A drifted registry must never make a run uncancellable."""
        client = _client(toolless_os.get_app())

        assert client.post("/agents/broken-agent/runs/r1/cancel").status_code == 200
        assert client.post("/teams/broken-team/runs/r1/cancel").status_code == 200

    def test_run_history_of_a_broken_component_stays_readable(self, toolless_os):
        """Run detail/listing routes use the component only as a db handle."""
        client = _client(toolless_os.get_app())

        response = client.get("/agents/broken-agent/runs", params={"session_id": "s1"})
        assert response.status_code in (200, 404)
        # A 404 here may only mean the session is missing, never the component.
        assert response.json().get("detail") != "Agent not found"


class TestRegistryAutoCollection:
    def test_stored_schema_reference_resolves_from_code_components(self, db):
        """Schemas declared on code components are auto-collected, so a stored
        component referencing the same schema class loads."""
        from pydantic import BaseModel

        class Report(BaseModel):
            text: str

        model = OpenAIChat(id="gpt-4o-mini")
        Agent(id="stored-schema-agent", name="Stored", model=model, output_schema=Report).save(db=db)
        code_agent = Agent(id="code-schema-agent", name="Code", model=model, output_schema=Report)
        os_app = AgentOS(id="schema-os", db=db, agents=[code_agent])
        client = _client(os_app.get_app())

        assert client.get("/agents/stored-schema-agent").status_code == 200

    def test_vector_only_knowledge_is_mirrored_into_registry(self, db):
        """Knowledge handed to AgentOS(knowledge=[...]) resolves by name even
        without a contents_db; only the knowledge routes need one."""
        from agno.knowledge.knowledge import Knowledge

        kb = Knowledge(name="Docs KB")
        os_app = AgentOS(id="kb-os", db=db, knowledge=[kb])
        os_app.get_app()

        assert os_app.registry is not None
        assert os_app.registry.get_knowledge("Docs KB") is kb

    def test_stored_function_step_resolves_from_code_workflows(self, db):
        """Step callables on code workflows are auto-collected, so a stored
        workflow referencing the same function loads strictly."""
        from agno.workflow.step import Step, StepInput, StepOutput
        from agno.workflow.workflow import Workflow

        def enrich(step_input: StepInput) -> StepOutput:
            return StepOutput(content="x")

        code_wf = Workflow(id="code-wf", name="CodeWF", steps=[Step(name="s1", executor=enrich)])
        Workflow(id="stored-wf", name="StoredWF", steps=[Step(name="s1", executor=enrich)]).save(db=db)
        os_app = AgentOS(id="fn-os", db=db, workflows=[code_wf])
        client = _client(os_app.get_app())

        assert client.get("/workflows/stored-wf").status_code == 200


class TestBrokenWorkflowLifecycle:
    def test_broken_workflow_stays_listed_cancellable_and_distinguishable(self, db):
        """Lenient loading builds a degraded-but-real workflow: it stays in
        listings, its runs stay reachable, and cancel answers 200, while the
        detail read and dispatch refuse with 422 rather than 404."""
        from agno.workflow.step import Step, StepInput, StepOutput
        from agno.workflow.workflow import Workflow

        def summarize(step_input: StepInput) -> StepOutput:
            return StepOutput(content="s")

        Workflow(id="fn-wf", name="FnWF", steps=[Step(name="s1", executor=summarize)]).save(db=db)
        os_app = AgentOS(id="fnwf-os", db=db, registry=Registry(dbs=[db]))
        client = _client(os_app.get_app())

        assert client.get("/workflows/fn-wf").status_code == 422
        listing = client.get("/workflows")
        assert listing.status_code == 200
        assert "fn-wf" in [w["id"] for w in listing.json()]
        assert client.post("/workflows/fn-wf/runs", data={"message": "hi", "stream": "false"}).status_code == 422
        assert client.post("/workflows/fn-wf/runs/r1/cancel").status_code == 200
        runs = client.get("/workflows/fn-wf/runs", params={"session_id": "s1"})
        assert runs.json().get("detail") != "Workflow not found"


class TestMcpResolutionStrictness:
    def test_mcp_run_resolution_is_strict_and_cancel_is_lenient(self, toolless_os):
        """The MCP run tools refuse a broken component with the actionable
        message; the cancel tool resolves leniently so a drifted registry
        never makes a run uncancellable on that surface."""
        import asyncio

        from agno.os.mcp import _resolve_run_component

        toolless_os.get_app()

        with pytest.raises(Exception, match="not resolvable from the registry"):
            asyncio.run(_resolve_run_component(toolless_os, "agents", "broken-agent", user_id=None, session_id=None))

        agent = asyncio.run(
            _resolve_run_component(toolless_os, "agents", "broken-agent", user_id=None, session_id=None, strict=False)
        )
        assert agent.id == "broken-agent"
