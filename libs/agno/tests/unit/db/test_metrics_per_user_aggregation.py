"""Unit tests for per-user metrics aggregation.

Locks in the contract that ``calculate_date_metrics`` buckets sessions by
``user_id`` and emits one metrics record per distinct user. Sessions without
a user_id aggregate into the sentinel empty-string bucket — the legacy
single-tenant deployment surface.
"""

from datetime import date

import pytest

from agno.db.sqlite.utils import calculate_date_metrics


def _agent_session(user_id, runs_count=1, input_tokens=10):
    """Build a fake agent session row as the DB layer would emit it."""
    runs = [{"model": "gpt-4", "model_provider": "OpenAI"} for _ in range(runs_count)]
    return {
        "user_id": user_id,
        "runs": runs,
        "session_data": {
            "session_metrics": {"input_tokens": input_tokens, "total_tokens": input_tokens},
        },
    }


class TestPerUserBucketing:
    """Each distinct user_id gets its own metrics row."""

    def test_two_users_produce_two_buckets(self):
        sessions_data = {
            "agent": [_agent_session("alice"), _agent_session("bob")],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        assert len(records) == 2
        users_seen = {r["user_id"] for r in records}
        assert users_seen == {"alice", "bob"}

    def test_same_user_multiple_sessions_aggregate(self):
        sessions_data = {
            "agent": [
                _agent_session("alice", runs_count=1, input_tokens=10),
                _agent_session("alice", runs_count=2, input_tokens=20),
            ],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        assert len(records) == 1
        assert records[0]["user_id"] == "alice"
        assert records[0]["agent_sessions_count"] == 2
        assert records[0]["agent_runs_count"] == 3
        assert records[0]["token_metrics"]["input_tokens"] == 30


class TestEmptyStringSentinelBucket:
    """Sessions without a user_id roll up under user_id=''. This is the
    legacy / RBAC-off surface — looks identical to global metrics."""

    def test_unowned_session_goes_to_empty_string_bucket(self):
        sessions_data = {
            "agent": [_agent_session(None), _agent_session(None)],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        assert len(records) == 1
        assert records[0]["user_id"] == ""
        assert records[0]["agent_sessions_count"] == 2

    def test_unowned_bucket_reports_users_count_zero(self):
        """The unowned bucket doesn't contribute to distinct-user accounting."""
        sessions_data = {
            "agent": [_agent_session(None), _agent_session(None)],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        assert records[0]["users_count"] == 0

    def test_per_user_bucket_reports_users_count_one(self):
        """Each per-user bucket represents exactly one user."""
        sessions_data = {
            "agent": [_agent_session("alice"), _agent_session("alice")],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        assert records[0]["users_count"] == 1


class TestMixedOwnership:
    """A realistic mix: some sessions have owners, some don't."""

    def test_mixed_yields_owned_buckets_plus_unowned_bucket(self):
        sessions_data = {
            "agent": [
                _agent_session("alice"),
                _agent_session("bob"),
                _agent_session(None),  # legacy / system
            ],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        assert len(records) == 3
        by_user = {r["user_id"]: r for r in records}
        assert by_user["alice"]["agent_sessions_count"] == 1
        assert by_user["bob"]["agent_sessions_count"] == 1
        assert by_user[""]["agent_sessions_count"] == 1

    def test_token_metrics_isolated_per_bucket(self):
        """One user's high-token session must not bleed into another's bucket."""
        sessions_data = {
            "agent": [
                _agent_session("alice", input_tokens=1000),
                _agent_session("bob", input_tokens=50),
            ],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)

        by_user = {r["user_id"]: r for r in records}
        assert by_user["alice"]["token_metrics"]["input_tokens"] == 1000
        assert by_user["bob"]["token_metrics"]["input_tokens"] == 50


class TestEmptySessionsData:
    def test_no_sessions_returns_empty_list(self):
        records = calculate_date_metrics(
            date(2026, 1, 1), {"agent": [], "team": [], "workflow": []}, user_isolation=True
        )
        assert records == []


class TestRecordShape:
    """Verify every record has the fields the upsert + downstream readers expect."""

    @pytest.fixture
    def single_user_record(self):
        sessions_data = {
            "agent": [_agent_session("alice", runs_count=3, input_tokens=100)],
            "team": [],
            "workflow": [],
        }
        records = calculate_date_metrics(date(2026, 1, 1), sessions_data, user_isolation=True)
        return records[0]

    def test_has_id(self, single_user_record):
        assert "id" in single_user_record
        assert isinstance(single_user_record["id"], str)

    def test_has_aggregation_period(self, single_user_record):
        assert single_user_record["aggregation_period"] == "daily"

    def test_has_date(self, single_user_record):
        assert single_user_record["date"] == date(2026, 1, 1)

    def test_has_user_id(self, single_user_record):
        assert single_user_record["user_id"] == "alice"

    def test_has_completed_flag(self, single_user_record):
        # 2026-01-01 is in the past relative to today (2026-06-04 per session ctx)
        assert single_user_record["completed"] is True

    def test_has_model_metrics(self, single_user_record):
        assert single_user_record["model_metrics"] == [{"model_id": "gpt-4", "model_provider": "OpenAI", "count": 3}]
