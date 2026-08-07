"""Tests for the schedule REST API router."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.schemas.scheduler import STUDIO_SCHEDULE_MANAGED_BY, ScheduleNameConflictError
from agno.db.sqlite import SqliteDb
from agno.os.routers.schedules import get_schedule_router
from agno.os.settings import AgnoAPISettings

STUDIO_SCHEDULE_ID = "studio-router-private-id"
STUDIO_PROMPT = "studio-router-private-prompt"
STUDIO_ACTOR = "studio-router-private-actor"

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


def _make_studio_schedule_dict(**overrides):
    """Create a Studio-owned schedule whose private fields must stay hidden."""
    defaults = {
        "id": STUDIO_SCHEDULE_ID,
        "name": "studio-router-private-schedule",
        "payload": {"message": STUDIO_PROMPT},
        "managed_by": "studio",
        "owner_actor_id": STUDIO_ACTOR,
        "target_type": "agent",
        "target_id": "studio-private-agent",
        "created_by_run_id": "studio-router-private-run",
        "created_by_session_id": "studio-router-private-session",
    }
    defaults.update(overrides)
    return _make_schedule_dict(**defaults)


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


def _make_client_for_db(db) -> TestClient:
    app = FastAPI()
    app.include_router(get_schedule_router(os_db=db, settings=AgnoAPISettings()))
    return TestClient(app, raise_server_exceptions=False)


class _RacingCreateSqliteDb:
    """Coordinate two requests so both miss create's name preflight."""

    def __init__(self, db, barrier, winner_created, wins_insert):
        self._db = db
        self._barrier = barrier
        self._winner_created = winner_created
        self._wins_insert = wins_insert
        self._first_lookup = True

    def __getattr__(self, name):
        return getattr(self._db, name)

    def get_schedule_by_name(self, name):
        result = self._db.get_schedule_by_name(name)
        if self._first_lookup:
            self._first_lookup = False
            self._barrier.wait(timeout=5)
        return result

    def create_schedule(self, schedule_data):
        if self._wins_insert:
            try:
                return self._db.create_schedule(schedule_data)
            finally:
                self._winner_created.set()
        if not self._winner_created.wait(timeout=5):
            raise RuntimeError("winning insert did not complete")
        try:
            return self._db.create_schedule(schedule_data)
        except ScheduleNameConflictError:
            winner = self._db.get_schedule_by_name(schedule_data["name"])
            assert winner is not None
            assert self._db.delete_schedule(winner["id"]) is True
            raise


class _RacingRenameSqliteDb:
    """Coordinate two requests so both miss rename's name preflight."""

    def __init__(self, db, barrier, winner_updated, wins_update, raced_name):
        self._db = db
        self._barrier = barrier
        self._winner_updated = winner_updated
        self._wins_update = wins_update
        self._raced_name = raced_name
        self._first_lookup = True

    def __getattr__(self, name):
        return getattr(self._db, name)

    def get_schedule_by_name(self, name):
        result = self._db.get_schedule_by_name(name)
        if name == self._raced_name and self._first_lookup:
            self._first_lookup = False
            self._barrier.wait(timeout=5)
        return result

    def update_schedule(self, schedule_id, **kwargs):
        if self._wins_update:
            try:
                return self._db.update_schedule(schedule_id, **kwargs)
            finally:
                self._winner_updated.set()
        if not self._winner_updated.wait(timeout=5):
            raise RuntimeError("winning update did not complete")
        try:
            return self._db.update_schedule(schedule_id, **kwargs)
        except ScheduleNameConflictError:
            winner = self._db.get_schedule_by_name(self._raced_name)
            assert winner is not None
            renamed = self._db.update_schedule(winner["id"], name="winner-after-race")
            assert renamed is not None
            raise


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
        assert call_kwargs["exclude_managed_by"] == STUDIO_SCHEDULE_MANAGED_BY


# =============================================================================
# Tests: POST /schedules
# =============================================================================


class TestCreateSchedule:
    def test_missing_scheduler_dependency_does_not_expose_exception_details(self, client):
        secret = "postgresql://admin:private-password@internal.example/agno"
        with patch("agno.scheduler.cron._require_croniter", side_effect=ImportError(secret)):
            response = client.post(
                "/schedules",
                json={
                    "name": "dependency-check",
                    "cron_expr": "0 9 * * *",
                    "endpoint": "/agents/a1/runs",
                },
            )

        assert response.status_code == 503
        assert response.json() == {"detail": "Scheduler dependencies are not installed"}
        assert secret not in response.text

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

    def test_concurrent_sqlite_create_returns_conflict_after_winner_is_deleted(self, tmp_path):
        db_path = str(tmp_path / "router-create-race.db")
        winner_db = SqliteDb(db_file=db_path, schedules_table="router_create_race_schedules")
        winner_db.create_schedule(_make_schedule_dict(id="prime", name="prime"))
        assert winner_db.delete_schedule("prime") is True
        loser_db = SqliteDb(db_file=db_path, schedules_table="router_create_race_schedules")

        barrier = Barrier(2)
        winner_created = Event()
        winner_client = _make_client_for_db(_RacingCreateSqliteDb(winner_db, barrier, winner_created, wins_insert=True))
        loser_client = _make_client_for_db(_RacingCreateSqliteDb(loser_db, barrier, winner_created, wins_insert=False))
        body = {
            "name": "shared-name",
            "cron_expr": "0 9 * * *",
            "endpoint": "/agents/a1/runs",
        }

        with winner_client, loser_client, ThreadPoolExecutor(max_workers=2) as pool:
            winner_future = pool.submit(winner_client.post, "/schedules", json=body)
            loser_future = pool.submit(loser_client.post, "/schedules", json=body)
            winner_response = winner_future.result(timeout=10)
            loser_response = loser_future.result(timeout=10)

        assert winner_response.status_code == 201
        assert loser_response.status_code == 409
        assert loser_response.json() == {"detail": "Schedule with name 'shared-name' already exists"}
        schedules, total = winner_db.get_schedules()
        assert total == 0
        assert schedules == []


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

    def test_concurrent_sqlite_rename_returns_conflict_after_winner_is_renamed(self, tmp_path):
        db_path = str(tmp_path / "router-rename-race.db")
        winner_db = SqliteDb(db_file=db_path, schedules_table="router_rename_race_schedules")
        winner_db.create_schedule(_make_schedule_dict(id="winner", name="winner-old"))
        winner_db.create_schedule(_make_schedule_dict(id="loser", name="loser-old"))
        loser_db = SqliteDb(db_file=db_path, schedules_table="router_rename_race_schedules")

        raced_name = "shared-name"
        barrier = Barrier(2)
        winner_updated = Event()
        winner_client = _make_client_for_db(
            _RacingRenameSqliteDb(winner_db, barrier, winner_updated, wins_update=True, raced_name=raced_name)
        )
        loser_client = _make_client_for_db(
            _RacingRenameSqliteDb(loser_db, barrier, winner_updated, wins_update=False, raced_name=raced_name)
        )

        with winner_client, loser_client, ThreadPoolExecutor(max_workers=2) as pool:
            winner_future = pool.submit(winner_client.patch, "/schedules/winner", json={"name": raced_name})
            loser_future = pool.submit(loser_client.patch, "/schedules/loser", json={"name": raced_name})
            winner_response = winner_future.result(timeout=10)
            loser_response = loser_future.result(timeout=10)

        assert winner_response.status_code == 200
        assert loser_response.status_code == 409
        assert loser_response.json() == {"detail": "Schedule with name 'shared-name' already exists"}
        assert winner_db.get_schedule_by_name(raced_name) is None
        assert winner_db.get_schedule("winner")["name"] == "winner-after-race"
        assert winner_db.get_schedule("loser")["name"] == "loser-old"


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
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict())
        mock_db.get_schedule_run = MagicMock(return_value=run)
        resp = client.get("/schedules/sched-1/runs/r1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "r1"

    def test_get_run_not_found(self, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict())
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
        mock_db.get_schedule = MagicMock(return_value=_make_schedule_dict())
        mock_db.get_schedule_run = MagicMock(return_value=run)
        resp = client.get("/schedules/sched-1/runs/r1")
        assert resp.status_code == 404


# =============================================================================
# Tests: Studio-managed schedule isolation
# =============================================================================


class TestStudioManagedIsolation:
    @staticmethod
    def _assert_private_values_hidden(response_text: str) -> None:
        assert STUDIO_SCHEDULE_ID not in response_text
        assert STUDIO_PROMPT not in response_text
        assert STUDIO_ACTOR not in response_text
        assert "studio-router-private-run" not in response_text
        assert "studio-router-private-session" not in response_text
        assert "managed_by" not in response_text

    def test_list_hides_studio_schedule_and_provenance(self, client, mock_db):
        ordinary = _make_schedule_dict(id="ordinary-id", name="ordinary")
        studio = _make_studio_schedule_dict()
        # A custom/non-compliant adapter may ignore the query filter. The
        # response boundary must still refuse to serialize the Studio row.
        mock_db.get_schedules = MagicMock(return_value=([studio, ordinary], 1))

        response = client.get("/schedules")

        assert response.status_code == 200
        assert [schedule["id"] for schedule in response.json()["data"]] == ["ordinary-id"]
        assert response.json()["meta"]["total_count"] == 1
        self._assert_private_values_hidden(response.text)
        mock_db.get_schedules.assert_called_once_with(
            enabled=None,
            limit=100,
            page=1,
            exclude_managed_by=STUDIO_SCHEDULE_MANAGED_BY,
        )

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("GET", f"/schedules/{STUDIO_SCHEDULE_ID}", None),
            ("PATCH", f"/schedules/{STUDIO_SCHEDULE_ID}", {"description": "changed"}),
            ("DELETE", f"/schedules/{STUDIO_SCHEDULE_ID}", None),
            ("POST", f"/schedules/{STUDIO_SCHEDULE_ID}/enable", None),
            ("POST", f"/schedules/{STUDIO_SCHEDULE_ID}/disable", None),
            ("POST", f"/schedules/{STUDIO_SCHEDULE_ID}/trigger", None),
            ("GET", f"/schedules/{STUDIO_SCHEDULE_ID}/runs", None),
            ("GET", f"/schedules/{STUDIO_SCHEDULE_ID}/runs/private-run-id", None),
        ],
    )
    def test_direct_reads_and_mutations_treat_studio_schedule_as_not_found(self, method, path, body, client, mock_db):
        mock_db.get_schedule = MagicMock(return_value=_make_studio_schedule_dict())

        response = client.request(method, path, json=body)

        assert response.status_code == 404
        assert response.json() == {"detail": "Schedule not found"}
        self._assert_private_values_hidden(response.text)
        mock_db.update_schedule.assert_not_called()
        mock_db.delete_schedule.assert_not_called()
        mock_db.get_schedule_runs.assert_not_called()
        mock_db.get_schedule_run.assert_not_called()

    @patch("agno.scheduler.cron._require_pytz")
    @patch("agno.scheduler.cron._require_croniter")
    @patch("agno.scheduler.cron.validate_cron_expr", return_value=True)
    @patch("agno.scheduler.cron.validate_timezone", return_value=True)
    @patch("agno.scheduler.cron.compute_next_run", return_value=int(time.time()) + 60)
    def test_create_cannot_replace_studio_schedule_with_same_name(
        self, mock_compute, mock_tz, mock_cron, mock_req_cron, mock_req_pytz, client, mock_db
    ):
        studio = _make_studio_schedule_dict()
        mock_db.get_schedule_by_name = MagicMock(return_value=studio)

        response = client.post(
            "/schedules",
            json={
                "name": studio["name"],
                "cron_expr": "0 9 * * *",
                "endpoint": "/agents/a1/runs",
            },
        )

        assert response.status_code == 409
        self._assert_private_values_hidden(response.text)
        mock_db.create_schedule.assert_not_called()


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
