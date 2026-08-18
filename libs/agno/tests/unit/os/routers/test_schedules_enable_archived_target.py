"""POST /schedules/{id}/enable refuses archived targets and allows code-defined ones.

B5 REST surface: the enable route applies the same predicate as
SchedulerTools.enable_schedule (agno.tools.scheduler.archived_target_refusal):
refuse with 409 if and only if the schedule's provenance target, or the target
named by a system "target_archived:<type>:<id>" disabled_reason, is a really
archived component row. A target with no catalog row is a live code-defined
component and must re-enable freely.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.schedules import get_schedule_router
from agno.os.settings import AgnoAPISettings
from agno.tools.scheduler import SchedulerTools


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="schedules-enable-guard-db", db_file=str(tmp_path / "enable_guard.db"))


@pytest.fixture
def tools(db):
    return SchedulerTools(db=db, default_endpoint="/agents/code-agent/runs", default_payload={"message": "go"})


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(get_schedule_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app)


def _create(tools, name, endpoint=None):
    kwargs = {"name": name, "cron": "0 9 * * *", "payload": '{"message": "x"}'}
    if endpoint is not None:
        kwargs["endpoint"] = endpoint
    out = json.loads(tools.create_schedule(**kwargs))
    assert out.get("status") == "created", out
    return out["id"]


def _archive_with_cascade(db, component_id):
    db.upsert_component(component_id=component_id, component_type=ComponentType.AGENT, name=component_id)
    db.delete_component(component_id)
    db.disable_schedules_for_target("agent", component_id, reason=f"target_archived:agent:{component_id}")


class TestEnableRouteArchivedTargetGuard:
    def test_plain_schedule_enables(self, db, tools, client):
        sid = _create(tools, "plain", endpoint="/webhooks/notify")
        db.update_schedule(sid, enabled=False)
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] in (True, 1)

    def test_code_defined_target_enables(self, db, tools, client):
        # Provenance names a target that has no components row: registry/code-defined
        sid = _create(tools, "code-defined")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="code-agent")
        db.update_schedule(sid, enabled=False)
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 200, resp.text
        assert resp.json()["enabled"] in (True, 1)

    def test_archived_provenance_tagged_target_is_409(self, db, tools, client):
        sid = _create(tools, "tagged", endpoint="/agents/arch-agent/runs")
        db.stamp_schedule_provenance(sid, managed_by="studio", target_type="agent", target_id="arch-agent")
        _archive_with_cascade(db, "arch-agent")
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert "agent" in detail and "arch-agent" in detail
        assert "Restore the component first" in detail
        row = db.get_schedule(sid)
        assert row["enabled"] in (False, 0)
        assert row["disabled_reason"] == "target_archived:agent:arch-agent"

    def test_generic_row_disabled_by_cascade_is_409(self, db, tools, client):
        # No provenance columns; only the system disabled_reason names the target
        sid = _create(tools, "generic", endpoint="/agents/arch-agent/runs")
        _archive_with_cascade(db, "arch-agent")
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 409, resp.text
        assert "Restore the component first" in resp.json()["detail"]

    def test_enable_allowed_after_restore_and_reason_clears(self, db, tools, client):
        sid = _create(tools, "revivable", endpoint="/agents/arch-agent/runs")
        _archive_with_cascade(db, "arch-agent")
        assert db.restore_component("arch-agent")
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 200, resp.text
        row = db.get_schedule(sid)
        assert row["enabled"] in (True, 1)
        assert row["disabled_reason"] is None

    def test_enable_allowed_after_hard_delete(self, db, tools, client):
        # A hard-deleted target has no row to restore; the stale reason must not brick the row
        sid = _create(tools, "orphaned", endpoint="/agents/arch-agent/runs")
        _archive_with_cascade(db, "arch-agent")
        db.delete_component("arch-agent", hard_delete=True)
        resp = client.post(f"/schedules/{sid}/enable")
        assert resp.status_code == 200, resp.text
