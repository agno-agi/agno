import copy
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from pymongo.results import UpdateResult

from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.mongo.utils import (
    OS_METRICS_LOCK_ID,
    bulk_upsert_os_metrics,
    upsert_os_metrics_totals_row,
)
from agno.db.utils import build_os_metrics_totals_row, build_single_run_row, calculate_date_os_metrics
from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

_MATCH_OPERATORS = {
    "$in": lambda value, arg: value in arg,
    "$ne": lambda value, arg: value != arg,
    "$gt": lambda value, arg: value is not None and value > arg,
    "$gte": lambda value, arg: value is not None and value >= arg,
    "$lt": lambda value, arg: value is not None and value < arg,
    "$lte": lambda value, arg: value is not None and value <= arg,
}


def _get(doc: Any, path: str) -> Any:
    """The value at a dotted path of a document, None when it has none"""
    for part in path.split("."):
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc


def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Whether a document matches a query of equalities, comparison operators and $or"""
    for field, condition in query.items():
        if field == "$or":
            if not any(_matches(doc, option) for option in condition):
                return False
        elif isinstance(condition, dict) and all(key.startswith("$") for key in condition):
            if not all(_MATCH_OPERATORS[operator](_get(doc, field), arg) for operator, arg in condition.items()):
                return False
        elif _get(doc, field) != condition:
            return False
    return True


def _evaluate(expression: Any, doc: Dict[str, Any], this: Any = None) -> Any:
    """The value of an aggregation expression for a document"""
    if isinstance(expression, str) and expression.startswith("$$this"):
        return _get({"this": this}, expression[2:])
    if isinstance(expression, str) and expression.startswith("$"):
        return _get(doc, expression[1:])
    if isinstance(expression, list):
        return [_evaluate(item, doc, this) for item in expression]
    if not isinstance(expression, dict) or not expression:
        return expression
    operator, args = next(iter(expression.items()))
    if not operator.startswith("$"):
        return {key: _evaluate(value, doc, this) for key, value in expression.items()}
    if operator == "$map":
        return [_evaluate(args["in"], doc, item) for item in _evaluate(args["input"], doc, this)]
    if operator == "$filter":
        return [item for item in _evaluate(args["input"], doc, this) if _evaluate(args["cond"], doc, item)]
    value = _evaluate(args, doc, this)
    if operator == "$concatArrays":
        return [item for array in value for item in array]
    if operator == "$objectToArray":
        return [{"k": key, "v": item} for key, item in value.items()]
    if operator == "$ifNull":
        return value[0] if value[0] is not None else value[1]
    if operator == "$isNumber":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise NotImplementedError(operator)


def _group(docs: List[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The $group stage, with the $sum and $max accumulators"""
    groups: Dict[str, Any] = {}
    for doc in docs:
        key = _evaluate(spec["_id"], doc)
        groups.setdefault(json.dumps(key, sort_keys=True), (key, []))[1].append(doc)
    results = []
    for key, members in groups.values():
        result = {"_id": key}
        for field, accumulator in spec.items():
            if field == "_id":
                continue
            operator, expression = next(iter(accumulator.items()))
            values = [_evaluate(expression, doc) for doc in members]
            numbers = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
            result[field] = sum(numbers) if operator == "$sum" else max(numbers, default=None)
        results.append(result)
    return results


class _FakeCursor(list):
    """The documents a find or an aggregate returned"""

    def sort(self, keys):
        for key, order in reversed(keys):
            list.sort(self, key=lambda doc: (doc.get(key) is not None, doc.get(key)), reverse=order == -1)
        return self

    def batch_size(self, size):
        return self

    async def to_list(self, length=None):
        documents = self[:length]
        del self[:length]
        return documents


class _FakeCollection:
    """An in-memory collection with the calls the OS metrics methods make"""

    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None):
        self.docs: List[Dict[str, Any]] = docs or []

    def find(self, filter=None, projection=None):
        return _FakeCursor(copy.deepcopy([doc for doc in self.docs if _matches(doc, filter or {})]))

    def find_one(self, filter=None, projection=None, sort=None):
        cursor = self.find(filter).sort(sort or [])
        return cursor[0] if cursor else None

    def update_one(self, filter, update, upsert=False):
        doc = next((doc for doc in self.docs if _matches(doc, filter)), None)
        result = UpdateResult({"n": int(doc is not None)}, acknowledged=True)
        if doc is None:
            if not upsert:
                return result
            if "_id" in filter and any(stored.get("_id") == filter["_id"] for stored in self.docs):
                raise DuplicateKeyError("E11000 duplicate key error")
            doc = {"_id": ObjectId(), **{key: value for key, value in filter.items() if not key.startswith("$")}}
            doc.update(update.get("$setOnInsert", {}))
            self.docs.append(doc)
        doc.update(copy.deepcopy(update.get("$set", {})))
        for key, amount in update.get("$inc", {}).items():
            doc[key] = doc.get(key, 0) + amount
        for key in update.get("$unset", {}):
            doc.pop(key, None)
        return result

    def bulk_write(self, operations):
        for operation in operations:
            self.update_one(operation._filter, operation._doc, upsert=operation._upsert)

    def delete_many(self, filter):
        self.docs = [doc for doc in self.docs if not _matches(doc, filter)]

    def aggregate(self, pipeline):
        docs = copy.deepcopy(self.docs)
        for stage in pipeline:
            operator, spec = next(iter(stage.items()))
            if operator == "$match":
                docs = [doc for doc in docs if _matches(doc, spec)]
            elif operator == "$project":
                docs = [
                    {
                        key: doc.get(key) if value == 1 else _evaluate(value, doc)
                        for key, value in spec.items()
                        if value != 0
                    }
                    for doc in docs
                ]
            elif operator == "$unwind":
                docs = [{**doc, spec[1:]: item} for doc in docs for item in doc[spec[1:]]]
            elif operator == "$group":
                docs = _group(docs, spec)
            else:
                raise NotImplementedError(operator)
        return _FakeCursor(docs)


class _AsyncFakeCollection:
    """A _FakeCollection whose calls are awaited, but for the ones that return a cursor"""

    def __init__(self, collection: _FakeCollection):
        self.collection = collection

    def __getattr__(self, name):
        method = getattr(self.collection, name)
        if name in ["find", "aggregate"]:
            return method

        async def call(*args, **kwargs):
            return method(*args, **kwargs)

        return call


def _day_start(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())


def _run_document(run_id: str, user_id: Optional[str], created_at: int, status: RunStatus) -> Dict[str, Any]:
    """A run as upsert_run stores it, written at the start of its day so no update lands in the current second"""
    run = RunOutput(
        run_id=run_id,
        agent_id="researcher",
        user_id=user_id,
        status=status,
        model="gpt-5.6-luna",
        model_provider="OpenAI",
        created_at=created_at,
        metrics=RunMetrics(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            duration=2.0,
            time_to_first_token=0.5,
            details={"model": [ModelMetrics(id="gpt-5.6-luna", provider="OpenAI", input_tokens=100)]},
        ),
    )
    document = build_single_run_row(run=run, session_id=f"session-{run_id}", user_id=user_id, run_index=0)
    document["updated_at"] = created_at
    return document


def _collections() -> Dict[str, _FakeCollection]:
    """Today's sessions and runs: alice with two completed runs, and an errored run with no user"""
    today_start = _day_start(datetime.now(timezone.utc).date())
    sessions = [
        {
            "session_id": "session-alice",
            "session_type": "agent",
            "agent_id": "researcher",
            "user_id": "alice",
            "created_at": today_start,
            "updated_at": today_start,
        },
        {
            "session_id": "session-anonymous",
            "session_type": "agent",
            "agent_id": "researcher",
            "user_id": None,
            "created_at": today_start,
            "updated_at": today_start,
        },
    ]
    runs = [
        _run_document("run-1", "alice", today_start, RunStatus.completed),
        _run_document("run-2", "alice", today_start, RunStatus.completed),
        _run_document("run-3", None, today_start, RunStatus.error),
    ]
    return {
        "sessions": _FakeCollection(sessions),
        "runs": _FakeCollection(runs),
        "os_metrics": _FakeCollection(),
        "os_metrics_totals": _FakeCollection(),
    }


@pytest.fixture
def collections() -> Dict[str, _FakeCollection]:
    return _collections()


@pytest.fixture
def db(collections, monkeypatch: pytest.MonkeyPatch) -> MongoDb:
    mongo_db = MongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    monkeypatch.setattr(
        mongo_db,
        "_get_collection",
        lambda table_type, create_collection_if_not_found=False: collections[table_type],
    )
    return mongo_db


@pytest.fixture
def async_db(collections, monkeypatch: pytest.MonkeyPatch) -> AsyncMongoDb:
    async_collections = {name: _AsyncFakeCollection(collection) for name, collection in collections.items()}
    mongo_db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    monkeypatch.setattr(
        mongo_db,
        "_get_collection",
        AsyncMock(side_effect=lambda table_type, create_collection_if_not_found=False: async_collections[table_type]),
    )
    return mongo_db


def _totals_by_date(collections: Dict[str, _FakeCollection]) -> Dict[str, Dict[str, Any]]:
    return {doc["date"]: doc for doc in collections["os_metrics_totals"].docs if doc["aggregation_period"] == "daily"}


def test_calculate_os_metrics_writes_rows_and_a_totals_row_per_day(db, collections):
    """A rebuild writes one row per owner and component, and a totals row for every day, yesterday included"""
    db.calculate_os_metrics()

    today = datetime.now(timezone.utc).date()
    rows = sorted(
        [doc for doc in collections["os_metrics"].docs if "aggregation_period" in doc], key=lambda doc: doc["user_id"]
    )
    assert [(row["date"], row["user_id"], row["component_id"], row["runs_count"]) for row in rows] == [
        (today.isoformat(), "", "researcher", 1),
        (today.isoformat(), "alice", "researcher", 2),
    ]
    assert rows[1]["status_metrics"] == {"COMPLETED": 2}
    assert rows[1]["model_metrics"] == [{"model_id": "gpt-5.6-luna", "model_provider": "OpenAI", "count": 2}]

    totals = _totals_by_date(collections)
    assert set(totals) == {(today - timedelta(days=1)).isoformat(), today.isoformat()}
    assert totals[today.isoformat()]["runs_count"] == 3
    assert totals[today.isoformat()]["sessions_count"] == 2
    assert totals[today.isoformat()]["version"] == 1
    assert totals[today.isoformat()]["completed"] is False
    # A day without traffic gets a row of zeros, so it can complete
    assert totals[(today - timedelta(days=1)).isoformat()]["runs_count"] == 0


def test_rebuild_with_nothing_new_writes_nothing_and_a_change_moves_the_version(db, collections):
    """An unchanged day keeps its totals version; a new run rewrites the day and its version moves by one"""
    db.calculate_os_metrics()
    previous_updated_at, latest_updated_at, changed = db.refresh_os_metrics()
    assert changed is False
    assert previous_updated_at == latest_updated_at

    today = datetime.now(timezone.utc).date()
    collections["runs"].docs.append(_run_document("run-4", "alice", _day_start(today), RunStatus.cancelled))
    _, _, changed = db.refresh_os_metrics()

    assert changed is True
    totals = _totals_by_date(collections)
    assert totals[today.isoformat()]["version"] == 2
    assert totals[today.isoformat()]["runs_count"] == 4
    assert totals[(today - timedelta(days=1)).isoformat()]["version"] == 1


def test_rebuild_deletes_the_rows_a_day_no_longer_has(db, collections):
    """A row whose sessions and runs are gone is deleted when its day is rebuilt"""
    db.calculate_os_metrics()
    collections["sessions"].docs = [doc for doc in collections["sessions"].docs if doc["user_id"] == "alice"]
    collections["runs"].docs = [doc for doc in collections["runs"].docs if doc["user_id"] == "alice"]

    _, _, changed = db.refresh_os_metrics()

    assert changed is True
    rows = [doc for doc in collections["os_metrics"].docs if "aggregation_period" in doc]
    assert [(row["user_id"], row["runs_count"]) for row in rows] == [("alice", 2)]
    today = datetime.now(timezone.utc).date()
    assert _totals_by_date(collections)[today.isoformat()]["runs_count"] == 2


def test_runs_kept_in_the_legacy_runs_field_are_counted_once(db, collections):
    """A run not yet migrated out of a session's legacy runs field is counted; one also in the runs collection is not
    counted again"""
    today_start = _day_start(datetime.now(timezone.utc).date())
    legacy_run = copy.deepcopy(_run_document("run-legacy", "alice", today_start, RunStatus.completed)["run_data"])
    collections["sessions"].docs[0]["runs"] = [copy.deepcopy(collections["runs"].docs[0]["run_data"]), legacy_run]

    db.calculate_os_metrics()

    today = datetime.now(timezone.utc).date().isoformat()
    assert _totals_by_date(collections)[today]["runs_count"] == 4


def test_lazy_refresh_with_nothing_new_is_skipped(db):
    """The lazy refresh compares the fingerprint of the sessions and runs; an explicit one always rebuilds"""
    assert db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert db._os_metrics_fingerprint is not None

    assert db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert db._calculate_os_metrics(wait_for_rebuild=True) is not None


def test_lazy_refresh_skips_while_another_rebuild_holds_the_lock(db, collections):
    """A held lock skips the lazy refresh and resets the throttle; the read is then incomplete"""
    collections["os_metrics"].docs.append(
        {"_id": OS_METRICS_LOCK_ID, "locked_by": "another-rebuild", "locked_at": int(time.time())}
    )

    assert db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert db._os_metrics_refreshed_at == 0.0
    today = datetime.now(timezone.utc).date()
    assert db.get_os_metrics_versions(today, today) is None

    # A lock older than its expiry belongs to a rebuild that stopped, and is taken over
    collections["os_metrics"].docs[0]["locked_at"] = int(time.time()) - 3600
    assert db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert collections["os_metrics"].docs[0]["locked_by"] is None


def test_get_os_metrics_versions(db):
    """Every totals row of the date range, keyed by its aggregation period and date"""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    assert db.get_os_metrics_versions(yesterday, today) == {
        f"daily {yesterday.isoformat()}": 1,
        f"daily {today.isoformat()}": 1,
    }


def test_get_os_metrics_reads_every_owner_from_totals_and_one_owner_from_rows(db):
    """A read for everyone totals the totals rows, a read for one owner that owner's rows"""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    days, updated_at = db.get_os_metrics(yesterday, today, fields=["runs_count", "status_metrics", "max_duration_ms"])
    assert [(day["date"], day["runs_count"], day["status_metrics"]) for day in days] == [
        (yesterday, 0, {}),
        (today, 3, {"COMPLETED": 2, "ERROR": 1}),
    ]
    assert days[1]["max_duration_ms"] == 2000
    assert updated_at is not None

    days, _ = db.get_os_metrics(yesterday, today, user_id="alice", fields=["runs_count", "duration_buckets"])
    assert [(day["date"], day["runs_count"], day["duration_buckets"]) for day in days] == [(today, 2, {"le_2000": 2})]

    totals, _ = db.get_os_metrics_totals(yesterday, today, fields=["model_metrics", "total_tokens"])
    assert totals == {
        "model_metrics": [{"model_id": "gpt-5.6-luna", "model_provider": "OpenAI", "count": 3}],
        "total_tokens": 360,
    }


def _completed_month(collections: Dict[str, _FakeCollection]) -> date:
    """A completed month with a session of alice on each of its first two days, and no traffic on its last"""
    month_start = (datetime.now(timezone.utc).date().replace(day=1) - timedelta(days=40)).replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    for day in [month_start, month_start + timedelta(days=1), month_end]:
        sessions = [{"session_type": "agent", "agent_id": "researcher", "user_id": "alice"}] if day != month_end else []
        rows = calculate_date_os_metrics(day, sessions, [], set(), [])
        bulk_upsert_os_metrics(collections["os_metrics"], rows)
        upsert_os_metrics_totals_row(
            collections["os_metrics_totals"], build_os_metrics_totals_row(rows, "daily", day, completed=True)
        )
    return month_start


def test_month_rows_are_written_once_a_month_completes(db, collections, monkeypatch: pytest.MonkeyPatch):
    """A completed month gets one month row per owner and component, added up a batch of days at a time, and a
    completed month totals row last"""
    monkeypatch.setattr("agno.db.mongo.mongo.OS_METRICS_BATCH_SIZE", 1)
    month_start = _completed_month(collections)

    written = db._calculate_month_os_metrics(collections["os_metrics"], collections["os_metrics_totals"], True)

    assert [row["date"] for row in written] == [month_start]
    month_rows = [doc for doc in collections["os_metrics"].docs if doc.get("aggregation_period") == "monthly"]
    assert [(row["date"], row["user_id"], row["sessions_count"]) for row in month_rows] == [
        (month_start.isoformat(), "alice", 2)
    ]
    month_totals = [doc for doc in collections["os_metrics_totals"].docs if doc["aggregation_period"] == "monthly"]
    assert [(row["sessions_count"], row["completed"], row["version"]) for row in month_totals] == [(2, True, 1)]

    # Written once
    assert db._calculate_month_os_metrics(collections["os_metrics"], collections["os_metrics_totals"], True) == []


@pytest.mark.asyncio
async def test_async_calculate_and_read_os_metrics(async_db, collections):
    """The async class rebuilds and reads the same rows as the sync one"""
    await async_db.calculate_os_metrics()

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    totals = _totals_by_date(collections)
    assert set(totals) == {yesterday.isoformat(), today.isoformat()}
    assert totals[today.isoformat()]["runs_count"] == 3

    _, _, changed = await async_db.refresh_os_metrics()
    assert changed is False
    assert await async_db.get_os_metrics_versions(yesterday, today) == {
        f"daily {yesterday.isoformat()}": 1,
        f"daily {today.isoformat()}": 1,
    }

    days, _ = await async_db.get_os_metrics(yesterday, today, user_id="alice", fields=["runs_count"])
    assert [(day["date"], day["runs_count"]) for day in days] == [(today, 2)]
    totals_read, _ = await async_db.get_os_metrics_totals(yesterday, today, fields=["sessions_count"])
    assert totals_read == {"sessions_count": 2}


@pytest.mark.asyncio
async def test_async_month_rows_are_written_once_a_month_completes(
    async_db, collections, monkeypatch: pytest.MonkeyPatch
):
    """The async class adds up a completed month a batch of days at a time, as the sync one does"""
    monkeypatch.setattr("agno.db.mongo.async_mongo.OS_METRICS_BATCH_SIZE", 1)
    month_start = _completed_month(collections)
    os_metrics = await async_db._get_collection("os_metrics")
    os_metrics_totals = await async_db._get_collection("os_metrics_totals")

    written = await async_db._calculate_month_os_metrics(os_metrics, os_metrics_totals, True)

    assert [(row["date"], row["sessions_count"]) for row in written] == [(month_start, 2)]
    month_rows = [doc for doc in collections["os_metrics"].docs if doc.get("aggregation_period") == "monthly"]
    assert [(row["date"], row["user_id"], row["sessions_count"]) for row in month_rows] == [
        (month_start.isoformat(), "alice", 2)
    ]
