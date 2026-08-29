"""RBAC filtering covers DB-loaded components on the list endpoints.

The list endpoints filter REGISTRY components through
filter_resources_by_access when authorization is enabled - but the
DB-loaded components appended below that check bypassed the filter on
teams and workflows (agents already filtered): a caller whose scope
excluded a team or workflow still received its full config from
GET /teams and GET /workflows. These tests scope a caller to registry
components only and assert DB-loaded ones stay invisible, with agents
pinned as the reference behavior.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.team import Team
from agno.workflow import Workflow


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="reg-agent", name="Reg Agent", db=db)
    team = Team(id="reg-team", name="Reg Team", members=[], db=db)
    workflow = Workflow(id="reg-wf", name="Reg WF", db=db, steps=[])
    app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], db=db, telemetry=False).get_app()

    # Authorization enabled for every request (the middleware the real
    # deployment installs sets this from the JWT/scopes config)
    @app.middleware("http")
    async def _enable_authz(request, call_next):
        request.state.authorization_enabled = True
        return await call_next(request)

    # The caller's scope: registry components visible, db-* components not
    def scoped_filter(request, resources, resource_type):
        return [r for r in resources if not str(getattr(r, "id", "")).startswith("db-")]

    monkeypatch.setattr("agno.os.auth.filter_resources_by_access", scoped_filter)
    monkeypatch.setattr("agno.os.auth.get_accessible_resources", lambda request, kind: {"reg"})

    # The DB hands back one out-of-scope component per type
    monkeypatch.setattr(
        "agno.agent.agent.get_agents",
        lambda db, registry=None, exclude_component_ids=None, user_id=None: [Agent(id="db-agent", name="DB Agent")],
    )
    monkeypatch.setattr(
        "agno.team.team.get_teams",
        lambda db, registry=None, exclude_component_ids=None, user_id=None: [
            Team(id="db-team", name="DB Team", members=[])
        ],
    )
    monkeypatch.setattr(
        "agno.workflow.workflow.get_workflows",
        lambda db, registry=None, exclude_component_ids=None, user_id=None: [
            Workflow(id="db-wf", name="DB WF", steps=[])
        ],
    )
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False))


def ids_of(response):
    assert response.status_code == 200, response.text[:300]
    return {item.get("id") or item.get("workflow_id") for item in response.json()}


class TestDbLoadedComponentsAreScoped:
    def test_teams_list_filters_db_loaded_teams(self, harness):
        ids = ids_of(harness.client.get("/teams"))
        assert "reg-team" in ids
        assert "db-team" not in ids, "an out-of-scope DB-loaded team leaked through GET /teams"

    def test_workflows_list_filters_db_loaded_workflows(self, harness):
        ids = ids_of(harness.client.get("/workflows"))
        assert "reg-wf" in ids
        assert "db-wf" not in ids, "an out-of-scope DB-loaded workflow leaked through GET /workflows"

    def test_agents_list_keeps_filtering_db_loaded_agents(self, harness):
        """The reference behavior teams/workflows now mirror."""
        ids = ids_of(harness.client.get("/agents"))
        assert "reg-agent" in ids
        assert "db-agent" not in ids
