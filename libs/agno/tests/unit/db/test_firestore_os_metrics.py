"""Unit tests for the OS Metrics related methods of the FirestoreDb class"""

from __future__ import annotations

import operator
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

try:
    from google.api_core.exceptions import AlreadyExists
    from google.cloud.firestore import FieldFilter, Increment

    from agno.db.firestore import FirestoreDb
    from agno.db.firestore.utils import bulk_upsert_os_metrics, deserialize_os_metrics_record, lock_os_metrics
except ImportError:
    FirestoreDb = None  # type: ignore[misc,assignment]

from agno.db.utils import (
    build_os_metrics_totals_row,
    calculate_date_os_metrics,
    os_metrics_month_end,
    os_metrics_nested_run_ids,
)
from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

pytestmark = pytest.mark.skipif(FirestoreDb is None, reason="google-cloud-firestore not installed")

_OPERATORS = {
    "==": operator.eq,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "in": lambda a, b: a in b,
}


class _FakeDocument:
    """A reference to one document of a collection."""

    def __init__(self, docs: Dict[str, Dict[str, Any]], doc_id: str):
        self.docs = docs
        self.id = doc_id

    def get(self, transaction=None) -> SimpleNamespace:
        data = self.docs.get(self.id)
        return SimpleNamespace(
            id=self.id,
            reference=self,
            exists=data is not None,
            to_dict=lambda: dict(data) if data is not None else None,
            update_time=None,
        )

    def create(self, data: Dict[str, Any]) -> None:
        if self.id in self.docs:
            raise AlreadyExists(self.id)
        self.docs[self.id] = dict(data)

    def set(self, data: Dict[str, Any], merge: Any = False) -> None:
        stored = dict(self.docs.get(self.id, {})) if merge else {}
        for key, value in data.items():
            stored[key] = stored.get(key, 0) + value.value if isinstance(value, Increment) else value
        self.docs[self.id] = stored

    def update(self, data: Dict[str, Any], option: Any = None) -> None:
        self.docs[self.id] = {**self.docs[self.id], **data}

    def delete(self, option: Any = None) -> None:
        self.docs.pop(self.id, None)


class _FakeQuery:
    """A collection, or the documents of it that pass the filters given so far."""

    def __init__(self, docs: Dict[str, Dict[str, Any]], filters=(), order=None, count: Optional[int] = None):
        self.docs = docs
        self.filters = filters
        self.order = order
        self.count_limit = count

    def document(self, doc_id: Optional[str] = None) -> _FakeDocument:
        return _FakeDocument(self.docs, doc_id or f"doc_{len(self.docs)}")

    def where(self, filter: FieldFilter) -> _FakeQuery:
        return _FakeQuery(self.docs, self.filters + (filter,), self.order, self.count_limit)

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> _FakeQuery:
        return _FakeQuery(self.docs, self.filters, (field_path, direction == "DESCENDING"), self.count_limit)

    def limit(self, count: int) -> _FakeQuery:
        return _FakeQuery(self.docs, self.filters, self.order, count)

    def select(self, field_paths: List[str]) -> _FakeQuery:
        return self

    def stream(self, transaction=None) -> List[SimpleNamespace]:
        docs = self.docs
        for f in self.filters:
            docs = {
                doc_id: doc
                for doc_id, doc in docs.items()
                if doc.get(f.field_path) is not None and _OPERATORS[f.op_string](doc[f.field_path], f.value)
            }
        doc_ids = list(docs)
        if self.order is not None:
            doc_ids = [doc_id for doc_id in doc_ids if docs[doc_id].get(self.order[0]) is not None]
            doc_ids.sort(key=lambda doc_id: docs[doc_id][self.order[0]], reverse=self.order[1])
        return [self.document(doc_id).get() for doc_id in doc_ids[: self.count_limit]]

    def count(self, alias: str) -> SimpleNamespace:
        docs = [doc.to_dict() for doc in self.stream()]

        def _sum(field_path: str, alias: str) -> SimpleNamespace:
            total = sum(doc.get(field_path) or 0 for doc in docs)
            results = [SimpleNamespace(alias="count", value=len(docs)), SimpleNamespace(alias=alias, value=total)]
            return SimpleNamespace(get=lambda: [results])

        return SimpleNamespace(sum=_sum)


class _FakeClient:
    """An in-memory Firestore client with the calls an OS metrics rebuild and read make."""

    def __init__(self):
        self.collections: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def collection(self, collection_name: str) -> _FakeQuery:
        collection = _FakeQuery(self.collections.setdefault(collection_name, {}))
        # A batch is taken from the client of the collection it writes to
        collection._client = self
        return collection

    def batch(self) -> SimpleNamespace:
        # Each write is stored as the batch is given it
        return SimpleNamespace(
            set=lambda reference, data, merge=False: reference.set(data, merge=merge),
            delete=lambda reference: reference.delete(),
            commit=lambda: None,
        )

    def transaction(self, read_only: bool = False) -> SimpleNamespace:
        return SimpleNamespace()

    def write_option(self, **kwargs: Any) -> None:
        return None

    def get_all(self, references: List[_FakeDocument], field_paths=None, transaction=None) -> List[SimpleNamespace]:
        return [reference.get() for reference in references]


@pytest.fixture
def firestore_db(monkeypatch) -> FirestoreDb:
    """Fixture returning a FirestoreDb on a fake client, without the index creation that goes to the Admin API"""
    monkeypatch.setattr("agno.db.firestore.firestore.create_collection_indexes", lambda *args, **kwargs: None)
    # The fake transaction reads as the queries are given, so the function runs once
    monkeypatch.setattr("agno.db.firestore.firestore.transactional", lambda function: function)
    return FirestoreDb(
        db_client=_FakeClient(),
        session_collection="test_sessions",
        runs_collection="test_runs",
        os_metrics_collection="test_os_metrics",
        os_metrics_totals_collection="test_os_metrics_totals",
    )


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _month_start(months_ago: int) -> date:
    """The first day of the calendar month ``months_ago`` months back."""
    month_start = datetime.now(timezone.utc).date().replace(day=1)
    for _ in range(months_ago):
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    return month_start


def _session_on(day: date, session_id: str, user_id: str, input_tokens: int = 10) -> AgentSession:
    """An agent session created at midday UTC of the given day, with one completed run."""
    created_at = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
    tokens = dict(input_tokens=input_tokens, output_tokens=5, total_tokens=input_tokens + 5)
    run = RunOutput(
        run_id=f"{session_id}_run",
        agent_id="agent-1",
        user_id=user_id,
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(**tokens, details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI", **tokens)]}),
        created_at=created_at,
    )
    return AgentSession(session_id=session_id, agent_id="agent-1", user_id=user_id, runs=[run], created_at=created_at)


def _persist(db: FirestoreDb, session: AgentSession) -> None:
    """Store a session the way v3 does: the document, then each run in the runs collection."""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _age_writes(db: FirestoreDb) -> None:
    """Move every session and run write a minute back, so no write shares the current second."""
    for collection_name in ["test_sessions", "test_runs"]:
        for doc in db.db_client.collections[collection_name].values():
            doc["updated_at"] = int(time.time()) - 60


def _stored_rows(db: FirestoreDb, collection_name: str) -> List[Dict[str, Any]]:
    """Every OS metrics row stored in the collection, with its day as a date."""
    docs = db.db_client.collections.get(collection_name, {})
    return [deserialize_os_metrics_record(doc) for doc in docs.values() if "aggregation_period" in doc]


@pytest.fixture
def sample_sessions_for_os_metrics(firestore_db: FirestoreDb) -> List[AgentSession]:
    """Fixture storing one session each for alice and bob yesterday, and one for alice today"""
    sessions = [
        _session_on(_utc_date(1), "alice_session", "alice", input_tokens=10),
        _session_on(_utc_date(1), "bob_session", "bob", input_tokens=20),
        _session_on(_utc_date(0), "alice_today_session", "alice", input_tokens=30),
    ]
    for session in sessions:
        _persist(firestore_db, session)
    return sessions


def test_calculate_os_metrics(firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild stores a row per day and owner, and a totals row per day at version 1"""
    assert firestore_db.calculate_os_metrics()

    rows = {(row["date"], row["user_id"]): row for row in _stored_rows(firestore_db, "test_os_metrics")}
    assert {key: (row["sessions_count"], row["runs_count"], row["input_tokens"]) for key, row in rows.items()} == {
        (_utc_date(1), "alice"): (1, 1, 10),
        (_utc_date(1), "bob"): (1, 1, 20),
        (_utc_date(0), "alice"): (1, 1, 30),
    }
    assert rows[(_utc_date(1), "bob")]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1}
    ]

    totals_rows = {row["date"]: row for row in _stored_rows(firestore_db, "test_os_metrics_totals")}
    assert set(totals_rows) == {_utc_date(1), _utc_date(0)}
    assert (totals_rows[_utc_date(1)]["sessions_count"], totals_rows[_utc_date(1)]["total_tokens"]) == (2, 40)
    assert {row["version"] for row in totals_rows.values()} == {1}
    assert not any(row["completed"] for row in totals_rows.values())


def test_calculate_os_metrics_moves_only_the_version_of_a_changed_day(
    firestore_db: FirestoreDb, sample_sessions_for_os_metrics
):
    """Ensure a rebuild with nothing new leaves every version, and a new run moves only its day's"""
    firestore_db.calculate_os_metrics()
    versions = firestore_db.get_os_metrics_versions(_utc_date(1), _utc_date(0))

    firestore_db.calculate_os_metrics()
    assert firestore_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == versions

    _persist(firestore_db, _session_on(_utc_date(1), "carol_session", "carol"))
    firestore_db.calculate_os_metrics()
    assert firestore_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == {
        f"daily {_utc_date(1).isoformat()}": 2,
        f"daily {_utc_date(0).isoformat()}": 1,
    }


def test_get_os_metrics_by_date(firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals each day for every owner, and only one owner's rows for that owner"""
    firestore_db.calculate_os_metrics()
    yesterday, today = _utc_date(1), _utc_date(0)

    metrics, latest_updated_at = firestore_db.get_os_metrics(
        starting_date=yesterday, ending_date=today, fields=["sessions_count", "total_tokens"]
    )
    assert latest_updated_at is not None
    assert metrics == [
        {"date": yesterday, "sessions_count": 2, "total_tokens": 40},
        {"date": today, "sessions_count": 1, "total_tokens": 35},
    ]

    metrics, _ = firestore_db.get_os_metrics(
        starting_date=yesterday, ending_date=today, user_id="bob", fields=["sessions_count", "total_tokens"]
    )
    assert metrics == [{"date": yesterday, "sessions_count": 1, "total_tokens": 25}]


def test_calculate_os_metrics_skips_a_refresh_with_nothing_new(firestore_db: FirestoreDb):
    """Ensure a refresh that does not wait skips the rebuild while no session or run changed, and runs after one did"""
    _persist(firestore_db, _session_on(_utc_date(0), "skipped_session", "alice"))
    _age_writes(firestore_db)

    assert firestore_db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert firestore_db._calculate_os_metrics(wait_for_rebuild=False) is None

    _persist(firestore_db, _session_on(_utc_date(0), "new_session", "alice"))
    _age_writes(firestore_db)
    assert firestore_db._calculate_os_metrics(wait_for_rebuild=False) is not None
    metrics, _ = firestore_db.get_os_metrics(_utc_date(0), _utc_date(0), fields=["sessions_count"])
    assert metrics == [{"date": _utc_date(0), "sessions_count": 2}]


def test_calculate_os_metrics_keeps_the_lock_through_a_day_longer_than_it(
    firestore_db: FirestoreDb, sample_sessions_for_os_metrics, monkeypatch
):
    """Ensure the lock is renewed between the reads of a day, so a day that reads for longer than the lock is
    written and another rebuild cannot take the lock meanwhile"""
    clock = [time.time()]
    monkeypatch.setattr("agno.db.firestore.utils.time", SimpleNamespace(time=lambda: clock[0], sleep=time.sleep))
    totals_collection_ref = firestore_db.db_client.collection("test_os_metrics_totals")
    taken_over: List[bool] = []

    def slow(function, take_over: bool = False):
        def call(*args):
            clock[0] += 40
            if take_over:
                taken_over.append(lock_os_metrics(totals_collection_ref, False) is not None)
            return function(*args)

        return call

    monkeypatch.setattr("agno.db.firestore.firestore.os_metrics_nested_run_ids", slow(os_metrics_nested_run_ids))
    monkeypatch.setattr(
        "agno.db.firestore.firestore.calculate_date_os_metrics", slow(calculate_date_os_metrics, take_over=True)
    )

    firestore_db.calculate_os_metrics()

    assert taken_over == [False, False]
    assert {row["date"] for row in _stored_rows(firestore_db, "test_os_metrics_totals")} == {_utc_date(1), _utc_date(0)}


def test_bulk_upsert_os_metrics_stops_between_commits_once_the_lock_is_lost(firestore_db: FirestoreDb):
    """Ensure a write of more than one commit renews the lock between commits, and stops before the totals row once
    the lock is lost"""
    sessions = [{"session_type": "agent", "agent_id": "agent-1", "user_id": f"user-{i}"} for i in range(600)]
    rows = calculate_date_os_metrics(_utc_date(0), sessions, [], set(), [])

    # No lock document holds the token, as when another process took the lock
    assert not bulk_upsert_os_metrics(
        firestore_db.db_client.collection("test_os_metrics"),
        rows,
        totals_collection_ref=firestore_db.db_client.collection("test_os_metrics_totals"),
        totals_row=build_os_metrics_totals_row(rows, "daily", _utc_date(0), False),
        lock_token="lost-token",
    )
    assert _stored_rows(firestore_db, "test_os_metrics_totals") == []


def test_get_os_metrics_versions_is_none_while_today_is_unbuilt(firestore_db: FirestoreDb):
    """Ensure a database with sessions today and no total row for today has no versions, so a read skips it"""
    _persist(firestore_db, _session_on(_utc_date(0), "unbuilt_session", "alice"))
    firestore_db.calculate_os_metrics()
    firestore_db.db_client.collections["test_os_metrics_totals"].pop(f"{_utc_date(0).isoformat()}_daily")

    # Inside the refresh throttle, as between a refresh and the rebuild of today
    firestore_db._os_metrics_refreshed_at = time.time()
    assert firestore_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is None

    firestore_db._os_metrics_refreshed_at = 0.0
    assert f"daily {_utc_date(0).isoformat()}" in firestore_db.get_os_metrics_versions(_utc_date(1), _utc_date(0))


def test_calculate_os_metrics_writes_month_rows_for_a_completed_month(firestore_db: FirestoreDb):
    """Ensure a completed month gets a row per owner and a total row, and its total is read from them"""
    month_start = _month_start(2)
    _persist(firestore_db, _session_on(month_start, "alice_session", "alice", input_tokens=10))
    _persist(firestore_db, _session_on(month_start + timedelta(days=3), "bob_session", "bob", input_tokens=20))
    firestore_db.calculate_os_metrics()

    month_rows = {
        row["user_id"]: row
        for row in _stored_rows(firestore_db, "test_os_metrics")
        if row["aggregation_period"] == "monthly" and row["date"] == month_start
    }
    assert {user_id: row["sessions_count"] for user_id, row in month_rows.items()} == {"alice": 1, "bob": 1}
    month_totals_row = next(
        row
        for row in _stored_rows(firestore_db, "test_os_metrics_totals")
        if row["aggregation_period"] == "monthly" and row["date"] == month_start
    )
    assert (month_totals_row["sessions_count"], month_totals_row["completed"]) == (2, True)

    # Without its daily total rows, the month is still read whole from its month rows
    totals_docs = firestore_db.db_client.collections["test_os_metrics_totals"]
    for doc_id in [doc_id for doc_id, doc in totals_docs.items() if doc.get("aggregation_period") == "daily"]:
        totals_docs.pop(doc_id)
    firestore_db._os_metrics_refreshed_at = time.time()
    totals, _ = firestore_db.get_os_metrics_totals(
        month_start, os_metrics_month_end(month_start), fields=["sessions_count", "total_tokens"]
    )
    assert totals == {"sessions_count": 2, "total_tokens": 40}
    totals, _ = firestore_db.get_os_metrics_totals(
        month_start, os_metrics_month_end(month_start), user_id="bob", fields=["sessions_count"]
    )
    assert totals == {"sessions_count": 1}
