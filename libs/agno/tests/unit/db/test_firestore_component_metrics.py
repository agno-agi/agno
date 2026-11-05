"""Unit tests for the component metrics methods of the FirestoreDb class.

These tests use mocks so we don't need a live Firestore.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

try:
    from google.api_core.exceptions import AlreadyExists, FailedPrecondition
    from google.cloud.firestore import Increment

    from agno.db.firestore.firestore import FIRESTORE_BATCH_LIMIT, FirestoreDb
except ImportError:
    FirestoreDb = None  # type: ignore[misc,assignment]

from agno.db.utils import build_aggregate_metrics_rows

pytestmark = pytest.mark.skipif(FirestoreDb is None, reason="google-cloud-firestore not installed")


def _make_db_with_mock_client(monkeypatch) -> FirestoreDb:
    """Instantiate FirestoreDb without touching real Firestore, each transaction applying its writes as given."""
    db = FirestoreDb.__new__(FirestoreDb)
    db.db_client = MagicMock()
    db._metrics_days_not_reopened = set()
    db._metrics_legacy_runs = None
    monkeypatch.setattr("agno.db.firestore.firestore.transactional", lambda function: function)
    return db


def _old_day_timestamp() -> int:
    day = datetime.now(timezone.utc).date() - timedelta(days=5)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _mock_collections(db: FirestoreDb, aggregate_metrics_exists: bool) -> MagicMock:
    """Give db an aggregate metrics collection that holds a document or not, and return it."""
    db.aggregate_metrics_table_name = "agno_aggregate_metrics"
    db.db_client.collection.return_value.limit.return_value.stream.return_value = (
        [MagicMock()] if aggregate_metrics_exists else []
    )
    aggregate_metrics_collection_ref = MagicMock()
    collections = {"aggregate_metrics": aggregate_metrics_collection_ref}
    db._get_collection = MagicMock(side_effect=lambda table_type: collections[table_type])  # type: ignore[method-assign]
    return aggregate_metrics_collection_ref


class TestReopenMetricsDays:
    def test_reopens_a_day_once_a_day_was_calculated(self, monkeypatch):
        """A day is reopened once the aggregate metrics collection holds a row, and left to the first calculation before"""
        db = _make_db_with_mock_client(monkeypatch)
        aggregate_metrics_collection_ref = _mock_collections(db, aggregate_metrics_exists=False)

        db._reopen_metrics_days([_old_day_timestamp()])
        aggregate_metrics_collection_ref.document.return_value.update.assert_not_called()

        aggregate_metrics_collection_ref = _mock_collections(db, aggregate_metrics_exists=True)
        db._reopen_metrics_days([_old_day_timestamp()])
        aggregate_metrics_collection_ref.document.return_value.update.assert_called_once()


class TestMetricsRefresh:
    def _refreshes(self, stored):
        refreshes_collection_ref = MagicMock()
        snapshot = MagicMock(exists=stored is not None)
        snapshot.to_dict.return_value = stored
        refreshes_collection_ref.document.return_value.get.return_value = snapshot
        return refreshes_collection_ref

    def test_claim_takes_over_a_stale_lock(self, monkeypatch):
        """Ensure a claim takes over a stale lock and keeps the last finished_at"""
        db = _make_db_with_mock_client(monkeypatch)
        refreshes_collection_ref = self._refreshes({"locked_by": "another", "locked_at": 0, "finished_at": 5})
        transaction = db.db_client.transaction.return_value

        refresh_row = db._claim_metrics_refresh(refreshes_collection_ref, "worker")

        assert (refresh_row["locked_by"], refresh_row["status"], refresh_row["finished_at"]) == ("worker", "running", 5)
        transaction.set.assert_called_once()

    def test_release_without_a_worker_writes_only_while_no_process_holds_it(self, monkeypatch):
        """Ensure a failure before the claim is written only while no process holds the refresh"""
        db = _make_db_with_mock_client(monkeypatch)

        stored = {"locked_by": "another", "locked_at": 0, "started_at": 1, "finished_at": 5}
        db._release_metrics_refresh(self._refreshes(stored), None, error="boom", started_at=1, finished_at=5)
        db.db_client.transaction.return_value.update.assert_not_called()

        stored = {"locked_by": None, "started_at": 1, "finished_at": 5}
        db._release_metrics_refresh(self._refreshes(stored), None, error="boom", started_at=1, finished_at=5)
        values = db.db_client.transaction.return_value.update.call_args.args[1]
        assert (values["status"], values["error"]) == ("failed", "boom")


class TestMetricsFingerprint:
    def test_unknown_while_the_index_of_the_sum_is_not_built(self, monkeypatch):
        """Ensure the fingerprint is unknown while the index of the sum is not built"""
        db = _make_db_with_mock_client(monkeypatch)
        sessions_collection_ref = MagicMock()
        sessions_collection_ref.where.return_value.count.return_value.sum.return_value.get.side_effect = (
            FailedPrecondition("The query requires an index")
        )

        assert db._get_metrics_fingerprint(sessions_collection_ref, None, date(2026, 1, 1)) is None


class TestWriteAggregateMetricsRows:
    def _write(self, monkeypatch, row_writes, heartbeat=True):
        db = _make_db_with_mock_client(monkeypatch)
        transactions = []

        def new_transaction():
            transaction = MagicMock()
            transactions.append(transaction)
            return transaction

        db.db_client.transaction.side_effect = new_transaction
        db._heartbeat_metrics_refresh = MagicMock(return_value=heartbeat)  # type: ignore[method-assign]
        day = date(2026, 1, 1)
        aggregate_metrics_collection_ref = MagicMock()
        # The stored everyone row of the day, at version 3
        stored_row = {**build_aggregate_metrics_rows([], "daily", day, True)[0], "date": day.isoformat(), "version": 3}
        aggregate_metrics_collection_ref.where.return_value.where.return_value.stream.return_value = [
            MagicMock(to_dict=MagicMock(return_value=stored_row))
        ]
        aggregate_metrics_collection_ref.document.return_value.get.return_value = MagicMock(
            exists=True, to_dict=MagicMock(return_value=stored_row)
        )
        written = db._write_aggregate_metrics_rows(
            aggregate_metrics_collection_ref,
            build_aggregate_metrics_rows([], "daily", day, False),
            rows_changed=True,
            read_version=3,
            refreshes_collection_ref=MagicMock(),
            worker_id="worker",
            row_writes=row_writes,
        )
        return written, transactions

    def test_moves_the_version_first_when_the_rows_take_more_than_one_commit(self, monkeypatch):
        """Ensure the version moves first when the rows take more than one commit, each leaving a write for the
        heartbeat"""
        written, transactions = self._write(
            monkeypatch, [(MagicMock(), {"n": i}) for i in range(FIRESTORE_BATCH_LIMIT)]
        )

        assert written
        assert [len(t.set.call_args_list) + len(t.update.call_args_list) for t in transactions] == [
            FIRESTORE_BATCH_LIMIT - 1,
            2,
            1,
        ]
        first_update = transactions[0].update.call_args_list[0]
        assert isinstance(first_update.args[1]["version"], Increment)

    def test_writes_nothing_once_another_worker_took_the_refresh_over(self, monkeypatch):
        """Ensure nothing is written once another worker took the refresh over"""
        written, transactions = self._write(monkeypatch, [(MagicMock(), {"n": 1})], heartbeat=False)

        assert not written
        assert len(transactions) == 1
        transactions[0].set.assert_not_called()


class TestCalculateMetrics:
    def test_writes_each_day_and_its_aggregate_metrics_rows_last(self, monkeypatch):
        """Each day gets one row per user, then its everyone row; only a day ended a day ago is completed, and
        the refresh is released with the fingerprint."""
        db = _make_db_with_mock_client(monkeypatch)
        today = datetime.now(timezone.utc).date()
        days = [today - timedelta(days=days_ago) for days_ago in [2, 1, 0]]
        sessions_collection_ref = MagicMock()
        sessions_collection_ref.where.return_value.where.return_value.select.return_value.stream.return_value = [
            MagicMock(
                to_dict=MagicMock(
                    return_value={
                        "session_id": f"{user_id}-session",
                        "session_type": "agent",
                        "user_id": user_id,
                        "agent_id": "agent-1",
                    }
                )
            )
            for user_id in ["alice", "bob"]
        ]
        collection_ref = MagicMock()
        aggregate_metrics_collection_ref = MagicMock()
        aggregate_metrics_collection_ref.document.return_value.get.return_value.exists = False
        collections = {
            "component_metrics": collection_ref,
            "aggregate_metrics": aggregate_metrics_collection_ref,
            "metrics_refreshes": MagicMock(),
            "sessions": sessions_collection_ref,
            "runs": None,
        }
        db._get_collection = MagicMock(side_effect=lambda table_type, **kwargs: collections[table_type])  # type: ignore[method-assign]
        db._claim_metrics_refresh = MagicMock(return_value={"finished_at": None, "fingerprint": None})  # type: ignore[method-assign]
        db._get_metrics_dates_to_calculate = MagicMock(return_value=(days, ["fingerprint"]))  # type: ignore[method-assign]
        db._heartbeat_metrics_refresh = MagicMock(return_value=True)  # type: ignore[method-assign]
        db._release_metrics_refresh = MagicMock()  # type: ignore[method-assign]
        db.session_table_name = "test_sessions"
        db.get_latest_schema_version = MagicMock(return_value="3.0.0")  # type: ignore[method-assign]

        assert db.calculate_metrics_dates() == days

        written = db.db_client.transaction.return_value.set.call_args_list
        rows = [call.args[1] for call in written if call.args[0] is collection_ref.document.return_value]
        assert [(row["date"], row["user_id"], row["sessions_count"]) for row in rows] == [
            (day.isoformat(), user_id, 1) for day in days for user_id in ["alice", "bob"]
        ]
        everyone_rows = [
            call.args[1]
            for call in written
            if call.args[0] is aggregate_metrics_collection_ref.document.return_value and call.args[1]["user_id"] == ""
        ]
        assert [
            (row["date"], row["agent_sessions_count"], row["completed"])
            for row in everyone_rows
            if row["aggregation_period"] == "daily"
        ] == [
            (days[0].isoformat(), 2, True),
            (days[1].isoformat(), 2, False),
            (days[2].isoformat(), 2, False),
        ]
        assert db._release_metrics_refresh.call_args.kwargs == {
            "fingerprint": ["fingerprint"],
            "claimed_fingerprint": None,
        }

    def test_reads_an_unstamped_sessions_collection_with_no_legacy_runs_for_them_once(self, monkeypatch):
        """A sessions collection stamped with no version, as 3.0 and 3.1 left it, is read for legacy runs once, and
        not again once that read of every session found none."""
        db = _make_db_with_mock_client(monkeypatch)
        day = date(2026, 10, 1)
        db._get_collection = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]
        db._claim_metrics_refresh = MagicMock(return_value={"finished_at": 1, "fingerprint": None})  # type: ignore[method-assign]
        db._get_metrics_dates_to_calculate = MagicMock(return_value=([day], None))  # type: ignore[method-assign]
        db._get_metrics_legacy_runs = MagicMock(return_value=({}, {}))  # type: ignore[method-assign]
        db._heartbeat_metrics_refresh = MagicMock(return_value=True)  # type: ignore[method-assign]
        db._calculate_date_metrics = MagicMock(return_value=True)  # type: ignore[method-assign]
        db._get_open_metrics_months = MagicMock(return_value=[])  # type: ignore[method-assign]
        db._calculate_month_metrics = MagicMock(return_value=True)  # type: ignore[method-assign]
        db._release_metrics_refresh = MagicMock()  # type: ignore[method-assign]
        db.session_table_name = "test_sessions"
        db.get_latest_schema_version = MagicMock(return_value="2.0.0")  # type: ignore[method-assign]

        assert db.calculate_metrics_dates() == [day]
        assert db.calculate_metrics_dates() == [day]

        # The one read starts at 0, so it read every session
        assert [call.args[2] for call in db._get_metrics_legacy_runs.call_args_list] == [0]


class TestSessionsCollectionVersion:
    def test_keeps_the_stored_version_of_an_empty_sessions_collection(self, monkeypatch):
        """Ensure an empty sessions collection with a version stored keeps it"""
        db = _make_db_with_mock_client(monkeypatch)
        db.versions_table_name = "agno_versions"
        monkeypatch.setattr("agno.db.firestore.firestore.create_collection_indexes", MagicMock())
        sessions_collection_ref, versions_collection_ref = MagicMock(), MagicMock()
        sessions_collection_ref.limit.return_value.select.return_value.stream.return_value = iter([])
        versions_collection_ref.document.return_value.create.side_effect = AlreadyExists("stored")
        collections = {"test_sessions": sessions_collection_ref, "agno_versions": versions_collection_ref}
        db.db_client.collection.side_effect = lambda name: collections[name]

        assert db._get_or_create_collection("test_sessions", "sessions") is sessions_collection_ref

        versions_collection_ref.document.return_value.set.assert_not_called()
