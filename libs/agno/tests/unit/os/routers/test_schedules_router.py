"""Unit tests for schedule router endpoints."""

import pytest
from fastapi import HTTPException

# ── get_db helper ──────────────────────────────────────────────────────


async def test_get_db_selects_matching_db_id(tmp_path):
    from agno.db.sqlite import SqliteDb
    from agno.os.routers.schedules.router import get_db

    agent_db = SqliteDb(db_file=str(tmp_path / "agent.db"), id="agent-db")
    os_db = SqliteDb(db_file=str(tmp_path / "os.db"), id="os-db")

    dbs = {
        agent_db.id: [agent_db],
        os_db.id: [os_db],
    }

    # Without specifying db_id, get_db returns the first sync DB it sees.
    selected_default = await get_db(dbs)
    assert selected_default is agent_db

    # With db_id, get_db consistently returns the matching DB.
    selected = await get_db(dbs, db_id=os_db.id)
    assert selected is os_db


# ── Validation helpers ─────────────────────────────────────────────────


class TestNormalizeHttpMethod:
    def test_valid_methods(self):
        from agno.os.routers.schedules.router import _normalize_http_method

        assert _normalize_http_method("post") == "POST"
        assert _normalize_http_method("GET") == "GET"
        assert _normalize_http_method(" put ") == "PUT"
        assert _normalize_http_method("delete") == "DELETE"

    def test_invalid_method_raises(self):
        from agno.os.routers.schedules.router import _normalize_http_method

        with pytest.raises(HTTPException) as exc_info:
            _normalize_http_method("PATCH")
        assert exc_info.value.status_code == 400
        assert "Unsupported method" in exc_info.value.detail


class TestValidateEndpointPath:
    def test_valid_path(self):
        from agno.os.routers.schedules.router import _validate_endpoint_path

        assert _validate_endpoint_path("/agents/my-agent/runs") == "/agents/my-agent/runs"
        assert _validate_endpoint_path("  /foo  ") == "/foo"

    def test_missing_leading_slash(self):
        from agno.os.routers.schedules.router import _validate_endpoint_path

        with pytest.raises(HTTPException) as exc_info:
            _validate_endpoint_path("agents/my-agent/runs")
        assert exc_info.value.status_code == 400
        assert "must start with '/'" in exc_info.value.detail

    def test_full_url_rejected(self):
        from agno.os.routers.schedules.router import _validate_endpoint_path

        # URL without leading "/" is caught by the first check
        with pytest.raises(HTTPException) as exc_info:
            _validate_endpoint_path("http://example.com/agents/runs")
        assert exc_info.value.status_code == 400

        # URL with leading "/" but containing "://" is caught by the second check
        with pytest.raises(HTTPException) as exc_info:
            _validate_endpoint_path("/http://evil.com")
        assert exc_info.value.status_code == 400
        assert "relative path" in exc_info.value.detail


# ── Schema validation ──────────────────────────────────────────────────


class TestScheduleCreateRequestValidation:
    def test_valid_name(self):
        from agno.os.routers.schedules.schema import ScheduleCreateRequest

        req = ScheduleCreateRequest(
            name="daily-report",
            endpoint="/agents/my-agent/runs",
            cron_expr="0 3 * * *",
        )
        assert req.name == "daily-report"

    def test_name_with_dots_and_underscores(self):
        from agno.os.routers.schedules.schema import ScheduleCreateRequest

        req = ScheduleCreateRequest(
            name="my.schedule_v2",
            endpoint="/agents/my-agent/runs",
            cron_expr="0 3 * * *",
        )
        assert req.name == "my.schedule_v2"

    def test_name_special_chars_rejected(self):
        from pydantic import ValidationError

        from agno.os.routers.schedules.schema import ScheduleCreateRequest

        with pytest.raises(ValidationError):
            ScheduleCreateRequest(
                name="invalid name!",
                endpoint="/agents/my-agent/runs",
                cron_expr="0 3 * * *",
            )

    def test_name_too_long_rejected(self):
        from pydantic import ValidationError

        from agno.os.routers.schedules.schema import ScheduleCreateRequest

        with pytest.raises(ValidationError):
            ScheduleCreateRequest(
                name="a" * 256,
                endpoint="/agents/my-agent/runs",
                cron_expr="0 3 * * *",
            )

    def test_name_leading_hyphen_rejected(self):
        from pydantic import ValidationError

        from agno.os.routers.schedules.schema import ScheduleCreateRequest

        with pytest.raises(ValidationError):
            ScheduleCreateRequest(
                name="-invalid",
                endpoint="/agents/my-agent/runs",
                cron_expr="0 3 * * *",
            )

    def test_empty_name_rejected(self):
        from pydantic import ValidationError

        from agno.os.routers.schedules.schema import ScheduleCreateRequest

        with pytest.raises(ValidationError):
            ScheduleCreateRequest(
                name="",
                endpoint="/agents/my-agent/runs",
                cron_expr="0 3 * * *",
            )


# ── Router endpoint tests ─────────────────────────────────────────────


@pytest.fixture()
def schedule_app(tmp_path):
    """Create a FastAPI app with the schedule router backed by SQLite."""
    from fastapi import FastAPI

    from agno.db.sqlite import SqliteDb
    from agno.os.routers.schedules.router import get_schedule_router
    from agno.os.settings import AgnoAPISettings

    db = SqliteDb(db_file=str(tmp_path / "sched.db"), id="test-db")
    dbs = {db.id: [db]}

    settings = AgnoAPISettings()
    settings.os_security_key = None  # disable auth for testing

    router = get_schedule_router(dbs=dbs, settings=settings, db_id=db.id)
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture()
def client(schedule_app):
    """Synchronous TestClient for the schedule app."""
    from starlette.testclient import TestClient

    return TestClient(schedule_app)


_VALID_CREATE = {
    "name": "test-schedule",
    "endpoint": "/agents/my-agent/runs",
    "cron_expr": "0 3 * * *",
}


class TestScheduleEndpoints:
    def test_create_schedule(self, client):
        resp = client.post("/schedules", json=_VALID_CREATE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-schedule"
        assert data["cron_expr"] == "0 3 * * *"
        assert data["enabled"] is True
        assert data["next_run_at"] is not None

    def test_create_and_get_schedule(self, client):
        resp = client.post("/schedules", json=_VALID_CREATE)
        schedule_id = resp.json()["id"]

        resp = client.get(f"/schedules/{schedule_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == schedule_id

    def test_get_nonexistent_schedule_returns_404(self, client):
        resp = client.get("/schedules/nonexistent-id")
        assert resp.status_code == 404

    def test_duplicate_name_rejected(self, client):
        client.post("/schedules", json=_VALID_CREATE)

        resp = client.post("/schedules", json=_VALID_CREATE)
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_invalid_cron_rejected(self, client):
        resp = client.post(
            "/schedules",
            json={**_VALID_CREATE, "name": "bad-cron", "cron_expr": "not-a-cron"},
        )
        assert resp.status_code == 400

    def test_invalid_endpoint_rejected(self, client):
        resp = client.post(
            "/schedules",
            json={**_VALID_CREATE, "name": "bad-ep", "endpoint": "http://evil.com/hack"},
        )
        assert resp.status_code == 400

    def test_list_schedules(self, client):
        client.post("/schedules", json=_VALID_CREATE)
        client.post("/schedules", json={**_VALID_CREATE, "name": "second"})

        resp = client.get("/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["schedules"]) == 2

    def test_list_schedules_filter_enabled(self, client):
        client.post("/schedules", json=_VALID_CREATE)
        client.post("/schedules", json={**_VALID_CREATE, "name": "disabled", "enabled": False})

        resp = client.get("/schedules", params={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_update_schedule(self, client):
        resp = client.post("/schedules", json=_VALID_CREATE)
        schedule_id = resp.json()["id"]

        resp = client.patch(f"/schedules/{schedule_id}", json={"description": "updated"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "updated"

    def test_delete_schedule(self, client):
        resp = client.post("/schedules", json=_VALID_CREATE)
        schedule_id = resp.json()["id"]

        resp = client.delete(f"/schedules/{schedule_id}")
        assert resp.status_code == 204

        resp = client.get(f"/schedules/{schedule_id}")
        assert resp.status_code == 404

    def test_enable_disable(self, client):
        resp = client.post("/schedules", json=_VALID_CREATE)
        schedule_id = resp.json()["id"]

        # Disable
        resp = client.post(f"/schedules/{schedule_id}/disable")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

        # Enable
        resp = client.post(f"/schedules/{schedule_id}/enable")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_schedule_runs_empty(self, client):
        resp = client.post("/schedules", json=_VALID_CREATE)
        schedule_id = resp.json()["id"]

        resp = client.get(f"/schedules/{schedule_id}/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["runs"] == []
