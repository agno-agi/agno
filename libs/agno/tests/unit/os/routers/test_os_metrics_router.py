"""Tests for the GET /os/metrics/* routes and POST /os/metrics/refresh on the metrics router."""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.utils import resolve_os_metrics_fields
from agno.os.routers.metrics.metrics import MAX_WINDOW_DAYS, get_metrics_router
from agno.os.settings import AgnoAPISettings

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
    db.calculate_os_metrics = MagicMock(return_value=None)
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

        kwargs = _read_kwargs(mock_db)
        assert kwargs["fields"] == ["model_metrics"]
        assert kwargs["starting_date"] == _day(1)
        assert [(model["model_id"], model["model_provider"], model["run_count"]) for model in body["models"]] == [
            ("gpt-5.5", "OpenAI", 4),
            ("claude-opus-5", "Anthropic", 1),
        ]
        assert [model["run_share"] for model in body["models"]] == [80.0, 20.0]
        assert body["total_model_runs"] == 5
        assert body["window_days"] == 2
        assert set(body["models"][0]) == {"model_id", "model_provider", "run_count", "run_share"}
        assert body["updated_at"] == UPDATED_AT_ISO

    def test_window_without_runs_lists_no_models(self, client, mock_db):
        mock_db.get_os_metrics.side_effect = _totals()
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

        assert body == {"updated_at": UPDATED_AT_ISO}
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
        assert body == {"updated_at": UPDATED_AT_ISO}


# =============================================================================
# Availability and window bounds, shared by every route
# =============================================================================

READ_ROUTES = ("sessions", "tokens", "runs", "latency", "models", "refresh/status")


class TestAvailability:
    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_database_without_os_metrics_is_a_501(self, client, mock_db, route):
        mock_db.get_os_metrics.side_effect = NotImplementedError
        with _scope(None):
            response = client.get(f"/os/metrics/{route}?{_last(1)}")

        assert response.status_code == 501
        assert response.json()["detail"] == "OS metrics not supported by the configured database"

    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_os_without_a_database_is_a_503(self, route):
        with _scope(None):
            response = _client().get(f"/os/metrics/{route}?{_last(1)}")

        assert response.status_code == 503

    def test_os_without_a_database_cannot_refresh(self):
        with _scope(None):
            assert _client().post("/os/metrics/refresh").status_code == 503

    def test_database_failure_is_a_500(self, client, mock_db):
        mock_db.get_os_metrics.side_effect = RuntimeError("boom")
        with _scope(None):
            response = client.get(f"/os/metrics/sessions?{_last(1)}")

        assert response.status_code == 500

    def test_async_database_is_awaited_for_a_read(self):
        db = MagicMock(spec=AsyncBaseDb)
        db.id = "db-async"
        db.get_os_metrics = AsyncMock(side_effect=_totals(_today_row()))
        with _scope(None):
            body = _client(db).get(f"/os/metrics/sessions?{_last(1)}").json()

        db.get_os_metrics.assert_awaited_once()
        assert body["total_sessions"] == 3


class TestWindow:
    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_start_after_the_end_is_refused(self, client, mock_db, route):
        with _scope(None):
            response = client.get(
                f"/os/metrics/{route}?starting_date={_day(0).isoformat()}&ending_date={_day(1).isoformat()}"
            )

        assert response.status_code == 400
        mock_db.get_os_metrics.assert_not_called()

    def test_window_may_cover_the_maximum_number_of_days(self, client):
        with _scope(None):
            response = client.get(f"/os/metrics/sessions?{_last(MAX_WINDOW_DAYS)}")

        assert response.status_code == 200
        assert len(response.json()["metrics"]) == MAX_WINDOW_DAYS

    @pytest.mark.parametrize("route", READ_ROUTES)
    def test_window_of_one_day_more_is_refused(self, client, mock_db, route):
        with _scope(None):
            response = client.get(f"/os/metrics/{route}?{_last(MAX_WINDOW_DAYS + 1)}")

        assert response.status_code == 400
        assert str(MAX_WINDOW_DAYS) in response.json()["detail"]
        mock_db.get_os_metrics.assert_not_called()

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
