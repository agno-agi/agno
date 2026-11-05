"""get_runs cursor filters, has_unindexed_runs and get_session(include_runs) on the document-store adapters.

No Mongo or SurrealDB server runs in unit tests, so their tests pin the queries the adapters build.
Firestore runs the shared contract against a small in-memory stand-in for the client.
"""

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.db.run_cursor_contract import check_contract

# -- MongoDb / AsyncMongoDb --

PAGE_QUERY = {
    "session_id": "s1",
    "status": {"$in": ["COMPLETED", "ERROR"]},
    "run_index": {"$lt": 6},
    "created_at": {"$gte": 1000, "$lte": 2000},
}
PAGE_KWARGS: Dict[str, Any] = dict(
    session_id="s1",
    deserialize=False,
    top_level_only=True,
    status=["completed", "ERROR"],
    before_run_index=6,
    created_after=1000,
    created_before=2000,
    limit=2,
    sort_by="run_index",
    sort_order="desc",
)


def _mongo_db() -> Any:
    pytest.importorskip("pymongo")
    from agno.db.mongo import MongoDb

    return MongoDb(db_url="mongodb://localhost:27017", db_name="test_db")


def _async_mongo_db() -> Any:
    pytest.importorskip("pymongo")
    from agno.db.mongo import AsyncMongoDb

    return AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")


def _runs_collection() -> MagicMock:
    coll = MagicMock()
    coll.name = "agno_runs"
    return coll


def _assert_top_level_page(page_pipeline: List[Dict[str, Any]], count_pipeline: List[Dict[str, Any]]) -> None:
    assert page_pipeline[0] == {"$match": PAGE_QUERY}
    # Sort right after the match so the (session_id, run_index) index serves it and the limit stops the lookups
    assert page_pipeline[1] == {"$sort": {"run_index": -1}}
    lookup = page_pipeline[2]["$lookup"]
    assert lookup["from"] == "agno_runs"
    assert lookup["pipeline"][0] == {
        "$match": {
            "$expr": {
                "$and": [
                    {"$eq": ["$run_id", "$$parent_run_id"]},
                    {"$ne": ["$run_id", "$$run_id"]},
                    {"$eq": ["$session_id", "$$session_id"]},
                ]
            }
        }
    }
    assert page_pipeline[3] == {"$match": {"_parent_run": {"$size": 0}}}
    assert page_pipeline[-1] == {"$limit": 2}
    assert count_pipeline[0] == {"$match": PAGE_QUERY}
    assert count_pipeline[-1] == {"$count": "count"}
    assert {"$sort": {"run_index": -1}} not in count_pipeline


def test_mongo_top_level_page_query():
    db = _mongo_db()
    coll = _runs_collection()
    rows = [{"run_id": "r2", "run_index": 5, "run_data": {"run_id": "r2"}}]
    coll.aggregate.side_effect = [[{"count": 4}], rows]
    with patch.object(db, "_get_collection", return_value=coll):
        result = db.get_runs(**PAGE_KWARGS)

    assert result == (rows, 4)
    count_pipeline, page_pipeline = (call.args[0] for call in coll.aggregate.call_args_list)
    _assert_top_level_page(page_pipeline, count_pipeline)
    coll.find.assert_not_called()


def test_mongo_top_level_count_is_zero_without_matches():
    db = _mongo_db()
    coll = _runs_collection()
    coll.aggregate.side_effect = [[], []]
    with patch.object(db, "_get_collection", return_value=coll):
        assert db.get_runs(session_id="s1", deserialize=False, top_level_only=True) == ([], 0)


def test_mongo_parent_run_ids_and_after_cursor_use_find():
    db = _mongo_db()
    coll = _runs_collection()
    coll.count_documents.return_value = 2
    coll.find.return_value.sort.return_value = [{"run_id": "c1"}, {"run_id": "g1"}]
    with patch.object(db, "_get_collection", return_value=coll):
        rows, count = db.get_runs(session_id="s1", parent_run_ids=["r1", "c1"], after_run_index=0, deserialize=False)

    expected = {"session_id": "s1", "run_index": {"$gt": 0}, "parent_run_id": {"$in": ["r1", "c1"]}}
    coll.count_documents.assert_called_once_with(expected)
    coll.find.assert_called_once_with(expected)
    coll.find.return_value.sort.assert_called_once_with([("run_index", 1), ("created_at", 1)])
    assert [row["run_id"] for row in rows] == ["c1", "g1"]
    assert count == 2


def test_mongo_single_status_is_canonical():
    db = _mongo_db()
    coll = _runs_collection()
    coll.count_documents.return_value = 0
    coll.find.return_value.sort.return_value = []
    with patch.object(db, "_get_collection", return_value=coll):
        db.get_runs(session_id="s1", status="error", deserialize=False)
    coll.find.assert_called_once_with({"session_id": "s1", "status": {"$in": ["ERROR"]}})


def _collections(sessions: MagicMock, runs: MagicMock):
    requested: List[str] = []

    def get_collection(table_type: str, **kwargs: Any) -> MagicMock:
        requested.append(table_type)
        return sessions if table_type == "sessions" else runs

    return get_collection, requested


@pytest.mark.parametrize(
    "legacy, unindexed, expected",
    [({"_id": 1}, None, True), (None, {"_id": 2}, True), (None, None, False)],
)
def test_mongo_has_unindexed_runs(legacy, unindexed, expected):
    db = _mongo_db()
    sessions, runs = MagicMock(), _runs_collection()
    sessions.find_one.return_value = legacy
    runs.find_one.return_value = unindexed
    get_collection, _ = _collections(sessions, runs)
    with patch.object(db, "_get_collection", side_effect=get_collection):
        assert db.has_unindexed_runs("s1") is expected

    legacy_query, projection = sessions.find_one.call_args.args
    assert legacy_query["session_id"] == "s1"
    assert {"runs.0": {"$exists": True}} in legacy_query["$or"]
    assert projection == {"_id": 1}
    if legacy is None:
        runs.find_one.assert_called_once_with({"session_id": "s1", "run_index": None}, {"_id": 1})
    else:
        runs.find_one.assert_not_called()


def test_mongo_get_session_without_runs_skips_runs_collection():
    db = _mongo_db()
    sessions, runs = MagicMock(), _runs_collection()
    sessions.find_one.return_value = {"session_id": "s1", "session_type": "agent", "runs": [{"run_id": "old"}]}
    get_collection, requested = _collections(sessions, runs)
    with patch.object(db, "_get_collection", side_effect=get_collection):
        session = db.get_session("s1", deserialize=False, include_runs=False)

    assert session["runs"] is None
    assert requested == ["sessions"]
    runs.aggregate.assert_not_called()


def test_mongo_get_session_runs_carry_stored_run_index():
    db = _mongo_db()
    sessions, runs = MagicMock(), _runs_collection()
    sessions.find_one.return_value = {"session_id": "s1", "session_type": "agent"}
    runs.aggregate.return_value = [
        {"run_id": "r0", "run_index": 0, "run_data": {"run_id": "r0"}},
        {"run_id": "r2", "run_index": 2, "run_data": {"run_id": "r2", "run_index": 9}},
    ]
    get_collection, _ = _collections(sessions, runs)
    with patch.object(db, "_get_collection", side_effect=get_collection):
        session = db.get_session("s1", deserialize=False)
    assert [(run["run_id"], run["run_index"]) for run in session["runs"]] == [("r0", 0), ("r2", 2)]


async def test_async_mongo_top_level_page_query():
    db = _async_mongo_db()
    coll = _runs_collection()
    rows = [{"run_id": "r2", "run_index": 5, "run_data": {"run_id": "r2"}}]
    aggregate = AsyncMock(side_effect=[[{"count": 4}], rows])
    with (
        patch.object(db, "_get_collection", AsyncMock(return_value=coll)),
        patch.object(db, "_aggregate_to_list", aggregate),
    ):
        result = await db.get_runs(**PAGE_KWARGS)

    assert result == (rows, 4)
    count_pipeline, page_pipeline = (call.args[1] for call in aggregate.call_args_list)
    _assert_top_level_page(page_pipeline, count_pipeline)


async def test_async_mongo_parent_run_ids_use_find():
    db = _async_mongo_db()
    coll = _runs_collection()
    coll.count_documents = AsyncMock(return_value=0)
    coll.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
    with patch.object(db, "_get_collection", AsyncMock(return_value=coll)):
        assert await db.get_runs(session_id="s1", parent_run_ids=[], deserialize=False) == ([], 0)
    coll.find.assert_called_once_with({"session_id": "s1", "parent_run_id": {"$in": []}})


@pytest.mark.parametrize("legacy, unindexed, expected", [({"_id": 1}, None, True), (None, None, False)])
async def test_async_mongo_has_unindexed_runs(legacy, unindexed, expected):
    db = _async_mongo_db()
    sessions, runs = MagicMock(), _runs_collection()
    sessions.find_one = AsyncMock(return_value=legacy)
    runs.find_one = AsyncMock(return_value=unindexed)

    async def get_collection(table_type: str, **kwargs: Any) -> MagicMock:
        return sessions if table_type == "sessions" else runs

    with patch.object(db, "_get_collection", side_effect=get_collection):
        assert await db.has_unindexed_runs("s1") is expected
    if legacy is None:
        runs.find_one.assert_awaited_once_with({"session_id": "s1", "run_index": None}, {"_id": 1})


async def test_async_mongo_get_session_without_runs_skips_runs_collection():
    db = _async_mongo_db()
    sessions = MagicMock()
    sessions.find_one = AsyncMock(return_value={"session_id": "s1", "session_type": "agent"})
    requested: List[str] = []

    async def get_collection(table_type: str, **kwargs: Any) -> MagicMock:
        requested.append(table_type)
        return sessions

    with patch.object(db, "_get_collection", side_effect=get_collection):
        session = await db.get_session("s1", deserialize=False, include_runs=False)
    assert session["runs"] is None
    assert requested == ["sessions"]


# -- FirestoreDb, against an in-memory stand-in for the client --


def _firestore_matches(data: Dict[str, Any], field: str, op: Any, value: Any) -> bool:
    # FieldFilter turns `== None` into a unary IS_NULL filter, which skips documents missing the field
    if getattr(op, "name", None) == "IS_NULL":
        return field in data and data[field] is None
    if op == "==":
        return field in data and data[field] == value
    if field not in data or data[field] is None:
        return False
    current = data[field]
    if op == "in":
        return current in value
    if op in ("<", ">", "<=", ">="):
        # Firestore range filters only match values of the same type
        if type(current) is not type(value):
            return False
        return {"<": current < value, ">": current > value, "<=": current <= value, ">=": current >= value}[op]
    raise NotImplementedError(op)


class _Snapshot:
    def __init__(self, ref: "_DocRef", data: Optional[Dict[str, Any]]):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> Optional[Dict[str, Any]]:
        return dict(self._data) if self._data is not None else None


class _DocRef:
    def __init__(self, docs: Dict[str, Dict[str, Any]], doc_id: str):
        self._docs = docs
        self.id = doc_id

    def get(self) -> _Snapshot:
        return _Snapshot(self, self._docs.get(self.id))

    def set(self, data: Dict[str, Any], merge: bool = False) -> None:
        self._docs[self.id] = {**self._docs.get(self.id, {}), **data} if merge else dict(data)

    def update(self, data: Dict[str, Any]) -> None:
        self._docs[self.id].update(data)

    def delete(self) -> None:
        self._docs.pop(self.id, None)


class _CountResult:
    def __init__(self, value: int):
        self.value = value


class _Query:
    def __init__(self, docs: Dict[str, Dict[str, Any]], filters=(), orders=(), fields=None, limit=None, offset=0):
        self._docs = docs
        self._filters = list(filters)
        self._orders = list(orders)
        self._fields = fields
        self._limit = limit
        self._offset = offset

    def _copy(self, **changes: Any) -> "_Query":
        state = dict(
            filters=self._filters, orders=self._orders, fields=self._fields, limit=self._limit, offset=self._offset
        )
        state.update(changes)
        return _Query(self._docs, **state)

    def where(self, filter: Any) -> "_Query":
        return self._copy(filters=[*self._filters, (filter.field_path, filter.op_string, filter.value)])

    def order_by(self, field: str, direction: str = "ASCENDING") -> "_Query":
        return self._copy(orders=[*self._orders, (field, direction)])

    def select(self, fields: List[str]) -> "_Query":
        return self._copy(fields=list(fields))

    def limit(self, count: int) -> "_Query":
        return self._copy(limit=count)

    def offset(self, count: int) -> "_Query":
        return self._copy(offset=count)

    def document(self, doc_id: Optional[str] = None) -> _DocRef:
        return _DocRef(self._docs, doc_id or f"auto-{len(self._docs)}")

    def _matching(self) -> List[str]:
        ids = [
            doc_id
            for doc_id, data in self._docs.items()
            if all(_firestore_matches(data, *condition) for condition in self._filters)
        ]
        for field, direction in reversed(self._orders):
            # Firestore drops documents that lack an ordered field; nulls sort first
            ids = [doc_id for doc_id in ids if field in self._docs[doc_id]]
            ids.sort(
                key=lambda doc_id: (self._docs[doc_id][field] is not None, self._docs[doc_id][field] or 0),
                reverse=direction == "DESCENDING",
            )
        ids = ids[self._offset :]
        return ids[: self._limit] if self._limit is not None else ids

    def stream(self):
        for doc_id in self._matching():
            data = self._docs[doc_id]
            if self._fields is not None:
                data = {field: data[field] for field in self._fields if field in data}
            yield _Snapshot(_DocRef(self._docs, doc_id), data)

    def count(self, alias: Optional[str] = None):
        total = len(self._matching())
        return MagicMock(get=MagicMock(return_value=[[_CountResult(total)]]))


class _FirestoreClient:
    def __init__(self):
        self.collections: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def collection(self, name: str) -> _Query:
        return _Query(self.collections.setdefault(name, {}))

    def get_all(self, refs: List[_DocRef]):
        for ref in reversed(refs):
            yield ref.get()


def _firestore_db():
    pytest.importorskip("google.cloud.firestore")
    from agno.db.firestore import firestore

    return firestore, firestore.FirestoreDb(db_client=_FirestoreClient())


def test_firestore_contract():
    firestore, db = _firestore_db()
    with patch.object(firestore, "create_collection_indexes"):
        asyncio.run(check_contract(db))


def test_firestore_top_level_page_fetches_only_the_page():
    firestore, db = _firestore_db()
    with patch.object(firestore, "create_collection_indexes"):
        asyncio.run(check_contract(db))
        get_all = MagicMock(side_effect=db.db_client.get_all)
        db.db_client.get_all = get_all
        rows, count = db.get_runs(
            session_id="cursor-session",
            deserialize=False,
            top_level_only=True,
            limit=2,
            sort_by="run_index",
            sort_order="desc",
        )
    assert [row["run_id"] for row in rows] == ["r3", "orphan"]
    assert count == 5
    assert [ref.id for ref in get_all.call_args.args[0]] == ["r3", "orphan"]


def test_firestore_has_unindexed_runs_sees_legacy_blob_and_null_run_index():
    firestore, db = _firestore_db()
    with patch.object(firestore, "create_collection_indexes"):
        asyncio.run(check_contract(db))
        sessions = db.db_client.collections[db.session_table_name]
        runs = db.db_client.collections[db.runs_table_name]
        session_doc = next(iter(sessions.values()))

        session_doc["runs"] = [{"run_id": "legacy"}]
        assert db.has_unindexed_runs("cursor-session") is True
        session_doc["runs"] = []
        assert db.has_unindexed_runs("cursor-session") is False
        runs["r3"]["run_index"] = None
        assert db.has_unindexed_runs("cursor-session") is True
        assert db.has_unindexed_runs("missing-session") is False


def test_firestore_get_session_without_runs_skips_runs_collection():
    firestore, db = _firestore_db()
    with patch.object(firestore, "create_collection_indexes"):
        asyncio.run(check_contract(db))
        with patch.object(db, "_get_session_runs_docs") as runs_docs:
            session = db.get_session("cursor-session", deserialize=False, include_runs=False, runs_limit=3)
    assert session["runs"] is None
    runs_docs.assert_not_called()


# -- SurrealDb --


def _surreal_db():
    pytest.importorskip("surrealdb")
    from agno.db.surrealdb import SurrealDb

    db = SurrealDb.__new__(SurrealDb)
    db.runs_table_name = "agno_runs"
    db.session_table_name = "agno_sessions"
    return db


def test_surreal_top_level_page_query():
    db = _surreal_db()
    queries: List[Any] = []

    def query(sql: str, vars: Dict[str, Any], record_type: Any) -> List[Any]:
        queries.append((sql, vars))
        return ["r0", "r1", "c1"] if "SELECT VALUE run_id" in sql else []

    with (
        patch.object(db, "_get_table", return_value="agno_runs"),
        patch.object(db, "_query", side_effect=query),
        patch.object(db, "_count", return_value=4) as count,
    ):
        assert db.get_runs(**PAGE_KWARGS) == ([], 4)

    ids_sql, ids_vars = queries[0]
    assert "WHERE session_id = $sid" in ids_sql and ids_vars == {"sid": "s1"}
    page_sql, page_vars = queries[1]
    where_clause = count.call_args.args[1]
    assert where_clause in page_sql
    assert "status IN $" in where_clause
    assert "(run_index != NONE AND run_index != NULL)" in where_clause
    assert "(run_index < $before_run_index)" in where_clause
    assert "parent_run_id NOT IN $session_run_ids" in where_clause
    assert "ORDER BY run_index DESC LIMIT 2" in page_sql
    assert page_vars["session_run_ids"] == ["r0", "r1", "c1"]
    assert page_vars["before_run_index"] == 6
    assert sorted(v for v in page_vars.values() if isinstance(v, list) and "ERROR" in v) == [["COMPLETED", "ERROR"]]


def test_surreal_get_session_without_runs_skips_runs_table():
    db = _surreal_db()
    with (
        patch.object(db, "_get_table", return_value="agno_sessions"),
        patch.object(db, "_query_one", return_value={"id": "s1", "session_type": "agent", "runs": [{"run_id": "x"}]}),
        patch.object(db, "_get_session_runs_data") as runs_data,
    ):
        session = db.get_session("s1", deserialize=False, include_runs=False)
    assert session["runs"] is None
    runs_data.assert_not_called()
