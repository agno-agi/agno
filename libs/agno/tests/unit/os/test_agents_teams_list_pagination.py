from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.routers.agents.schema import AgentResponse
from agno.os.routers.teams.schema import TeamResponse
from agno.os.schema import WorkflowSummaryResponse
from agno.team import Team
from agno.workflow import Workflow


def make_client(resource_type, count):
    if resource_type == "agents":
        resources = [Agent(id=f"agent-{i}", name=f"Agent {i}") for i in range(count)]
        os = AgentOS(
            agents=resources,
            teams=None if resources else [Team(id="sentinel-team", name="Sentinel Team", members=[])],
            telemetry=False,
        )
    elif resource_type == "teams":
        resources = [Team(id=f"team-{i}", name=f"Team {i}", members=[]) for i in range(count)]
        os = AgentOS(
            agents=None if resources else [Agent(id="sentinel-agent", name="Sentinel Agent")],
            teams=resources,
            telemetry=False,
        )
    else:
        resources = [Workflow(id=f"workflow-{i}", name=f"Workflow {i}", steps=[]) for i in range(count)]
        os = AgentOS(
            agents=None if resources else [Agent(id="sentinel-agent", name="Sentinel Agent")],
            workflows=resources,
            telemetry=False,
        )
    return SimpleNamespace(client=TestClient(os.get_app()), resources=resources)


def assert_meta(body, **expected):
    assert {key: body["meta"][key] for key in expected} == expected


@pytest.mark.parametrize("resource_type", ["agents", "teams", "workflows"])
class TestListPagination:
    def test_default_first_page(self, resource_type):
        harness = make_client(resource_type, 25)

        response = harness.client.get(f"/{resource_type}")

        assert response.status_code == 200
        body = response.json()
        assert [item["id"] for item in body["data"]] == [f"{resource_type[:-1]}-{i}" for i in range(20)]
        assert_meta(body, page=1, limit=20, total_pages=2, total_count=25)

    def test_page_beyond_range_returns_empty_data(self, resource_type):
        harness = make_client(resource_type, 3)

        response = harness.client.get(f"/{resource_type}", params={"limit": 2, "page": 3})

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert_meta(body, page=3, limit=2, total_pages=2, total_count=3)

    def test_limit_upper_bound(self, resource_type):
        harness = make_client(resource_type, 1)

        response = harness.client.get(f"/{resource_type}", params={"limit": 1000})

        assert response.status_code == 200
        assert response.json()["meta"]["limit"] == 1000
        assert harness.client.get(f"/{resource_type}", params={"limit": 1001}).status_code == 422

    def test_empty_list(self, resource_type):
        harness = make_client(resource_type, 0)

        response = harness.client.get(f"/{resource_type}")

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert_meta(body, page=1, limit=20, total_pages=0, total_count=0)

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": -1}, {"page": 0}, {"page": -1}])
    def test_invalid_pagination(self, resource_type, params):
        harness = make_client(resource_type, 1)
        assert harness.client.get(f"/{resource_type}", params=params).status_code == 422

    def test_non_default_page_only_serializes_current_page(self, resource_type, monkeypatch):
        harness = make_client(resource_type, 5)
        serialized_ids = []

        if resource_type == "agents":

            async def from_agent(cls, agent, is_component=False):
                serialized_ids.append(agent.id)
                return AgentResponse(id=agent.id, name=agent.name, is_component=is_component)

            monkeypatch.setattr(AgentResponse, "from_agent", classmethod(from_agent))
        elif resource_type == "teams":

            async def from_team(cls, team, is_component=False):
                serialized_ids.append(team.id)
                return TeamResponse(id=team.id, name=team.name, is_component=is_component)

            monkeypatch.setattr(TeamResponse, "from_team", classmethod(from_team))

        else:

            def from_workflow(cls, workflow, is_component=False):
                serialized_ids.append(workflow.id)
                return WorkflowSummaryResponse(id=workflow.id, name=workflow.name, is_component=is_component)

            monkeypatch.setattr(WorkflowSummaryResponse, "from_workflow", classmethod(from_workflow))

        response = harness.client.get(f"/{resource_type}", params={"limit": 2, "page": 2})

        assert response.status_code == 200
        expected_ids = [f"{resource_type[:-1]}-2", f"{resource_type[:-1]}-3"]
        assert [item["id"] for item in response.json()["data"]] == expected_ids
        assert serialized_ids == expected_ids
        assert_meta(response.json(), page=2, limit=2, total_pages=3, total_count=5)


def test_workflow_pagination_filters_and_combines_sources(tmp_path, monkeypatch):
    from agno.db.sqlite import SqliteDb

    configured = [Workflow(id=name, name=name, steps=[]) for name in ["hidden-code", "code"]]
    stored = [Workflow(id=name, name=name, steps=[]) for name in ["hidden-db", "db-1", "db-2"]]
    db = SqliteDb(db_file=str(tmp_path / "pagination.db"))
    app = AgentOS(workflows=configured, db=db, telemetry=False).get_app()

    @app.middleware("http")
    async def authorize(request, call_next):
        request.state.authorization_enabled = True
        return await call_next(request)

    monkeypatch.setattr("agno.os.auth.get_accessible_resources", lambda request, kind: {"allowed"})
    monkeypatch.setattr(
        "agno.os.auth.filter_resources_by_access",
        lambda request, resources, kind: [r for r in resources if not r.id.startswith("hidden")],
    )
    monkeypatch.setattr("agno.workflow.workflow.get_workflows", lambda **kwargs: stored)
    serialized = []

    def from_workflow(cls, workflow, is_component=False):
        serialized.append((workflow.id, is_component))
        return WorkflowSummaryResponse(id=workflow.id, name=workflow.name, is_component=is_component)

    monkeypatch.setattr(WorkflowSummaryResponse, "from_workflow", classmethod(from_workflow))
    client = TestClient(app)
    first = client.get("/workflows", params={"limit": 2}).json()
    assert [w["id"] for w in first["data"]] == ["code", "db-1"]
    assert serialized == [("code", False), ("db-1", True)]
    assert_meta(first, total_count=3, total_pages=2, page=1, limit=2)
    serialized.clear()
    second = client.get("/workflows", params={"limit": 2, "page": 2}).json()
    assert [w["id"] for w in second["data"]] == ["db-2"]
    assert serialized == [("db-2", True)]
    assert_meta(second, total_count=3, total_pages=2, page=2, limit=2)
