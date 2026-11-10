"""Tests for the metrics REST API router."""

import logging
import time
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.routers.metrics.metrics import get_metrics_router
from agno.os.settings import AgnoAPISettings
from agno.remote.base import RemoteDb

# =============================================================================
# Fixtures
# =============================================================================


def _make_metric(user_id, *, date="2026-01-01", runs=1, tokens=10, model="gpt-5-mini", period="daily"):
    """Create a stored per-user metrics row as the db layer emits it."""
    now = int(time.time())
    return {
        "id": f"{date}_{user_id}_{period}",
        "user_id": user_id,
        "date": date,
        "aggregation_period": period,
        "completed": True,
        "agent_runs_count": runs,
        "agent_sessions_count": 1,
        "team_runs_count": 0,
        "team_sessions_count": 0,
        "workflow_runs_count": 0,
        "workflow_sessions_count": 0,
        "users_count": 0 if user_id in (None, "") else 1,
        "token_metrics": {"input_tokens": tokens, "total_tokens": tokens},
        "model_metrics": [{"model_id": model, "model_provider": "OpenAI", "count": runs}],
        "created_at": now,
        "updated_at": now,
    }


def _refresh_status(status, *, error=None):
    """Create a refresh status as the db layer emits it."""
    return {"status": status, "started_at": 1767225600, "finished_at": None, "error": error}


@pytest.fixture
def alice_row():
    return _make_metric("alice", runs=2, tokens=100)


@pytest.fixture
def bob_row():
    return _make_metric("bob", runs=3, tokens=40)


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def mock_db(alice_row, bob_row):
    """A day with two owners plus the unowned bucket."""
    rows = [alice_row, bob_row, _make_metric("", runs=1, tokens=5)]
    db = MagicMock()
    db.id = "db-1"
    db.get_metrics = MagicMock(return_value=(rows, int(time.time())))
    db.get_metrics_by_date = MagicMock(side_effect=lambda **kwargs: BaseDb.get_metrics_by_date(db, **kwargs))
    db.calculate_metrics = MagicMock(return_value=rows)
    return db


def _client(settings, db):
    """A test client of the metrics router with auth off, for an AgentOS with the given database."""
    app = FastAPI()
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        app.include_router(get_metrics_router(dbs={db.id: [db]}, settings=settings))
    return TestClient(app)


@pytest.fixture
def client(mock_db, settings):
    return _client(settings, mock_db)


@pytest.fixture
def lock_row_db(alice_row, bob_row):
    """A database that keeps its refresh status on a lock row, as PostgresDb does."""
    rows = [alice_row, bob_row]
    db = MagicMock(spec=PostgresDb)
    db.id = "db-1"
    db.get_metrics = MagicMock(return_value=(rows, int(time.time())))
    db.get_metrics_by_date = MagicMock(side_effect=lambda **kwargs: BaseDb.get_metrics_by_date(db, **kwargs))
    db.calculate_metrics = MagicMock(return_value=rows)
    db.calculate_metrics_dates = MagicMock(return_value=[date(2026, 1, 1)])
    db.get_metrics_refresh_status = MagicMock(return_value=None)
    return db


@pytest.fixture
def lock_row_client(lock_row_db, settings):
    return _client(settings, lock_row_db)


def _scope(user_id):
    """Patch who is calling, at the helper the router resolves the scope through."""
    return patch("agno.os.middleware.user_scope.get_scoped_user_id", return_value=user_id)


# =============================================================================
# GET /metrics
# =============================================================================


class TestGetMetrics:
    def test_unscoped_caller_gets_one_aggregated_row_per_day(self, client, mock_db):
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert len(metrics) == 1
        row = metrics[0]
        assert row["agent_runs_count"] == 6
        assert row["agent_sessions_count"] == 3
        assert row["users_count"] == 2
        assert row["token_metrics"]["total_tokens"] == 145
        assert row["model_metrics"] == [{"model_id": "gpt-5-mini", "model_provider": "OpenAI", "count": 6}]

    def test_unscoped_read_takes_one_row_per_day_and_carries_the_refresh_status(
        self, lock_row_client, lock_row_db, alice_row
    ):
        """A database with its own read of every user's day is not asked for each user's rows, nor to calculate."""
        lock_row_db.get_metrics_by_date = MagicMock(return_value=([alice_row], int(time.time())))
        lock_row_db.get_metrics_refresh_status.return_value = _refresh_status("running")
        with _scope(None):
            resp = lock_row_client.get("/metrics")

        assert resp.status_code == 200
        assert resp.json()["refresh"]["status"] == "running"
        assert [metric["agent_runs_count"] for metric in resp.json()["metrics"]] == [2]
        lock_row_db.calculate_metrics.assert_not_called()
        lock_row_db.get_metrics.assert_not_called()

    def test_aggregate_row_carries_no_user_identity(self, client):
        """The stored id embeds the owner on key-value backends; the aggregate must not."""
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["id"] == "2026-01-01_daily"

    def test_scoped_caller_gets_its_own_bucket_unaggregated(self, client, mock_db, alice_row):
        mock_db.get_metrics.return_value = ([alice_row], int(time.time()))
        with _scope("alice"):
            resp = client.get("/metrics")

        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert len(metrics) == 1
        assert metrics[0]["agent_runs_count"] == 2
        assert mock_db.get_metrics.call_args.kwargs["user_id"] == "alice"

    def test_scoped_row_id_does_not_come_from_storage(self, client, mock_db, alice_row):
        """Stored ids are the backend's own -- a uuid on SQL, an owner-bearing string on Redis."""
        alice_row["id"] = "ac086ccf-66d7-4b97-ac92-8c5d6e38da1a"
        mock_db.get_metrics.return_value = ([alice_row], int(time.time()))
        with _scope("alice"):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["id"] == "2026-01-01_alice_daily"

    def test_admin_can_narrow_to_one_user(self, client, mock_db, alice_row):
        mock_db.get_metrics.return_value = ([alice_row], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics?user_id=alice")

        assert mock_db.get_metrics.call_args.kwargs["user_id"] == "alice"
        metrics = resp.json()["metrics"]
        assert len(metrics) == 1
        assert metrics[0]["agent_runs_count"] == 2
        assert metrics[0]["id"] == "2026-01-01_alice_daily"

    def test_scoped_caller_cannot_widen_to_another_user(self, client, mock_db, alice_row):
        """The JWT subject wins over the query param, so ?user_id=bob cannot reach bob."""
        mock_db.get_metrics.return_value = ([alice_row], int(time.time()))
        with _scope("alice"):
            client.get("/metrics?user_id=bob")

        assert mock_db.get_metrics.call_args.kwargs["user_id"] == "alice"

    def test_identity_less_caller_gets_403_not_500(self, client):
        """The fail-closed scoping status must not be masked by the broad handler."""
        with patch(
            "agno.os.middleware.user_scope.get_scoped_user_id",
            side_effect=HTTPException(status_code=403, detail="Authenticated request is missing a user identity"),
        ):
            resp = client.get("/metrics")

        assert resp.status_code == 403

    def test_db_failure_is_still_a_500(self, client, mock_db):
        mock_db.get_metrics.side_effect = RuntimeError("boom")
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.status_code == 500

    @pytest.mark.parametrize("remote_status, status", [(403, 403), (503, 503)])
    def test_remote_refusal_is_passed_through_without_the_remote_url(self, settings, remote_status, status):
        """A remote AgentOS that refuses the read is answered with its status, one that fails with a 500, neither
        naming its URL."""
        remote_response = httpx.Response(
            remote_status,
            json={"detail": "Admin privileges required"},
            request=httpx.Request("GET", "http://remote-os/metrics"),
        )
        remote_db = MagicMock(spec=RemoteDb)
        remote_db.id = "remote-1"
        remote_db.get_metrics.side_effect = lambda **kwargs: remote_response.raise_for_status()
        client = _client(settings, remote_db)
        # The AgentOS handler of a refusal re-raised by the route
        os_app = AgentOS(agents=[Agent(id="assistant")]).get_app()
        client.app.add_exception_handler(httpx.HTTPStatusError, os_app.exception_handlers[httpx.HTTPStatusError])
        with _scope("alice"):
            resp = client.get("/metrics")

        assert resp.status_code == status
        if remote_status < 500:
            assert "Admin privileges required" in resp.json()["detail"]
        assert "http://" not in resp.text


# =============================================================================
# POST /metrics/refresh
# =============================================================================


class TestRefreshMetrics:
    def test_scoped_caller_only_gets_its_own_bucket_back(self, client):
        with _scope("alice"):
            resp = client.post("/metrics/refresh")

        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["agent_runs_count"] == 2

    def test_unscoped_caller_gets_the_aggregate(self, client):
        with _scope(None):
            resp = client.post("/metrics/refresh")

        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["agent_runs_count"] == 6
        assert rows[0]["id"] == "2026-01-01_daily"

    def test_identity_less_caller_gets_403_not_500(self, client):
        with patch(
            "agno.os.middleware.user_scope.get_scoped_user_id",
            side_effect=HTTPException(status_code=403, detail="Authenticated request is missing a user identity"),
        ):
            resp = client.post("/metrics/refresh")

        assert resp.status_code == 403

    def test_a_second_caller_is_told_one_is_already_running(self, client, mock_db):
        """The guard the background path always had, now on the synchronous path too."""
        seen = {}

        def reenter():
            # Fired while the first refresh is still in flight, so the state says "running"
            seen["inner"] = client.post("/metrics/refresh").json()
            return []

        mock_db.calculate_metrics.side_effect = reenter
        with _scope(None):
            outer = client.post("/metrics/refresh")

        assert outer.status_code == 200
        assert seen["inner"]["status"] == "already_running"

    def test_sync_refresh_records_its_outcome(self, client):
        """It used to leave no state at all, so the status endpoint reported idle."""
        with _scope(None):
            client.post("/metrics/refresh")
            status = client.get("/metrics/refresh/status").json()

        assert status["status"] == "completed"
        assert status["started_at"] is not None and status["finished_at"] is not None

    def test_failed_sync_refresh_is_recorded_and_still_raises(self, client, mock_db):
        mock_db.calculate_metrics.side_effect = RuntimeError("boom")
        with _scope(None):
            resp = client.post("/metrics/refresh")
            status = client.get("/metrics/refresh/status").json()

        assert resp.status_code == 500
        assert status["status"] == "failed"
        assert status["finished_at"] is not None

    def test_a_caller_that_loses_the_lock_row_is_told_one_is_already_running(self, lock_row_client, lock_row_db):
        """The claim of the lock row is the check, so a caller that loses it to another process says so."""
        lock_row_db.calculate_metrics_dates.return_value = None
        with _scope(None):
            resp = lock_row_client.post("/metrics/refresh")

        assert resp.status_code == 200
        assert resp.json()["status"] == "already_running"

    def test_a_rebuild_from_a_future_date_is_refused(self, lock_row_client, lock_row_db):
        """A rebuild from a day that has not come yet would rebuild nothing, so it is refused."""
        with _scope(None):
            resp = lock_row_client.post("/metrics/refresh", params={"rebuild_from": "2999-01-01"})

        assert resp.status_code == 422
        lock_row_db.calculate_metrics_dates.assert_not_called()

    def test_a_rebuild_on_a_database_without_a_lock_row_is_refused(self, client, mock_db):
        """A database without the aggregate metrics table has no days to reopen, so a rebuild is refused."""
        with _scope(None):
            resp = client.post("/metrics/refresh", params={"rebuild_from": "2026-01-01"})

        assert resp.status_code == 503
        assert resp.json()["detail"] == "rebuild_from not supported by the configured database"
        mock_db.calculate_metrics.assert_not_called()

    def test_a_refresh_reads_the_days_it_calculated_back_from_the_tables(self, lock_row_client, lock_row_db):
        """The build gives only the days it calculated, so their rows are read back from the tables, one per day."""
        rows = [_make_metric("", date=date(2026, 1, 1), runs=5, tokens=140), _make_metric("", date=date(2026, 1, 2))]
        lock_row_db.get_metrics_by_date = MagicMock(return_value=(rows, int(time.time())))
        with _scope(None):
            resp = lock_row_client.post("/metrics/refresh")

        assert resp.status_code == 200
        assert [(day["date"], day["agent_runs_count"]) for day in resp.json()] == [("2026-01-01T00:00:00Z", 5)]
        lock_row_db.calculate_metrics.assert_not_called()
        assert lock_row_db.get_metrics_by_date.call_args.kwargs == {
            "starting_date": date(2026, 1, 1),
            "ending_date": date(2026, 1, 1),
        }

    def test_a_refresh_lists_a_day_it_calculated_to_no_sessions_or_runs(self, lock_row_client, lock_row_db):
        """A day whose sessions were deleted is rebuilt to zeros, which reads leave out, and still comes back."""
        lock_row_db.calculate_metrics_dates.return_value = [date(2026, 1, 1), date(2026, 1, 2)]
        rows = [_make_metric("", date=date(2026, 1, 1), runs=5, tokens=140)]
        lock_row_db.get_metrics_by_date = MagicMock(return_value=(rows, int(time.time())))
        with _scope(None):
            resp = lock_row_client.post("/metrics/refresh", params={"rebuild_from": "2026-01-01"})

        assert resp.status_code == 200
        days = [(day["date"], day["agent_runs_count"], day["token_metrics"]["total_tokens"]) for day in resp.json()]
        assert days == [
            ("2026-01-01T00:00:00Z", 5, 140),
            ("2026-01-02T00:00:00Z", 0, 0),
        ]
        # Its token metrics have the cost key every other day has
        assert resp.json()[1]["token_metrics"]["cost"] is None

    def test_a_background_rebuild_during_a_running_refresh_still_reopens_its_days(self, lock_row_client, lock_row_db):
        """The days of a rebuild asked while a refresh runs are reopened, so the next refresh rebuilds them."""
        lock_row_db.get_metrics_refresh_status.return_value = _refresh_status("running")
        lock_row_db.calculate_metrics_dates.return_value = None
        with _scope(None):
            resp = lock_row_client.post("/metrics/refresh?background=true&rebuild_from=2026-01-01")

        assert resp.status_code == 202
        assert resp.json()["status"] == "already_running"
        assert lock_row_db.calculate_metrics_dates.call_args.kwargs["rebuild_from"] == date(2026, 1, 1)
        lock_row_db.calculate_metrics.assert_not_called()

    def test_status_is_read_from_the_database(self, lock_row_client, lock_row_db):
        with _scope(None):
            before = lock_row_client.get("/metrics/refresh/status").json()
            lock_row_db.get_metrics_refresh_status.return_value = _refresh_status("failed", error="boom")
            status = lock_row_client.get("/metrics/refresh/status").json()

        # Idle before any refresh
        assert before["status"] == "idle"
        assert status["status"] == "failed"
        assert status["error"] == "boom"
        assert status["started_at"] is not None

    def test_refresh_is_refused_and_a_read_never_calculates_when_calculation_is_turned_off(self, lock_row_db):
        """A database that calculates its metrics on read is stopped from doing so."""
        client = _client(AgnoAPISettings(metrics_calculation_enabled=False), lock_row_db)
        with _scope(None):
            resp = client.post("/metrics/refresh")
            background = client.post("/metrics/refresh?background=true")

        assert (resp.status_code, resp.json()["status"]) == (200, "disabled")
        # A background refresh never starts either, so it is answered the same way
        assert (background.status_code, background.json()["status"]) == (200, "disabled")
        lock_row_db.calculate_metrics.assert_not_called()
        lock_row_db.calculate_metrics_dates.assert_not_called()
        lock_row_db.stop_metrics_refresh_on_read.assert_called_once()

    def test_background_refresh_of_a_remote_database_forwards_the_user(self, settings):
        remote_db = MagicMock(spec=RemoteDb)
        remote_db.id = "remote-1"
        with _scope("alice"):
            resp = _client(settings, remote_db).post("/metrics/refresh?background=true")

        assert resp.status_code == 202
        assert remote_db.refresh_metrics.call_args.kwargs["user_id"] == "alice"

    def test_no_metrics_returns_empty_list(self, client, mock_db):
        mock_db.calculate_metrics.return_value = None
        with _scope(None):
            resp = client.post("/metrics/refresh")

        assert resp.status_code == 200
        assert resp.json() == []


# =============================================================================
# Aggregation edges
# =============================================================================


class TestAggregationEdges:
    def test_periods_are_not_folded_together(self, client, mock_db, alice_row, bob_row):
        weekly = _make_metric("alice", runs=9, period="weekly")
        mock_db.get_metrics.return_value = ([alice_row, bob_row, weekly], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        metrics = resp.json()["metrics"]
        assert len(metrics) == 2
        assert sorted(m["agent_runs_count"] for m in metrics) == [5, 9]

    def test_disjoint_token_keys_are_preserved(self, client, mock_db):
        alice = _make_metric("alice")
        alice["token_metrics"] = {"input_tokens": 5, "reasoning_tokens": 3}
        bob = _make_metric("bob")
        bob["token_metrics"] = {"input_tokens": 7, "cached_tokens": 11}
        mock_db.get_metrics.return_value = ([alice, bob], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        tokens = resp.json()["metrics"][0]["token_metrics"]
        assert tokens == {"input_tokens": 12, "reasoning_tokens": 3, "cached_tokens": 11}

    def test_distinct_models_are_kept_apart(self, client, mock_db):
        alice = _make_metric("alice", runs=2, model="gpt-5-mini")
        bob = _make_metric("bob", runs=3, model="claude-opus-5")
        mock_db.get_metrics.return_value = ([alice, bob], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        models = {m["model_id"]: m["count"] for m in resp.json()["metrics"][0]["model_metrics"]}
        assert models == {"gpt-5-mini": 2, "claude-opus-5": 3}

    def test_duplicate_model_entries_are_folded(self, client, mock_db):
        """A stored row may already carry the same model twice."""
        alice = _make_metric("alice", runs=2)
        alice["model_metrics"] = [
            {"model_id": "gpt-5-mini", "model_provider": "OpenAI", "count": 2},
            {"model_id": "gpt-5-mini", "model_provider": "OpenAI", "count": 4},
        ]
        mock_db.get_metrics.return_value = ([alice, _make_metric("bob", runs=3)], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["model_metrics"] == [
            {"model_id": "gpt-5-mini", "model_provider": "OpenAI", "count": 9}
        ]

    def test_period_less_row_folds_into_the_daily_bucket(self, client, mock_db, alice_row):
        bob = _make_metric("bob", runs=3)
        bob["aggregation_period"] = None
        mock_db.get_metrics.return_value = ([alice_row, bob], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        metrics = resp.json()["metrics"]
        assert len(metrics) == 1
        assert metrics[0]["id"] == "2026-01-01_daily"
        assert metrics[0]["agent_runs_count"] == 5

    def test_datetime_date_yields_the_same_id_as_a_string_date(self, client, mock_db):
        """SurrealDB hands back a tz-aware datetime where other adapters give a day."""
        row = _make_metric("alice", runs=2)
        row["date"] = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_db.get_metrics.return_value = ([row], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["id"] == "2026-01-01_daily"

    def test_malformed_date_is_skipped_and_logged(self, client, mock_db, alice_row, caplog):
        """Key-value backends can hold a record whose date is not a day, so it is skipped and logged."""
        poison = _make_metric("bob", runs=3)
        poison["date"] = {"broken": True}
        mock_db.get_metrics.return_value = ([alice_row, poison], int(time.time()))
        with _scope(None), caplog.at_level(logging.WARNING):
            resp = client.get("/metrics")

        assert resp.status_code == 200
        metrics = resp.json()["metrics"]
        assert len(metrics) == 1
        assert metrics[0]["agent_runs_count"] == 2
        assert "is not a day" in caplog.text

    def test_one_day_stored_in_mixed_types_folds_into_one_bucket(self, client, mock_db):
        """The same day arrives as a date, a datetime or a string per backend."""
        rows = [_make_metric("alice", runs=2), _make_metric("bob", runs=3), _make_metric("carol", runs=4)]
        rows[1]["date"] = datetime.fromisoformat(f"{rows[1]['date']}T00:00:00")
        rows[2]["date"] = date.fromisoformat(rows[2]["date"])
        mock_db.get_metrics.return_value = (rows, int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        metrics = resp.json()["metrics"]
        assert len(metrics) == 1
        assert metrics[0]["agent_runs_count"] == 9

    def test_mixed_timestamp_types_do_not_fail_the_read(self, client, mock_db, alice_row):
        """One row stamped with a datetime must not break the epoch comparison."""
        other = _make_metric("bob", runs=3)
        other["created_at"] = datetime.fromisoformat("2026-01-01T00:00:00")
        mock_db.get_metrics.return_value = ([alice_row, other], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.status_code == 200
        assert resp.json()["metrics"][0]["agent_runs_count"] == 5

    def test_ids_are_unique_across_buckets(self, client, mock_db, alice_row):
        rows = [
            alice_row,
            _make_metric("bob", runs=3),
            _make_metric("alice", date="2026-01-02", runs=1),
            _make_metric("alice", runs=9, period="weekly"),
            _make_metric("carol", runs=4),
        ]
        rows[-1]["aggregation_period"] = None
        mock_db.get_metrics.return_value = (rows, int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        ids = [m["id"] for m in resp.json()["metrics"]]
        assert sorted(ids) == ["2026-01-01_daily", "2026-01-01_weekly", "2026-01-02_daily"]


class TestSupersededRecords:
    """Records written before metrics were bucketed per user must not be summed twice."""

    def test_record_without_a_user_id_is_dropped(self, client, mock_db, alice_row, bob_row):
        legacy = _make_metric("alice", runs=5)
        del legacy["user_id"]
        mock_db.get_metrics.return_value = ([alice_row, bob_row, legacy], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["agent_runs_count"] == 5

    def test_unowned_record_carrying_a_user_count_is_dropped(self, client, mock_db, alice_row, bob_row):
        """An earlier Valkey filed the whole day under the unowned bucket, counting its users."""
        legacy = _make_metric("", runs=5)
        legacy["users_count"] = 2
        mock_db.get_metrics.return_value = ([alice_row, bob_row, legacy], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        day = resp.json()["metrics"][0]
        assert day["agent_runs_count"] == 5
        assert day["users_count"] == 2

    def test_unowned_record_with_no_user_count_is_kept(self, client, mock_db, alice_row):
        """The bucket the per-user writer produces for unowned sessions is real traffic."""
        mock_db.get_metrics.return_value = ([alice_row, _make_metric("", runs=3)], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["agent_runs_count"] == 5

    def test_superseded_record_alone_is_still_the_day(self, client, mock_db):
        """With nothing to replace it, it is the only record of that day."""
        legacy = _make_metric("", runs=7)
        legacy["users_count"] = 3
        mock_db.get_metrics.return_value = ([legacy], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        assert resp.json()["metrics"][0]["agent_runs_count"] == 7

    def test_a_bucket_it_does_not_cover_is_untouched(self, client, mock_db, alice_row):
        """Dropping keys off the bucket, so another day's record survives."""
        legacy = _make_metric("", date="2026-01-02", runs=7)
        legacy["users_count"] = 3
        mock_db.get_metrics.return_value = ([alice_row, legacy], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics")

        by_id = {m["id"]: m["agent_runs_count"] for m in resp.json()["metrics"]}
        assert by_id == {"2026-01-01_daily": 2, "2026-01-02_daily": 7}

    def test_unowned_read_does_not_report_a_superseded_record(self, client, mock_db):
        """The SQL adapters stamp the unowned sentinel on such a record, so ``?user_id=`` selects it."""
        legacy = _make_metric("", runs=7)
        legacy["users_count"] = 3
        mock_db.get_metrics.return_value = ([legacy], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics?user_id=")

        assert resp.json()["metrics"] == []

    def test_unowned_read_reports_the_real_unowned_bucket(self, client, mock_db):
        """The bucket the per-user writer produces for unowned sessions is that owner's traffic."""
        mock_db.get_metrics.return_value = ([_make_metric("", runs=3)], int(time.time()))
        with _scope(None):
            resp = client.get("/metrics?user_id=")

        assert resp.json()["metrics"][0]["agent_runs_count"] == 3
