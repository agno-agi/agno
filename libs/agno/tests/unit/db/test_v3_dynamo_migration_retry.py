"""Regression tests for the v3 DynamoDB migration's per-run write.

The migration copies each legacy run into the runs table with a conditional
``put_item``. The original code wrapped that put in ``except Exception: log``,
so a throttled/transient failure silently skipped the run. The migration still
returned success, and because the legacy ``runs`` blob is lazily nulled on the
next session write, the skipped run was permanently lost.

Fix: ``_dynamo_put_run_with_retry`` retries transient throttling with backoff
and propagates any other error (or throttling that outlives the retry budget),
so a partial migration aborts loudly. The conditional write keeps it idempotent
and safe to re-run.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from agno.db.migrations.versions.v3_0_0 import _dynamo_put_run_with_retry, _migrate_dynamodb
except ImportError:
    _dynamo_put_run_with_retry = None  # type: ignore[assignment]
    _migrate_dynamodb = None  # type: ignore[assignment]


pytestmark = pytest.mark.skipif(_dynamo_put_run_with_retry is None, reason="sqlalchemy/boto3 not installed")


class _CondCheckFailed(Exception):
    """Stand-in for ``client.exceptions.ConditionalCheckFailedException``."""


class _ClientError(Exception):
    """botocore-style error exposing ``.response['Error']['Code']``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def _make_client() -> MagicMock:
    client = MagicMock()
    client.exceptions.ConditionalCheckFailedException = _CondCheckFailed
    return client


_ITEM = {"run_id": {"S": "r1"}}


class TestDynamoPutRunWithRetry:
    def test_returns_true_on_write(self):
        client = _make_client()
        assert _dynamo_put_run_with_retry(client, "runs", _ITEM) is True
        assert client.put_item.call_count == 1

    def test_returns_false_when_run_already_exists(self):
        """A conditional-check failure means the run was already migrated -- skip
        it (idempotent), don't count it, don't raise."""
        client = _make_client()
        client.put_item.side_effect = _CondCheckFailed()

        assert _dynamo_put_run_with_retry(client, "runs", _ITEM) is False

    def test_retries_throttling_then_succeeds(self):
        client = _make_client()
        client.put_item.side_effect = [
            _ClientError("ProvisionedThroughputExceededException"),
            _ClientError("ThrottlingException"),
            None,  # third attempt succeeds
        ]

        with patch("agno.db.migrations.versions.v3_0_0.time.sleep"):
            assert _dynamo_put_run_with_retry(client, "runs", _ITEM, initial_backoff_seconds=0) is True
        assert client.put_item.call_count == 3

    def test_propagates_non_throttling_error_immediately(self):
        """A real error (e.g. ValidationException) must abort at once -- never
        get swallowed into a silent skip."""
        client = _make_client()
        client.put_item.side_effect = _ClientError("ValidationException")

        with pytest.raises(_ClientError):
            _dynamo_put_run_with_retry(client, "runs", _ITEM, initial_backoff_seconds=0)
        assert client.put_item.call_count == 1

    def test_raises_when_throttling_outlives_retry_budget(self):
        client = _make_client()
        client.put_item.side_effect = _ClientError("ProvisionedThroughputExceededException")

        with patch("agno.db.migrations.versions.v3_0_0.time.sleep"):
            with pytest.raises(_ClientError):
                _dynamo_put_run_with_retry(client, "runs", _ITEM, max_retries=2, initial_backoff_seconds=0)
        # initial attempt + 2 retries
        assert client.put_item.call_count == 3


class TestMigrateDynamodbPropagates:
    def _make_db(self, client: MagicMock) -> MagicMock:
        db = MagicMock()
        db.client = client
        db.runs_table_name = "agno_runs"
        db._get_table = MagicMock()
        return db

    def _session_item_with_one_run(self) -> dict:
        import json

        run = {"run_id": "r1", "agent_id": "a1", "status": "COMPLETED"}
        return {
            "session_id": {"S": "s1"},
            "user_id": {"S": "u1"},
            "runs": {"S": json.dumps([run])},
        }

    def test_persistent_throttling_aborts_migration(self):
        """The whole point: a run that can't be written must NOT be silently
        skipped with the migration reporting success."""
        client = _make_client()
        client.scan.return_value = {"Items": [self._session_item_with_one_run()]}
        client.put_item.side_effect = _ClientError("ProvisionedThroughputExceededException")
        db = self._make_db(client)

        with patch("agno.db.migrations.versions.v3_0_0.time.sleep"):
            with pytest.raises(_ClientError):
                _migrate_dynamodb(db, "sessions", "agno_sessions")

    def test_successful_run_is_migrated(self):
        client = _make_client()
        client.scan.return_value = {"Items": [self._session_item_with_one_run()]}
        db = self._make_db(client)

        assert _migrate_dynamodb(db, "sessions", "agno_sessions") is True
        assert client.put_item.call_count == 1
