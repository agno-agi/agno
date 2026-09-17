"""Tests for the insights REST API router."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.routers.insights.insights import get_insights_router
from agno.os.settings import AgnoAPISettings

# =============================================================================
# Fixtures
# =============================================================================


def _make_metric(user_id, *, date="2026-01-01", runs=2, models=None, period="daily"):
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
        "token_metrics": {"input_tokens": 10, "total_tokens": 10},
        "model_metrics": models
        if models is not None
        else [{"model_id": "gpt-5-mini", "model_provider": "OpenAI", "count": runs}],
        "created_at": now,
        "updated_at": now,
    }


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


@pytest.fixture
def settings():
    return AgnoAPISettings()


@pytest.fixture
def mock_db():
    """Today's metrics for two owners."""
    rows = [_make_metric("alice", date=_today(), runs=2), _make_metric("bob", date=_today(), runs=4)]
    db = MagicMock()
    db.id = "db-1"
    db.get_metrics = MagicMock(return_value=(rows, int(time.time())))
    return db


@pytest.fixture
def client(mock_db, settings):
    app = FastAPI()
    with patch("agno.os.routers.insights.insights.get_authentication_dependency", return_value=lambda: True):
        app.include_router(get_insights_router(dbs={"db-1": [mock_db]}, settings=settings))
    return TestClient(app)


def _scope(user_id):
    """Patch who is calling, at the helper the router resolves the scope through."""
    return patch("agno.os.middleware.user_scope.get_scoped_user_id", return_value=user_id)


# =============================================================================
# GET /insights/metrics -- model usage
# =============================================================================


class TestModelUsage:
    def test_unscoped_read_adds_every_owners_model_runs(self, client):
        with _scope(None):
            usage = client.get("/insights/metrics").json()

        assert usage["total_runs"] == 6
        assert usage["models"] == [
            {"model_id": "gpt-5-mini", "model_provider": "OpenAI", "run_count": 6, "run_share": 100.0}
        ]

    def test_models_are_ordered_most_run_first_with_their_share(self, client, mock_db):
        models = [
            {"model_id": "claude-haiku-4-5", "model_provider": "Anthropic", "count": 1},
            {"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 3},
        ]
        mock_db.get_metrics.return_value = ([_make_metric("alice", date=_today(), runs=4, models=models)], 0)
        with _scope(None):
            usage = client.get("/insights/metrics").json()

        assert [(entry["model_id"], entry["run_share"]) for entry in usage["models"]] == [
            ("gpt-5.5", 75.0),
            ("claude-haiku-4-5", 25.0),
        ]

    def test_no_metrics_leaves_usage_empty(self, client, mock_db):
        mock_db.get_metrics.return_value = ([], None)
        with _scope(None):
            usage = client.get("/insights/metrics").json()

        assert usage["total_runs"] == 0
        assert usage["models"] == []

    def test_window_ends_today_and_spans_the_requested_days(self, client, mock_db):
        from datetime import datetime, timedelta, timezone

        with _scope(None):
            client.get("/insights/metrics?days=5")

        today = datetime.now(timezone.utc).date()
        assert mock_db.get_metrics.call_args.kwargs["ending_date"] == today
        assert mock_db.get_metrics.call_args.kwargs["starting_date"] == today - timedelta(days=4)

    def test_only_the_daily_metrics_are_read(self, client, mock_db):
        with _scope(None):
            client.get("/insights/metrics")

        mock_db.get_metrics.assert_called_once()
        mock_db.get_runs.assert_not_called()


# =============================================================================
# GET /insights/metrics -- scoping and caching
# =============================================================================


class TestScopingAndCaching:
    def test_scoped_caller_reads_only_its_own_rows(self, client, mock_db):
        mock_db.get_metrics.return_value = ([_make_metric("alice", date=_today(), runs=2)], 0)
        with _scope("alice"):
            usage = client.get("/insights/metrics?days=1").json()

        assert mock_db.get_metrics.call_args.kwargs["user_id"] == "alice"
        assert usage["total_runs"] == 2

    def test_unowned_bucket_drops_the_record_that_holds_every_users_traffic(self, client, mock_db):
        """Same rule GET /metrics applies to the empty-string owner."""
        unowned = _make_metric("", date=_today(), runs=1)
        legacy = _make_metric("", date=_today(), runs=5)
        legacy["users_count"] = 2
        mock_db.get_metrics.return_value = ([unowned, legacy], 0)
        with _scope(""):
            usage = client.get("/insights/metrics?days=1").json()

        assert usage["total_runs"] == 1

    def test_second_call_is_served_from_cache(self, client, mock_db):
        with _scope(None):
            first = client.get("/insights/metrics").json()
            second = client.get("/insights/metrics").json()

        assert first["computed_at"] == second["computed_at"]
        assert mock_db.get_metrics.call_count == 1

    def test_refresh_recomputes(self, client, mock_db):
        with _scope(None):
            client.get("/insights/metrics")
            client.get("/insights/metrics?refresh=true")

        assert mock_db.get_metrics.call_count == 2

    def test_each_window_is_cached_separately(self, client, mock_db):
        with _scope(None):
            client.get("/insights/metrics?days=7")
            client.get("/insights/metrics?days=30")

        assert mock_db.get_metrics.call_count == 2

    def test_one_owner_cannot_be_served_anothers_cached_insights(self, client, mock_db):
        with _scope("alice"):
            client.get("/insights/metrics")
        with _scope("bob"):
            client.get("/insights/metrics")

        assert mock_db.get_metrics.call_count == 2

    def test_stale_entry_is_served_immediately_and_recomputed_in_the_background(self, client, mock_db):
        """Opening the page never waits on a recompute once one has completed."""
        from agno.os.routers.insights import insights as insights_module

        with _scope(None):
            first = client.get("/insights/metrics").json()
            real_monotonic = time.monotonic
            with patch.object(
                insights_module.time,
                "monotonic",
                lambda: real_monotonic() + insights_module.CACHE_TTL_SECONDS + 1,
            ):
                stale = client.get("/insights/metrics").json()
            refreshed = client.get("/insights/metrics").json()

        assert stale["computed_at"] == first["computed_at"]
        assert mock_db.get_metrics.call_count == 2
        assert refreshed["computed_at"] != first["computed_at"]

    def test_failed_background_recompute_keeps_serving_the_stale_entry(self, client, mock_db):
        from agno.os.routers.insights import insights as insights_module

        with _scope(None):
            first = client.get("/insights/metrics").json()
            mock_db.get_metrics.side_effect = RuntimeError("database unavailable")
            real_monotonic = time.monotonic
            with patch.object(
                insights_module.time,
                "monotonic",
                lambda: real_monotonic() + insights_module.CACHE_TTL_SECONDS + 1,
            ):
                stale = client.get("/insights/metrics")
                retried = client.get("/insights/metrics")

        assert stale.status_code == 200
        assert stale.json()["computed_at"] == first["computed_at"]
        assert retried.status_code == 200
        assert mock_db.get_metrics.call_count == 3

    def test_oldest_entry_is_evicted_once_the_cache_is_full(self, client, mock_db):
        """The window and the owner both come from the caller, so the cache has to stay bounded."""
        from agno.os.routers.insights import insights as insights_module

        with _scope(None):
            client.get("/insights/metrics?days=1")
        for index in range(insights_module.CACHE_MAX_ENTRIES + 5):
            with _scope(f"user-{index}"):
                client.get("/insights/metrics?days=1")

        calls_before = mock_db.get_metrics.call_count
        with _scope(None):
            client.get("/insights/metrics?days=1")

        assert mock_db.get_metrics.call_count > calls_before

    def test_entry_well_inside_the_cap_survives(self, client, mock_db):
        with _scope(None):
            client.get("/insights/metrics?days=1")
        for index in range(10):
            with _scope(f"user-{index}"):
                client.get("/insights/metrics?days=1")

        calls_before = mock_db.get_metrics.call_count
        with _scope(None):
            client.get("/insights/metrics?days=1")

        assert mock_db.get_metrics.call_count == calls_before
