"""Tests for the v3.0.0 runs-table storage in DynamoDb.

Uses a tiny in-memory stub for the DynamoDB low-level client so no real AWS
account is needed.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import pytest

from agno.db.base import SessionType
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession

# ---------------------------------------------------------------------------
# In-memory DynamoDB client stub
# ---------------------------------------------------------------------------


class _ResourceNotFoundException(Exception):
    pass


class _ConditionalCheckFailedException(Exception):
    pass


class _ClientError(Exception):
    pass


class _Exceptions:
    ResourceNotFoundException = _ResourceNotFoundException
    ConditionalCheckFailedException = _ConditionalCheckFailedException
    ClientError = _ClientError


class _Waiter:
    def wait(self, **kwargs) -> None:
        return None


class _FakeDynamoClient:
    """Minimal in-memory DynamoDB client supporting the ops DynamoDb uses."""

    exceptions = _Exceptions

    def __init__(self) -> None:
        self._tables: Dict[str, Dict[str, Dict[str, Any]]] = {}  # table_name -> {pk_value: item}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def get_waiter(self, name: str) -> _Waiter:
        return _Waiter()

    def describe_table(self, TableName: str) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        return {"Table": {"TableName": TableName}}

    def create_table(self, **schema) -> Dict[str, Any]:
        name = schema["TableName"]
        self._tables.setdefault(name, {})
        self._schemas[name] = schema
        return {}

    def _pk_attr(self, table: str) -> str:
        schema = self._schemas.get(table, {})
        for k in schema.get("KeySchema", []):
            if k["KeyType"] == "HASH":
                return k["AttributeName"]
        # Fallback to common defaults
        return "session_id" if "session" in table else "run_id"

    def _pk_value(self, table: str, key: Dict[str, Any]) -> str:
        pk = self._pk_attr(table)
        return key[pk]["S"]

    def put_item(self, TableName: str, Item: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        pk = self._pk_attr(TableName)
        pk_val = Item[pk]["S"]

        # ConditionExpression handling for the small set we use
        ce = kwargs.get("ConditionExpression")
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs.get("ExpressionAttributeValues", {})
        existing = self._tables[TableName].get(pk_val)
        if ce and "attribute_not_exists(run_id)" in ce and existing is not None:
            raise _ConditionalCheckFailedException()
        if ce and existing is not None:
            # session put: "attribute_not_exists(session_id) OR #uid = :incoming_uid OR attribute_not_exists(#uid)"
            uid_field = names.get("#uid", "user_id") if names else "user_id"
            incoming = values.get(":incoming_uid", {}).get("S") if values else None
            existing_uid = (existing.get(uid_field) or {}).get("S")
            ok = False
            if "attribute_not_exists(session_id)" in ce and pk_val not in self._tables[TableName]:
                ok = True
            if incoming and existing_uid == incoming:
                ok = True
            if "attribute_not_exists(#uid)" in ce and existing_uid is None:
                ok = True
            if not ok:
                raise _ConditionalCheckFailedException()
        self._tables[TableName][pk_val] = Item
        return {}

    def get_item(self, TableName: str, Key: Dict[str, Any]) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        pk_val = self._pk_value(TableName, Key)
        item = self._tables[TableName].get(pk_val)
        if item is None:
            return {}
        return {"Item": item}

    def delete_item(self, TableName: str, Key: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        pk_val = self._pk_value(TableName, Key)
        existing = self._tables[TableName].get(pk_val)
        ce = kwargs.get("ConditionExpression")
        if ce and "attribute_exists(run_id)" in ce and existing is None:
            raise _ConditionalCheckFailedException()
        if existing is None:
            return {}
        # user_id condition for sessions
        values = kwargs.get("ExpressionAttributeValues", {})
        if values and ":user_id" in values:
            expected = values[":user_id"]["S"]
            actual = (existing.get("user_id") or {}).get("S")
            if expected != actual:
                raise _ConditionalCheckFailedException()
        self._tables[TableName].pop(pk_val, None)
        return {}

    def batch_write_item(self, RequestItems: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        for table, requests in RequestItems.items():
            for req in requests:
                if "DeleteRequest" in req:
                    pk = self._pk_attr(table)
                    key = req["DeleteRequest"]["Key"]
                    pk_val = key[pk]["S"]
                    self._tables.get(table, {}).pop(pk_val, None)
                elif "PutRequest" in req:
                    item = req["PutRequest"]["Item"]
                    pk = self._pk_attr(table)
                    self._tables.setdefault(table, {})[item[pk]["S"]] = item
        return {}

    def update_item(self, TableName: str, Key: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        pk_val = self._pk_value(TableName, Key)
        existing = self._tables[TableName].get(pk_val) or {}
        ue = kwargs.get("UpdateExpression", "")
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs.get("ExpressionAttributeValues", {})
        if ue.strip().startswith("REMOVE"):
            for token in ue.replace("REMOVE", "").split(","):
                attr = token.strip()
                attr = names.get(attr, attr)
                existing.pop(attr, None)
        elif ue.strip().startswith("SET"):
            # crude SET handling: parse "SET a = :a, b = :b"
            body = ue.strip()[3:].strip()
            for assignment in body.split(","):
                left, right = assignment.split("=")
                attr = left.strip()
                attr = names.get(attr, attr)
                placeholder = right.strip()
                existing[attr] = values[placeholder]
        for k, v in Key.items():
            existing[k] = v
        self._tables[TableName][pk_val] = existing
        return {"Attributes": existing}

    def _item_matches(self, item: Dict[str, Any], attr: str, expected: Dict[str, Any]) -> bool:
        val = item.get(attr)
        if val is None:
            return False
        # Compare on the typed value
        if "S" in expected:
            return val.get("S") == expected["S"]
        if "N" in expected:
            return val.get("N") == expected["N"]
        return False

    def query(
        self,
        TableName: str,
        KeyConditionExpression: str,
        ExpressionAttributeValues: Dict[str, Any],
        ExpressionAttributeNames: Optional[Dict[str, str]] = None,
        IndexName: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        # Crude parse: we only care about "<attr> = :placeholder" forms (the GSIs use partition + range).
        items = list(self._tables[TableName].values())
        names = ExpressionAttributeNames or {}
        # Split on AND
        parts = [p.strip() for p in KeyConditionExpression.split("AND")]
        for part in parts:
            if "=" in part and "BETWEEN" not in part:
                left, right = [s.strip() for s in part.split("=")]
                attr = names.get(left, left)
                placeholder = right
                expected = ExpressionAttributeValues[placeholder]
                items = [it for it in items if self._item_matches(it, attr, expected)]
            elif "BETWEEN" in part:
                # "<attr> BETWEEN :start AND :end"
                left, rest = part.split("BETWEEN")
                attr = names.get(left.strip(), left.strip())
                start_ph, end_ph = [t.strip() for t in rest.split("AND")]
                start = int(ExpressionAttributeValues[start_ph]["N"])
                end = int(ExpressionAttributeValues[end_ph]["N"])
                items = [it for it in items if attr in it and start <= int(it[attr].get("N", "0")) <= end]
        return {"Items": items}

    def scan(self, TableName: str, **kwargs) -> Dict[str, Any]:
        if TableName not in self._tables:
            raise _ResourceNotFoundException(TableName)
        return {"Items": list(self._tables[TableName].values())}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run(run_id: str, session_id: str, content: str) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        session_id=session_id,
        content=content,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content=f"q-{content}"),
            Message(role="assistant", content=f"a-{content}"),
        ],
    )


def _new_db():
    from agno.db.dynamo.dynamo import DynamoDb

    client = _FakeDynamoClient()
    db = DynamoDb(db_client=client)
    # Pre-create the tables we use to skip the create_if_not_found dance.
    db._create_all_tables()
    return db


def _insert_legacy_session(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    item = {
        "session_id": {"S": session_id},
        "session_type": {"S": "agent"},
        "agent_id": {"S": "agent-1"},
        "user_id": {"S": "u1"},
        "runs": {"S": json.dumps(runs)},
        "session_data": {"S": json.dumps({"session_state": {}})},
        "created_at": {"N": str(int(time.time()))},
        "updated_at": {"N": str(int(time.time()))},
    }
    db.client._tables[db.session_table_name][session_id] = item


def test_fresh_schema_round_trip():
    db = _new_db()
    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

    # Session item has no inline `runs`
    sess_item = db.client._tables[db.session_table_name]["s1"]
    assert "runs" not in sess_item

    # Runs table has 2 entries
    runs_items = db.client._tables[db.runs_table_name]
    assert len(runs_items) == 2

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]
    assert loaded.runs[0].messages[0].content == "q-one"


def test_legacy_blob_fallback_on_read():
    db = _new_db()
    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s2", runs)

    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name=db.session_table_name)

    # Runs table now has 2 entries
    assert len(db.client._tables[db.runs_table_name]) == 2

    # Legacy `runs` attribute is preserved on the session item
    sess_item = db.client._tables[db.session_table_name]["s6"]
    assert sess_item.get("runs") is not None


def test_cleanup_refuses_when_legacy_runs_still_present():
    db = _new_db()
    _insert_legacy_session(db, "s7", [_make_run("r1", "s7", "x").to_dict()])

    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    assert db.cleanup_legacy_runs_field(force=True) is True
    sess_item = db.client._tables[db.session_table_name]["s7"]
    assert "runs" not in sess_item


def test_get_run_get_runs_apis():
    db = _new_db()
    session = AgentSession(session_id="sx", agent_id="agent-1", user_id="u1")
    for i in range(3):
        session.upsert_run(_make_run(f"r{i}", "sx", f"c{i}"))
    db.upsert_session(session)

    run = db.get_run("r1")
    assert run is not None and run.content == "c1"

    runs = db.get_runs(session_id="sx")
    assert [r.run_id for r in runs] == ["r0", "r1", "r2"]

    db.delete_session("sx")
    assert len(db.client._tables[db.runs_table_name]) == 0
