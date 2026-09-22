"""Tests for POST /os/metrics/refresh and GET /os/metrics/refresh/status on the metrics router."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.os.routers.metrics.metrics import get_metrics_router
from agno.os.settings import AgnoAPISettings

# =============================================================================
# Fixtures
# =============================================================================


def _today():
    return datetime.now(timezone.utc).date()


def _last(days):
    """Query string for the window of the last ``days`` days, ending today."""
    start = _today() - timedelta(days=days - 1)
    return f"starting_date={start.isoformat()}"


def _row(day, user_id=None):
    """A stored daily metrics row as the db layer emits it."""
    now = int(time.time())
    return {
        "id": f"{day.isoformat()}_{user_id}_daily",
        "user_id": user_id,
        "date": day.isoformat(),
        "aggregation_period": "daily",
        "completed": True,
        "agent_runs_count": 1,
        "agent_sessions_count": 1,
        "team_runs_count": 0,
        "team_sessions_count": 0,
        "workflow_runs_count": 0,
        "workflow_sessions_count": 0,
        "users_count": 1,
        "token_metrics": {"input_tokens": 10, "total_tokens": 10},
        "model_metrics": [{"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 1}],
        "created_at": now,
        "updated_at": now,
    }


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def mock_db():
    """One row today; the daily metrics were last written at a fixed second."""
    db = MagicMock()
    db.id = "db-1"
    db.get_metrics = MagicMock(return_value=([_row(_today())], 1_800_000_000))
    db.calculate_metrics = MagicMock(return_value=None)
    return db


@pytest.fixture
def client(mock_db, settings):
    app = FastAPI()
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        app.include_router(get_metrics_router(dbs={"db-1": [mock_db]}, settings=settings, os_db=mock_db))
    return TestClient(app)


def _scope(user_id):
    """Patch who is calling, at the helper the route resolves the scope through."""
    return patch("agno.os.routers.metrics.metrics.get_scoped_user_id", return_value=user_id)


# =============================================================================
# GET /os/metrics/refresh/status
# =============================================================================


class TestRefreshStatus:
    def test_idle_before_any_refresh_with_the_database_stamp(self, client):
        with _scope(None):
            body = client.get("/os/metrics/refresh/status").json()

        assert body["status"] == "idle"
        assert body["started_at"] is None
        assert body["updated_at"] == "2027-01-15T08:00:00Z"
        assert body["computed_at"] == {"metrics": None, "session_metrics": None}

    def test_a_route_reports_when_its_answer_was_computed(self, client):
        with _scope(None):
            models = client.get(f"/os/metrics?{_last(1)}").json()
            body = client.get(f"/os/metrics/refresh/status?{_last(1)}").json()

        assert body["computed_at"]["metrics"] == models["computed_at"]
        assert body["computed_at"]["session_metrics"] is None

    def test_computed_at_times_are_per_owner_and_window(self, client):
        with _scope(None):
            client.get(f"/os/metrics?{_last(1)}")
            other_window = client.get(f"/os/metrics/refresh/status?{_last(7)}").json()
        with _scope("alice"):
            other_owner = client.get(f"/os/metrics/refresh/status?{_last(1)}").json()

        assert other_window["computed_at"]["metrics"] is None
        assert other_owner["computed_at"]["metrics"] is None

    def test_no_daily_metrics_yet_means_no_stamp(self, client, mock_db):
        mock_db.get_metrics.return_value = ([], None)
        with _scope(None):
            body = client.get("/os/metrics/refresh/status").json()

        assert body["updated_at"] is None

    def test_the_stamp_is_read_for_the_caller(self, client, mock_db):
        with _scope("alice"):
            client.get("/os/metrics/refresh/status")

        assert mock_db.get_metrics.call_args.kwargs["user_id"] == "alice"

    def test_the_stamp_is_read_for_the_window(self, client, mock_db):
        with _scope(None):
            client.get(f"/os/metrics/refresh/status?{_last(3)}")

        kwargs = mock_db.get_metrics.call_args.kwargs
        assert kwargs["starting_date"] == _today() - timedelta(days=2)
        assert kwargs["ending_date"] == _today()

    def test_an_os_without_a_database_is_unavailable(self, settings):
        app = FastAPI()
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            app.include_router(get_metrics_router(dbs={}, settings=settings))
        with _scope(None):
            assert TestClient(app).get("/os/metrics/refresh/status").status_code == 503
            assert TestClient(app).post("/os/metrics/refresh").status_code == 503


# =============================================================================
# POST /os/metrics/refresh
# =============================================================================


class TestRefresh:
    def test_rebuilds_the_daily_metrics_and_reports_completed(self, client, mock_db):
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        mock_db.calculate_metrics.assert_called_once()
        assert body["status"] == "completed"
        assert body["finished_at"] is not None
        assert "updated_at" not in body

    def test_every_cached_answer_is_forgotten(self, client, mock_db):
        """One call makes the next read of any OS metrics route recompute."""
        with _scope(None):
            models = client.get(f"/os/metrics?{_last(1)}").json()
            sessions = client.get(f"/os/metrics/sessions?{_last(1)}").json()
            client.post("/os/metrics/refresh")
            body = client.get(f"/os/metrics/refresh/status?{_last(1)}").json()
            models_after = client.get(f"/os/metrics?{_last(1)}").json()
            sessions_after = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["computed_at"] == {"metrics": None, "session_metrics": None}
        assert models_after["computed_at"] != models["computed_at"]
        assert sessions_after["computed_at"] != sessions["computed_at"]

    def test_status_reads_completed_afterwards(self, client):
        with _scope(None):
            client.post("/os/metrics/refresh")
            body = client.get("/os/metrics/refresh/status").json()

        assert body["status"] == "completed"

    def test_a_failed_rebuild_is_reported_and_raised(self, client, mock_db):
        mock_db.calculate_metrics.side_effect = RuntimeError("database unavailable")
        with _scope(None):
            response = client.post("/os/metrics/refresh")
            body = client.get("/os/metrics/refresh/status").json()

        assert response.status_code == 500
        assert body["status"] == "failed"
        assert "database unavailable" in body["error"]

    def test_background_refresh_returns_202_and_runs(self, client, mock_db):
        with _scope(None):
            response = client.post("/os/metrics/refresh?background=true")
            body = client.get("/os/metrics/refresh/status").json()

        assert response.status_code == 202
        assert response.json()["status"] == "started"
        mock_db.calculate_metrics.assert_called_once()
        assert body["status"] == "completed"

    def test_the_same_guard_serves_the_existing_refresh_route(self, client, mock_db):
        """The two refresh routes share one state per database."""
        with _scope(None):
            client.post("/os/metrics/refresh")
            legacy = client.get("/metrics/refresh/status").json()

        assert legacy["status"] == "completed"

    def test_a_caller_without_an_identity_cannot_start_a_refresh(self, client, mock_db):
        """The scope is resolved before any work, on both the background and the synchronous path."""
        with patch(
            "agno.os.routers.metrics.metrics.get_scoped_user_id",
            side_effect=HTTPException(status_code=403, detail="No user identity"),
        ):
            synchronous = client.post("/os/metrics/refresh")
            background = client.post("/os/metrics/refresh?background=true")

        assert synchronous.status_code == 403
        assert background.status_code == 403
        mock_db.calculate_metrics.assert_not_called()

    def test_the_os_database_is_refreshed_without_naming_it(self, settings, mock_db):
        """With several databases registered the existing refresh needs a db_id; this one never does."""
        other_db = MagicMock()
        other_db.id = "db-2"
        app = FastAPI()
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            app.include_router(
                get_metrics_router(dbs={"db-1": [mock_db], "db-2": [other_db]}, settings=settings, os_db=mock_db)
            )
        with _scope(None), TestClient(app) as client:
            legacy = client.post("/metrics/refresh")
            response = client.post("/os/metrics/refresh")

        assert legacy.status_code == 400
        assert response.status_code == 200
        mock_db.calculate_metrics.assert_called_once()
        other_db.calculate_metrics.assert_not_called()

    def test_a_read_computing_across_the_refresh_is_not_cached(self, client, mock_db):
        """The answer was read before the rebuild, so it is returned but the next read recomputes."""
        import threading

        mock_db.get_metrics.side_effect = lambda **kwargs: (time.sleep(0.3), ([_row(_today())], 1_800_000_000))[1]
        racing = {}
        with _scope(None):
            reader = threading.Thread(target=lambda: racing.update(client.get("/os/metrics").json()))
            reader.start()
            time.sleep(0.1)
            client.post("/os/metrics/refresh")
            reader.join()
            after = client.get("/os/metrics").json()

        assert after["computed_at"] != racing["computed_at"]
