from datetime import date
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.db.mongo import MongoDb
from agno.db.mongo.utils import (
    build_component_metrics_legacy_runs_projection,
    build_component_metrics_runs_projection,
)
from agno.db.utils import METRICS_REFRESH_ID
from agno.session import AgentSession


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


def test_created_sessions_collection_stores_latest_schema_version():
    """A sessions collection the store creates stores the latest schema version, so metrics never read its legacy runs."""
    db = _db()

    with (
        patch.object(db, "table_exists", return_value=False),
        patch.object(db, "upsert_schema_version") as upsert_schema_version,
        patch("agno.db.mongo.mongo.create_collection_indexes"),
    ):
        db._get_collection("sessions", create_collection_if_not_found=True)

    upsert_schema_version.assert_called_once_with(table_name=db.session_table_name, version="3.0.0")


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

    def test_update_learning_is_update_only(self):
        db = _db()
        coll = MagicMock()
        # matched -> True (existing row updated); never passes upsert=True (no insert)
        coll.update_one.return_value = MagicMock(matched_count=1)
        with patch.object(db, "_get_collection", return_value=coll):
            assert db.update_learning("a", content={"x": 1}, metadata={"m": 1}) is True
        assert coll.update_one.call_args[0][0] == {"learning_id": "a"}
        assert "upsert" not in coll.update_one.call_args[1]

    def test_update_learning_returns_false_when_no_row_matches(self):
        db = _db()
        coll = MagicMock()
        coll.update_one.return_value = MagicMock(matched_count=0)
        with patch.object(db, "_get_collection", return_value=coll):
            assert db.update_learning("missing", content={"x": 1}) is False

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


def test_text_filters_match_literal_text():
    """session_name and search_content are user text, not regex patterns."""
    db = _db()
    coll = MagicMock()
    with patch.object(db, "_get_collection", return_value=coll):
        db.get_sessions(session_name="v1.2(draft", deserialize=False)
        db.get_user_memories(search_content="v1.2(draft", deserialize=False)
    sessions_query, memories_query = [c.args[0] for c in coll.count_documents.call_args_list]
    assert sessions_query["session_data.session_name"] == {"$regex": r"v1\.2\(draft", "$options": "i"}
    assert memories_query["memory"] == {"$regex": r"v1\.2\(draft", "$options": "i"}


def test_metrics_legacy_runs_stop_when_refresh_taken_over():
    """The legacy runs are read with a heartbeat per batch, and stop once another process took the refresh over."""
    db = _db()

    cursor = MagicMock()
    cursor.batch_size.return_value = cursor
    cursor.__iter__.return_value = iter([{"session_id": "s1", "created_at": 0, "runs": [{"run_id": "r1"}]}])
    sessions_collection = Mock()
    sessions_collection.find.return_value = cursor

    with patch.object(db, "_heartbeat_metrics_refresh", Mock(return_value=False)) as heartbeat:
        result = db._get_metrics_legacy_runs(sessions_collection, None, 0, 86400, Mock(), "worker")

    assert result is None
    heartbeat.assert_called_once()


def test_metrics_runs_projections_keep_session_id():
    """A run and a legacy run keep their session, which names the session of each remote member run nested in them."""
    assert build_component_metrics_runs_projection()["session_id"] == 1
    assert build_component_metrics_legacy_runs_projection()["session_id"] == 1


def test_metrics_release_keeps_rebuild_mark_after_claim_of_none():
    """A claim of no fingerprint still compares, so a rebuild marked after it is kept."""
    db = _db()
    refreshes_collection = Mock()

    db._release_metrics_refresh(refreshes_collection, "worker", fingerprint=["2026-11-01", 1, 2])

    values = refreshes_collection.update_one.call_args.args[1][0]["$set"]
    assert values["fingerprint"]["$cond"][0] == {"$eq": [{"$ifNull": ["$fingerprint", None]}, {"$literal": None}]}
    assert values["fingerprint"]["$cond"][2] == "$fingerprint"


def test_metrics_rebuild_reopen_failure_marks_refresh_failed():
    """A rebuild whose reopen fails shows the error in the refresh status, unless a process holds the refresh or a
    calculation started or finished after the rebuild read it."""
    db = _db()
    refreshes_collection = Mock()
    refreshes_collection.find_one.return_value = {"id": METRICS_REFRESH_ID, "started_at": 100, "finished_at": 200}

    with (
        patch.object(db, "_get_collection", side_effect=lambda table_type, **kwargs: refreshes_collection),
        patch("agno.db.mongo.mongo.reopen_metrics_days_from", side_effect=Exception("reopen failed")),
    ):
        with pytest.raises(Exception, match="reopen failed"):
            db.calculate_metrics_dates(rebuild_from=date(2026, 10, 1))

    query, pipeline = refreshes_collection.update_one.call_args.args
    assert query == {"id": METRICS_REFRESH_ID, "locked_by": None, "started_at": 100, "finished_at": 200}
    assert pipeline[0]["$set"]["status"] == "failed"


def test_upsert_sessions_reads_back_in_chunks():
    """The sessions written are read back a chunk of ids at a time, so many long ids never exceed a query document."""
    db = _db()
    collection = Mock()
    # The lookup before the write passes a projection and finds nothing stored
    collection.find.side_effect = lambda query, *args: (
        [] if args else [{"session_id": sid, "session_type": "agent"} for sid in query["session_id"]["$in"]]
    )

    with (
        patch.object(db, "_get_collection", return_value=collection),
        patch.object(db, "_reopen_metrics_days"),
        patch("agno.db.mongo.mongo.METRICS_IN_LIST_LIMIT", 1),
    ):
        results = db.upsert_sessions([AgentSession(session_id="s1"), AgentSession(session_id="s2")])

    assert [session.session_id for session in results] == ["s1", "s2"]
    read_backs = [call.args[0] for call in collection.find.call_args_list if len(call.args) == 1]
    assert read_backs == [{"session_id": {"$in": ["s1"]}}, {"session_id": {"$in": ["s2"]}}]


def test_an_unstamped_sessions_collection_with_no_legacy_runs_is_read_for_them_once():
    """A sessions collection stamped with no version, as 3.0 and 3.1 left it, is read for legacy runs once, and not
    again once that read of every session found none."""
    db = _db()
    legacy_reads = Mock(return_value=({}, {}))

    with (
        patch.object(db, "_get_collection", return_value=Mock()),
        patch.object(db, "get_latest_schema_version", return_value="2.0.0"),
        patch.object(db, "_claim_metrics_refresh", return_value={"finished_at": 1, "fingerprint": None}),
        patch.object(db, "_get_metrics_dates_to_calculate", return_value=([date(2026, 10, 1)], None)),
        patch.object(db, "_get_metrics_legacy_runs", legacy_reads),
        patch.object(db, "_heartbeat_metrics_refresh", return_value=True),
        patch.object(db, "_calculate_date_metrics", return_value=True),
        patch.object(db, "_get_open_metrics_months", return_value=[]),
        patch.object(db, "_calculate_month_metrics", return_value=True),
        patch.object(db, "_release_metrics_refresh"),
    ):
        assert db.calculate_metrics_dates() == [date(2026, 10, 1)]
        assert db.calculate_metrics_dates() == [date(2026, 10, 1)]

    # The one read starts at 0, so it read every session
    assert [read.args[2] for read in legacy_reads.call_args_list] == [0]
