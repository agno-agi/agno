import json
from datetime import date
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.db.migrations.manager import MigrationManager
from agno.db.mongo import MongoDb
from agno.db.mongo.utils import (
    build_component_metrics_legacy_runs,
    build_component_metrics_legacy_runs_projection,
    build_component_metrics_runs_projection,
)
from agno.db.utils import METRICS_REFRESH_ID


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

    upsert_schema_version.assert_called_once_with(
        table_name=db.session_table_name, version=MigrationManager(db).latest_schema_version.public
    )


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


def test_metrics_runs_projections_keep_session_id():
    """A run and a legacy run keep their session, which names the session of each remote member run nested in them."""
    assert build_component_metrics_runs_projection()["session_id"] == 1
    assert build_component_metrics_legacy_runs_projection()["session_id"] == 1


def test_metrics_legacy_runs_count_runs_stored_as_json_string():
    """Legacy runs stored as a JSON string, as before v2.1.1, count like legacy runs stored as an array."""
    db = _db()
    sessions_collection = Mock()
    created_at = 1790000000
    sessions_cursor = Mock()
    # As the projection reads them: an array keeps its runs' fields, a JSON string comes back without runs
    sessions_cursor.batch_size.return_value = iter(
        [
            {
                "_id": 1,
                "session_id": "s1",
                "user_id": "u1",
                "created_at": created_at,
                "runs": [{"run_id": "r1", "agent_id": "a1", "created_at": created_at}],
            },
            {"_id": 2, "session_id": "s2", "user_id": "u1", "created_at": created_at},
        ]
    )
    # Only the session that came back without runs is read again, with its runs whole
    json_sessions = iter(
        [{"_id": 2, "runs": json.dumps([{"run_id": "r2", "agent_id": "a1", "created_at": created_at}])}]
    )
    sessions_collection.find.side_effect = [sessions_cursor, json_sessions]

    _, legacy_runs_by_id = db._get_metrics_legacy_runs(sessions_collection, None, created_at, created_at + 1)

    assert sorted(legacy_runs_by_id) == ["r1", "r2"]
    assert legacy_runs_by_id["r2"]["session_id"] == "s2"
    assert sessions_collection.find.call_args.args[0] == {"_id": {"$in": [2]}, "runs": {"$type": "string"}}


def test_metrics_legacy_runs_count_json_string_runs_of_sessions_sharing_an_id_once(monkeypatch):
    """Sessions sharing an id, possible without the unique index, count the JSON string runs of each once, read in
    the same batch or not."""
    monkeypatch.setattr("agno.db.mongo.mongo.METRICS_BATCH_SIZE", 1)
    db = _db()
    sessions_collection = Mock()
    created_at = 1790000000
    sessions_cursor = Mock()
    sessions_cursor.batch_size.return_value = iter(
        [
            {"_id": 1, "session_id": "dup", "user_id": "u1", "created_at": created_at},
            {"_id": 2, "session_id": "dup", "user_id": "u1", "created_at": created_at},
        ]
    )
    json_documents = [
        {
            "_id": 1,
            "session_id": "dup",
            "runs": json.dumps([{"run_id": "r1", "agent_id": "a1", "created_at": created_at}]),
        },
        {
            "_id": 2,
            "session_id": "dup",
            "runs": json.dumps([{"run_id": "r2", "agent_id": "a1", "created_at": created_at}]),
        },
    ]

    # Each batch's read of the JSON string runs returns the documents its filter matches, as MongoDB does
    def find(filter, projection):
        if filter.get("runs") != {"$type": "string"}:
            return sessions_cursor
        return iter(
            document
            for document in json_documents
            if all(document[key] in condition["$in"] for key, condition in filter.items() if key != "runs")
        )

    sessions_collection.find.side_effect = find

    legacy_runs_by_day, legacy_runs_by_id = db._get_metrics_legacy_runs(
        sessions_collection, None, created_at, created_at + 1
    )

    assert sorted(legacy_runs_by_id) == ["r1", "r2"]
    assert sum(len(runs) for runs in legacy_runs_by_day.values()) == 2


def test_metrics_legacy_runs_read_no_json_string_when_every_session_has_runs():
    """A batch whose sessions all came back with runs is read with no query for runs stored as a JSON string."""
    db = _db()
    sessions_collection = Mock()
    created_at = 1790000000
    sessions_cursor = Mock()
    sessions_cursor.batch_size.return_value = iter(
        [
            {
                "session_id": "s1",
                "user_id": "u1",
                "created_at": created_at,
                "runs": [{"run_id": "r1", "agent_id": "a1", "created_at": created_at}],
            }
        ]
    )
    sessions_collection.find.side_effect = [sessions_cursor]

    _, legacy_runs_by_id = db._get_metrics_legacy_runs(sessions_collection, None, created_at, created_at + 1)

    assert sorted(legacy_runs_by_id) == ["r1"]
    assert sessions_collection.find.call_count == 1


def test_metrics_runs_projection_keeps_what_tool_metrics_count():
    """A run keeps of its tool calls only what tool_metrics counts, never their arguments or result, and of its
    messages the tool call each answers, which a forked run's copied tool calls are found by."""
    projection = build_component_metrics_runs_projection()
    for field in [
        "tools.toolkit",
        "tools.tool_name",
        "tools.tool_call_error",
        "tools.requires_confirmation",
        "tools.confirmed",
        "tools.requires_user_input",
        "tools.external_execution_required",
        "tools.metrics.duration",
        "tools.tool_call_id",
        "messages.tool_call_id",
    ]:
        assert projection[f"run_data.{field}"] == 1
    assert not any(field.startswith(("run_data.tools.tool_args", "run_data.tools.result")) for field in projection)


def test_metrics_legacy_runs_json_string_keeps_what_tool_metrics_count():
    """A legacy run stored as a JSON string keeps what the projection keeps of the same run stored as an array, never
    its tool calls' arguments or result, or its messages' content."""
    created_at = 1790000000
    run = {
        "run_id": "r1",
        "agent_id": "a1",
        "created_at": created_at,
        "tools": [{"tool_call_id": "c1", "tool_name": "search", "tool_args": {"query": "q"}, "result": "result"}],
        "messages": [{"role": "tool", "tool_call_id": "c1", "content": "result"}],
    }
    assert build_component_metrics_legacy_runs(json.dumps([run])) == [
        {
            "run_id": "r1",
            "agent_id": "a1",
            "created_at": created_at,
            "tools": [{"tool_call_id": "c1", "tool_name": "search"}],
            "messages": [{"role": "tool", "tool_call_id": "c1"}],
        }
    ]


def test_component_metrics_totals_read_tool_metrics():
    """The totals of a day read back the tools each of its rows keeps as a list, and add them up."""
    db = _db()
    collection = Mock()
    collection.find.return_value = [
        {
            "aggregation_period": "daily",
            "date": "2026-10-01",
            "updated_at": 1,
            "tool_metrics": [
                {
                    "tool_name": "search",
                    "toolkit": "web",
                    "count": 1,
                    "failed_count": 0,
                    "total_ms": 200,
                    "max_ms": 200,
                    "buckets": {"le_200": 1},
                }
            ],
        },
        {
            "aggregation_period": "daily",
            "date": "2026-10-01",
            "updated_at": 2,
            "tool_metrics": [
                {
                    "tool_name": "search",
                    "toolkit": "web",
                    "count": 2,
                    "failed_count": 1,
                    "total_ms": 300,
                    "max_ms": 250,
                    "buckets": {"le_50": 1, "le_250": 1},
                }
            ],
        },
    ]

    with patch.object(db, "_get_collection", return_value=collection):
        totals, latest_updated_at = db.get_component_metrics(
            date(2026, 10, 1), date(2026, 10, 1), user_id="", fields=["tool_metrics"]
        )

    assert collection.find.call_args.args[1]["tool_metrics"] == 1
    assert totals[0]["tool_metrics"] == {
        "web": {
            "search": {
                "count": 3,
                "failed_count": 1,
                "total_ms": 500,
                "max_ms": 250,
                "buckets": {"le_200": 1, "le_50": 1, "le_250": 1},
            }
        }
    }
    assert latest_updated_at == 2


def test_metrics_rebuild_reopen_failure_marks_refresh_failed():
    """A rebuild whose reopen fails shows the error in the refresh status, unless a process holds the refresh."""
    db = _db()
    refreshes_collection = Mock()

    with (
        patch.object(db, "_get_collection", side_effect=lambda table_type, **kwargs: refreshes_collection),
        patch("agno.db.mongo.mongo.reopen_metrics_days_from", side_effect=Exception("reopen failed")),
    ):
        with pytest.raises(Exception, match="reopen failed"):
            db.calculate_metrics_dates(rebuild_from=date(2026, 10, 1))

    query, update = refreshes_collection.update_one.call_args.args
    assert query == {"id": METRICS_REFRESH_ID, "locked_by": None}
    assert update["$set"]["status"] == "failed"


def test_get_metrics_returns_a_day_with_only_a_regenerated_run():
    """A day whose only run is a regenerated one has its tokens but no count, and get_metrics still reads it."""
    db = _db()
    collection = Mock()
    collection.find.return_value.sort.return_value = []

    with patch.object(db, "_get_collection", return_value=collection):
        db._get_aggregate_metrics_rows(date(2026, 10, 1), date(2026, 10, 1), "")

    assert {"total_tokens": {"$gt": 0}} in collection.find.call_args.args[0]["$or"]
