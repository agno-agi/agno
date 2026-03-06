"""Tests for the schedule REST API router."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.routers.schedules import get_schedule_router
from agno.os.settings import AgnoAPISettings

# =============================================================================
# Fixtures
# =============================================================================


def _make_schedule_dict(**overrides):
    """Create a schedule dict with sensible defaults."""
    now = int(time.time())
    d = {
        "id": "sched-1",
        "name": "daily-check",
        "description": None,
        "method": "POST",
        "endpoint": "/agents/my-agent/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        "next_run_at": now + 3600,
        "locked_by": None,
        "locked_at": None,
        "created_at": now,
        "updated_at": None,
    }
    d.update(overrides)
    return d


@pytest.fixture
def mock_db():
    """Create a mock DB with schedule methods."""
    db = MagicMock()
    db.get_schedules = MagicMock(return_value=[])
    db.get_schedule = MagicMock(return_value=None)
    db.get_schedule_by_name = MagicMock(return_value=None)
    db.create_schedule = MagicMock(return_value=_make_schedule_dict())
    db.update_schedule = MagicMock(return_value=_make_schedule_dict())
    db.delete_schedule = MagicMock(return_value=True)
    db.get_schedule_runs = MagicMock(return_value=[])
    db.get_schedule_run = MagicMock(return_value=None)
    return db


@pytest.fixture
def settings():
    """Create test settings with auth disabled (no security key = auth disabled)."""
    return AgnoAPISettings()


@pytest.fixture
def client(mock_db, settings):
    app = FastAPI()
    router = get_schedule_router(os_db=mock_db, settings=settings)
    app.include_router(router)
    return TestClient(app)


# =============================================================================
# Tests: GET /schedules
# =============================================================================


class TestListSchedules:
    def test_empty_list(self, client, mock_db):
        mock_db.get_schedules = MagicMock(return_value=([], 0))
        resp = client.get("/schedules")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_returns_schedules(self, client, mock_db):
        schedules = [_make_schedule_dict(id="s1"), _make_schedule_dict(id="s2", name="second")]
        mock_db.get_schedules = MagicMock(return_value=(schedules, 2))
        resp = client.get("/schedules")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["id"] == "s1"

    def test_filter_enabled(self, client, mock_db):
        mock_db.get_schedules = MagicMock(return_value=([], 0))
        client.get("/schedules?enabled=true")
        mock_db.get_schedules.assert_called_once()
        call_kwargs = mock_db.get_schedules.call_args[1]
        assert call_kwargs["enabled"] is True


# =============================================================================
# Tests: POST /schedules
# =============================================================================


class TestCreateSchedule:
    @patch("agno.scheduler.cron._require_pytz")
    @patch("agno.scheduler.cron._require_croniter")
    @patch("agno.scheduler.cron.validate_cron_expr", return_value=True)
    @patch("agno.scheduler.cron.validate_timezone", return_value=True)
    @patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60)
    def test_create_success(self, mock_compute, mock_tz, mock_cron, mock_req_cron, mock_req_pytz, client, mock_db):
        mock_db.get_schedule_by_name = MagicMock(return_value=None)
        created = _make_schedule_dict(name="new-sched")
        mock_db.create_schedule = MagicMock(return_value=created)

        resp = client.post(
            "/schedules",
            json={
                "name": "new-sched",
                "cron_expr": "0 9 * * *",
                "endpoint": "/agents/a1/runs",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "new-sched"
        mock_db.create_schedule.assert_called_once()

    @patch("agno.scheduler.cron._require_pytz")
    @patch("agno.scheduler.cron._require_croniter")
    @patch("agno.scheduler.cron.validate_cron_expr", return_value=False)
    def test_create_invalid_cron(self, mock_cron, mock_req_cron, mock_req_pytz, client, mock_db):
        resp = client.post(
            "/schedules",
            json={
                "name": "bad-cron",
                "cron_expr": "not valid",
                "endpoint": "/test",
            },
        )
        assert resp.status_code == 422

    @patch("agno.scheduler.cron._require_pytz")
    @patch("agno.scheduler.cron._require_croniter")
    @patch("agno.scheduler.cron.validate_cron_expr", return_value=True)
    @patch("agno.scheduler.cron.validate_timezone", return_value=True)
    @patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60)
    def test_create_duplicate_name(
        self, mock_compute, mock_tz, mock_cron, mock_req_cron, mock_req_pytz, client, mock_db
    ):
        mock_db.get_schedule_by_name = MagicMock(return_value=_make_schedule_dict())
        resp = client.post(
            "/schedules",
            json={
                "name": "daily-check",
                "cron_expr": "0 9 * * *",
                "endpoint": "/test",
            },
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]


# =============================================================================
# Tests: GET /schedules/{schedule_id}
# =============================================================================


class TestGetSchedule:
    def test_found(self, client, mock_db):
        sched = _make_schedule_dict()
        mock_db.get_schedule = MagicMock(return_value=sched)
        resp = client.get("/schedules/sched-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "sched-1"

    def test_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        resp = client.get("/schedules/missing")
        assert resp.status_code == 404


# =============================================================================
# Tests: PATCH /schedules/{schedule_id}
# =============================================================================


class TestUpdateSchedule:
    def test_update_description(self, client, mock_db):
        existing = _make_schedule_dict()
        updated = _make_schedule_dict(description="Updated desc")
        mock_db.get_schedule = MagicMock(return_value=existing)
        mock_db.update_schedule = MagicMock(return_value=updated)

        resp = client.patch("/schedules/sched-1", json={"description": "Updated desc"})
        assert resp.status_code == 200
        mock_db.update_schedule.assert_called_once()

    def test_update_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        resp = client.patch("/schedules/missing", json={"description": "x"})
        assert resp.status_code == 404

    def test_update_empty_body(self, client, mock_db):
        existing = _make_schedule_dict()
        mock_db.get_schedule = MagicMock(return_value=existing)
        resp = client.patch("/schedules/sched-1", json={})
        assert resp.status_code == 200
        mock_db.update_schedule.assert_not_called()


# =============================================================================
# Tests: DELETE /schedules/{schedule_id}
# =============================================================================


class TestDeleteSchedule:
    def test_delete_success(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict())
        mock_db.delete_schedule = MagicMock(return_value=True)
        resp = client.delete("/schedules/sched-1")
        assert resp.status_code == 204
        mock_db.delete_schedule.assert_called_once_with("sched-1")

    def test_delete_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        resp = client.delete("/schedules/missing")
        assert resp.status_code == 404


# =============================================================================
# Tests: POST /schedules/{schedule_id}/enable
# =============================================================================


class TestEnableSchedule:
    @patch("agno.scheduler.cron._require_pytz")
    @patch("agno.scheduler.cron._require_croniter")
    @patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60)
    def test_enable_success(self, mock_compute, mock_req_cron, mock_req_pytz, client, mock_db):
        existing = _make_schedule_dict(enabled=False)
        enabled = _make_schedule_dict(enabled=True)
        mock_db.get_schedule = MagicMock(return_value=existing)
        mock_db.update_schedule = MagicMock(return_value=enabled)

        resp = client.post("/schedules/sched-1/enable")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_enable_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        resp = client.post("/schedules/missing/enable")
        assert resp.status_code == 404


# =============================================================================
# Tests: POST /schedules/{schedule_id}/disable
# =============================================================================


class TestDisableSchedule:
    def test_disable_success(self, client, mock_db):
        existing = _make_schedule_dict(enabled=True)
        disabled = _make_schedule_dict(enabled=False)
        mock_db.get_schedule = MagicMock(return_value=existing)
        mock_db.update_schedule = MagicMock(return_value=disabled)

        resp = client.post("/schedules/sched-1/disable")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_disable_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        resp = client.post("/schedules/missing/disable")
        assert resp.status_code == 404


# =============================================================================
# Tests: POST /schedules/{schedule_id}/trigger
# =============================================================================


class TestTriggerSchedule:
    def test_trigger_no_executor(self, client, mock_db):
        """Without a scheduler_executor on app.state, trigger returns 503."""
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict())
        resp = client.post("/schedules/sched-1/trigger")
        assert resp.status_code == 503

    def test_trigger_disabled_schedule(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict(enabled=False))
        resp = client.post("/schedules/sched-1/trigger")
        assert resp.status_code == 409
        assert "disabled" in resp.json()["detail"].lower()


# =============================================================================
# Tests: GET /schedules/{schedule_id}/runs
# =============================================================================


class TestListScheduleRuns:
    def test_list_runs(self, client, mock_db):
        now = int(time.time())
        runs = [
            {
                "id": "r1",
                "schedule_id": "sched-1",
                "attempt": 1,
                "triggered_at": now,
                "completed_at": now + 10,
                "status": "success",
                "status_code": 200,
                "run_id": None,
                "session_id": None,
                "error": None,
                "created_at": now,
            }
        ]
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict())
        mock_db.get_schedule_runs = MagicMock(return_value=(runs, 1))
        resp = client.get("/schedules/sched-1/runs")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_list_runs_schedule_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=None)
        resp = client.get("/schedules/missing/runs")
        assert resp.status_code == 404


# =============================================================================
# Tests: GET /schedules/{schedule_id}/runs/{run_id}
# =============================================================================


class TestGetScheduleRun:
    def test_get_run_found(self, client, mock_db):
        now = int(time.time())
        run = {
            "id": "r1",
            "schedule_id": "sched-1",
            "attempt": 1,
            "triggered_at": now,
            "completed_at": now + 10,
            "status": "success",
            "status_code": 200,
            "run_id": None,
            "session_id": None,
            "error": None,
            "created_at": now,
        }
        mock_db.get_schedule_run = MagicMock(return_value=run)
        resp = client.get("/schedules/sched-1/runs/r1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "r1"

    def test_get_run_not_found(self, client, mock_db):
        mock_db.get_schedule_run = MagicMock(return_value=None)
        resp = client.get("/schedules/sched-1/runs/missing")
        assert resp.status_code == 404

    def test_get_run_wrong_schedule(self, client, mock_db):
        run = {
            "id": "r1",
            "schedule_id": "other-sched",
            "attempt": 1,
            "status": "success",
            "created_at": int(time.time()),
        }
        mock_db.get_schedule_run = MagicMock(return_value=run)
        resp = client.get("/schedules/sched-1/runs/r1")
        assert resp.status_code == 404


# =============================================================================
# Tests: Pydantic schema validation
# =============================================================================


class TestScheduleCreateValidation:
    def test_invalid_name(self, client, mock_db):
        resp = client.post(
            "/schedules",
            json={
                "name": "!invalid name!",
                "cron_expr": "0 9 * * *",
                "endpoint": "/test",
            },
        )
        assert resp.status_code == 422

    def test_invalid_endpoint_no_slash(self, client, mock_db):
        resp = client.post(
            "/schedules",
            json={
                "name": "test",
                "cron_expr": "0 9 * * *",
                "endpoint": "no-leading-slash",
            },
        )
        assert resp.status_code == 422

    def test_invalid_endpoint_full_url(self, client, mock_db):
        resp = client.post(
            "/schedules",
            json={
                "name": "test",
                "cron_expr": "0 9 * * *",
                "endpoint": "http://example.com/test",
            },
        )
        assert resp.status_code == 422

    def test_invalid_method(self, client, mock_db):
        resp = client.post(
            "/schedules",
            json={
                "name": "test",
                "cron_expr": "0 9 * * *",
                "endpoint": "/test",
                "method": "INVALID",
            },
        )
        assert resp.status_code == 422
