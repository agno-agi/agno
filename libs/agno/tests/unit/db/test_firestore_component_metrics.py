"""Unit tests for the component metrics methods of the FirestoreDb class.

These tests use mocks so we don't need a live Firestore.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

try:
    from google.api_core.exceptions import FailedPrecondition, NotFound
    from google.cloud.firestore import Increment

    from agno.db.firestore.firestore import FIRESTORE_BATCH_LIMIT, FirestoreDb
except ImportError:
    FirestoreDb = None  # type: ignore[misc,assignment]

from agno.db.utils import build_user_metrics_rows

pytestmark = pytest.mark.skipif(FirestoreDb is None, reason="google-cloud-firestore not installed")


def _make_db_with_mock_client(monkeypatch) -> FirestoreDb:
    """Instantiate FirestoreDb without touching real Firestore, each transaction applying its writes as given."""
    db = FirestoreDb.__new__(FirestoreDb)
    db.db_client = MagicMock()
    db._metrics_days_not_reopened = set()
    db._metrics_refresh_found = False
    monkeypatch.setattr("agno.db.firestore.firestore.transactional", lambda function: function)
    return db


def _old_day_timestamp() -> int:
    day = datetime.now(timezone.utc).date() - timedelta(days=5)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _mock_collections(db: FirestoreDb, refresh_exists: bool) -> MagicMock:
    """Give db a metrics refreshes collection whose document exists or not, and return its user metrics collection."""
    refreshes_collection_ref = MagicMock()
    refreshes_collection_ref.document.return_value.get.return_value.exists = refresh_exists
    user_metrics_collection_ref = MagicMock()
    collections = {"metrics_refreshes": refreshes_collection_ref, "user_metrics": user_metrics_collection_ref}
    db._get_collection = MagicMock(side_effect=lambda table_type: collections[table_type])  # type: ignore[method-assign]
    return user_metrics_collection_ref


class TestReopenMetricsDays:
    def test_creates_an_open_row_for_a_day_without_one(self, monkeypatch):
        """Ensure a day without a totals row gets an open one"""
        db = _make_db_with_mock_client(monkeypatch)
        user_metrics_collection_ref = _mock_collections(db, refresh_exists=True)
        user_metrics_collection_ref.document.return_value.update.side_effect = NotFound("no row")

        db._reopen_metrics_days([_old_day_timestamp()])

        created = user_metrics_collection_ref.document.return_value.create.call_args.args[0]
        assert (created["completed"], created["version"], created["user_id"]) == (False, 1, "")

    def test_reopens_a_day_while_the_first_calculation_has_written_no_row(self, monkeypatch):
        """The refresh document is written by the claim, before the first calculation reads any day"""
        db = _make_db_with_mock_client(monkeypatch)
        user_metrics_collection_ref = _mock_collections(db, refresh_exists=True)
        user_metrics_collection_ref.limit.return_value.get.return_value = []

        db._reopen_metrics_days([_old_day_timestamp()])

        user_metrics_collection_ref.document.return_value.update.assert_called_once()

    def test_skips_a_database_no_calculation_built(self, monkeypatch):
        """Ensure a database no calculation built reopens no day and keeps none for later"""
        db = _make_db_with_mock_client(monkeypatch)
        user_metrics_collection_ref = _mock_collections(db, refresh_exists=False)
        db._metrics_days_not_reopened = {date(2026, 1, 1)}

        db._reopen_metrics_days([_old_day_timestamp()])

        user_metrics_collection_ref.document.assert_not_called()
        assert db._metrics_days_not_reopened == set()

    def test_keeps_a_day_it_could_not_reopen_for_the_next_write(self, monkeypatch):
        """Ensure a day that could not be reopened is kept for the next write"""
        db = _make_db_with_mock_client(monkeypatch)
        db._get_collection = MagicMock(side_effect=RuntimeError("unavailable"))  # type: ignore[method-assign]

        db._reopen_metrics_days([_old_day_timestamp()])

        assert len(db._metrics_days_not_reopened) == 1


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

    def test_heartbeat_and_release_only_for_the_worker_holding_it(self, monkeypatch):
        """Ensure only the worker holding the refresh heartbeats and releases it"""
        db = _make_db_with_mock_client(monkeypatch)
        refreshes_collection_ref = self._refreshes({"locked_by": "another", "locked_at": 0})
        transaction = MagicMock()

        assert not db._heartbeat_metrics_refresh(transaction, refreshes_collection_ref, "worker")
        db._release_metrics_refresh(refreshes_collection_ref, "worker", error="boom")

        transaction.update.assert_not_called()
        db.db_client.transaction.return_value.update.assert_not_called()


class TestMetricsFingerprint:
    def test_unknown_while_the_index_of_the_sum_is_not_built(self, monkeypatch):
        """Ensure the fingerprint is unknown while the index of the sum is not built"""
        db = _make_db_with_mock_client(monkeypatch)
        sessions_collection_ref = MagicMock()
        sessions_collection_ref.where.return_value.count.return_value.sum.return_value.get.side_effect = (
            FailedPrecondition("The query requires an index")
        )

        assert db._get_metrics_fingerprint(sessions_collection_ref, None, date(2026, 1, 1)) is None


class TestWriteMetricsTotalsRows:
    def _write(self, monkeypatch, row_writes, heartbeat=True):
        db = _make_db_with_mock_client(monkeypatch)
        batches = []

        def new_batch():
            batch = MagicMock()
            batches.append(batch)
            return batch

        db.db_client.batch.side_effect = new_batch
        db._heartbeat_metrics_refresh = MagicMock(return_value=heartbeat)  # type: ignore[method-assign]
        day = date(2026, 1, 1)
        user_metrics_collection_ref = MagicMock()
        # The stored everyone row of the day, at version 3
        stored_row = {**build_user_metrics_rows([], "daily", day, True)[0], "date": day.isoformat(), "version": 3}
        user_metrics_collection_ref.where.return_value.where.return_value.stream.return_value = [
            MagicMock(to_dict=MagicMock(return_value=stored_row))
        ]
        user_metrics_collection_ref.document.return_value.get.return_value = MagicMock(
            exists=True, to_dict=MagicMock(return_value=stored_row)
        )
        written = db._write_user_metrics_rows(
            user_metrics_collection_ref,
            build_user_metrics_rows([], "daily", day, False),
            rows_changed=True,
            read_version=3,
            refreshes_collection_ref=MagicMock(),
            worker_id="worker",
            row_writes=row_writes,
        )
        return written, batches

    def test_moves_the_version_first_when_the_rows_take_more_than_one_commit(self, monkeypatch):
        """Ensure the version moves first when the rows take more than one commit"""
        written, batches = self._write(monkeypatch, [(MagicMock(), {"n": i}) for i in range(FIRESTORE_BATCH_LIMIT)])

        assert written
        assert len(batches) == 2
        first_update = batches[0].update.call_args_list[0]
        assert isinstance(first_update.args[1]["version"], Increment)

    def test_moves_the_version_with_its_row_when_the_rows_take_one_commit(self, monkeypatch):
        """Ensure the version moves with its row when the rows take one commit"""
        written, batches = self._write(monkeypatch, [(MagicMock(), {"n": 1})])

        assert written
        assert len(batches) == 1
        batches[0].update.assert_not_called()

    def test_writes_nothing_once_another_worker_took_the_refresh_over(self, monkeypatch):
        """Ensure nothing is written once another worker took the refresh over"""
        written, batches = self._write(monkeypatch, [(MagicMock(), {"n": 1})], heartbeat=False)

        assert not written
        batches[0].commit.assert_not_called()


class TestGetMetricsVersions:
    def test_none_until_a_first_calculation_finished(self, monkeypatch):
        """Ensure no version is read until a first calculation has finished"""
        db = _make_db_with_mock_client(monkeypatch)
        db._metrics_refreshed_at = float("inf")
        db._get_collection = MagicMock()  # type: ignore[method-assign]
        db._metrics_calculated = MagicMock(return_value=False)  # type: ignore[method-assign]

        assert db.get_metrics_versions(date(2026, 1, 1), date(2026, 1, 31)) is None


class TestCalculateMetrics:
    def test_writes_each_day_and_its_totals_rows_last(self, monkeypatch):
        """Each day gets one row per user, then its everyone totals row; only a day ended a day ago is completed, and
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
        user_metrics_collection_ref = MagicMock()
        user_metrics_collection_ref.document.return_value.get.return_value.exists = False
        collections = {
            "component_metrics": collection_ref,
            "user_metrics": user_metrics_collection_ref,
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
        batches = []

        def new_batch():
            batch = MagicMock()
            batches.append(batch)
            return batch

        db.db_client.batch.side_effect = new_batch

        assert db.calculate_metrics_dates() == days

        rows = [
            call.args[1]
            for batch in batches
            for call in batch.set.call_args_list
            if call.args[0] is collection_ref.document.return_value
        ]
        assert [(row["date"], row["user_id"], row["sessions_count"]) for row in rows] == [
            (day.isoformat(), user_id, 1) for day in days for user_id in ["alice", "bob"]
        ]
        everyone_rows = [call.args[1] for call in db.db_client.transaction.return_value.set.call_args_list]
        assert [
            (row["date"], row["agent_sessions_count"], row["completed"])
            for row in everyone_rows
            if row["aggregation_period"] == "daily"
        ] == [
            (days[0].isoformat(), 2, True),
            (days[1].isoformat(), 2, False),
            (days[2].isoformat(), 2, False),
        ]
        assert db._release_metrics_refresh.call_args.kwargs == {"fingerprint": ["fingerprint"]}
