"""Regression tests for reviewer comment #11 on PR #8350.

Firestore batched writes have a hard 500-operation-per-commit limit. Several
FirestoreDb call sites (``delete_runs``, ``cleanup_legacy_runs_field``,
``delete_sessions`` cascade, ``delete_user_memories``) staged all operations
into a single batch and committed once — for any install with >500 ops in a
single logical delete, Firestore rejects with ``INVALID_ARGUMENT``.

Fix: chunk operations at ``FIRESTORE_BATCH_LIMIT`` (500) and commit each
chunk separately. These tests use mocks so we don't need a live Firestore.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

try:
    from agno.db.firestore.firestore import FIRESTORE_BATCH_LIMIT, FirestoreDb
except ImportError:
    FirestoreDb = None  # type: ignore[misc,assignment]


pytestmark = pytest.mark.skipif(FirestoreDb is None, reason="google-cloud-firestore not installed")


def _make_db_with_mock_client():
    """Instantiate FirestoreDb without touching real Firestore."""
    db = FirestoreDb.__new__(FirestoreDb)
    db.db_client = MagicMock()
    db.session_table_name = "sessions"
    db.runs_table_name = "runs"
    return db


class TestConstantExists:
    def test_firestore_batch_limit_is_500(self):
        assert FIRESTORE_BATCH_LIMIT == 500, (
            "Firestore's hard limit per batch commit is 500 ops; that constant must not drift"
        )


class TestDeleteRunsChunksAt500:
    def _setup_delete_runs(self, num_runs: int, db: FirestoreDb) -> tuple:
        """Wire up mocks so ``delete_runs`` sees ``num_runs`` existing docs."""
        collection = MagicMock()
        db._get_collection = MagicMock(return_value=collection)  # type: ignore[method-assign]

        # Each document exists and has a session_id
        snap = MagicMock()
        snap.exists = True
        snap.to_dict.return_value = {"session_id": "s1"}
        collection.document.return_value.get.return_value = snap

        # Batches: instantiate N distinct MagicMocks so we can count commits
        batches = []

        def new_batch():
            b = MagicMock()
            batches.append(b)
            return b

        db.db_client.batch.side_effect = new_batch
        # Silence the legacy-blob scrub so the test focuses on batch chunking
        db._scrub_run_ids_from_session_legacy_blob = MagicMock()  # type: ignore[method-assign]
        return collection, batches

    def test_501_runs_produces_two_commits(self):
        """501 deletes must split into two batches: 500 + 1."""
        db = _make_db_with_mock_client()
        collection, batches = self._setup_delete_runs(501, db)

        db.delete_runs([f"r{i}" for i in range(501)])

        # 501 ops, chunked at 500 → 2 batches, both committed
        assert len(batches) == 2, f"expected 2 batches for 501 ops, got {len(batches)}"
        assert batches[0].commit.call_count == 1
        assert batches[1].commit.call_count == 1
        assert batches[0].delete.call_count == 500
        assert batches[1].delete.call_count == 1

    def test_1000_runs_produces_two_commits(self):
        """Exactly 1000 ops = 2 full batches."""
        db = _make_db_with_mock_client()
        collection, batches = self._setup_delete_runs(1000, db)

        db.delete_runs([f"r{i}" for i in range(1000)])

        assert len(batches) == 2
        assert batches[0].delete.call_count == 500
        assert batches[1].delete.call_count == 500

    def test_499_runs_produces_one_commit(self):
        """Well under the limit — single batch."""
        db = _make_db_with_mock_client()
        collection, batches = self._setup_delete_runs(499, db)

        db.delete_runs([f"r{i}" for i in range(499)])

        assert len(batches) == 1
        assert batches[0].delete.call_count == 499
        assert batches[0].commit.call_count == 1

    def test_zero_runs_is_noop(self):
        db = _make_db_with_mock_client()
        collection, batches = self._setup_delete_runs(0, db)

        db.delete_runs([])

        # No batches created (loop never entered)
        assert len(batches) == 0


class TestDeleteSessionCascadeChunksAt500:
    """The single-session ``delete_session`` cascade also has to chunk its run
    deletes -- the plural ``delete_sessions`` did, but ``delete_session`` staged
    every run into one batch, so deleting a session with >500 runs (exactly the
    long-lived sessions v3 targets) hit Firestore's INVALID_ARGUMENT.
    """

    def _setup(self, num_runs: int, db: FirestoreDb) -> list:
        sessions_collection = MagicMock()
        runs_collection = MagicMock()

        def get_collection(table_type: str = "sessions", **kwargs):
            return runs_collection if table_type == "runs" else sessions_collection

        db._get_collection = MagicMock(side_effect=get_collection)  # type: ignore[method-assign]

        # One session doc matches the delete query.
        session_doc = MagicMock()
        sessions_collection.where.return_value.stream.return_value = [session_doc]

        # num_runs run docs cascade off it.
        run_docs = [MagicMock() for _ in range(num_runs)]
        runs_collection.where.return_value.stream.return_value = run_docs

        batches: list = []

        def new_batch():
            b = MagicMock()
            batches.append(b)
            return b

        db.db_client.batch.side_effect = new_batch
        return batches

    def test_501_runs_cascade_produces_two_commits(self):
        db = _make_db_with_mock_client()
        batches = self._setup(501, db)

        assert db.delete_session("s1") is True

        assert len(batches) == 2, f"expected 2 batches for 501 run deletes, got {len(batches)}"
        assert batches[0].delete.call_count == 500
        assert batches[1].delete.call_count == 1
        assert batches[0].commit.call_count == 1
        assert batches[1].commit.call_count == 1

    def test_499_runs_cascade_produces_one_commit(self):
        db = _make_db_with_mock_client()
        batches = self._setup(499, db)

        assert db.delete_session("s1") is True

        assert len(batches) == 1
        assert batches[0].delete.call_count == 499
        assert batches[0].commit.call_count == 1

    def test_zero_runs_cascade_commits_nothing(self):
        db = _make_db_with_mock_client()
        batches = self._setup(0, db)

        assert db.delete_session("s1") is True

        # An empty batch may be opened, but nothing is deleted or committed.
        for b in batches:
            assert b.delete.call_count == 0
            assert b.commit.call_count == 0
