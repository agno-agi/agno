"""Regression tests for v3 down-migration (revert) atomicity.

The revert rebuilds the legacy ``runs`` blob on each session, then deletes the
runs store. The original DynamoDB and SurrealDB reverts truncated the runs store
*unconditionally* -- even for sessions whose blob rebuild failed. A throttled
rebuild followed by the delete lost that session's runs entirely.

Fix: track sessions whose rebuild failed and preserve their runs (skip the
delete for them) so a partial revert never loses data and can be re-run.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

try:
    from agno.db.migrations.versions.v3_0_0 import _revert_dynamodb
except ImportError:
    _revert_dynamodb = None  # type: ignore[assignment]


pytestmark = pytest.mark.skipif(_revert_dynamodb is None, reason="sqlalchemy not installed")


def _run_item(run_id: str, session_id: str) -> dict:
    return {
        "run_id": {"S": run_id},
        "session_id": {"S": session_id},
        "run_index": {"N": "0"},
        "created_at": {"N": "0"},
        "run_data": {"S": json.dumps({"run_id": run_id})},
    }


class TestRevertDynamoPreservesRunsOnFailure:
    def _make_db(self, client: MagicMock) -> MagicMock:
        db = MagicMock()
        db.client = client
        db.runs_table_name = "agno_runs"
        return db

    def test_failed_session_rebuild_preserves_its_runs(self):
        client = MagicMock()
        client.scan.return_value = {"Items": [_run_item("r1", "s1"), _run_item("r2", "s2")]}

        # Rebuild succeeds for s1, throttles for s2.
        def update_item(**kwargs):
            if kwargs["Key"]["session_id"]["S"] == "s2":
                raise Exception("ProvisionedThroughputExceededException")
            return {}

        client.update_item.side_effect = update_item
        db = self._make_db(client)

        assert _revert_dynamodb(db, "sessions", "agno_sessions") is True

        deleted = {c.kwargs["Key"]["run_id"]["S"] for c in client.delete_item.call_args_list}
        assert "r1" in deleted, "successfully-reverted session's runs should be deleted"
        assert "r2" not in deleted, "failed session's runs must be preserved, not deleted"

    def test_all_success_deletes_everything(self):
        client = MagicMock()
        client.scan.return_value = {"Items": [_run_item("r1", "s1"), _run_item("r2", "s2")]}
        client.update_item.return_value = {}
        db = self._make_db(client)

        assert _revert_dynamodb(db, "sessions", "agno_sessions") is True

        deleted = {c.kwargs["Key"]["run_id"]["S"] for c in client.delete_item.call_args_list}
        assert deleted == {"r1", "r2"}
