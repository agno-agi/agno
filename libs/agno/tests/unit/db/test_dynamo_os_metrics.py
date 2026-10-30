"""Tests for the OS metrics methods of DynamoDb.

Uses an in-memory stub for the DynamoDB low-level client, which keeps items by their key and evaluates the key
conditions, filters, conditions and updates the OS metrics rebuild and reads send, so no real AWS account is needed.
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

try:
    from agno.db.dynamo import DynamoDb
    from agno.db.dynamo.utils import build_os_metrics_totals_update, serialize_to_dynamo_item
except ImportError:
    DynamoDb = None  # type: ignore[misc,assignment]

from agno.db.utils import build_os_metrics_totals_row
from agno.run.base import RunStatus

pytestmark = pytest.mark.skipif(DynamoDb is None, reason="boto3 not installed")

# ---------------------------------------------------------------------------
# In-memory DynamoDB client stub
# ---------------------------------------------------------------------------

_CLAUSE = re.compile(r"attribute_not_exists\((#?\w+)\)|(#?\w+) BETWEEN (:\w+) AND (:\w+)|(#?\w+) (=|>=|>|<) (:\w+)")


def _value(attribute: Dict[str, Any]) -> Any:
    if "N" in attribute:
        return float(attribute["N"])
    if "BOOL" in attribute:
        return attribute["BOOL"]
    return attribute["S"]


class _ResourceNotFoundException(Exception):
    pass


class _ConditionalCheckFailedException(Exception):
    pass


class _Exceptions:
    ResourceNotFoundException = _ResourceNotFoundException
    ConditionalCheckFailedException = _ConditionalCheckFailedException


class _Waiter:
    def wait(self, **kwargs) -> None:
        return None


class _FakeDynamoClient:
    """Minimal in-memory DynamoDB client supporting the ops the OS metrics methods use."""

    exceptions = _Exceptions

    def __init__(self) -> None:
        self._key_schemas: Dict[str, List[str]] = {}
        self._tables: Dict[str, Dict[tuple, Dict[str, Any]]] = {}
        # Items a query returns per page, as DynamoDB returns at most 1 MB per page. None returns one page
        self.page_size: Optional[int] = None

    def get_waiter(self, name: str) -> _Waiter:
        return _Waiter()

    def describe_table(self, TableName: str) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        return {"Table": {"TableName": TableName}}

    def create_table(self, TableName: str, KeySchema: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        self._key_schemas[TableName] = [key["AttributeName"] for key in KeySchema]
        self._tables.setdefault(TableName, {})
        return {}

    def _key(self, table_name: str, item: Dict[str, Any]) -> tuple:
        return tuple(item[name]["S"] for name in self._key_schemas[table_name])

    @staticmethod
    def _matches(item: Dict[str, Any], expression: str, names: Dict[str, str], values: Dict[str, Any]) -> bool:
        if " OR " in expression:
            return any(_FakeDynamoClient._matches(item, part, names, values) for part in expression.split(" OR "))
        for missing, between, low, high, name, operator, operand in _CLAUSE.findall(expression):
            if missing:
                if names.get(missing, missing) in item:
                    return False
                continue
            attribute = names.get(between or name, between or name)
            if attribute not in item:
                return False
            stored = _value(item[attribute])
            if between and not _value(values[low]) <= stored <= _value(values[high]):
                return False
            if name:
                compared = _value(values[operand])
                if operator == "=" and stored != compared:
                    return False
                if operator == ">=" and stored < compared:
                    return False
                if operator == ">" and stored <= compared:
                    return False
                if operator == "<" and stored >= compared:
                    return False
        return True

    def get_item(self, TableName: str, Key: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        item = self._tables[TableName].get(self._key(TableName, Key))
        return {"Item": item} if item else {}

    def put_item(self, TableName: str, Item: Dict[str, Any], ConditionExpression: Optional[str] = None, **kwargs):
        stored = self._tables[TableName].get(self._key(TableName, Item), {})
        if ConditionExpression and not self._matches(
            stored, ConditionExpression, kwargs.get("ExpressionAttributeNames", {}), kwargs["ExpressionAttributeValues"]
        ):
            raise _ConditionalCheckFailedException()
        self._tables[TableName][self._key(TableName, Item)] = Item

    def delete_item(self, TableName: str, Key: Dict[str, Any], ConditionExpression: Optional[str] = None, **kwargs):
        stored = self._tables[TableName].get(self._key(TableName, Key), {})
        if ConditionExpression and not self._matches(
            stored, ConditionExpression, kwargs.get("ExpressionAttributeNames", {}), kwargs["ExpressionAttributeValues"]
        ):
            raise _ConditionalCheckFailedException()
        self._tables[TableName].pop(self._key(TableName, Key), None)

    def update_item(
        self,
        TableName: str,
        Key: Dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: Dict[str, Any],
        ExpressionAttributeNames: Optional[Dict[str, str]] = None,
        ConditionExpression: Optional[str] = None,
    ) -> None:
        names = ExpressionAttributeNames or {}
        if ConditionExpression and not self._matches(
            self._tables[TableName].get(self._key(TableName, Key), {}),
            ConditionExpression,
            names,
            ExpressionAttributeValues,
        ):
            raise _ConditionalCheckFailedException()
        item = dict(self._tables[TableName].get(self._key(TableName, Key), Key))
        sets, removes, adds = re.match(r"SET (.*?)(?: REMOVE (.*?))?(?: ADD (.*))?$", UpdateExpression).groups()
        for part in re.split(r", (?=#)", sets):
            name, value = part.split(" = ")
            if value.startswith("if_not_exists"):
                value = re.search(r"(:\w+)\)$", value).group(1)
                if names[name] in item:
                    continue
            item[names.get(name, name)] = ExpressionAttributeValues[value]
        for name in (removes or "").split(", "):
            item.pop(names.get(name, name), None)
        if adds:
            name, value = adds.split(" ")
            current = _value(item.get(names[name], {"N": "0"}))
            item[names[name]] = {"N": str(int(current + _value(ExpressionAttributeValues[value])))}
        self._tables[TableName][self._key(TableName, Key)] = item

    def batch_write_item(self, RequestItems: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        for table_name, requests in RequestItems.items():
            for request in requests:
                if "PutRequest" in request:
                    self.put_item(table_name, request["PutRequest"]["Item"])
                else:
                    self.delete_item(table_name, request["DeleteRequest"]["Key"])
        return {}

    def batch_get_item(self, RequestItems: Dict[str, Any]) -> Dict[str, Any]:
        responses = {}
        for table_name, request in RequestItems.items():
            items = [self._tables[table_name].get(self._key(table_name, key)) for key in request["Keys"]]
            responses[table_name] = [item for item in items if item]
        return {"Responses": responses}

    def query(self, TableName: str, KeyConditionExpression: str, **kwargs) -> Dict[str, Any]:
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs["ExpressionAttributeValues"]
        if "IndexName" in kwargs:
            # An index holds only the items that have its keys, in the order of its sort key
            hash_key, sort_key = re.match(r"(\w+?)-(\w+)-index", kwargs["IndexName"]).groups()
        else:
            hash_key, sort_key = self._key_schemas[TableName]
        expression = KeyConditionExpression + " AND " + kwargs.get("FilterExpression", "")
        items = [
            item
            for item in self._tables[TableName].values()
            if hash_key in item and sort_key in item and self._matches(item, expression, names, values)
        ]
        items.sort(key=lambda item: _value(item[sort_key]), reverse=not kwargs.get("ScanIndexForward", True))
        if self.page_size is None:
            return {"Items": items[: kwargs.get("Limit")]}
        start = kwargs.get("ExclusiveStartKey", 0)
        response: Dict[str, Any] = {"Items": items[start : start + self.page_size]}
        if start + self.page_size < len(items):
            response["LastEvaluatedKey"] = start + self.page_size
        return response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _day(days_ago: int) -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _timestamp(days_ago: int) -> int:
    """A moment of the UTC day days_ago days back, in the past."""
    midnight = int(datetime.combine(_day(days_ago), datetime.min.time()).replace(tzinfo=timezone.utc).timestamp())
    return max(midnight, int(time.time()) - 30) if days_ago == 0 else midnight + 3600


def _new_db():
    client = _FakeDynamoClient()
    db = DynamoDb(
        db_client=client,
        session_table="test_sessions",
        runs_table="test_runs",
        os_metrics_table="test_os_metrics",
        os_metrics_totals_table="test_os_metrics_totals",
    )
    # Pre-create the tables we use to skip the create_if_not_found dance.
    db._create_all_tables()
    return db


def _store(db, session_id: str, days_ago: int, user_id: Optional[str] = "alice", tokens: int = 10) -> None:
    """Store an agent session with one completed run, as upsert_session and upsert_run write them."""
    created_at = _timestamp(days_ago)
    run_id = f"{session_id}-run"
    run_data = {
        "run_id": run_id,
        "agent_id": "agent-1",
        "status": RunStatus.completed.value,
        "model": "gpt-5",
        "model_provider": "OpenAI",
        "metrics": {
            "input_tokens": tokens,
            "output_tokens": tokens,
            "total_tokens": 2 * tokens,
            "duration": 1.5,
            "details": {"model": [{"id": "gpt-5"}]},
        },
    }
    db.client.put_item(
        TableName=db._get_table("sessions"),
        Item=serialize_to_dynamo_item(
            {
                "session_id": session_id,
                "session_type": "agent",
                "agent_id": "agent-1",
                "user_id": user_id,
                "created_at": created_at,
                "updated_at": created_at,
            }
        ),
    )
    db.client.put_item(
        TableName=db._get_table("runs"),
        Item=serialize_to_dynamo_item(
            {
                "run_id": run_id,
                "session_id": session_id,
                "run_type": "agent",
                "agent_id": "agent-1",
                "user_id": user_id,
                "status": RunStatus.completed.value,
                "run_data": run_data,
                "created_at": created_at,
                "updated_at": created_at,
            }
        ),
    )


def _versions(db) -> Dict[str, int]:
    db._os_metrics_refreshed_at = time.time()
    return db.get_os_metrics_versions(_day(70), _day(0))


def test_rebuild_writes_rows_of_each_day_and_the_totals_row_last():
    db = _new_db()
    _store(db, "s1", 0, user_id="alice")
    _store(db, "s2", 0, user_id=None)
    _store(db, "s3", 1, user_id="bob")

    records = db.calculate_os_metrics()

    assert sorted((record["date"], record["user_id"]) for record in records) == [
        (_day(1), "bob"),
        (_day(0), ""),
        (_day(0), "alice"),
    ]
    today_rows = db._get_os_metrics_rows("test_os_metrics", "daily", _day(0))
    assert sorted((row["user_id"], row["runs_count"], row["total_tokens"]) for row in today_rows) == [
        ("", 1, 20),
        ("alice", 1, 20),
    ]
    totals = db._get_os_metrics_totals_rows("test_os_metrics_totals", "daily")
    assert [(row["date"], row["sessions_count"], row["completed"], row["version"]) for row in totals] == [
        (_day(1), 1, False, 1),
        (_day(0), 2, False, 1),
    ]
    # The lock item is deleted once the rebuild is done
    assert ("lock", "test_os_metrics") not in db.client._tables["test_os_metrics_totals"]


def test_rebuild_with_nothing_new_keeps_the_versions():
    db = _new_db()
    _store(db, "s1", 0)
    db.calculate_os_metrics()
    versions = _versions(db)

    previous_updated_at, latest_updated_at, changed = db.refresh_os_metrics()

    assert changed is False
    assert previous_updated_at == latest_updated_at
    assert _versions(db) == versions


def test_a_new_run_moves_the_version_of_its_day():
    db = _new_db()
    _store(db, "s1", 0)
    db.calculate_os_metrics()
    assert _versions(db)[f"daily {_day(0).isoformat()}"] == 1

    _store(db, "s2", 0)
    _, _, changed = db.refresh_os_metrics()

    assert changed is True
    versions = _versions(db)
    assert versions[f"daily {_day(0).isoformat()}"] == 2
    assert versions[f"daily {_day(1).isoformat()}"] == 1


def test_lazy_refresh_with_nothing_new_is_skipped(monkeypatch):
    db = _new_db()
    _store(db, "s1", 0)
    db._calculate_os_metrics(wait_for_rebuild=False)
    assert db._os_metrics_fingerprint is not None

    calculated = []
    monkeypatch.setattr(db, "_get_os_metrics_rows", lambda *args: calculated.append(args) or [])
    assert db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert calculated == []

    # An explicit refresh always rebuilds
    db._calculate_os_metrics(wait_for_rebuild=True)
    assert calculated


def test_lazy_refresh_skips_while_another_rebuild_holds_the_lock():
    db = _new_db()
    _store(db, "s1", 0)
    assert db._lock_os_metrics("test_os_metrics_totals", "test_os_metrics", "other-rebuild", False)

    assert db._calculate_os_metrics(wait_for_rebuild=False) is None
    # The throttle is reset, so the next read tries again
    assert db._os_metrics_refreshed_at == 0.0

    db._unlock_os_metrics("test_os_metrics_totals", "test_os_metrics", "other-rebuild")
    assert db._calculate_os_metrics(wait_for_rebuild=False) is not None


def test_versions_are_none_while_today_has_sessions_and_no_totals_row():
    db = _new_db()
    _store(db, "s1", 1)
    db.calculate_os_metrics()
    assert _versions(db) is not None

    _store(db, "s2", 0)
    db.client.delete_item(
        TableName="test_os_metrics_totals",
        Key={"aggregation_period": {"S": "daily"}, "date": {"S": _day(0).isoformat()}},
    )

    assert _versions(db) is None
    assert db._os_metrics_fingerprint is None


def test_completed_month_gets_month_rows_and_a_month_totals_row():
    db = _new_db()
    last_month_end = _day(0).replace(day=1) - timedelta(days=1)
    month_start = last_month_end.replace(day=1)
    if last_month_end > _day(2):
        pytest.skip("last month is not completed until the second day of this month")
    days_ago = (_day(0) - month_start).days
    _store(db, "s1", days_ago, user_id="alice", tokens=10)
    _store(db, "s2", days_ago - 1, user_id="alice", tokens=5)

    db.calculate_os_metrics()

    month_rows = db._get_os_metrics_rows("test_os_metrics", "monthly", month_start)
    assert [(row["user_id"], row["runs_count"], row["total_tokens"]) for row in month_rows] == [("alice", 2, 30)]
    month_totals = db._get_os_metrics_totals_rows("test_os_metrics_totals", "monthly")
    assert [(row["date"], row["runs_count"], row["completed"]) for row in month_totals] == [(month_start, 2, True)]

    db._os_metrics_refreshed_at = time.time()
    totals, _ = db.get_os_metrics_totals(month_start, last_month_end, user_id="alice", fields=["runs_count"])
    assert totals == {"runs_count": 2}


def test_reads_every_owner_from_totals_rows_and_one_owner_from_their_rows():
    db = _new_db()
    _store(db, "s1", 0, user_id="alice", tokens=10)
    _store(db, "s2", 0, user_id=None, tokens=3)
    _store(db, "s3", 1, user_id="alice", tokens=7)
    db.calculate_os_metrics()
    db._os_metrics_refreshed_at = time.time()
    fields = ["sessions_count", "total_tokens", "model_metrics"]

    everyone, updated_at = db.get_os_metrics(_day(1), _day(0), fields=fields)
    alice, _ = db.get_os_metrics(_day(1), _day(0), user_id="alice", fields=fields)
    no_owner, _ = db.get_os_metrics(_day(1), _day(0), user_id="", fields=fields)

    model = {"model_id": "gpt-5", "model_provider": "OpenAI"}
    assert everyone == [
        {"date": _day(1), "sessions_count": 1, "total_tokens": 14, "model_metrics": [{**model, "count": 1}]},
        {"date": _day(0), "sessions_count": 2, "total_tokens": 26, "model_metrics": [{**model, "count": 2}]},
    ]
    assert updated_at is not None
    assert [(day["date"], day["total_tokens"]) for day in alice] == [(_day(1), 14), (_day(0), 20)]
    assert [(day["date"], day["total_tokens"]) for day in no_owner] == [(_day(0), 6)]


def test_month_step_reads_only_the_days_after_the_latest_month(monkeypatch):
    db = _new_db()
    for days_ago in range(1, 120):
        db.client.update_item(
            **build_os_metrics_totals_update(
                "test_os_metrics_totals",
                build_os_metrics_totals_row([], "daily", _day(days_ago), days_ago > 1),
            )
        )
    latest_month = _day(1).replace(day=1)
    db.client.update_item(
        **build_os_metrics_totals_update(
            "test_os_metrics_totals",
            build_os_metrics_totals_row([], "monthly", (latest_month - timedelta(days=1)).replace(day=1), True),
        )
    )
    day_rows_read: List[int] = []
    query = db.client.query

    def counting_query(**kwargs):
        response = query(**kwargs)
        if kwargs["ExpressionAttributeValues"].get(":period") == {"S": "daily"} and "Limit" not in kwargs:
            day_rows_read.append(len(response["Items"]))
        return response

    monkeypatch.setattr(db.client, "query", counting_query)
    db._calculate_month_os_metrics("test_os_metrics", "test_os_metrics_totals", "lock-1", True)

    assert day_rows_read[0] == (_day(1) - latest_month).days + 1


def test_a_day_that_reads_for_longer_than_the_lock_keeps_it(monkeypatch):
    db = _new_db()
    _store(db, "s1", 1)
    lock_key = ("lock", "test_os_metrics")
    query_os_metrics_sources = db._query_os_metrics_sources
    other_rebuild_locked: List[bool] = []

    def slow_read(*args, **kwargs):
        records = query_os_metrics_sources(*args, **kwargs)
        lock = db.client._tables["test_os_metrics_totals"].get(lock_key)
        if "user_id" in args[4] and lock and not other_rebuild_locked:
            if args[1] == "session_type-created_at-index":
                # The sessions read outlasts the lock
                lock["expires_at"] = {"N": "0"}
            else:
                other_rebuild_locked.append(
                    db._lock_os_metrics("test_os_metrics_totals", "test_os_metrics", "other-rebuild", False)
                )
        return records

    monkeypatch.setattr(db, "_query_os_metrics_sources", slow_read)
    db._calculate_os_metrics(wait_for_rebuild=True)

    assert other_rebuild_locked == [False]
    totals = db._get_os_metrics_totals_rows("test_os_metrics_totals", "daily")
    assert (_day(1), 1) in [(row["date"], row["sessions_count"]) for row in totals]
