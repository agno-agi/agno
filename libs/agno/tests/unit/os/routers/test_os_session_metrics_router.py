"""Tests for GET /os/metrics/sessions on the metrics router."""

import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
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


def _row(day, agents=0, teams=0, workflows=0, user_id=None):
    """A stored daily metrics row as the db layer emits it."""
    now = int(time.time())
    return {
        "id": f"{day.isoformat()}_{user_id}_daily",
        "user_id": user_id,
        "date": day.isoformat(),
        "aggregation_period": "daily",
        "completed": True,
        "agent_runs_count": agents,
        "agent_sessions_count": agents,
        "team_runs_count": teams,
        "team_sessions_count": teams,
        "workflow_runs_count": workflows,
        "workflow_sessions_count": workflows,
        "users_count": 1,
        "token_metrics": {"input_tokens": 10, "total_tokens": 10},
        "model_metrics": [],
        "created_at": now,
        "updated_at": now,
    }


def _rows_by_window(*rows):
    """Answer each daily metrics read with the rows that fall inside the window it asks for."""

    def read(*args, **kwargs):
        starting_date, ending_date = kwargs["starting_date"], kwargs["ending_date"]
        inside = [row for row in rows if starting_date <= date.fromisoformat(row["date"]) <= ending_date]
        return inside, int(time.time())

    return read


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def mock_db():
    """Three sessions today, one yesterday, and four in the window before that."""
    db = MagicMock()
    db.id = "db-1"
    db.get_metrics = MagicMock(
        side_effect=_rows_by_window(
            _row(_today(), agents=2, teams=1),
            _row(_today() - timedelta(days=1), workflows=1),
            _row(_today() - timedelta(days=3), agents=4),
        )
    )
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
# GET /os/metrics/sessions -- counts
# =============================================================================


class TestSessionCounts:
    def test_agent_team_and_workflow_sessions_add_up_per_day(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(2)}").json()

        assert body["metrics"] == [
            {"date": f"{(_today() - timedelta(days=1)).isoformat()}T00:00:00Z", "sessions_count": 1},
            {"date": f"{_today().isoformat()}T00:00:00Z", "sessions_count": 3},
        ]
        assert body["total_sessions"] == 4

    def test_the_change_is_against_the_window_of_the_same_length_before(self, client):
        """A two-day window ending today is compared with the two days before it."""
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(2)}").json()

        assert body["previous_total_sessions"] == 4
        assert body["change_percent"] == 0.0

    def test_a_rise_and_a_fall_carry_their_sign(self, client, mock_db):
        yesterday = _today() - timedelta(days=1)
        mock_db.get_metrics.side_effect = _rows_by_window(
            _row(_today(), agents=5),
            _row(yesterday, agents=4),
            _row(_today() - timedelta(days=2), agents=8),
        )
        with _scope(None):
            rise = client.get(f"/os/metrics/sessions?{_last(1)}").json()
            fall = client.get(
                f"/os/metrics/sessions?starting_date={yesterday.isoformat()}&ending_date={yesterday.isoformat()}"
            ).json()

        assert rise["change_percent"] == 25.0
        assert fall["change_percent"] == -50.0

    def test_no_sessions_before_means_no_rate(self, client, mock_db):
        """A window with nothing before it cannot show an infinite rise."""
        mock_db.get_metrics.side_effect = _rows_by_window(_row(_today(), agents=3))
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 3
        assert body["previous_total_sessions"] == 0
        assert body["change_percent"] is None

    def test_every_day_of_the_window_is_returned(self, client, mock_db):
        """A chart must not have to guess at a day nothing was started on."""
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(5)}").json()

        assert [entry["sessions_count"] for entry in body["metrics"]] == [0, 4, 0, 1, 3]

    def test_no_sessions_at_all_leaves_zeros(self, client, mock_db):
        mock_db.get_metrics.side_effect = _rows_by_window()
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(3)}").json()

        assert body["total_sessions"] == 0
        assert body["previous_total_sessions"] == 0
        assert body["change_percent"] is None
        assert len(body["metrics"]) == 3

    def test_both_windows_come_from_one_read_of_the_daily_metrics(self, client, mock_db):
        """One read spans the window and the one before it, so both halves see the same rollup."""
        with _scope(None):
            client.get(f"/os/metrics/sessions?{_last(7)}")

        mock_db.get_metrics.assert_called_once()
        kwargs = mock_db.get_metrics.call_args.kwargs
        assert kwargs["starting_date"] == _today() - timedelta(days=13)
        assert kwargs["ending_date"] == _today()
        mock_db.get_runs.assert_not_called()

    def test_a_row_outside_both_windows_is_dropped(self, client, mock_db):
        mock_db.get_metrics.side_effect = lambda *args, **kwargs: (
            [_row(_today(), agents=1), _row(_today() - timedelta(days=30), agents=9)],
            int(time.time()),
        )
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 1
        assert body["previous_total_sessions"] == 0

    def test_every_owners_sessions_are_added_when_unscoped(self, client, mock_db):
        """The per-owner rows collapse into one row per day, the way GET /metrics collapses them."""
        mock_db.get_metrics.side_effect = _rows_by_window(
            _row(_today(), agents=2, user_id="alice"),
            _row(_today(), agents=3, user_id="bob"),
        )
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 5


# =============================================================================
# GET /os/metrics/sessions -- scoping and caching
# =============================================================================


class TestScopingAndCaching:
    def test_scoped_caller_reads_only_its_own_rows(self, client, mock_db):
        with _scope("alice"):
            client.get(f"/os/metrics/sessions?{_last(1)}")

        assert all(call.kwargs["user_id"] == "alice" for call in mock_db.get_metrics.call_args_list)

    def test_second_call_is_served_from_cache(self, client, mock_db):
        with _scope(None):
            first = client.get("/os/metrics/sessions").json()
            second = client.get("/os/metrics/sessions").json()

        assert first["computed_at"] == second["computed_at"]
        assert mock_db.get_metrics.call_count == 1

    def test_refresh_recomputes(self, client, mock_db):
        with _scope(None):
            client.get("/os/metrics/sessions")
            client.get("/os/metrics/sessions?refresh=true")

        assert mock_db.get_metrics.call_count == 2

    def test_one_owner_cannot_be_served_anothers_cached_sessions(self, client, mock_db):
        with _scope("alice"):
            client.get("/os/metrics/sessions")
        with _scope("bob"):
            client.get("/os/metrics/sessions")

        assert mock_db.get_metrics.call_count == 2

    def test_model_usage_and_session_counts_are_cached_apart(self, client, mock_db):
        """One cache serves both routes, so the key has to carry the route."""
        with _scope(None):
            client.get(f"/os/metrics/models?{_last(1)}")
            client.get(f"/os/metrics/sessions?{_last(1)}")

        assert mock_db.get_metrics.call_count == 2

    def test_stale_entry_is_served_immediately_and_recomputed_in_the_background(self, client, mock_db):
        from agno.os.routers.metrics import metrics as metrics_module

        with _scope(None):
            first = client.get("/os/metrics/sessions").json()
            real_monotonic = time.monotonic
            with patch.object(
                metrics_module.time,
                "monotonic",
                lambda: real_monotonic() + metrics_module.CACHE_TTL_SECONDS + 1,
            ):
                stale = client.get("/os/metrics/sessions").json()
            refreshed = client.get("/os/metrics/sessions").json()

        assert stale["computed_at"] == first["computed_at"]
        assert mock_db.get_metrics.call_count == 2
        assert refreshed["computed_at"] != first["computed_at"]

    def test_a_rebuild_of_the_daily_metrics_drops_the_cached_answer(self, client, mock_db):
        """The counts come from the daily metrics, so POST /metrics/refresh makes them current."""
        mock_db.calculate_metrics = MagicMock(return_value=None)
        with _scope(None):
            first = client.get(f"/os/metrics/sessions?{_last(1)}").json()
            client.post("/metrics/refresh")
            second = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert mock_db.get_metrics.call_count == 2
        assert second["computed_at"] != first["computed_at"]

    def test_an_os_without_a_database_is_unavailable(self, settings):
        app = FastAPI()
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            app.include_router(get_metrics_router(dbs={}, settings=settings))
        with _scope(None):
            response = TestClient(app).get("/os/metrics/sessions")

        assert response.status_code == 503
