"""Unit tests for the OS Metrics related methods of the DynamoDb class"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

try:
    from agno.db.dynamo import DynamoDb
    from agno.db.dynamo.utils import OS_METRICS_STATE_ID, deserialize_os_metrics_record
except ImportError:
    DynamoDb = None  # type: ignore[misc,assignment]

from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

pytestmark = pytest.mark.skipif(DynamoDb is None, reason="boto3 not installed")


class _FakeClient:
    """An in-memory DynamoDB client with the calls an OS metrics rebuild and read make"""

    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

        class ConditionalCheckFailedException(Exception):
            pass

    def __init__(self):
        self.tables: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def _items(self, table_name: str) -> Dict[str, Dict[str, Any]]:
        return self.tables.setdefault(table_name, {})

    @staticmethod
    def _key(item: Dict[str, Any]) -> str:
        return next(item[name]["S"] for name in ("run_id", "session_id", "id") if name in item)

    @staticmethod
    def _value(attribute: Dict[str, str]) -> Any:
        return float(attribute["N"]) if "N" in attribute else attribute["S"]

    def describe_table(self, TableName: str) -> Dict[str, Any]:
        return {}

    def get_item(self, TableName: str, Key: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        item = self._items(TableName).get(self._key(Key))
        return {"Item": item} if item else {}

    def put_item(self, TableName: str, Item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        self._items(TableName)[self._key(Item)] = Item
        return {}

    def delete_item(self, TableName: str, Key: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        self._items(TableName).pop(self._key(Key), None)
        return {}

    def update_item(
        self,
        TableName: str,
        Key: Dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: Dict[str, Any],
        **kwargs,
    ):
        item = self._items(TableName).setdefault(self._key(Key), dict(Key))
        values = dict(ExpressionAttributeValues)
        marks = values.pop(":rebuilding", {}).get("SS", [])
        stored_marks = item.pop("rebuilding", {}).get("SS", [])
        if UpdateExpression.startswith("ADD"):
            item["rebuilding"] = {"SS": [*stored_marks, *marks]}
            return
        if [mark for mark in stored_marks if mark not in marks]:
            item["rebuilding"] = {"SS": [mark for mark in stored_marks if mark not in marks]}
        item.update({name[1:]: value for name, value in values.items()})

    def batch_get_item(self, RequestItems: Dict[str, Any]) -> Dict[str, Any]:
        responses = {}
        for table_name, request in RequestItems.items():
            items = [self._items(table_name).get(self._key(key)) for key in request["Keys"]]
            responses[table_name] = [item for item in items if item]
        return {"Responses": responses}

    def query(self, TableName: str, IndexName: str, KeyConditionExpression: str, **kwargs) -> Dict[str, Any]:
        # An index holds only the items that have its sort key, in the order of that key
        sort_key = IndexName.split("-")[1]
        items = [item for item in self._items(TableName).values() if sort_key in item]
        expression = f"{KeyConditionExpression} AND {kwargs.get('FilterExpression', '')}"
        values = kwargs["ExpressionAttributeValues"]
        for name, operator, first, last in re.findall(r"(#?\w+) (=|>|BETWEEN) (:\w+)(?: AND (:\w+))?", expression):
            name = kwargs.get("ExpressionAttributeNames", {}).get(name, name)
            low = self._value(values[first])
            high = self._value(values[last]) if last else low
            if operator == ">":
                items = [item for item in items if name in item and self._value(item[name]) > low]
            else:
                items = [item for item in items if name in item and low <= self._value(item[name]) <= high]
        items.sort(key=lambda item: self._value(item[sort_key]), reverse=not kwargs.get("ScanIndexForward", True))
        return {"Items": items[: kwargs.get("Limit")]}


@pytest.fixture
def dynamo_db() -> DynamoDb:
    """Create a DynamoDb on a fake client"""
    return DynamoDb(
        db_client=_FakeClient(),
        session_table="test_sessions",
        runs_table="test_runs",
        os_metrics_table="test_os_metrics",
    )


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _persist(db: DynamoDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table"""
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


def _all_rows(db: DynamoDb) -> List[Dict]:
    """Every OS metrics row stored, in the shape calculate_date_os_metrics writes, without the state record"""
    items = db.client.tables[db._get_table("os_metrics")].values()
    return [deserialize_os_metrics_record(item) for item in items if item["id"]["S"] != OS_METRICS_STATE_ID]


def _stored_rows(db: DynamoDb) -> Dict[tuple, Dict]:
    """Every OS metrics row of an owner in the table, keyed by (date, user_id)"""
    return {(row["date"], row["user_id"]): row for row in _all_rows(db) if row["aggregation_period"] == "daily"}


@pytest.fixture
def sample_sessions_for_os_metrics(dynamo_db: DynamoDb) -> List[AgentSession]:
    """Store one session each for alice and bob yesterday, and one for alice today"""
    sessions = [
        _session_on(_utc_date(1), "alice_session", "alice", input_tokens=10),
        _session_on(_utc_date(1), "bob_session", "bob", input_tokens=20),
        _session_on(_utc_date(0), "alice_today_session", "alice", input_tokens=30),
    ]
    for session in sessions:
        _persist(dynamo_db, session)
    return sessions


class TestOsMetrics:
    def test_calculate_os_metrics(self, dynamo_db: DynamoDb, sample_sessions_for_os_metrics):
        """Ensure a rebuild stores the rows of each day with the numbers of each owner"""
        assert dynamo_db.calculate_os_metrics()

        rows = _stored_rows(dynamo_db)
        assert {key: (row["sessions_count"], row["runs_count"]) for key, row in rows.items()} == {
            (_utc_date(1), "alice"): (1, 1),
            (_utc_date(1), "bob"): (1, 1),
            (_utc_date(0), "alice"): (1, 1),
        }
        alice_tokens = rows[(_utc_date(1), "alice")]["token_metrics"]
        assert alice_tokens == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        bob_tokens = rows[(_utc_date(1), "bob")]["token_metrics"]
        assert bob_tokens == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}

    def test_get_os_metrics_by_date(self, dynamo_db: DynamoDb, sample_sessions_for_os_metrics):
        """Ensure get_os_metrics totals the rows of each day, with only the fields asked for"""
        dynamo_db.calculate_os_metrics()
        yesterday, today = _utc_date(1), _utc_date(0)

        metrics, latest_updated_at = dynamo_db.get_os_metrics(starting_date=yesterday, ending_date=today)
        assert latest_updated_at is not None
        assert [m["date"] for m in metrics] == [yesterday, today]
        assert (metrics[0]["sessions_count"], metrics[0]["runs_count"]) == (2, 2)
        assert metrics[0]["token_metrics"] == {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}
        assert metrics[1]["token_metrics"] == {"input_tokens": 30, "output_tokens": 5, "total_tokens": 35}

        metrics, _ = dynamo_db.get_os_metrics(yesterday, yesterday, fields=["sessions_count", "runs_count"])
        assert metrics == [{"date": yesterday, "sessions_count": 2, "runs_count": 2}]

    def test_get_os_metrics_by_user(self, dynamo_db: DynamoDb, sample_sessions_for_os_metrics):
        """Ensure get_os_metrics totals only the rows of the given owner"""
        dynamo_db.calculate_os_metrics()

        metrics, _ = dynamo_db.get_os_metrics(starting_date=_utc_date(1), ending_date=_utc_date(0), user_id="bob")
        assert [m["date"] for m in metrics] == [_utc_date(1)]
        assert (metrics[0]["sessions_count"], metrics[0]["runs_count"]) == (1, 1)
        assert metrics[0]["token_metrics"] == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}

    def test_calculate_os_metrics_after_new_run(self, dynamo_db: DynamoDb, sample_sessions_for_os_metrics):
        """Ensure a rebuild with nothing new changes no row, and one after a new run changes the numbers"""
        dynamo_db.calculate_os_metrics()
        rows = _all_rows(dynamo_db)

        dynamo_db.calculate_os_metrics()
        assert _all_rows(dynamo_db) == rows

        run = _run_on(_utc_date(1), "alice_run_2", "alice", input_tokens=40)
        dynamo_db.upsert_run(run, session_id="alice_session", user_id="alice", run_index=1)
        dynamo_db.calculate_os_metrics()

        alice_row = _stored_rows(dynamo_db)[(_utc_date(1), "alice")]
        assert (alice_row["sessions_count"], alice_row["runs_count"]) == (1, 2)
        assert alice_row["token_metrics"] == {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}

    def test_refresh_os_metrics(self, dynamo_db: DynamoDb, sample_sessions_for_os_metrics):
        """Ensure refresh_os_metrics reports when the rows were updated before and after, and whether any changed"""
        previous_updated_at, updated_at, changed = dynamo_db.refresh_os_metrics()
        assert previous_updated_at is None
        assert updated_at is not None and changed is True

        assert dynamo_db.refresh_os_metrics() == (updated_at, updated_at, False)

    def test_get_os_metrics_state(self, dynamo_db: DynamoDb, sample_sessions_for_os_metrics, monkeypatch):
        """Ensure get_os_metrics_state returns when the rows were last written and the hash of the state"""
        dynamo_db.calculate_os_metrics()

        # A state the indexes may not have followed yet is not reported
        assert dynamo_db.get_os_metrics_state() == (None, "")

        monkeypatch.setattr("agno.db.dynamo.dynamo.OS_METRICS_INDEX_LAG_SECONDS", 0)
        updated_at, state_hash = dynamo_db.get_os_metrics_state()
        assert updated_at == max(row["updated_at"] for row in _all_rows(dynamo_db))
        assert state_hash
