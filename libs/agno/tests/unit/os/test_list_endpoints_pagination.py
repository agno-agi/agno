"""Opt-in pagination on the GET /agents, /teams and /workflows list endpoints.

Without page/limit the endpoints keep returning a bare array, so existing clients
are unaffected. With either one they return a PaginatedResponse ({data, meta})
that pages over code-defined components followed by DB-loaded ones, counting
only what the caller is allowed to see.
"""

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.team import Team
from agno.workflow import Workflow

ROUTES = ["/agents", "/teams", "/workflows"]


def build_client(tmp_path, monkeypatch, authorization=False):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    # Two code-defined and three DB-loaded components per type, so pages can
    # straddle the boundary between the two sources.
    agents = [Agent(id=f"code-agent-{i}", name=f"Code Agent {i}", db=db) for i in (1, 2)]
    teams = [Team(id=f"code-team-{i}", name=f"Code Team {i}", members=[], db=db) for i in (1, 2)]
    workflows = [Workflow(id=f"code-wf-{i}", name=f"Code WF {i}", db=db, steps=[]) for i in (1, 2)]
    app = AgentOS(agents=agents, teams=teams, workflows=workflows, db=db, telemetry=False).get_app()

    monkeypatch.setattr(
        "agno.agent.agent.get_agents",
        lambda db, registry=None, exclude_component_ids=None, user_id=None: [
            Agent(id=f"db-agent-{i}", name=f"DB Agent {i}") for i in (1, 2, 3)
        ],
    )
    monkeypatch.setattr(
        "agno.team.team.get_teams",
        lambda db, registry=None, exclude_component_ids=None, user_id=None: [
            Team(id=f"db-team-{i}", name=f"DB Team {i}", members=[]) for i in (1, 2, 3)
        ],
    )
    monkeypatch.setattr(
        "agno.workflow.workflow.get_workflows",
        lambda db, registry=None, exclude_component_ids=None, user_id=None: [
            Workflow(id=f"db-wf-{i}", name=f"DB WF {i}", steps=[]) for i in (1, 2, 3)
        ],
    )

    if authorization:

        @app.middleware("http")
        async def _enable_authz(request, call_next):
            request.state.authorization_enabled = True
            return await call_next(request)

        # The caller cannot see the last DB-loaded component of each type
        async def scoped_filter(request, resources, resource_type):
            return [r for r in resources if not str(getattr(r, "id", "")).endswith("-3")]

        async def scoped_ids(request, kind):
            return {"scoped"}

        monkeypatch.setattr("agno.os.auth.afilter_resources_by_access", scoped_filter)
        monkeypatch.setattr("agno.os.auth.aget_accessible_resources", scoped_ids)

    return TestClient(app, raise_server_exceptions=False)


def ids_of(items):
    return [item.get("id") or item.get("workflow_id") for item in items]


def prefix(route):
    return {"/agents": "agent", "/teams": "team", "/workflows": "wf"}[route]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    return build_client(tmp_path, monkeypatch)


@pytest.mark.parametrize("route", ROUTES)
class TestOptInPagination:
    def test_without_params_returns_the_full_bare_list(self, client, route):
        response = client.get(route)

        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert isinstance(body, list)
        p = prefix(route)
        assert ids_of(body) == [f"code-{p}-1", f"code-{p}-2", f"db-{p}-1", f"db-{p}-2", f"db-{p}-3"]

    def test_page_spans_code_and_db_components(self, client, route):
        response = client.get(route, params={"page": 2, "limit": 2})

        assert response.status_code == 200, response.text[:300]
        body = response.json()
        p = prefix(route)
        assert ids_of(body["data"]) == [f"db-{p}-1", f"db-{p}-2"]
        assert body["meta"]["page"] == 2
        assert body["meta"]["limit"] == 2
        assert body["meta"]["total_count"] == 5
        assert body["meta"]["total_pages"] == 3

    def test_limit_alone_starts_at_page_one(self, client, route):
        body = client.get(route, params={"limit": 3}).json()

        p = prefix(route)
        assert ids_of(body["data"]) == [f"code-{p}-1", f"code-{p}-2", f"db-{p}-1"]
        assert body["meta"]["page"] == 1

    def test_page_alone_uses_default_limit(self, client, route):
        body = client.get(route, params={"page": 1}).json()

        assert len(body["data"]) == 5
        assert body["meta"]["limit"] == 20
        assert body["meta"]["total_pages"] == 1

    def test_page_past_the_end_is_empty(self, client, route):
        body = client.get(route, params={"page": 4, "limit": 2}).json()

        assert body["data"] == []
        assert body["meta"]["total_count"] == 5

    def test_rejects_page_zero(self, client, route):
        assert client.get(route, params={"page": 0}).status_code == 422


@pytest.mark.parametrize("route", ROUTES)
def test_total_count_excludes_components_the_caller_cannot_see(tmp_path, monkeypatch, route):
    client = build_client(tmp_path, monkeypatch, authorization=True)

    body = client.get(route, params={"page": 1, "limit": 10}).json()

    p = prefix(route)
    assert f"db-{p}-3" not in ids_of(body["data"])
    assert body["meta"]["total_count"] == 4


@pytest.mark.parametrize("route", ROUTES)
def test_rejects_limit_above_the_cap(client, route):
    assert client.get(route, params={"limit": 101}).status_code == 422
    assert client.get(route, params={"limit": 100}).status_code == 200
