"""Tests for the schedule API router — validation rules, CRUD flows with mocked DB."""

import time
from contextlib import contextmanager
from typing import Dict
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.routers.schedules.router import get_schedule_router
from agno.os.settings import AgnoAPISettings

# ---------------------------------------------------------------------------
# Fake DB adapter
# ---------------------------------------------------------------------------


class FakeSchedulerDb:
    def __init__(self):
        self._schedules: Dict[str, Dict] = {}
        self._runs: Dict[str, Dict] = {}

    async def get_schedules(self, enabled=None, limit=100, offset=0):
        items = list(self._schedules.values())
        if enabled is not None:
            items = [s for s in items if s["enabled"] == enabled]
        return items[offset : offset + limit]

    async def get_schedule(self, schedule_id):
        return self._schedules.get(schedule_id)

    async def get_schedule_by_name(self, name):
        for s in self._schedules.values():
            if s["name"] == name:
                return s
        return None

    async def create_schedule(self, schedule_dict):
        self._schedules[schedule_dict["id"]] = schedule_dict
        return schedule_dict

    async def update_schedule(self, schedule_id, **kwargs):
        s = self._schedules.get(schedule_id)
        if s is None:
            return None
        s.update(kwargs)
        return s

    async def delete_schedule(self, schedule_id):
        if schedule_id in self._schedules:
            del self._schedules[schedule_id]
            return True
        return False

    async def get_schedule_runs(self, schedule_id, limit=100, offset=0):
        items = [r for r in self._runs.values() if r["schedule_id"] == schedule_id]
        return items[offset : offset + limit]

    async def get_schedule_run(self, run_id):
        return self._runs.get(run_id)

    async def create_schedule_run(self, run_dict):
        self._runs[run_dict["id"]] = run_dict
        return run_dict

    async def update_schedule_run(self, run_id, **kwargs):
        r = self._runs.get(run_id)
        if r:
            r.update(kwargs)
        return r


# ---------------------------------------------------------------------------
# Patch helpers — mock away croniter/pytz deps so tests run without them
# ---------------------------------------------------------------------------


@contextmanager
def _mock_scheduler_deps(
    validate_cron=True,
    validate_tz=True,
    next_run=None,
):
    """Patch all scheduler dependency functions for the router tests."""
    if next_run is None:
        next_run = int(time.time()) + 60
    with (
        patch("agno.scheduler.cron._require_croniter"),
        patch("agno.scheduler.cron._require_pytz"),
        patch("agno.scheduler.cron.validate_cron_expr", return_value=validate_cron),
        patch("agno.scheduler.cron.validate_timezone", return_value=validate_tz),
        patch("agno.scheduler.cron.compute_next_run", return_value=next_run),
    ):
        yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    return FakeSchedulerDb()


@pytest.fixture
def client(db):
    settings = AgnoAPISettings()
    router = get_schedule_router(os_db=db, settings=settings)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _valid_create_body(**overrides):
    body = {
        "name": "my-schedule",
        "cron_expr": "*/5 * * * *",
        "endpoint": "/agents/test-agent/runs",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestScheduleValidation:
    def test_name_must_start_with_alphanumeric(self, client):
        resp = client.post("/schedules", json=_valid_create_body(name="-bad"))
        assert resp.status_code == 422

    def test_name_allows_dots_underscores_dashes(self, client):
        with _mock_scheduler_deps():
            resp = client.post("/schedules", json=_valid_create_body(name="my.schedule_v2-test"))
        assert resp.status_code == 201

    def test_endpoint_must_start_with_slash(self, client):
        resp = client.post("/schedules", json=_valid_create_body(endpoint="no-slash"))
        assert resp.status_code == 422

    def test_endpoint_rejects_full_url(self, client):
        resp = client.post("/schedules", json=_valid_create_body(endpoint="http://example.com/path"))
        assert resp.status_code == 422

    def test_invalid_method(self, client):
        resp = client.post("/schedules", json=_valid_create_body(method="OPTIONS"))
        assert resp.status_code == 422

    def test_valid_methods(self, client):
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            with _mock_scheduler_deps():
                resp = client.post(
                    "/schedules",
                    json=_valid_create_body(name=f"sched-{method.lower()}", method=method),
                )
            assert resp.status_code == 201, f"Method {method} should be valid"

    def test_invalid_cron(self, client):
        with _mock_scheduler_deps(validate_cron=False):
            resp = client.post("/schedules", json=_valid_create_body(cron_expr="bad"))
        assert resp.status_code == 422

    def test_invalid_timezone(self, client):
        with _mock_scheduler_deps(validate_tz=False):
            resp = client.post("/schedules", json=_valid_create_body())
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CRUD endpoint tests
# ---------------------------------------------------------------------------


class TestScheduleCRUD:
    def _create(self, client, **overrides):
        with _mock_scheduler_deps():
            return client.post("/schedules", json=_valid_create_body(**overrides))

    def test_create_returns_201(self, client):
        resp = self._create(client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-schedule"
        assert data["enabled"] is True
        assert data["id"] is not None

    def test_create_duplicate_name_409(self, client):
        resp1 = self._create(client, name="dup")
        assert resp1.status_code == 201
        resp2 = self._create(client, name="dup")
        assert resp2.status_code == 409

    def test_get_schedule(self, client):
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        resp2 = client.get(f"/schedules/{schedule_id}")
        assert resp2.status_code == 200
        assert resp2.json()["id"] == schedule_id

    def test_get_not_found(self, client):
        resp = client.get("/schedules/nonexistent")
        assert resp.status_code == 404

    def test_list_schedules(self, client):
        self._create(client, name="s1")
        self._create(client, name="s2")
        resp = client.get("/schedules")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_update_schedule(self, client):
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        resp2 = client.patch(f"/schedules/{schedule_id}", json={"description": "updated"})
        assert resp2.status_code == 200
        assert resp2.json()["description"] == "updated"

    def test_update_partial_merge(self, client):
        """Only fields included in the request should be updated."""
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        original = resp.json()

        # Update only description, other fields should remain unchanged
        resp2 = client.patch(f"/schedules/{schedule_id}", json={"description": "new desc"})
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["description"] == "new desc"
        assert data["name"] == original["name"]
        assert data["cron_expr"] == original["cron_expr"]
        assert data["endpoint"] == original["endpoint"]
        assert data["max_retries"] == original["max_retries"]

    def test_update_empty_body_returns_existing(self, client):
        """An update with no fields should return the existing schedule unchanged."""
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        resp2 = client.patch(f"/schedules/{schedule_id}", json={})
        assert resp2.status_code == 200
        assert resp2.json()["id"] == schedule_id

    def test_update_not_found(self, client):
        resp = client.patch("/schedules/nonexistent", json={"description": "x"})
        assert resp.status_code == 404

    def test_delete_schedule(self, client):
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        resp2 = client.delete(f"/schedules/{schedule_id}")
        assert resp2.status_code == 204
        resp3 = client.get(f"/schedules/{schedule_id}")
        assert resp3.status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/schedules/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Enable / disable tests
# ---------------------------------------------------------------------------


class TestScheduleEnableDisable:
    def _create(self, client, **overrides):
        with _mock_scheduler_deps():
            return client.post("/schedules", json=_valid_create_body(**overrides))

    def test_disable(self, client):
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        resp2 = client.post(f"/schedules/{schedule_id}/disable")
        assert resp2.status_code == 200
        assert resp2.json()["enabled"] is False

    def test_enable(self, client):
        resp = self._create(client)
        schedule_id = resp.json()["id"]
        client.post(f"/schedules/{schedule_id}/disable")
        with _mock_scheduler_deps():
            resp2 = client.post(f"/schedules/{schedule_id}/enable")
        assert resp2.status_code == 200
        assert resp2.json()["enabled"] is True


# ---------------------------------------------------------------------------
# Trigger tests
# ---------------------------------------------------------------------------


def _seed_schedule(db, schedule_id="s1"):
    now = int(time.time())
    db._schedules[schedule_id] = {
        "id": schedule_id,
        "name": "test",
        "cron_expr": "* * * * *",
        "endpoint": "/agents/test/runs",
        "method": "POST",
        "enabled": True,
        "next_run_at": now,
        "created_at": now,
        "updated_at": None,
        "description": None,
        "payload": None,
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "locked_by": None,
        "locked_at": None,
    }


class TestScheduleTrigger:
    def test_trigger_no_poller_no_executor_503(self, client, db):
        _seed_schedule(db)
        resp = client.post("/schedules/s1/trigger")
        assert resp.status_code == 503

    def test_trigger_not_found(self, client):
        resp = client.post("/schedules/nonexistent/trigger")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Run history tests
# ---------------------------------------------------------------------------


class TestScheduleRuns:
    def test_list_runs_empty(self, client, db):
        _seed_schedule(db)
        resp = client.get("/schedules/s1/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_run_not_found(self, client, db):
        _seed_schedule(db)
        resp = client.get("/schedules/s1/runs/nonexistent")
        assert resp.status_code == 404
