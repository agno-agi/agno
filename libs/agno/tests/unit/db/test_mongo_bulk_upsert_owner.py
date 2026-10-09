"""``upsert_sessions`` must apply the same owner check as ``upsert_session``.

The single-row upsert refuses to update a stored session whose ``user_id``
differs from the incoming one (``mongo.py`` reads the stored owner and returns
``None`` on a mismatch). The Mongo bulk path issued
``ReplaceOne(filter={"session_id": ...})``, which matches regardless of owner
and swaps the whole document -- so a batch containing another user's
``session_id`` reassigned the stored row and overwrote its data.

PR #9937 fixed this shape on SQLite and notes Postgres already carried the
predicate; this brings ``MongoDb`` and ``AsyncMongoDb`` in line.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agno.db.mongo import MongoDb
from agno.session.agent import AgentSession


def _session(user_id: str, marker: str) -> AgentSession:
    return AgentSession(
        session_id="shared",
        agent_id="a1",
        user_id=user_id,
        session_data={"session_state": {"owner": marker}},
        created_at=1000,
        updated_at=1000,
    )


class TestSessionWriteAllowed:
    """The predicate the bulk path consults, exercised through the adapter."""

    def test_absent_row_is_claimable(self):
        db, collection = _db_with_no_stored_rows()
        with patch.object(MongoDb, "_get_collection", return_value=collection):
            db.upsert_sessions([_session("alice", "v1")], deserialize=False)
        collection.bulk_write.assert_called_once()

    def test_unowned_row_is_claimable(self):
        db, collection = _db_with_stored(None)
        with patch.object(MongoDb, "_get_collection", return_value=collection):
            db.upsert_sessions([_session("alice", "v1")], deserialize=False)
        collection.bulk_write.assert_called_once()

    def test_anonymous_writer_is_refused_an_owned_row(self):
        db, collection = _db_with_stored("alice")
        anonymous = AgentSession(session_id="shared", agent_id="a1", user_id=None, created_at=1, updated_at=1)
        with patch.object(MongoDb, "_get_collection", return_value=collection):
            db.upsert_sessions([anonymous], deserialize=False)
        collection.bulk_write.assert_not_called()


def _db_with_no_stored_rows():
    db = MongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = MagicMock()
    collection.find.return_value = iter([])
    return db, collection


def _db_with_stored(stored_owner: str | None):
    """A MongoDb whose sessions collection holds one row owned by ``stored_owner``."""
    db = MongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collection = MagicMock()
    collection.find.return_value = iter([{"session_id": "shared", "user_id": stored_owner}])
    return db, collection


class TestBulkUpsertOwnerCheck:
    def test_another_users_session_is_not_written(self):
        db, collection = _db_with_stored("alice")

        with patch.object(MongoDb, "_get_collection", return_value=collection):
            db.upsert_sessions([_session("bob", "bob-data")])

        # Nothing was queued for the refused session, so bulk_write never ran.
        collection.bulk_write.assert_not_called()

    def test_the_owners_own_session_is_written(self):
        db, collection = _db_with_stored("alice")

        with patch.object(MongoDb, "_get_collection", return_value=collection):
            db.upsert_sessions([_session("alice", "v2")], deserialize=False)

        collection.bulk_write.assert_called_once()
        operations = collection.bulk_write.call_args[0][0]
        assert len(operations) == 1

    def test_a_batch_writes_only_the_sessions_its_owner_may_touch(self):
        db, collection = _db_with_stored("alice")
        mine = AgentSession(session_id="mine", agent_id="a1", user_id="bob", created_at=1, updated_at=1)

        with patch.object(MongoDb, "_get_collection", return_value=collection):
            db.upsert_sessions([_session("bob", "bob-data"), mine], deserialize=False)

        collection.bulk_write.assert_called_once()
        operations = collection.bulk_write.call_args[0][0]
        written_ids = [op._filter["session_id"] for op in operations]
        assert written_ids == ["mine"]
