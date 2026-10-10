"""Unit tests for the OS Metrics related methods of the FirestoreDb class"""

from __future__ import annotations

import operator
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

try:
    from google.cloud.firestore import FieldFilter, Increment

    from agno.db.firestore import FirestoreDb
    from agno.db.firestore.utils import OS_METRICS_STATE_ID, deserialize_os_metrics_record
except ImportError:
    FirestoreDb = None  # type: ignore[misc,assignment]

from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

pytestmark = pytest.mark.skipif(FirestoreDb is None, reason="google-cloud-firestore not installed")

_OPERATORS = {"==": operator.eq, ">=": operator.ge, "<=": operator.le, "<": operator.lt, "in": lambda a, b: a in b}


class _FakeDocument:
    """A reference to one document of a collection"""

    def __init__(self, docs: Dict[str, Dict[str, Any]], doc_id: str):
        self.docs = docs
        self.id = doc_id

    def get(self) -> SimpleNamespace:
        data = self.docs.get(self.id)
        to_dict = lambda: dict(data) if data is not None else None  # noqa: E731
        return SimpleNamespace(id=self.id, reference=self, exists=data is not None, to_dict=to_dict)

    def set(self, data: Dict[str, Any], merge: bool = False) -> None:
        stored = dict(self.docs.get(self.id, {})) if merge else {}
        for key, value in data.items():
            stored[key] = stored.get(key, 0) + value.value if isinstance(value, Increment) else value
        self.docs[self.id] = stored


class _FakeQuery:
    """A collection, or the documents of it that pass the filters given so far"""

    def __init__(self, docs: Dict[str, Dict[str, Any]], filters=(), order=None, count: Optional[int] = None):
        self.docs, self.filters, self.order, self.count = docs, filters, order, count

    def document(self, doc_id: Optional[str] = None) -> _FakeDocument:
        return _FakeDocument(self.docs, doc_id or f"doc_{len(self.docs)}")

    def where(self, filter: FieldFilter) -> _FakeQuery:
        return _FakeQuery(self.docs, (*self.filters, filter), self.order, self.count)

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> _FakeQuery:
        return _FakeQuery(self.docs, self.filters, (field_path, direction == "DESCENDING"), self.count)

    def limit(self, count: int) -> _FakeQuery:
        return _FakeQuery(self.docs, self.filters, self.order, count)

    def select(self, field_paths: List[str]) -> _FakeQuery:
        return self

    def stream(self) -> List[SimpleNamespace]:
        docs = self.docs
        for f in self.filters:
            docs = {
                doc_id: doc
                for doc_id, doc in docs.items()
                if doc.get(f.field_path) is not None and _OPERATORS[f.op_string](doc[f.field_path], f.value)
            }
        doc_ids = list(docs)
        if self.order is not None:
            doc_ids.sort(key=lambda doc_id: docs[doc_id][self.order[0]], reverse=self.order[1])
        return [self.document(doc_id).get() for doc_id in doc_ids[: self.count]]


class _FakeClient:
    """An in-memory Firestore client with the calls an OS metrics rebuild and read make"""

    def __init__(self):
        self.collections: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def collection(self, collection_name: str) -> _FakeQuery:
        return _FakeQuery(self.collections.setdefault(collection_name, {}))

    def batch(self) -> SimpleNamespace:
        # Each write is stored as the batch is given it
        return SimpleNamespace(
            create=lambda reference, data: reference.set(data),
            update=lambda reference, data: reference.set(data, merge=True),
            set=lambda reference, data, merge=False: reference.set(data, merge=merge),
            commit=lambda: None,
        )

    def get_all(self, references: List[_FakeDocument]) -> List[SimpleNamespace]:
        return [reference.get() for reference in references]


@pytest.fixture
def firestore_db(monkeypatch) -> FirestoreDb:
    """Create a FirestoreDb on a fake client, without the index creation that goes to the Admin API"""
    monkeypatch.setattr("agno.db.firestore.firestore.create_collection_indexes", lambda *args, **kwargs: None)
    return FirestoreDb(
        db_client=_FakeClient(),
        session_collection="test_sessions",
        runs_collection="test_runs",
        os_metrics_collection="test_os_metrics",
    )


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _persist(db: FirestoreDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs collection"""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _run_on(day: date, run_id: str, user_id: str, input_tokens: int) -> RunOutput:
    """A completed run created at midday UTC of the given day, with 5 output tokens"""
    tokens = dict(input_tokens=input_tokens, output_tokens=5, total_tokens=input_tokens + 5)
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        user_id=user_id,
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(**tokens, details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI", **tokens)]}),
        created_at=int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp()),
    )


def _session_on(day: date, session_id: str, user_id: str, input_tokens: int = 10) -> AgentSession:
    """An agent session created at midday UTC of the given day, with one completed run"""
    run = _run_on(day, f"{session_id}_run", user_id, input_tokens)
    return AgentSession(
        session_id=session_id,
        agent_id="agent-1",
        user_id=user_id,
        runs=[run],
        created_at=run.created_at,
    )


def _all_rows(db: FirestoreDb) -> List[Dict]:
    """Every OS metrics row stored, in the shape calculate_date_os_metrics writes, without the state document"""
    docs = db._get_collection(table_type="os_metrics").stream()
    return [deserialize_os_metrics_record(doc.to_dict()) for doc in docs if doc.id != OS_METRICS_STATE_ID]


def _stored_rows(db: FirestoreDb) -> Dict[tuple, Dict]:
    """Every OS metrics row of an owner in the collection, keyed by (date, user_id)"""
    return {(row["date"], row["user_id"]): row for row in _all_rows(db) if row["aggregation_period"] == "daily"}


@pytest.fixture
def sample_sessions_for_os_metrics(firestore_db: FirestoreDb) -> List[AgentSession]:
    """Store one session each for alice and bob yesterday, and one for alice today"""
    sessions = [
        _session_on(_utc_date(1), "alice_session", "alice", input_tokens=10),
        _session_on(_utc_date(1), "bob_session", "bob", input_tokens=20),
        _session_on(_utc_date(0), "alice_today_session", "alice", input_tokens=30),
    ]
    for session in sessions:
        _persist(firestore_db, session)
    return sessions


class TestOsMetrics:
    def test_calculate_os_metrics(self, firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
        """Ensure a rebuild stores the rows of each day with the numbers of each owner"""
        assert firestore_db.calculate_os_metrics()

        rows = _stored_rows(firestore_db)
        assert {key: (row["sessions_count"], row["runs_count"]) for key, row in rows.items()} == {
            (_utc_date(1), "alice"): (1, 1),
            (_utc_date(1), "bob"): (1, 1),
            (_utc_date(0), "alice"): (1, 1),
        }
        alice_tokens = rows[(_utc_date(1), "alice")]["token_metrics"]
        assert alice_tokens == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        bob_tokens = rows[(_utc_date(1), "bob")]["token_metrics"]
        assert bob_tokens == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}

    def test_get_os_metrics_by_date(self, firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
        """Ensure get_os_metrics totals the rows of each day, with only the fields asked for"""
        firestore_db.calculate_os_metrics()
        yesterday, today = _utc_date(1), _utc_date(0)

        metrics, latest_updated_at = firestore_db.get_os_metrics(starting_date=yesterday, ending_date=today)
        assert latest_updated_at is not None
        assert [m["date"] for m in metrics] == [yesterday, today]
        assert (metrics[0]["sessions_count"], metrics[0]["runs_count"]) == (2, 2)
        assert metrics[0]["token_metrics"] == {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}
        assert metrics[1]["token_metrics"] == {"input_tokens": 30, "output_tokens": 5, "total_tokens": 35}

        metrics, _ = firestore_db.get_os_metrics(yesterday, yesterday, fields=["sessions_count", "runs_count"])
        assert metrics == [{"date": yesterday, "sessions_count": 2, "runs_count": 2}]

    def test_get_os_metrics_by_user(self, firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
        """Ensure get_os_metrics totals only the rows of the given owner"""
        firestore_db.calculate_os_metrics()

        metrics, _ = firestore_db.get_os_metrics(starting_date=_utc_date(1), ending_date=_utc_date(0), user_id="bob")
        assert [m["date"] for m in metrics] == [_utc_date(1)]
        assert (metrics[0]["sessions_count"], metrics[0]["runs_count"]) == (1, 1)
        assert metrics[0]["token_metrics"] == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}

    def test_calculate_os_metrics_after_new_run(self, firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
        """Ensure a rebuild with nothing new changes no row, and one after a new run changes the numbers"""
        firestore_db.calculate_os_metrics()
        rows = _all_rows(firestore_db)

        firestore_db.calculate_os_metrics()
        assert _all_rows(firestore_db) == rows

        run = _run_on(_utc_date(1), "alice_run_2", "alice", input_tokens=40)
        firestore_db.upsert_run(run, session_id="alice_session", user_id="alice", run_index=1)
        firestore_db.calculate_os_metrics()

        alice_row = _stored_rows(firestore_db)[(_utc_date(1), "alice")]
        assert (alice_row["sessions_count"], alice_row["runs_count"]) == (1, 2)
        assert alice_row["token_metrics"] == {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}

    def test_refresh_os_metrics(self, firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
        """Ensure refresh_os_metrics reports when the rows were updated before and after, and whether any changed"""
        previous_updated_at, updated_at, changed = firestore_db.refresh_os_metrics()
        assert previous_updated_at is None
        assert updated_at is not None and changed is True

        assert firestore_db.refresh_os_metrics() == (updated_at, updated_at, False)

    def test_get_os_metrics_state(self, firestore_db: FirestoreDb, sample_sessions_for_os_metrics):
        """Ensure get_os_metrics_state returns when the rows were last written and the hash of the state"""
        firestore_db.calculate_os_metrics()

        updated_at, state_hash = firestore_db.get_os_metrics_state()
        assert updated_at == max(row["updated_at"] for row in _all_rows(firestore_db))
        assert state_hash
