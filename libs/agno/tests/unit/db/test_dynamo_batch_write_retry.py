"""Regression tests for reviewer comment #10 on PR #8350.

DynamoDB's ``batch_write_item`` returns partial success: some items may end
up in ``UnprocessedItems`` due to throttling or provisioned-throughput
exceeded. The old code ignored that response and silently dropped those
items — a data-loss bug.

The new ``batch_write_with_retry`` helper retries the unprocessed subset
with exponential backoff and raises if items still can't be written after
``max_retries``. These tests exercise it against a fake client so we don't
need a real DynamoDB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from agno.db.dynamo.utils import batch_write_with_retry
except ImportError:
    batch_write_with_retry = None  # type: ignore[assignment]


pytestmark = pytest.mark.skipif(batch_write_with_retry is None, reason="boto3 not installed")


class TestBatchWriteWithRetry:
    def test_no_unprocessed_returns_after_one_call(self):
        client = MagicMock()
        client.batch_write_item.return_value = {}  # no UnprocessedItems key

        batch_write_with_retry(client, {"table_x": [{"PutRequest": {"Item": {"a": 1}}}]}, max_retries=3)
        assert client.batch_write_item.call_count == 1

    def test_empty_unprocessed_items_is_success(self):
        client = MagicMock()
        client.batch_write_item.return_value = {"UnprocessedItems": {}}

        batch_write_with_retry(client, {"table_x": [{"PutRequest": {"Item": {"a": 1}}}]})
        assert client.batch_write_item.call_count == 1

    def test_retry_sends_only_unprocessed_subset(self):
        """The second call should carry ONLY the items DynamoDB flagged as
        unprocessed — not the whole original batch."""
        client = MagicMock()
        unprocessed_items = {"table_x": [{"PutRequest": {"Item": {"a": 2}}}]}
        client.batch_write_item.side_effect = [
            {"UnprocessedItems": unprocessed_items},  # first call: some unprocessed
            {"UnprocessedItems": {}},  # retry: success
        ]

        with patch("agno.db.dynamo.utils.time.sleep"):  # skip real backoff sleeps
            batch_write_with_retry(
                client,
                {"table_x": [{"PutRequest": {"Item": {"a": 1}}}, {"PutRequest": {"Item": {"a": 2}}}]},
                max_retries=3,
                initial_backoff_seconds=0,
            )

        assert client.batch_write_item.call_count == 2
        # Second call must be the unprocessed subset only
        second_call_args = client.batch_write_item.call_args_list[1][1]
        assert second_call_args["RequestItems"] == unprocessed_items

    def test_raises_when_unprocessed_persists_past_max_retries(self):
        """Every retry still returns UnprocessedItems → helper must raise
        rather than silently return."""
        client = MagicMock()
        client.batch_write_item.return_value = {"UnprocessedItems": {"table_x": [{"PutRequest": {"Item": {"a": 1}}}]}}

        with patch("agno.db.dynamo.utils.time.sleep"):
            with pytest.raises(RuntimeError, match="UnprocessedItems"):
                batch_write_with_retry(
                    client,
                    {"table_x": [{"PutRequest": {"Item": {"a": 1}}}]},
                    max_retries=2,
                    initial_backoff_seconds=0,
                )

        # Should have tried the full budget: initial + 2 retries = 3 calls
        assert client.batch_write_item.call_count == 3

    def test_exponential_backoff_applied(self):
        """First retry uses ``initial_backoff_seconds``; subsequent retries
        double up to a 5s cap."""
        client = MagicMock()
        # Always returns unprocessed
        client.batch_write_item.return_value = {"UnprocessedItems": {"t": [{"PutRequest": {"Item": {"a": 1}}}]}}

        with patch("agno.db.dynamo.utils.time.sleep") as sleep_mock:
            with pytest.raises(RuntimeError):
                batch_write_with_retry(
                    client,
                    {"t": [{"PutRequest": {"Item": {"a": 1}}}]},
                    max_retries=3,
                    initial_backoff_seconds=0.1,
                )

        # 3 retries → 3 sleeps at 0.1, 0.2, 0.4
        sleep_calls = [call.args[0] for call in sleep_mock.call_args_list]
        assert sleep_calls == [0.1, 0.2, 0.4]
