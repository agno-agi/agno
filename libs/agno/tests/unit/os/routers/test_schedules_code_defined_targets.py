"""The REST schedule routes exempt code-defined targets from the draft refusal.

Same predicate as SchedulerTools (agno.tools.scheduler.adraft_endpoint_refusal /
adraft_target_refusal): a schedule aimed at a component this process defines in
code is allowed even while a catalog row of the same id carries only drafts,
because the run route resolves the code-defined component before it consults the
catalog. The router learns which components those are from the lists it is built
with; built without them, the catalog decides alone.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.schedules import get_schedule_router
from agno.os.settings import AgnoAPISettings


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="schedules-code-defined-db", db_file=str(tmp_path / "code_defined.db"))


def _client(db, **lists):
    app = FastAPI()
    app.include_router(get_schedule_router(os_db=db, settings=AgnoAPISettings(), **lists))
    return TestClient(app)


@pytest.fixture
def client(db):
    return _client(db, include_agents=[SimpleNamespace(id="news-agent")], include_teams=[SimpleNamespace(id="crew")])


@pytest.fixture
def blind_client(db):
    return _client(db)


def _draft_only(db, component_id, component_type=ComponentType.AGENT, user_id=None):
    db.upsert_component(component_id=component_id, component_type=component_type, name=component_id, user_id=user_id)
    db.upsert_config(component_id, config={"name": component_id}, stage="draft")


def _body(name, endpoint):
    return {
        "name": name,
        "endpoint": endpoint,
        "method": "POST",
        "payload": {"message": "x"},
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
    }


class TestCreateRoute:
    def test_code_defined_target_with_a_draft_row_is_created(self, db, client):
        _draft_only(db, "news-agent")
        resp = client.post("/schedules", json=_body("daily-news", "/agents/news-agent/runs"))
        assert resp.status_code == 201, resp.text

    def test_a_genuinely_draft_only_target_is_still_409(self, db, client):
        _draft_only(db, "db-only-agent")
        resp = client.post("/schedules", json=_body("armed", "/agents/db-only-agent/runs"))
        assert resp.status_code == 409, resp.text
        assert "no published version" in resp.json()["detail"]

    def test_without_the_lists_the_catalog_still_decides(self, db, blind_client):
        _draft_only(db, "news-agent")
        resp = blind_client.post("/schedules", json=_body("blind", "/agents/news-agent/runs"))
        assert resp.status_code == 409, resp.text

    def test_a_code_defined_agent_does_not_exempt_a_draft_team(self, db, client):
        _draft_only(db, "news-agent", component_type=ComponentType.TEAM)
        resp = client.post("/schedules", json=_body("wrong-type", "/teams/news-agent/runs"))
        assert resp.status_code == 409, resp.text

    def test_a_code_defined_team_is_exempt(self, db, client):
        _draft_only(db, "crew", component_type=ComponentType.TEAM)
        resp = client.post("/schedules", json=_body("crew-run", "/teams/crew/runs"))
        assert resp.status_code == 201, resp.text

    def test_an_archived_code_defined_target_is_still_409(self, db, client):
        db.upsert_component(component_id="news-agent", component_type=ComponentType.AGENT, name="news-agent")
        db.delete_component("news-agent")
        resp = client.post("/schedules", json=_body("archived", "/agents/news-agent/runs"))
        assert resp.status_code == 409, resp.text
        assert "archived" in resp.json()["detail"]


class TestRepointRoute:
    def _sid(self, client, name="plain", endpoint="/webhooks/notify"):
        resp = client.post("/schedules", json=_body(name, endpoint))
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def test_repoint_at_a_code_defined_target_with_a_draft_row_is_allowed(self, db, client):
        sid = self._sid(client)
        _draft_only(db, "news-agent")
        resp = client.patch(f"/schedules/{sid}", json={"endpoint": "/agents/news-agent/runs"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["endpoint"] == "/agents/news-agent/runs"

    def test_repoint_at_a_genuinely_draft_only_target_is_still_409(self, db, client):
        sid = self._sid(client, name="plain-2")
        _draft_only(db, "db-only-agent")
        resp = client.patch(f"/schedules/{sid}", json={"endpoint": "/agents/db-only-agent/runs"})
        assert resp.status_code == 409, resp.text

    def test_without_the_lists_the_repoint_is_still_409(self, db, blind_client):
        sid = self._sid(blind_client, name="plain-3")
        _draft_only(db, "news-agent")
        resp = blind_client.patch(f"/schedules/{sid}", json={"endpoint": "/agents/news-agent/runs"})
        assert resp.status_code == 409, resp.text


class TestEnableRoute:
    def _disabled_sid(self, db, client, name, endpoint):
        resp = client.post("/schedules", json=_body(name, endpoint))
        assert resp.status_code == 201, resp.text
        sid = resp.json()["id"]
        db.update_schedule(sid, enabled=False)
        return sid

    def test_enable_a_code_defined_target_that_later_got_a_draft_row(self, db, client):
        sid = self._disabled_sid(db, client, "news", "/agents/news-agent/runs")
        _draft_only(db, "news-agent")
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] in (True, 1)

    def test_enable_a_genuinely_draft_only_target_is_still_409(self, db, client):
        sid = self._disabled_sid(db, client, "db-only", "/agents/db-only-agent/runs")
        _draft_only(db, "db-only-agent")
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 409, resp.text
        assert "no published version" in resp.json()["detail"]

    def test_without_the_lists_the_enable_is_still_409(self, db, blind_client):
        sid = self._disabled_sid(db, blind_client, "news-blind", "/agents/news-agent/runs")
        _draft_only(db, "news-agent")
        resp = blind_client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 409, resp.text
