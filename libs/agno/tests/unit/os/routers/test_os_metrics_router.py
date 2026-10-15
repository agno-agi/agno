"""Tests for the GET /os/metrics/* routes and POST /os/metrics/refresh on the metrics router."""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.utils import merge_os_metrics_totals, resolve_os_metrics_fields
from agno.os.routers.metrics.metrics import get_metrics_router
from agno.os.settings import AgnoAPISettings
from agno.remote.base import RemoteDb

# =============================================================================
# Fixtures
# =============================================================================

# The second the database last wrote the rows of every window, as the mock reports it
UPDATED_AT = 1_800_000_000
UPDATED_AT_ISO = "2027-01-15T08:00:00Z"


def _today():
    return datetime.now(timezone.utc).date()


def _last(days):
    """Query string for the window of the last ``days`` days, ending today."""
    start = _today() - timedelta(days=days - 1)
    return f"starting_date={start.isoformat()}"


def _day(days_ago):
    return _today() - timedelta(days=days_ago)


def _iso(day):
    return f"{day.isoformat()}T00:00:00Z"


def _row(day, **fields):
    """One day's totals as get_os_metrics emits them, keyed by the field names a route asks for."""
    return {"date": day, **fields}


def _totals(*rows):
    """Answer each get_os_metrics read with the requested fields of the rows inside its window."""

    def read(*args, **kwargs):
        starting_date, ending_date = kwargs["starting_date"], kwargs["ending_date"]
        inside = [row for row in rows if starting_date <= row["date"] <= ending_date]
        fields = kwargs["fields"]
        return [
            {"date": row["date"], **{field: row[field] for field in fields if field in row}}
            for row in sorted(inside, key=lambda row: row["date"])
        ], UPDATED_AT

    return read


def _window_totals(*rows):
    """Answer each get_os_metrics_totals read with the requested fields of the rows inside its window, as one total."""

    def read(*args, **kwargs):
        totals, updated_at = _totals(*rows)(*args, **kwargs)
        return merge_os_metrics_totals(totals, kwargs["fields"]), updated_at if totals else None

    return read


def _today_row():
    """Today: 3 sessions, 4 runs of which 3 completed, 300 tokens, two models."""
    return _row(
        _day(0),
        sessions_count=3,
        runs_count=4,
        status_metrics={"COMPLETED": 3, "ERROR": 1},
        token_metrics={"input_tokens": 200, "output_tokens": 100, "total_tokens": 300},
        duration_metrics={
            "duration_runs_count": 3,
            "total_duration_ms": 6000,
            "max_duration_ms": 4000,
            "time_to_first_token_runs_count": 3,
            "total_time_to_first_token_ms": 1500,
            "max_time_to_first_token_ms": 800,
            "model_calls_count": 4,
            "total_model_call_ms": 4000,
            "max_model_call_ms": 2000,
        },
        duration_buckets={
            "duration_ms_buckets": {"le_1000": 1, "le_2500": 1, "le_4000": 1},
            "time_to_first_token_ms_buckets": {"le_1000": 3},
            "model_call_ms_buckets": {"le_1000": 4},
        },
        model_metrics=[
            {
                "model_id": "gpt-5.5",
                "model_provider": "OpenAI",
                "agent_id": "a1",
                "count": 3,
            },
            {
                "model_id": "claude-opus-5",
                "model_provider": "Anthropic",
                "agent_id": "a2",
                "count": 1,
            },
        ],
    )


def _yesterday_row():
    """Yesterday: 1 session, 1 cancelled run and 1 completed run that was timed, 100 tokens."""
    return _row(
        _day(1),
        sessions_count=1,
        runs_count=2,
        status_metrics={"CANCELLED": 1, "COMPLETED": 1},
        token_metrics={"input_tokens": 60, "output_tokens": 40, "total_tokens": 100},
        duration_metrics={
            "duration_runs_count": 1,
            "total_duration_ms": 1000,
            "max_duration_ms": 1000,
            "time_to_first_token_runs_count": 1,
            "total_time_to_first_token_ms": 300,
            "max_time_to_first_token_ms": 300,
            "model_calls_count": 1,
            "total_model_call_ms": 500,
            "max_model_call_ms": 500,
        },
        duration_buckets={
            "duration_ms_buckets": {"le_1000": 1},
            "time_to_first_token_ms_buckets": {"le_300": 1},
            "model_call_ms_buckets": {"le_500": 1},
        },
        model_metrics=[
            {
                "model_id": "gpt-5.5",
                "model_provider": "OpenAI",
                "agent_id": "a2",
                "count": 1,
            }
        ],
    )


def _three_days_ago_row():
    """Three days ago: 4 sessions, 2 completed runs, 400 tokens, nothing timed."""
    return _row(
        _day(3),
        sessions_count=4,
        runs_count=2,
        status_metrics={"COMPLETED": 2},
        token_metrics={"input_tokens": 300, "output_tokens": 100, "total_tokens": 400},
        duration_metrics={},
        duration_buckets={},
        model_metrics=[],
    )


@pytest.fixture
def mock_db():
    """Rows for today, yesterday and three days ago, so a two-day window has the two days before it to compare with."""
    db = MagicMock()
    db.id = "db-1"
    db.get_os_metrics = MagicMock(side_effect=_totals(_today_row(), _yesterday_row(), _three_days_ago_row()))
    db.get_os_metrics_totals = MagicMock(
        side_effect=_window_totals(_today_row(), _yesterday_row(), _three_days_ago_row())
    )
    db.calculate_os_metrics = MagicMock(return_value=None)
    # A database that only rebuilds, as the committed tests of the refresh assume
    db.refresh_os_metrics = MagicMock(side_effect=NotImplementedError)
    return db


def _client(db=None):
    """A test client of the metrics router with auth off, the given database as the AgentOS database."""
    app = FastAPI()
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        app.include_router(
            get_metrics_router(dbs={db.id: [db]} if db is not None else {}, settings=AgnoAPISettings(), os_db=db)
        )
    return TestClient(app)


@pytest.fixture
def client(mock_db):
    return _client(mock_db)


def _scope(user_id):
    """Patch who is calling, at the helper the routes resolve the scope through."""
    return patch("agno.os.routers.metrics.metrics.get_scoped_user_id", return_value=user_id)


def _read_kwargs(mock_db):
    return mock_db.get_os_metrics.call_args.kwargs


# =============================================================================
# GET /os/metrics/sessions
# =============================================================================


class TestSessions:
    def test_every_day_of_the_window_is_listed_with_zero_for_a_day_without_rows(self, client):
        """A four-day window has one day without rows; all four days are still listed, oldest first."""
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(4)}").json()

        assert body["metrics"] == [
            {"date": _iso(_day(3)), "sessions_count": 4},
            {"date": _iso(_day(2)), "sessions_count": 0},
            {"date": _iso(_day(1)), "sessions_count": 1},
            {"date": _iso(_day(0)), "sessions_count": 3},
        ]
        assert body["total_sessions"] == 8
        assert body["updated_at"] == UPDATED_AT_ISO

    def test_both_windows_come_from_one_read_starting_at_the_previous_window(self, client, mock_db):
        """A two-day window ending today is read together with the two days before it."""
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(2)}").json()

        assert mock_db.get_os_metrics.call_count == 1
        kwargs = _read_kwargs(mock_db)
        assert kwargs["starting_date"] == _day(3)
        assert kwargs["ending_date"] == _day(0)
        assert kwargs["fields"] == ["sessions_count"]
        assert body["total_sessions"] == 4
        assert body["previous_total_sessions"] == 4
        assert body["change_percent"] == 0.0

    def test_rise_and_a_fall_carry_their_sign(self, client, mock_db):
        """Today's 3 sessions against yesterday's 1; yesterday's 1 against 4 the day before."""
        mock_db.get_os_metrics.side_effect = _totals(_today_row(), _yesterday_row(), _row(_day(2), sessions_count=4))
        yesterday = _day(1)
        with _scope(None):
            rise = client.get(f"/os/metrics/sessions?{_last(1)}").json()
            fall = client.get(
                f"/os/metrics/sessions?starting_date={yesterday.isoformat()}&ending_date={yesterday.isoformat()}"
            ).json()

        assert rise["change_percent"] == 200.0
        assert fall["change_percent"] == -75.0

    def test_no_sessions_before_means_no_rate(self, client, mock_db):
        """A window with nothing before it cannot show an infinite rise."""
        mock_db.get_os_metrics.side_effect = _totals(_today_row())
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["previous_total_sessions"] == 0
        assert body["change_percent"] is None

    def test_default_window_is_the_last_thirty_days(self, client, mock_db):
        with _scope(None):
            body = client.get("/os/metrics/sessions").json()

        assert len(body["metrics"]) == 30
        assert body["metrics"][0]["date"] == _iso(_day(29))
        assert _read_kwargs(mock_db)["starting_date"] == _day(59)

    def test_admin_can_narrow_to_one_user(self, client, mock_db):
        with _scope(None):
            client.get(f"/os/metrics/sessions?{_last(1)}&user_id=alice")

        assert _read_kwargs(mock_db)["user_id"] == "alice"

    def test_scoped_caller_cannot_widen_to_another_user(self, client, mock_db):
        with _scope("alice"):
            client.get(f"/os/metrics/sessions?{_last(1)}&user_id=bob")

        assert _read_kwargs(mock_db)["user_id"] == "alice"

    def test_unscoped_caller_reads_every_owner(self, client, mock_db):
        with _scope(None):
            client.get(f"/os/metrics/sessions?{_last(1)}")

        assert _read_kwargs(mock_db)["user_id"] is None


# =============================================================================
# GET /os/metrics/tokens
# =============================================================================


class TestTokens:
    def test_each_day_carries_its_total_tokens(self, client, mock_db):
        with _scope(None):
            body = client.get(f"/os/metrics/tokens?{_last(2)}").json()

        assert [(day["date"], day["tokens_count"]) for day in body["metrics"]] == [
            (_iso(_day(1)), 100),
            (_iso(_day(0)), 300),
        ]
        assert set(body["metrics"][0]) == {"date", "tokens_count"}
        assert body["total_tokens"] == 400
        assert body["previous_total_tokens"] == 400
        assert body["change_percent"] == 0.0
        assert _read_kwargs(mock_db)["starting_date"] == _day(3)

    def test_day_without_rows_counts_no_tokens(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/tokens?{_last(3)}").json()

        assert body["metrics"][0] == {
            "date": _iso(_day(2)),
            "tokens_count": 0,
        }

    def test_no_tokens_before_means_no_rate(self, client, mock_db):
        mock_db.get_os_metrics.side_effect = _totals(_today_row())
        with _scope(None):
            body = client.get(f"/os/metrics/tokens?{_last(1)}").json()

        assert body["change_percent"] is None

    def test_asks_only_for_fields_the_database_can_total(self, client, mock_db):
        """A real adapter rejects an unknown field with ValueError, which the route turns into a 500."""
        with _scope(None):
            client.get(f"/os/metrics/tokens?{_last(1)}")

        assert resolve_os_metrics_fields(_read_kwargs(mock_db)["fields"]) == ["token_metrics"]

    def test_window_days_counts_both_ends(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/tokens?{_last(3)}").json()

        assert body["window_days"] == 3
        assert len(body["metrics"]) == 3


# =============================================================================
# GET /os/metrics/runs
# =============================================================================


class TestRuns:
    def test_each_day_carries_its_runs_by_status(self, client, mock_db):
        with _scope(None):
            body = client.get(f"/os/metrics/runs?{_last(2)}").json()

        assert body["metrics"] == [
            {"date": _iso(_day(1)), "runs_count": 2, "status_metrics": {"CANCELLED": 1, "COMPLETED": 1}},
            {"date": _iso(_day(0)), "runs_count": 4, "status_metrics": {"COMPLETED": 3, "ERROR": 1}},
        ]
        assert body["total_runs"] == 6
        assert body["status_metrics"] == {"CANCELLED": 1, "COMPLETED": 4, "ERROR": 1}
        assert _read_kwargs(mock_db)["fields"] == ["runs_count", "status_metrics"]

    def test_change_is_against_the_window_of_the_same_length_before(self, client, mock_db):
        with _scope(None):
            body = client.get(f"/os/metrics/runs?{_last(2)}").json()

        assert _read_kwargs(mock_db)["starting_date"] == _day(3)
        assert body["previous_total_runs"] == 2
        assert body["change_percent"] == 200.0

    def test_day_without_rows_has_no_runs(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/runs?{_last(3)}").json()

        assert body["metrics"][0] == {"date": _iso(_day(2)), "runs_count": 0, "status_metrics": {}}

    def test_success_rate_is_the_completed_share_of_the_finished_runs(self, client):
        """4 completed of the 6 finished (completed, errored or cancelled) runs."""
        with _scope(None):
            body = client.get(f"/os/metrics/runs?{_last(2)}").json()

        assert body["success_rate"] == 66.7

    def test_run_still_running_is_not_rated(self, client, mock_db):
        mock_db.get_os_metrics.side_effect = _totals(
            _row(_day(0), runs_count=2, status_metrics={"RUNNING": 1, "PAUSED": 1})
        )
        with _scope(None):
            body = client.get(f"/os/metrics/runs?{_last(1)}").json()

        assert body["total_runs"] == 2
        assert body["success_rate"] is None
        assert body["change_percent"] is None


# =============================================================================
# GET /os/metrics/latency
# =============================================================================


class TestLatency:
    def test_each_day_carries_its_count_average_median_and_slowest(self, client, mock_db):
        """Yesterday one run of 1000 ms in le_1000; today 3 runs, 6000 ms in all, one each in le_1000, le_2500, le_4000."""
        with _scope(None):
            body = client.get(f"/os/metrics/latency?{_last(2)}").json()

        assert _read_kwargs(mock_db)["fields"] == ["duration_metrics", "duration_buckets"]
        assert body["metrics"] == [
            {
                "date": _iso(_day(1)),
                "runs_count": 1,
                "avg_duration_ms": 1000,
                # one run: its median and p95 are the run itself, the day's max
                "median_duration_ms": 1000,
                "p95_duration_ms": 1000,
                "max_duration_ms": 1000,
                "avg_time_to_first_token_ms": 300,
                "median_time_to_first_token_ms": 300,
                "p95_time_to_first_token_ms": 300,
                "max_time_to_first_token_ms": 300,
                "avg_model_call_ms": 500,
                "median_model_call_ms": 500,
                "p95_model_call_ms": 500,
                "max_model_call_ms": 500,
            },
            {
                "date": _iso(_day(0)),
                "runs_count": 3,
                "avg_duration_ms": 2000,
                # the middle run is the one in le_2500, read a third of the way through 1000-2500
                "median_duration_ms": 2250,
                # target 2.85 of 3 lands 0.85 of the way through the 3000-4000 bucket
                "p95_duration_ms": 3850,
                "max_duration_ms": 4000,
                "avg_time_to_first_token_ms": 500,
                # three runs in le_1000 read as 900 and 990, capped at the day's slowest, 800
                "median_time_to_first_token_ms": 800,
                "p95_time_to_first_token_ms": 800,
                "max_time_to_first_token_ms": 800,
                "avg_model_call_ms": 1000,
                # four calls in the 800-1000 bucket, the middle read halfway, the p95 near the top
                "median_model_call_ms": 900,
                "p95_model_call_ms": 990,
                "max_model_call_ms": 2000,
            },
        ]

    def test_window_reads_over_every_timed_run(self, client):
        """4 runs took 7000 ms in all; the buckets add up to {le_1000: 2, le_2500: 1, le_4000: 1}."""
        with _scope(None):
            body = client.get(f"/os/metrics/latency?{_last(2)}").json()

        assert body["runs_count"] == 4
        assert body["avg_duration_ms"] == 1750
        assert body["median_duration_ms"] == 1000
        # target 3.8 of 4 lands eight tenths of the way through the 3000-4000 bucket
        assert body["p95_duration_ms"] == 3800
        assert body["max_duration_ms"] == 4000
        assert body["avg_time_to_first_token_ms"] == 450
        assert body["median_time_to_first_token_ms"] == 800
        assert body["p95_time_to_first_token_ms"] == 800
        assert body["max_time_to_first_token_ms"] == 800
        assert body["avg_model_call_ms"] == 900
        # 1 model call in le_500 and 4 in le_1000: both percentiles land in the 800-1000 bucket
        assert body["median_model_call_ms"] == 875
        assert body["p95_model_call_ms"] == 988
        assert body["max_model_call_ms"] == 2000
        assert body["window_days"] == 2

    def test_day_without_a_completed_run_has_no_timings(self, client):
        three_days_ago = _day(3)
        with _scope(None):
            body = client.get(
                f"/os/metrics/latency?starting_date={three_days_ago.isoformat()}&ending_date={three_days_ago.isoformat()}"
            ).json()

        assert body["metrics"] == [
            {
                "date": _iso(three_days_ago),
                "runs_count": 0,
                "avg_duration_ms": None,
                "median_duration_ms": None,
                "p95_duration_ms": None,
                "max_duration_ms": None,
                "avg_time_to_first_token_ms": None,
                "median_time_to_first_token_ms": None,
                "p95_time_to_first_token_ms": None,
                "max_time_to_first_token_ms": None,
                "avg_model_call_ms": None,
                "median_model_call_ms": None,
                "p95_model_call_ms": None,
                "max_model_call_ms": None,
            }
        ]
        assert body["runs_count"] == 0
        assert body["avg_duration_ms"] is None
        assert body["median_duration_ms"] is None
        assert body["p95_model_call_ms"] is None

    def test_median_never_exceeds_the_slowest_timing(self, client, mock_db):
        """One run of 1709 ms fills the 2000 ms bucket; read alone it would be 1750, the max says 1709."""
        one_run = _row(
            _day(0),
            duration_metrics={"duration_runs_count": 1, "total_duration_ms": 1709, "max_duration_ms": 1709},
            duration_buckets={"duration_ms_buckets": {"le_2000": 1}},
        )
        mock_db.get_os_metrics.side_effect = _totals(one_run)
        with _scope(None):
            body = client.get(f"/os/metrics/latency?{_last(1)}").json()

        assert body["metrics"][0]["median_duration_ms"] == 1709
        assert body["median_duration_ms"] == 1709
        assert body["p95_duration_ms"] == 1709
        assert body["max_duration_ms"] == 1709


# =============================================================================
# GET /os/metrics/models
# =============================================================================


class TestModels:
    def test_runs_add_up_per_model_across_the_days_most_run_first(self, client, mock_db):
        """gpt-5.5 served 3 runs today and 1 yesterday, claude 1 today."""
        with _scope(None):
            body = client.get(f"/os/metrics/models?{_last(2)}").json()

        mock_db.get_os_metrics.assert_not_called()
        kwargs = mock_db.get_os_metrics_totals.call_args.kwargs
        assert kwargs["fields"] == ["model_metrics"]
        assert kwargs["starting_date"] == _day(1)
        assert kwargs["ending_date"] == _day(0)
        assert [(model["model_id"], model["model_provider"], model["runs_count"]) for model in body["models"]] == [
            ("gpt-5.5", "OpenAI", 4),
            ("claude-opus-5", "Anthropic", 1),
        ]
        assert [model["runs_share"] for model in body["models"]] == [80.0, 20.0]
        assert body["total_model_runs"] == 5
        assert body["window_days"] == 2
        assert set(body["models"][0]) == {"model_id", "model_provider", "runs_count", "runs_share"}
        assert body["updated_at"] == UPDATED_AT_ISO

    def test_database_without_window_totals_has_its_days_totalled(self, client, mock_db):
        """The window is read per day and totalled by the route."""
        mock_db.get_os_metrics_totals.side_effect = NotImplementedError
        with _scope(None):
            body = client.get(f"/os/metrics/models?{_last(2)}").json()

        kwargs = _read_kwargs(mock_db)
        assert kwargs["fields"] == ["model_metrics"]
        assert kwargs["starting_date"] == _day(1)
        assert [(model["model_id"], model["runs_count"]) for model in body["models"]] == [
            ("gpt-5.5", 4),
            ("claude-opus-5", 1),
        ]
        assert body["updated_at"] == UPDATED_AT_ISO

    def test_scoped_caller_reads_only_their_own_models(self, client, mock_db):
        with _scope("alice"):
            client.get(f"/os/metrics/models?{_last(1)}&user_id=bob")

        assert mock_db.get_os_metrics_totals.call_args.kwargs["user_id"] == "alice"

    def test_window_without_runs_lists_no_models(self, client, mock_db):
        mock_db.get_os_metrics_totals.side_effect = _window_totals()
        with _scope(None):
            body = client.get(f"/os/metrics/models?{_last(1)}").json()

        assert body["models"] == []
        assert body["total_model_runs"] == 0


# =============================================================================
# POST /os/metrics/refresh
# =============================================================================


class TestRefresh:
    def test_rebuilds_the_os_metrics_and_reports_completed(self, client, mock_db):
        with _scope(None):
            response = client.post("/os/metrics/refresh")

        assert response.status_code == 200
        mock_db.calculate_os_metrics.assert_called_once_with()
        body = response.json()
        assert body["status"] == "completed"
        assert body["started_at"] is not None
        assert body["finished_at"] is not None
        assert body["error"] is None

    def test_async_database_is_awaited(self):
        db = MagicMock(spec=AsyncBaseDb)
        db.id = "db-async"
        db.calculate_os_metrics = AsyncMock(return_value=None)
        db.refresh_os_metrics = AsyncMock(side_effect=NotImplementedError)
        with _scope(None):
            response = _client(db).post("/os/metrics/refresh")

        assert response.status_code == 200
        db.calculate_os_metrics.assert_awaited_once_with()
        assert response.json()["status"] == "completed"

    @pytest.mark.parametrize("background", [False, True])
    def test_database_without_os_metrics_cannot_refresh(self, background):
        """A database still on the base stubs is refused before anything runs, so nothing is told 'started'."""

        class NoOsMetricsDb(MagicMock):
            get_os_metrics = BaseDb.get_os_metrics
            calculate_os_metrics = BaseDb.calculate_os_metrics

        db = NoOsMetricsDb(spec=BaseDb)
        db.id = "db-1"
        with _scope(None):
            response = _client(db).post(f"/os/metrics/refresh?background={str(background).lower()}")

        assert response.status_code == 501
        assert response.json()["detail"] == "OS metrics not supported by the configured database"

    def test_database_with_only_one_of_the_two_methods_is_a_501(self):
        """Implementing the read without the rebuild, or the reverse, is not storing the table."""

        class OnlyRead(MagicMock):
            calculate_os_metrics = BaseDb.calculate_os_metrics

        db = OnlyRead(spec=BaseDb)
        db.id = "db-1"
        client = _client(db)
        with _scope(None):
            assert client.post("/os/metrics/refresh").status_code == 501
            assert client.post("/os/metrics/refresh?background=true").status_code == 501

    def test_rebuild_that_raises_without_a_message_is_a_failure(self, client, mock_db):
        """An override that raises a bare NotImplementedError cannot be told apart by its type: it fails, loudly."""
        mock_db.calculate_os_metrics.side_effect = NotImplementedError
        with _scope(None):
            response = client.post("/os/metrics/refresh")

        assert response.status_code == 500
        # The refresh is recorded as failed, so the next caller is not told one is running
        mock_db.calculate_os_metrics.side_effect = None
        with _scope(None):
            assert client.post("/os/metrics/refresh").json()["status"] == "completed"

    def test_background_failure_without_a_message_is_still_logged_as_one(self, client, mock_db, caplog):
        """str(NotImplementedError()) is empty; the failure is logged by its type instead of as nothing."""
        mock_db.calculate_os_metrics.side_effect = NotImplementedError
        with _scope(None), caplog.at_level(logging.ERROR, logger="agno"):
            assert client.post("/os/metrics/refresh?background=true").status_code == 202

        assert "Error refreshing OS metrics: NotImplementedError" in caplog.text

    def test_failed_rebuild_is_reported_and_raised(self, client, mock_db):
        mock_db.calculate_os_metrics.side_effect = RuntimeError("database unavailable")
        with _scope(None):
            response = client.post("/os/metrics/refresh")

        assert response.status_code == 500
        assert "database unavailable" in response.json()["detail"]

    def test_second_caller_is_told_one_is_already_running(self, client, mock_db):
        seen = {}

        def reenter():
            # Fired while the first refresh is still in flight, so the state says "running"
            seen["inner"] = client.post("/os/metrics/refresh").json()
            return None

        mock_db.calculate_os_metrics.side_effect = reenter
        with _scope(None):
            outer = client.post("/os/metrics/refresh")

        assert outer.status_code == 200
        assert outer.json()["status"] == "completed"
        assert seen["inner"]["status"] == "already_running"
        assert mock_db.calculate_os_metrics.call_count == 1

    def test_background_refresh_returns_202_and_runs(self, client, mock_db):
        with _scope(None):
            response = client.post("/os/metrics/refresh?background=true")

        assert response.status_code == 202
        assert response.json() == {"status": "started", "message": "Metrics refresh started in background"}
        mock_db.calculate_os_metrics.assert_called_once_with()

    def test_refresh_that_found_nothing_new_reports_no_change(self, client, mock_db):
        mock_db.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        mock_db.refresh_os_metrics.assert_called_once_with()
        mock_db.calculate_os_metrics.assert_not_called()
        assert body["status"] == "completed"
        assert body["changed"] is False
        assert body["previous_updated_at"] == UPDATED_AT_ISO
        assert body["updated_at"] == UPDATED_AT_ISO
        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO}
        assert body["skipped_db_ids"] == {}

    def test_refresh_that_wrote_a_row_reports_the_change(self, client, mock_db):
        mock_db.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT + 60, True))
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        assert body["changed"] is True
        assert body["previous_updated_at"] == UPDATED_AT_ISO
        assert body["updated_at"] == "2027-01-15T08:01:00Z"

    def test_change_is_what_the_rebuild_did_not_what_the_stamps_say(self, client, mock_db):
        """Two rebuilds within one second, or a rebuild that only deleted rows, leave the stamp where it was."""
        mock_db.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, True))
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        assert body["previous_updated_at"] == body["updated_at"]
        assert body["changed"] is True

    def test_first_refresh_of_an_empty_table_has_no_previous_stamp(self, client, mock_db):
        mock_db.refresh_os_metrics = MagicMock(return_value=(None, UPDATED_AT, True))
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        assert body["previous_updated_at"] is None
        assert body["updated_at"] == UPDATED_AT_ISO

    def test_database_that_only_rebuilds_is_taken_to_have_changed(self, client, mock_db):
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        mock_db.calculate_os_metrics.assert_called_once_with()
        assert body["changed"] is True
        assert body["updated_at"] is None
        assert body["db_ids"] == {"db-1": None}

    def test_async_database_is_awaited_for_what_changed(self):
        db = MagicMock(spec=AsyncBaseDb)
        db.id = "db-async"
        db.refresh_os_metrics = AsyncMock(return_value=(UPDATED_AT, UPDATED_AT + 60, True))
        with _scope(None):
            body = _client(db).post("/os/metrics/refresh").json()

        db.refresh_os_metrics.assert_awaited_once_with()
        assert body["changed"] is True

    def test_every_database_is_refreshed_and_one_change_is_a_change(self):
        first, second, third = _db("db-1"), _db("db-2"), _db("db-3")
        first.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
        second.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT - 60, UPDATED_AT + 60, True))
        third.refresh_os_metrics = MagicMock(side_effect=RuntimeError("database unavailable"))
        with _scope(None):
            response = _dbs_client(first, second, third).post("/os/metrics/refresh")

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "completed"
        assert body["changed"] is True
        assert body["previous_updated_at"] == UPDATED_AT_ISO
        assert body["updated_at"] == "2027-01-15T08:01:00Z"
        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO, "db-2": "2027-01-15T08:01:00Z"}
        assert body["skipped_db_ids"] == {"db-3": "failed"}

    def test_db_id_chooses_the_databases_to_refresh(self):
        first, second = _db("db-1"), _db("db-2")
        first.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
        second.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
        with _scope(None):
            body = _dbs_client(first, second).post("/os/metrics/refresh?db_id=db-2").json()

        first.refresh_os_metrics.assert_not_called()
        assert list(body["db_ids"]) == ["db-2"]

    def test_refresh_of_another_database_is_not_told_one_is_already_running(self):
        first, second = _db("db-1"), _db("db-2")
        client = _dbs_client(first, second)
        seen = {}

        def reenter():
            # Fired while the refresh of db-1 is still in flight
            seen["other"] = client.post("/os/metrics/refresh?db_id=db-2").json()
            seen["same"] = client.post("/os/metrics/refresh?db_id=db-1").json()
            return UPDATED_AT, UPDATED_AT, False

        first.refresh_os_metrics = MagicMock(side_effect=reenter)
        second.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
        with _scope(None):
            client.post("/os/metrics/refresh?db_id=db-1")

        assert seen["other"]["status"] == "completed"
        assert seen["same"]["status"] == "already_running"
        second.refresh_os_metrics.assert_called_once_with()

    def test_refresh_of_a_database_already_being_refreshed_is_told_one_is_running(self):
        first, second = _db("db-1"), _db("db-2")
        client = _dbs_client(first, second)
        seen = {}

        def reenter():
            # Fired while the refresh of every database is still in flight
            seen["one"] = client.post("/os/metrics/refresh?db_id=db-2").json()
            return UPDATED_AT, UPDATED_AT, False

        first.refresh_os_metrics = MagicMock(side_effect=reenter)
        second.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
        with _scope(None):
            client.post("/os/metrics/refresh")
            after = client.post("/os/metrics/refresh?db_id=db-2").json()

        assert seen["one"]["status"] == "already_running"
        assert after["status"] == "completed"

    def test_background_refresh_is_read_back_from_the_status(self, client, mock_db):
        """The 202 is sent before the rebuild runs, so what changed is read from the status afterwards."""
        mock_db.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT - 60, UPDATED_AT, True))
        with _scope(None):
            started = client.post("/os/metrics/refresh?background=true")
            status = client.get("/os/metrics/refresh/status").json()

        assert started.status_code == 202
        assert started.json() == {"status": "started", "message": "Metrics refresh started in background"}
        mock_db.refresh_os_metrics.assert_called_once_with()
        assert status == {"updated_at": UPDATED_AT_ISO, "db_ids": {"db-1": UPDATED_AT_ISO}, "skipped_db_ids": {}}

    def test_identity_less_caller_cannot_start_a_refresh(self, client, mock_db):
        with patch(
            "agno.os.routers.metrics.metrics.get_scoped_user_id",
            side_effect=HTTPException(status_code=403, detail="Authenticated request is missing a user identity"),
        ):
            response = client.post("/os/metrics/refresh?background=true")

        assert response.status_code == 403
        mock_db.calculate_os_metrics.assert_not_called()


# =============================================================================
# GET /os/metrics/refresh/status
# =============================================================================


class TestRefreshStatus:
    def test_reports_when_the_database_last_wrote_the_window(self, client, mock_db):
        with _scope(None):
            body = client.get(f"/os/metrics/refresh/status?{_last(3)}").json()

        assert body == {"updated_at": UPDATED_AT_ISO, "db_ids": {"db-1": UPDATED_AT_ISO}, "skipped_db_ids": {}}
        kwargs = _read_kwargs(mock_db)
        assert kwargs["starting_date"] == _day(2)
        assert kwargs["ending_date"] == _day(0)

    def test_window_without_rows_has_no_stamp(self, client, mock_db):
        mock_db.get_os_metrics.side_effect = None
        mock_db.get_os_metrics.return_value = ([], None)
        with _scope(None):
            body = client.get("/os/metrics/refresh/status").json()

        assert body["updated_at"] is None

    def test_stamp_is_read_for_the_caller(self, client, mock_db):
        with _scope("alice"):
            client.get("/os/metrics/refresh/status")

        assert _read_kwargs(mock_db)["user_id"] == "alice"

    def test_synchronous_refresh_answers_when_the_rebuild_has_landed(self, client, mock_db):
        """The caller that needs to know a rebuild is done awaits the POST; the status carries no refresh state."""
        with _scope(None):
            refresh = client.post("/os/metrics/refresh").json()
            body = client.get("/os/metrics/refresh/status").json()

        assert refresh["status"] == "completed"
        mock_db.calculate_os_metrics.assert_called_once_with()
        assert body["updated_at"] == UPDATED_AT_ISO


# =============================================================================
# Availability and window bounds, shared by every route
# =============================================================================

READ_ROUTES = ("sessions", "tokens", "runs", "latency", "models", "refresh/status")


class TestAvailability:
    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_only_database_without_os_metrics_is_a_501(self, client, mock_db, route):
        mock_db.get_os_metrics.side_effect = NotImplementedError
        mock_db.get_os_metrics_totals.side_effect = NotImplementedError
        with _scope(None):
            response = client.get(f"/os/metrics/{route}?{_last(1)}")

        assert response.status_code == 501
        assert response.json()["detail"] == "OS metrics not supported by the configured database"

    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_os_without_a_database_is_a_400(self, route):
        with _scope(None):
            response = _client().get(f"/os/metrics/{route}?{_last(1)}")

        assert response.status_code == 400
        assert response.json()["detail"] == "No database is configured on this AgentOS"

    def test_os_without_a_database_cannot_refresh(self):
        with _scope(None):
            assert _client().post("/os/metrics/refresh").status_code == 400

    def test_os_without_its_own_database_reads_the_registered_databases(self):
        """An AgentOS given no db still has the databases of its agents, teams and workflows."""
        db = _db("db-1", _today_row())
        app = FastAPI()
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            app.include_router(get_metrics_router(dbs={db.id: [db]}, settings=AgnoAPISettings(), os_db=None))
        with _scope(None):
            body = TestClient(app).get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 3
        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO}

    def test_only_database_failing_is_a_503(self, client, mock_db):
        mock_db.get_os_metrics.side_effect = RuntimeError("boom")
        with _scope(None):
            response = client.get(f"/os/metrics/sessions?{_last(1)}")

        assert response.status_code == 503
        assert response.json()["detail"] == "OS metrics not available from any database: 'db-1' (failed)"

    def test_async_database_is_awaited_for_a_read(self):
        db = MagicMock(spec=AsyncBaseDb)
        db.id = "db-async"
        db.get_os_metrics = AsyncMock(side_effect=_totals(_today_row()))
        with _scope(None):
            body = _client(db).get(f"/os/metrics/sessions?{_last(1)}").json()

        db.get_os_metrics.assert_awaited_once()
        assert body["total_sessions"] == 3


# =============================================================================
# Several databases, read at the same time and added up
# =============================================================================


def _db(db_id, *rows):
    """A database with the given id that answers both reads from the given rows."""
    db = MagicMock()
    db.id = db_id
    db.get_os_metrics = MagicMock(side_effect=_totals(*rows))
    db.get_os_metrics_totals = MagicMock(side_effect=_window_totals(*rows))
    return db


def _dbs_client(os_db, *other_dbs):
    """A test client of the metrics router for an AgentOS with the given databases, the first its own."""
    app = FastAPI()
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        app.include_router(
            get_metrics_router(dbs={db.id: [db] for db in (os_db, *other_dbs)}, settings=AgnoAPISettings(), os_db=os_db)
        )
    return TestClient(app)


def _same_id_client(support_table, sales_table, *other_dbs):
    """A test client for two databases registered under one id, each with the given OS metrics table."""
    support_db, sales_db = _db("db-1", _today_row()), _db("db-1", _today_row())
    support_db.os_metrics_table_name, sales_db.os_metrics_table_name = support_table, sales_table
    for db in (support_db, sales_db):
        db.refresh_os_metrics = MagicMock(return_value=(UPDATED_AT, UPDATED_AT, False))
    app = FastAPI()
    with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
        app.include_router(
            get_metrics_router(
                dbs={"db-1": [support_db, sales_db], **{db.id: [db] for db in other_dbs}},
                settings=AgnoAPISettings(),
                os_db=support_db,
            )
        )
    return TestClient(app), support_db, sales_db


class TestDatabases:
    def test_databases_are_added_up(self):
        """Two databases hold today's row each, and one also yesterday's: every number is the sum."""
        client = _dbs_client(_db("db-1", _today_row(), _yesterday_row()), _db("db-2", _today_row()))
        with _scope(None):
            sessions = client.get(f"/os/metrics/sessions?{_last(2)}").json()
            runs = client.get(f"/os/metrics/runs?{_last(2)}").json()
            latency = client.get(f"/os/metrics/latency?{_last(1)}").json()
            models = client.get(f"/os/metrics/models?{_last(2)}").json()

        assert [day["sessions_count"] for day in sessions["metrics"]] == [1, 6]
        assert sessions["total_sessions"] == 7
        assert runs["metrics"][1]["status_metrics"] == {"COMPLETED": 6, "ERROR": 2}
        assert runs["total_runs"] == 10
        # A maximum is the larger of the two, and the median is read from the added bucket counts
        assert latency["runs_count"] == 6
        assert latency["avg_duration_ms"] == 2000
        assert latency["max_duration_ms"] == 4000
        assert (
            latency["median_duration_ms"]
            == _client(_db("db-3", _today_row())).get(f"/os/metrics/latency?{_last(1)}").json()["median_duration_ms"]
        )
        assert [(model["model_id"], model["runs_count"]) for model in models["models"]] == [
            ("gpt-5.5", 7),
            ("claude-opus-5", 2),
        ]
        assert sessions["db_ids"] == {"db-1": UPDATED_AT_ISO, "db-2": UPDATED_AT_ISO}
        assert sessions["skipped_db_ids"] == {}

    def test_one_database_still_names_itself(self, client):
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO}
        assert body["skipped_db_ids"] == {}

    def test_updated_at_is_the_newest_of_the_databases(self):
        later = _db("db-2", _today_row())
        later.get_os_metrics.side_effect = lambda **kwargs: ([], UPDATED_AT + 60)
        with _scope(None):
            body = _dbs_client(_db("db-1", _today_row()), later).get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO, "db-2": "2027-01-15T08:01:00Z"}
        assert body["updated_at"] == "2027-01-15T08:01:00Z"

    @pytest.mark.parametrize(
        "error, reason", [(RuntimeError("boom"), "failed"), (NotImplementedError(), "unsupported")]
    )
    def test_database_that_cannot_be_read_is_skipped(self, error, reason):
        """The other database still answers, and the response names the one left out and why."""
        broken = _db("db-2", _today_row())
        broken.get_os_metrics.side_effect = error
        broken.get_os_metrics_totals.side_effect = error
        client = _dbs_client(_db("db-1", _today_row()), broken)
        with _scope(None):
            sessions = client.get(f"/os/metrics/sessions?{_last(1)}")
            models = client.get(f"/os/metrics/models?{_last(1)}")

        assert sessions.status_code == 200
        assert sessions.json()["total_sessions"] == 3
        assert sessions.json()["db_ids"] == {"db-1": UPDATED_AT_ISO}
        assert sessions.json()["skipped_db_ids"] == {"db-2": reason}
        assert models.json()["total_model_runs"] == 4
        assert models.json()["skipped_db_ids"] == {"db-2": reason}

    def test_database_that_does_not_answer_in_time_is_skipped(self):
        slow = _db("db-2", _today_row())
        slow.get_os_metrics.side_effect = lambda **kwargs: time.sleep(0.5) or ([], None)
        client = _dbs_client(_db("db-1", _today_row()), slow)
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}&timeout_seconds=0.05").json()

        assert body["total_sessions"] == 3
        assert body["skipped_db_ids"] == {"db-2": "timeout"}

    def test_caller_can_wait_longer_for_a_database(self):
        slow = _db("db-2", _today_row())
        read = slow.get_os_metrics.side_effect
        slow.get_os_metrics.side_effect = lambda **kwargs: time.sleep(0.3) or read(**kwargs)
        client = _dbs_client(_db("db-1", _today_row()), slow)
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}&timeout_seconds=1").json()
            refused = client.get(f"/os/metrics/sessions?{_last(1)}&timeout_seconds=0")

        assert body["total_sessions"] == 6
        assert body["skipped_db_ids"] == {}
        assert refused.status_code == 422

    def test_remote_database_is_unsupported(self):
        remote = MagicMock(spec=RemoteDb)
        remote.id = "db-remote"
        with _scope(None):
            body = _dbs_client(_db("db-1", _today_row()), remote).get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["skipped_db_ids"] == {"db-remote": "unsupported"}

    def test_every_database_skipped_is_a_503(self):
        first, second = _db("db-1"), _db("db-2")
        first.get_os_metrics.side_effect = RuntimeError("boom")
        second.get_os_metrics.side_effect = NotImplementedError
        with _scope(None):
            response = _dbs_client(first, second).get(f"/os/metrics/sessions?{_last(1)}")

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "OS metrics not available from any database: 'db-1' (failed), 'db-2' (unsupported)"
        )

    def test_db_id_chooses_the_databases_to_read(self):
        dbs = [_db("db-1", _today_row()), _db("db-2", _today_row()), _db("db-3", _today_row())]
        client = _dbs_client(*dbs)
        with _scope(None):
            one = client.get(f"/os/metrics/sessions?{_last(1)}&db_id=db-2").json()
            two = client.get(f"/os/metrics/sessions?{_last(1)}&db_id=db-3&db_id=db-1").json()

        assert one["total_sessions"] == 3
        assert list(one["db_ids"]) == ["db-2"]
        assert two["total_sessions"] == 6
        assert set(two["db_ids"]) == {"db-1", "db-3"}
        assert dbs[0].get_os_metrics.call_count == 1

    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_unknown_db_id_is_refused(self, client, mock_db, route):
        with _scope(None):
            response = client.get(f"/os/metrics/{route}?{_last(1)}&db_id=db-1&db_id=nope")

        assert response.status_code == 404
        assert response.json()["detail"] == "No database found with id 'nope'"
        mock_db.get_os_metrics.assert_not_called()

    def test_database_registered_more_than_once_is_read_once(self):
        db = _db("db-1", _today_row())
        app = FastAPI()
        with patch("agno.os.routers.metrics.metrics.get_authentication_dependency", return_value=lambda: True):
            app.include_router(get_metrics_router(dbs={"db-1": [db, db]}, settings=AgnoAPISettings(), os_db=db))
        with _scope(None):
            body = TestClient(app).get(f"/os/metrics/sessions?{_last(1)}").json()

        assert db.get_os_metrics.call_count == 1
        assert body["total_sessions"] == 3

    def test_databases_with_one_id_and_their_own_tables_are_added_up(self):
        """Two databases registered under one id keep their OS metrics in different tables: both are read."""
        client, support_db, sales_db = _same_id_client("support_os_metrics", "sales_os_metrics")
        sales_db.get_os_metrics.side_effect = lambda **kwargs: ([_row(_day(0), sessions_count=4)], UPDATED_AT + 60)
        with _scope(None):
            sessions = client.get(f"/os/metrics/sessions?{_last(1)}").json()
            models = client.get(f"/os/metrics/models?{_last(1)}&db_id=db-1").json()

        assert support_db.get_os_metrics.call_count == 1
        assert sales_db.get_os_metrics.call_count == 1
        assert sessions["total_sessions"] == 7
        # One entry for the id, with the newest update of its databases
        assert sessions["db_ids"] == {"db-1": "2027-01-15T08:01:00Z"}
        assert sessions["updated_at"] == "2027-01-15T08:01:00Z"
        assert models["total_model_runs"] == 8

    def test_databases_with_one_id_that_share_a_table_are_read_once(self):
        """Reading both would count the rows of the shared table twice."""
        client, support_db, sales_db = _same_id_client("agno_os_metrics", "agno_os_metrics")
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()
            refresh = client.post("/os/metrics/refresh").json()

        assert support_db.get_os_metrics.call_count == 1
        sales_db.get_os_metrics.assert_not_called()
        assert body["total_sessions"] == 3
        support_db.refresh_os_metrics.assert_called_once_with()
        sales_db.refresh_os_metrics.assert_not_called()
        assert refresh["db_ids"] == {"db-1": UPDATED_AT_ISO}

    def test_one_database_of_an_id_skipped_still_counts_the_other(self):
        """The database that did answer is counted, and its id is named with the reason the other was left out."""
        client, _, sales_db = _same_id_client("support_os_metrics", "sales_os_metrics")
        sales_db.get_os_metrics.side_effect = RuntimeError("boom")
        with _scope(None):
            body = client.get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 3
        assert body["db_ids"] == {"db-1": UPDATED_AT_ISO}
        assert body["skipped_db_ids"] == {"db-1": "failed"}

    def test_every_database_of_an_id_is_refreshed(self):
        client, support_db, sales_db = _same_id_client("support_os_metrics", "sales_os_metrics")
        sales_db.refresh_os_metrics.return_value = (UPDATED_AT, UPDATED_AT + 60, True)
        with _scope(None):
            body = client.post("/os/metrics/refresh").json()

        support_db.refresh_os_metrics.assert_called_once_with()
        sales_db.refresh_os_metrics.assert_called_once_with()
        assert body["changed"] is True
        assert body["db_ids"] == {"db-1": "2027-01-15T08:01:00Z"}

    def test_read_that_timed_out_is_left_to_finish(self):
        """A read may have started a rebuild: the route stops waiting for it, and never cancels it."""
        finished = []

        async def slow_read(**kwargs):
            await asyncio.sleep(1.5)
            finished.append(True)
            return [], None

        slow = MagicMock(spec=AsyncBaseDb)
        slow.id = "db-2"
        slow.get_os_metrics = AsyncMock(side_effect=slow_read)
        with _scope(None):
            # Entered, so the event loop of the first request is still running after it has answered
            with _dbs_client(_db("db-1", _today_row()), slow) as client:
                # Long enough for the other database to answer on a busy machine: one that did not would be skipped too
                body = client.get(f"/os/metrics/sessions?{_last(1)}&timeout_seconds=0.5").json()
                assert body["skipped_db_ids"] == {"db-2": "timeout"}
                assert finished == []
                time.sleep(1.5)

        assert finished == [True]

    def test_every_database_is_read_for_the_caller(self):
        dbs = [_db("db-1", _today_row()), _db("db-2", _today_row())]
        with _scope("alice"):
            _dbs_client(*dbs).get(f"/os/metrics/sessions?{_last(1)}&user_id=bob")

        assert [db.get_os_metrics.call_args.kwargs["user_id"] for db in dbs] == ["alice", "alice"]

    def test_more_databases_than_are_read_at_once(self):
        dbs = [_db(f"db-{index}", _today_row()) for index in range(10)]
        with _scope(None):
            body = _dbs_client(*dbs).get(f"/os/metrics/sessions?{_last(1)}").json()

        assert body["total_sessions"] == 30
        assert len(body["db_ids"]) == 10


KEPT_ROUTES = ("sessions", "tokens", "runs", "latency", "models")


def _state(seconds_old=3600, state_hash="hash-1"):
    """What get_os_metrics_state reports: when a row was last written, ``seconds_old`` seconds ago, and the hash."""
    return int(time.time()) - seconds_old, state_hash


def _kept_db(db_id, *rows):
    """A database that answers both reads from the given rows, with a state old enough to keep an answer by."""
    db = _db(db_id, *rows)
    db.get_os_metrics_state = MagicMock(return_value=_state())
    return db


@pytest.fixture
def kept_db(mock_db):
    """The mock database, with a state old enough to keep an answer by."""
    mock_db.get_os_metrics_state = MagicMock(return_value=_state())
    return mock_db


def _reads(db):
    return db.get_os_metrics.call_count + db.get_os_metrics_totals.call_count


def _clock(now):
    """Patch the time the routes read."""

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    return patch("agno.os.routers.metrics.metrics.datetime", Clock)


def _sessions_by_owner(sessions_counts):
    """Answer each get_os_metrics read with today's sessions of the owner it asks for."""

    def read(**kwargs):
        return [_row(_day(0), sessions_count=sessions_counts[kwargs["user_id"]])], UPDATED_AT

    return read


class TestETag:
    @pytest.mark.parametrize("route", KEPT_ROUTES)
    def test_answer_carries_an_etag_and_a_caller_that_holds_it_gets_a_304(self, client, route):
        """The 304 has no body and names the same ETag."""
        with _scope(None):
            first = client.get(f"/os/metrics/{route}?{_last(2)}")
            second = client.get(f"/os/metrics/{route}?{_last(2)}", headers={"If-None-Match": first.headers["etag"]})

        assert first.status_code == 200
        assert first.headers["etag"].startswith('"') and first.headers["etag"].endswith('"')
        assert second.status_code == 304
        assert second.content == b""
        assert second.headers["etag"] == first.headers["etag"]

    def test_caller_that_holds_another_etag_gets_the_answer(self, client):
        with _scope(None):
            first = client.get(f"/os/metrics/sessions?{_last(2)}")
            second = client.get(f"/os/metrics/sessions?{_last(2)}", headers={"If-None-Match": '"another"'})

        assert second.status_code == 200
        assert second.json() == first.json()
        assert second.headers["etag"] == first.headers["etag"]

    def test_if_none_match_is_read_as_a_list_of_etags(self, client):
        """A weak ETag in a list and * are a match, an ETag inside other text is not."""
        with _scope(None):
            etag = client.get(f"/os/metrics/sessions?{_last(2)}").headers["etag"]
            statuses = [
                client.get(f"/os/metrics/sessions?{_last(2)}", headers={"If-None-Match": held}).status_code
                for held in (f'"another", W/{etag}', "*", f"xx{etag}yy")
            ]

        assert statuses == [304, 304, 200]

    def test_etag_of_one_caller_is_not_the_etag_of_another_callers_numbers(self):
        """alice's ETag does not get bob a 304: his answer has his own numbers and ETag."""
        db = _kept_db("db-1")
        db.get_os_metrics.side_effect = _sessions_by_owner({"alice": 2, "bob": 5})
        client = _client(db)
        with _scope("alice"):
            etag = client.get(f"/os/metrics/sessions?{_last(1)}").headers["etag"]
        with _scope("bob"):
            response = client.get(f"/os/metrics/sessions?{_last(1)}", headers={"If-None-Match": etag})

        assert response.status_code == 200
        assert response.json()["total_sessions"] == 5
        assert response.headers["etag"] != etag


class TestKeptAnswers:
    @pytest.fixture
    def owners_db(self):
        """Today's sessions: 9 of every owner, 2 of alice, 5 of bob, 1 without an owner."""
        db = _kept_db("db-1")
        db.get_os_metrics.side_effect = _sessions_by_owner({None: 9, "alice": 2, "bob": 5, "": 1})
        return db

    @pytest.mark.parametrize("route", KEPT_ROUTES)
    def test_same_request_with_the_same_state_is_not_read_again(self, client, kept_db, route):
        """The state is asked for before and after the rows are read, the rows are read on the first request only."""
        with _scope(None):
            first = client.get(f"/os/metrics/{route}?{_last(2)}")
            second = client.get(f"/os/metrics/{route}?{_last(2)}")

        assert _reads(kept_db) == 1
        assert kept_db.get_os_metrics_state.call_count == 3
        assert second.status_code == 200
        assert second.json() == first.json()

    @pytest.mark.parametrize("state", [_state(seconds_old=1800), _state(seconds_old=3600, state_hash="hash-2")])
    def test_changed_state_is_read_again_with_the_new_numbers(self, client, kept_db, state):
        """A newer updated_at, or another hash, is another state."""
        with _scope(None):
            first = client.get(f"/os/metrics/sessions?{_last(2)}").json()
            kept_db.get_os_metrics.side_effect = _totals({**_today_row(), "sessions_count": 7}, _yesterday_row())
            kept = client.get(f"/os/metrics/sessions?{_last(2)}").json()
            kept_db.get_os_metrics_state.return_value = state
            second = client.get(f"/os/metrics/sessions?{_last(2)}").json()

        assert kept_db.get_os_metrics.call_count == 2
        assert first["total_sessions"] == 4
        assert kept["total_sessions"] == 4
        assert second["total_sessions"] == 8

    def test_database_without_a_state_is_read_every_time(self, client, kept_db):
        """No state is what a database reports again once its state is lost, so no answer is kept under it."""
        kept_db.get_os_metrics_state.return_value = (None, "")
        with _scope(None):
            first = client.get(f"/os/metrics/sessions?{_last(2)}")
            second = client.get(f"/os/metrics/sessions?{_last(2)}")

        assert kept_db.get_os_metrics.call_count == 2
        assert first.json()["total_sessions"] == second.json()["total_sessions"] == 4

    def test_state_is_asked_for_the_last_day_of_the_window(self, client, kept_db):
        """A database answers a window of completed days with the state of its completed days."""
        with _scope(None):
            client.get(f"/os/metrics/sessions?starting_date={_day(9).isoformat()}&ending_date={_day(4).isoformat()}")

        kept_db.get_os_metrics_state.assert_called_with(_day(4))

    def test_states_are_read_in_the_batches_of_the_rows(self):
        """The state read is the one that starts a rebuild, so no more run at once than rows reads do."""
        reading = []
        most_at_once = []

        def read_state(db_id):
            def read(ending_date):
                reading.append(db_id)
                most_at_once.append(len(reading))
                time.sleep(0.05)
                reading.remove(db_id)
                return _state()

            return read

        dbs = [_kept_db(f"db-{index}", _today_row()) for index in range(20)]
        for db in dbs:
            db.get_os_metrics_state.side_effect = read_state(db.id)
        with _scope(None):
            body = _dbs_client(*dbs).get(f"/os/metrics/sessions?{_last(1)}").json()

        assert len(body["db_ids"]) == 20
        assert max(most_at_once) <= 8

    def test_answer_read_while_the_state_changed_is_not_kept(self, client, kept_db):
        """A rebuild landing between the state read and the rows read would be kept under the older state."""
        older, newer = _state(seconds_old=3600), _state(seconds_old=1800)
        read = kept_db.get_os_metrics.side_effect

        def read_while_a_rebuild_lands(**kwargs):
            kept_db.get_os_metrics_state.return_value = newer
            return read(**kwargs)

        kept_db.get_os_metrics.side_effect = read_while_a_rebuild_lands
        with _scope(None):
            client.get(f"/os/metrics/sessions?{_last(2)}")
            # The state reads as the older one again
            kept_db.get_os_metrics_state.return_value = older
            client.get(f"/os/metrics/sessions?{_last(2)}")

        assert kept_db.get_os_metrics.call_count == 2

    def test_answer_for_a_window_longer_than_a_year_is_not_kept(self, client, kept_db):
        with _scope(None):
            first = client.get(f"/os/metrics/sessions?{_last(400)}")
            second = client.get(f"/os/metrics/sessions?{_last(400)}")

        assert kept_db.get_os_metrics.call_count == 2
        assert second.json() == first.json()

    def test_state_read_and_rows_read_share_the_time_of_a_request(self):
        slow = _kept_db("db-2", _today_row())
        slow.get_os_metrics_state.side_effect = lambda ending_date: time.sleep(2.5) or _state()
        slow.get_os_metrics.side_effect = lambda **kwargs: time.sleep(2.5) or ([], None)
        client = _dbs_client(_kept_db("db-1", _today_row()), slow)
        with _scope(None):
            started_at = time.time()
            body = client.get(f"/os/metrics/sessions?{_last(1)}&timeout_seconds=1").json()
            elapsed = time.time() - started_at

        assert body["total_sessions"] == 3
        assert body["skipped_db_ids"] == {"db-2": "timeout"}
        assert elapsed < 1.7

    def _total_sessions(self, client, query=""):
        return client.get(f"/os/metrics/sessions?{_last(1)}{query}").json()["total_sessions"]

    def test_scoped_caller_is_not_given_the_answer_kept_for_another_user(self, owners_db):
        client = _client(owners_db)
        with _scope("alice"):
            alice = self._total_sessions(client)
        with _scope("bob"):
            bob = self._total_sessions(client)
            bob_asking_for_alice = self._total_sessions(client, "&user_id=alice")

        assert (alice, bob, bob_asking_for_alice) == (2, 5, 5)
        assert [call.kwargs["user_id"] for call in owners_db.get_os_metrics.call_args_list] == ["alice", "bob"]


class TestWindow:
    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_start_after_the_end_is_refused(self, client, mock_db, route):
        with _scope(None):
            response = client.get(
                f"/os/metrics/{route}?starting_date={_day(0).isoformat()}&ending_date={_day(1).isoformat()}"
            )

        assert response.status_code == 422
        mock_db.get_os_metrics.assert_not_called()

    def test_window_may_cover_more_than_a_year(self, client):
        with _scope(None):
            response = client.get(f"/os/metrics/sessions?{_last(730)}")

        assert response.status_code == 200
        assert len(response.json()["metrics"]) == 730

    def test_single_day_is_a_window(self, client, mock_db):
        today = _day(0)
        with _scope(None):
            body = client.get(
                f"/os/metrics/sessions?starting_date={today.isoformat()}&ending_date={today.isoformat()}"
            ).json()

        assert body["metrics"] == [{"date": _iso(today), "sessions_count": 3}]
        # The previous window is the one day before
        assert _read_kwargs(mock_db)["starting_date"] == _day(1)
        assert body["previous_total_sessions"] == 1

    def test_malformed_date_is_a_422(self, client):
        with _scope(None):
            response = client.get("/os/metrics/sessions?starting_date=yesterday")

        assert response.status_code == 422
