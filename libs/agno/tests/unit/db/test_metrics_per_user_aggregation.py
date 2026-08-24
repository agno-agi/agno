"""Unit tests for per-user metrics aggregation.

``calculate_date_metrics`` buckets sessions by ``user_id`` and emits one record per
distinct user. Sessions without a user_id roll up under the empty-string bucket.
"""

from datetime import date

from agno.db.sqlite.utils import calculate_date_metrics

TARGET_DATE = date(2026, 1, 1)


def _agent_session(user_id, runs_count=1, input_tokens=10):
    """Build a fake agent session row as the DB layer would emit it."""
    return {
        "user_id": user_id,
        "runs": [{"model": "gpt-4", "model_provider": "OpenAI"} for _ in range(runs_count)],
        "session_data": {"session_metrics": {"input_tokens": input_tokens, "total_tokens": input_tokens}},
    }


def _by_user(*agent_sessions):
    records = calculate_date_metrics(TARGET_DATE, {"agent": list(agent_sessions), "team": [], "workflow": []})
    return {r["user_id"]: r for r in records}


class TestPerUserBucketing:
    def test_two_users_produce_two_buckets(self):
        assert set(_by_user(_agent_session("alice"), _agent_session("bob"))) == {"alice", "bob"}

    def test_same_user_multiple_sessions_aggregate(self):
        by_user = _by_user(
            _agent_session("alice", runs_count=1, input_tokens=10),
            _agent_session("alice", runs_count=2, input_tokens=20),
        )

        assert set(by_user) == {"alice"}
        assert by_user["alice"]["agent_sessions_count"] == 2
        assert by_user["alice"]["agent_runs_count"] == 3
        assert by_user["alice"]["token_metrics"]["input_tokens"] == 30

    def test_per_user_bucket_reports_users_count_one(self):
        assert _by_user(_agent_session("alice"), _agent_session("alice"))["alice"]["users_count"] == 1


class TestEmptyStringSentinelBucket:
    def test_unowned_sessions_share_the_empty_string_bucket(self):
        by_user = _by_user(_agent_session(None), _agent_session(None))

        assert set(by_user) == {""}
        assert by_user[""]["agent_sessions_count"] == 2
        # The unowned bucket doesn't contribute to distinct-user accounting.
        assert by_user[""]["users_count"] == 0

    def test_an_owner_literally_named_empty_string_lands_in_the_sentinel_bucket(self):
        """Elsewhere ``""`` is a real owner that scopes to itself; metrics fold it into the unowned bucket."""
        by_user = _by_user(_agent_session(""), _agent_session(None))

        assert set(by_user) == {""}
        assert by_user[""]["agent_sessions_count"] == 2
        assert by_user[""]["users_count"] == 0


class TestMixedOwnership:
    def test_mixed_yields_owned_buckets_plus_unowned_bucket(self):
        by_user = _by_user(_agent_session("alice"), _agent_session("bob"), _agent_session(None))

        assert set(by_user) == {"alice", "bob", ""}
        assert all(by_user[u]["agent_sessions_count"] == 1 for u in by_user)

    def test_token_metrics_isolated_per_bucket(self):
        """One user's high-token session must not bleed into another's bucket."""
        by_user = _by_user(_agent_session("alice", input_tokens=1000), _agent_session("bob", input_tokens=50))

        assert by_user["alice"]["token_metrics"]["input_tokens"] == 1000
        assert by_user["bob"]["token_metrics"]["input_tokens"] == 50

    def test_no_sessions_returns_empty_list(self):
        assert calculate_date_metrics(TARGET_DATE, {"agent": [], "team": [], "workflow": []}) == []


class TestRecordShape:
    def test_record_carries_the_fields_the_upsert_expects(self):
        record = _by_user(_agent_session("alice", runs_count=3, input_tokens=100))["alice"]

        assert isinstance(record["id"], str)
        assert record["aggregation_period"] == "daily"
        assert record["date"] == TARGET_DATE
        assert record["user_id"] == "alice"
        assert record["completed"] is True  # the target date is in the past
        assert record["model_metrics"] == [{"model_id": "gpt-4", "model_provider": "OpenAI", "count": 3}]
