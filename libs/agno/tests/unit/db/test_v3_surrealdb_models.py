"""Tests for the v3.0.0 runs-table support in the SurrealDb models layer.

The full SurrealDb adapter requires a live SurrealDB instance; these tests cover
the pure model/serialization helpers used by the v3.0 port.
"""

from __future__ import annotations

from datetime import datetime, timezone

from surrealdb import RecordID

from agno.db.surrealdb.models import (
    desurrealize_run_row,
    get_schema,
    serialize_run_row,
)


def _row(**overrides):
    base = {
        "run_id": "r1",
        "session_id": "s1",
        "run_type": "agent",
        "agent_id": "agent-1",
        "user_id": "u1",
        "status": "COMPLETED",
        "run_index": 0,
        "run_data": {"messages": [{"role": "user", "content": "hi"}]},
        "created_at": 1718476200,
        "updated_at": 1718476200,
    }
    base.update(overrides)
    return base


def test_serialize_run_row_attaches_record_id():
    out = serialize_run_row(_row(), "agno_runs")
    assert isinstance(out["id"], RecordID)
    assert out["id"].table_name == "agno_runs"
    assert out["id"].id == "r1"


def test_serialize_run_row_converts_dates():
    out = serialize_run_row(_row(), "agno_runs")
    assert isinstance(out["created_at"], datetime)
    assert out["created_at"].tzinfo == timezone.utc
    assert isinstance(out["updated_at"], datetime)


def test_desurrealize_run_row_round_trips_run_id_and_dates():
    surreal = serialize_run_row(_row(), "agno_runs")
    back = desurrealize_run_row(surreal)
    assert back["run_id"] == "r1"
    assert back["created_at"] == 1718476200
    assert back["updated_at"] == 1718476200


def test_desurrealize_preserves_run_data_payload():
    surreal = serialize_run_row(_row(), "agno_runs")
    back = desurrealize_run_row(surreal)
    assert back["run_data"]["messages"][0]["content"] == "hi"


def test_get_schema_for_runs_defines_indexes():
    sql = get_schema("runs", "agno_runs")
    assert "DEFINE TABLE agno_runs SCHEMALESS" in sql
    assert "DEFINE INDEX idx_run_id ON agno_runs FIELDS run_id UNIQUE" in sql
    assert "DEFINE INDEX idx_session_id ON agno_runs FIELDS session_id" in sql
    assert "DEFINE INDEX idx_status ON agno_runs FIELDS status" in sql
