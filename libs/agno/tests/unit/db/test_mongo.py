from unittest.mock import MagicMock, Mock, patch

from agno.db.mongo import MongoDb


def _db():
    return MongoDb(db_url="mongodb://localhost:27017", db_name="test_db", learnings_collection="learnings")


def test_get_collection_refetches_when_cached_none():
    """Regression (mirrors async_mongo): a read with create=False on a not-yet-created
    learnings collection must not cache None and silently drop later writes."""
    db = _db()
    sentinel = object()
    db._get_or_create_collection = Mock(side_effect=[None, sentinel])

    first = db._get_collection("learnings", create_collection_if_not_found=False)
    assert first is None
    second = db._get_collection("learnings", create_collection_if_not_found=True)
    assert second is sentinel
    assert db._get_or_create_collection.call_count == 2


class TestSyncMongoLearnings:
    """Wiring tests for the sync MongoDb learning methods (parity with async_mongo)."""

    def test_upsert_learning_uses_deterministic_pk_upsert(self):
        db = _db()
        coll = MagicMock()
        with patch.object(db, "_get_collection", return_value=coll):
            db.upsert_learning(id="user_profile_u1", learning_type="user_profile", user_id="u1", content={"a": 1})
        assert coll.update_one.call_args[0][0] == {"learning_id": "user_profile_u1"}
        assert coll.update_one.call_args[1]["upsert"] is True

    def test_get_learning_by_id_strips_mongo_id(self):
        db = _db()
        coll = MagicMock()
        coll.find_one.return_value = {"_id": "x", "learning_id": "a", "user_id": "u1"}
        with patch.object(db, "_get_collection", return_value=coll):
            rec = db.get_learning_by_id("a")
        assert rec == {"learning_id": "a", "user_id": "u1"}

    def test_list_learnings_returns_records_and_count(self):
        db = _db()
        coll = MagicMock()
        coll.count_documents.return_value = 1
        coll.find.return_value.sort.return_value.skip.return_value.limit.return_value = [
            {"_id": "x", "learning_id": "a", "user_id": "u1"}
        ]
        with patch.object(db, "_get_collection", return_value=coll):
            rows, total = db.list_learnings(user_id="u1")
        assert total == 1
        assert rows == [{"learning_id": "a", "user_id": "u1"}]

    def test_delete_user_learnings_returns_count(self):
        db = _db()
        coll = MagicMock()
        coll.delete_many.return_value = MagicMock(deleted_count=3)
        with patch.object(db, "_get_collection", return_value=coll):
            assert db.delete_user_learnings("u1") == 3
        assert coll.delete_many.call_args[0][0] == {"user_id": "u1"}

    def test_get_learnings_user_stats_groups_by_user(self):
        db = _db()
        coll = MagicMock()
        coll.aggregate.side_effect = [
            [{"total": 2}],
            [{"_id": "u1", "last_learning_updated_at": 5}, {"_id": "u2", "last_learning_updated_at": 4}],
        ]
        with patch.object(db, "_get_collection", return_value=coll):
            stats, total = db.get_learnings_user_stats()
        assert total == 2
        assert [s["user_id"] for s in stats] == ["u1", "u2"]

    def test_router_facing_methods_raise_on_db_error(self):
        # router-facing reads/deletes surface DB errors (parity with async + the other adapters)
        db = _db()
        coll = MagicMock()
        coll.find_one.side_effect = RuntimeError("boom")
        coll.count_documents.side_effect = RuntimeError("boom")
        coll.delete_many.side_effect = RuntimeError("boom")
        with patch.object(db, "_get_collection", return_value=coll):
            for call in (
                lambda: db.get_learning_by_id("a"),
                lambda: db.list_learnings(),
                lambda: db.delete_user_learnings("u1"),
            ):
                try:
                    call()
                    raise AssertionError("expected RuntimeError")
                except RuntimeError:
                    pass
