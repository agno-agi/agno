"""Unit tests for the OS Metrics related methods of the MongoDb and AsyncMongoDb classes"""

import copy
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, Mock

import pytest

from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

_MATCH_OPERATORS = {
    "$eq": lambda value, arg: value == arg,
    "$ne": lambda value, arg: value != arg,
    "$in": lambda value, arg: value in arg,
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


def _matches(doc: Dict, query: Dict) -> bool:
    """Whether a document matches a query of equalities, comparison operators and $or"""
    for field, condition in query.items():
        if field == "$or":
            if not any(_matches(doc, option) for option in condition):
                return False
            continue
        if not (isinstance(condition, dict) and all(key.startswith("$") for key in condition)):
            condition = {"$eq": condition}
        if not all(_MATCH_OPERATORS[operator](_get(doc, field), arg) for operator, arg in condition.items()):
            return False
    return True


def _evaluate(expression: Any, doc: Dict) -> Any:
    """The value of an aggregation expression for a document"""
    if isinstance(expression, str) and expression.startswith("$"):
        return _get(doc, expression[1:])
    if not isinstance(expression, dict):
        return expression
    operator, args = next(iter(expression.items()))
    if not operator.startswith("$"):
        return {key: _evaluate(value, doc) for key, value in expression.items()}
    values = [_evaluate(arg, doc) for arg in args] if isinstance(args, list) else [_evaluate(args, doc)]
    return {
        "$ifNull": lambda: values[0] if values[0] is not None else values[1],
        "$cond": lambda: values[1] if values[0] else values[2],
        "$eq": lambda: values[0] == values[1],
        "$gt": lambda: values[0] is not None and (values[1] is None or values[0] > values[1]),
        "$divide": lambda: values[0] / values[1],
        "$floor": lambda: int(values[0] // 1),
    }[operator]()


def _group(docs: List[Dict], spec: Dict) -> List[Dict]:
    """The $group stage, with the $sum and $max accumulators"""
    groups: Dict[str, Tuple[Any, List[Dict]]] = {}
    for doc in docs:
        key = _evaluate(spec["_id"], doc)
        groups.setdefault(json.dumps(key, sort_keys=True), (key, []))[1].append(doc)
    results = []
    for key, members in groups.values():
        result = {"_id": key}
        for field, accumulator in spec.items():
            if field != "_id":
                operator, expression = next(iter(accumulator.items()))
                values = [value for value in (_evaluate(expression, doc) for doc in members) if value is not None]
                result[field] = sum(values) if operator == "$sum" else max(values, default=None)
        results.append(result)
    return results


class _FakeCursor(list):
    """The documents a find or an aggregate returned"""

    def sort(self, keys, direction=None):
        for key, order in reversed([(keys, direction)] if isinstance(keys, str) else list(keys)):
            list.sort(self, key=lambda doc: (doc.get(key) is not None, doc.get(key)), reverse=order == -1)
        return self

    def limit(self, count):
        return _FakeCursor(self[:count])

    async def to_list(self, length=None):
        return list(self)

    async def __aiter__(self):
        for doc in list(self):
            yield doc


class _FakeCollection:
    """An in-memory collection with the calls the OS metrics methods make"""

    def __init__(self):
        self.docs: List[Dict] = []

    def find(self, filter=None, projection=None):
        return _FakeCursor(copy.deepcopy([doc for doc in self.docs if _matches(doc, filter or {})]))

    def find_one(self, filter=None, projection=None, sort=None):
        cursor = self.find(filter).sort(sort or [])
        return cursor[0] if cursor else None

    def count_documents(self, filter):
        return len(self.find(filter))

    def estimated_document_count(self):
        return len(self.docs)

    def distinct(self, field, filter=None):
        return sorted({doc[field] for doc in self.find(filter)})

    def aggregate(self, pipeline):
        docs = copy.deepcopy(self.docs)
        for stage in pipeline:
            operator, spec = next(iter(stage.items()))
            if operator == "$match":
                docs = [doc for doc in docs if _matches(doc, spec)]
            elif operator == "$addFields":
                docs = [{**doc, **{key: _evaluate(value, doc) for key, value in spec.items()}} for doc in docs]
            elif operator == "$group":
                docs = _group(docs, spec)
            elif operator != "$project":
                raise NotImplementedError(operator)
        return _FakeCursor(docs)

    def update_many(self, filter, update, upsert=False, limit=None):
        matched = [doc for doc in self.docs if _matches(doc, filter)][:limit]
        if not matched and upsert:
            matched = [{**filter, **update.get("$setOnInsert", {})}]
            self.docs.extend(matched)
        for doc in matched:
            doc.update(update.get("$set", {}))

    def update_one(self, filter, update, upsert=False):
        self.update_many(filter, update, upsert=upsert, limit=1)

    def bulk_write(self, operations):
        for operation in operations:
            self.update_one(operation._filter, operation._doc, upsert=operation._upsert)

    def delete_many(self, filter):
        self.docs = [doc for doc in self.docs if not _matches(doc, filter)]

    def replace_one(self, filter, replacement, upsert=False):
        self.delete_many(filter)
        self.docs.append(copy.deepcopy(replacement))

    def find_one_and_replace(self, filter, replacement, **kwargs):
        self.replace_one(filter, replacement)
        return copy.deepcopy(replacement)


class _AsyncFakeCollection:
    """A _FakeCollection whose calls are awaited, but for the ones that return a cursor"""

    def __init__(self):
        self.collection = _FakeCollection()

    def __getattr__(self, name):
        method = getattr(self.collection, name)
        if name in ["find", "aggregate"]:
            return method

        async def call(*args, **kwargs):
            return method(*args, **kwargs)

        return call


TOKEN_FIELDS = ["sessions_count", "runs_count", "token_metrics"]


@pytest.fixture
def mongo_db() -> MongoDb:
    """Fixture returning a MongoDb whose collections are in memory"""
    db = MongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collections: Dict[str, _FakeCollection] = defaultdict(_FakeCollection)
    db._get_collection = Mock(side_effect=lambda table_type, *args, **kwargs: collections[table_type])
    return db


@pytest.fixture
def async_mongo_db() -> AsyncMongoDb:
    """Fixture returning an AsyncMongoDb whose collections are in memory"""
    db = AsyncMongoDb(db_url="mongodb://localhost:27017", db_name="test_db")
    collections: Dict[str, _AsyncFakeCollection] = defaultdict(_AsyncFakeCollection)
    db._get_collection = AsyncMock(side_effect=lambda table_type, *args, **kwargs: collections[table_type])
    return db


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back"""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _run_metrics(input_tokens: int, output_tokens: int) -> RunMetrics:
    """The metrics a finished run carries: tokens and the model that served it"""
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        details={
            "model": [
                ModelMetrics(
                    id="gpt-5",
                    provider="OpenAI",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                )
            ]
        },
    )


def _run(run_id: str, user_id: str, input_tokens: int, output_tokens: int) -> RunOutput:
    """A completed run of agent-1, created two days back"""
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        user_id=user_id,
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(input_tokens, output_tokens),
        created_at=_noon_utc(2),
    )


@pytest.fixture
def sample_sessions_for_os_metrics() -> List[AgentSession]:
    """Fixture returning the sessions of one past day: one of alice with two runs, one of bob with one run"""
    base_time = _noon_utc(2)
    return [
        AgentSession(
            session_id="alice_agent_session",
            agent_id="agent-1",
            user_id="alice",
            runs=[_run("alice_run_1", "alice", 100, 50), _run("alice_run_2", "alice", 10, 5)],
            created_at=base_time,
            updated_at=base_time,
        ),
        AgentSession(
            session_id="bob_agent_session",
            agent_id="agent-1",
            user_id="bob",
            runs=[_run("bob_run_1", "bob", 200, 100)],
            created_at=base_time,
            updated_at=base_time,
        ),
    ]


def _persist(db: MongoDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table"""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


async def _apersist(db: AsyncMongoDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table"""
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _stored_rows(db: MongoDb) -> Dict[str, Dict]:
    """Every OS metrics row of two days back in the collection, keyed by its user_id"""
    docs = db._get_collection("os_metrics").find({"aggregation_period": "daily", "date": _utc_date(2).isoformat()})
    return {doc["user_id"]: doc for doc in docs}


async def _astored_rows(db: AsyncMongoDb) -> Dict[str, Dict]:
    """Every OS metrics row of two days back in the collection, keyed by its user_id"""
    collection = await db._get_collection("os_metrics")
    docs = collection.find({"aggregation_period": "daily", "date": _utc_date(2).isoformat()})
    return {doc["user_id"]: doc for doc in docs}


def test_calculate_os_metrics(mongo_db: MongoDb, sample_sessions_for_os_metrics):
    """Test that a rebuild stores the sessions, runs and tokens of each owner"""
    for session in sample_sessions_for_os_metrics:
        _persist(mongo_db, session)

    mongo_db.calculate_os_metrics()

    rows = _stored_rows(mongo_db)
    assert set(rows) == {"alice", "bob"}
    assert (rows["alice"]["sessions_count"], rows["alice"]["runs_count"]) == (1, 2)
    assert rows["alice"]["token_metrics"]["input_tokens"] == 110
    assert rows["alice"]["token_metrics"]["output_tokens"] == 55
    assert rows["alice"]["token_metrics"]["total_tokens"] == 165
    assert (rows["bob"]["sessions_count"], rows["bob"]["runs_count"]) == (1, 1)
    assert rows["bob"]["token_metrics"]["total_tokens"] == 300


def test_get_os_metrics_by_date(mongo_db: MongoDb, sample_sessions_for_os_metrics):
    """Test that a read returns the totals of each day in the date range, with only the fields asked for"""
    for session in sample_sessions_for_os_metrics:
        _persist(mongo_db, session)
    mongo_db.calculate_os_metrics()

    totals, latest_updated_at = mongo_db.get_os_metrics(_utc_date(3), _utc_date(0), fields=TOKEN_FIELDS)

    assert [day["date"] for day in totals] == [_utc_date(2)]
    assert set(totals[0]) == {"date", *TOKEN_FIELDS}
    assert (totals[0]["sessions_count"], totals[0]["runs_count"]) == (2, 3)
    assert totals[0]["token_metrics"]["total_tokens"] == 465
    assert latest_updated_at is not None


def test_get_os_metrics_by_user(mongo_db: MongoDb, sample_sessions_for_os_metrics):
    """Test that a read for one user returns only that user's numbers"""
    for session in sample_sessions_for_os_metrics:
        _persist(mongo_db, session)
    mongo_db.calculate_os_metrics()

    totals, _ = mongo_db.get_os_metrics(_utc_date(3), _utc_date(0), user_id="bob", fields=TOKEN_FIELDS)

    assert len(totals) == 1
    assert (totals[0]["sessions_count"], totals[0]["runs_count"]) == (1, 1)
    assert totals[0]["token_metrics"]["total_tokens"] == 300


def test_refresh_os_metrics(mongo_db: MongoDb, sample_sessions_for_os_metrics):
    """Test that a refresh reports the updated_at before and after it, and whether any record changed"""
    for session in sample_sessions_for_os_metrics:
        _persist(mongo_db, session)

    previous_updated_at, latest_updated_at, changed = mongo_db.refresh_os_metrics()

    assert previous_updated_at is None
    assert latest_updated_at is not None
    assert changed is True

    assert mongo_db.refresh_os_metrics() == (latest_updated_at, latest_updated_at, False)


def test_calculate_os_metrics_rebuilds_a_day_written_part_way(mongo_db: MongoDb, sample_sessions_for_os_metrics):
    """Test that a completed day left without its total record is calculated again"""
    for session in sample_sessions_for_os_metrics:
        _persist(mongo_db, session)
    mongo_db.calculate_os_metrics()

    # A write that failed after the daily records leaves them completed, without the total record
    collection = mongo_db._get_collection("os_metrics")
    collection.docs = [doc for doc in collection.docs if doc["aggregation_period"] == "daily"]
    mongo_db.calculate_os_metrics()

    assert collection.count_documents({"aggregation_period": "daily_total", "user_id": ""}) == 1


def test_get_os_metrics_state(mongo_db: MongoDb, sample_sessions_for_os_metrics):
    """Test that the state is when the records were last written and the hash of the state"""
    for session in sample_sessions_for_os_metrics:
        _persist(mongo_db, session)
    _, latest_updated_at, _ = mongo_db.refresh_os_metrics()

    updated_at, state_hash = mongo_db.get_os_metrics_state()
    assert updated_at == latest_updated_at
    assert state_hash


@pytest.mark.asyncio
async def test_async_calculate_os_metrics(async_mongo_db: AsyncMongoDb, sample_sessions_for_os_metrics):
    """Test that a rebuild stores the sessions, runs and tokens of each owner"""
    for session in sample_sessions_for_os_metrics:
        await _apersist(async_mongo_db, session)

    await async_mongo_db.calculate_os_metrics()

    rows = await _astored_rows(async_mongo_db)
    assert set(rows) == {"alice", "bob"}
    assert (rows["alice"]["sessions_count"], rows["alice"]["runs_count"]) == (1, 2)
    assert rows["alice"]["token_metrics"]["input_tokens"] == 110
    assert rows["alice"]["token_metrics"]["output_tokens"] == 55
    assert rows["alice"]["token_metrics"]["total_tokens"] == 165
    assert (rows["bob"]["sessions_count"], rows["bob"]["runs_count"]) == (1, 1)
    assert rows["bob"]["token_metrics"]["total_tokens"] == 300


@pytest.mark.asyncio
async def test_async_get_os_metrics_by_date(async_mongo_db: AsyncMongoDb, sample_sessions_for_os_metrics):
    """Test that a read returns the totals of each day in the date range, with only the fields asked for"""
    for session in sample_sessions_for_os_metrics:
        await _apersist(async_mongo_db, session)
    await async_mongo_db.calculate_os_metrics()

    totals, latest_updated_at = await async_mongo_db.get_os_metrics(_utc_date(3), _utc_date(0), fields=TOKEN_FIELDS)

    assert [day["date"] for day in totals] == [_utc_date(2)]
    assert set(totals[0]) == {"date", *TOKEN_FIELDS}
    assert (totals[0]["sessions_count"], totals[0]["runs_count"]) == (2, 3)
    assert totals[0]["token_metrics"]["total_tokens"] == 465
    assert latest_updated_at is not None


@pytest.mark.asyncio
async def test_async_get_os_metrics_by_user(async_mongo_db: AsyncMongoDb, sample_sessions_for_os_metrics):
    """Test that a read for one user returns only that user's numbers"""
    for session in sample_sessions_for_os_metrics:
        await _apersist(async_mongo_db, session)
    await async_mongo_db.calculate_os_metrics()

    totals, _ = await async_mongo_db.get_os_metrics(_utc_date(3), _utc_date(0), user_id="bob", fields=TOKEN_FIELDS)

    assert len(totals) == 1
    assert (totals[0]["sessions_count"], totals[0]["runs_count"]) == (1, 1)
    assert totals[0]["token_metrics"]["total_tokens"] == 300


@pytest.mark.asyncio
async def test_async_refresh_os_metrics(async_mongo_db: AsyncMongoDb, sample_sessions_for_os_metrics):
    """Test that a refresh reports the updated_at before and after it, and whether any record changed"""
    for session in sample_sessions_for_os_metrics:
        await _apersist(async_mongo_db, session)

    previous_updated_at, latest_updated_at, changed = await async_mongo_db.refresh_os_metrics()

    assert previous_updated_at is None
    assert latest_updated_at is not None
    assert changed is True

    assert await async_mongo_db.refresh_os_metrics() == (latest_updated_at, latest_updated_at, False)


@pytest.mark.asyncio
async def test_async_get_os_metrics_state(async_mongo_db: AsyncMongoDb, sample_sessions_for_os_metrics):
    """Test that the state is when the records were last written and the hash of the state"""
    for session in sample_sessions_for_os_metrics:
        await _apersist(async_mongo_db, session)
    _, latest_updated_at, _ = await async_mongo_db.refresh_os_metrics()

    updated_at, state_hash = await async_mongo_db.get_os_metrics_state()
    assert updated_at == latest_updated_at
    assert state_hash
