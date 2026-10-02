"""The v3.0.0 SurrealDB migration must leave already-migrated runs untouched on a re-run.

The stub below is the adapter surface the migration touches: ``_query`` returns the session
records, ``_query_one`` answers the per-run existence check and records the writes.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

surrealdb = pytest.importorskip("surrealdb")

from surrealdb import RecordID  # noqa: E402

from agno.db.migrations.versions.v3_0_0 import _migrate_surrealdb  # noqa: E402


class StubSurrealDb:
    runs_table_name = "agno_runs"

    def __init__(self, sessions: List[Dict[str, Any]]):
        self.sessions = sessions
        self.runs: Dict[str, Dict[str, Any]] = {}
        self.queries: List[str] = []
        self.fail_reads = False

    def _get_table(self, table_type: str, create_table_if_not_found: bool = True) -> str:
        return self.runs_table_name

    def _query(self, query: str, vars: Dict[str, Any], record_type: type) -> List[Dict[str, Any]]:
        self.queries.append(query)
        return self.sessions

    def _query_one(self, query: str, vars: Dict[str, Any], record_type: type):
        self.queries.append(query)
        record = vars["record"]
        assert isinstance(record, RecordID) and record.table_name == self.runs_table_name
        if query.startswith("SELECT"):
            if self.fail_reads:
                raise RuntimeError("!! Query execution error: SELECT * FROM ONLY $record")
            return self.runs.get(record.id)
        if query.startswith("CREATE"):
            if record.id in self.runs:
                raise RuntimeError(f"Database record `{record}` already exists")
            self.runs[record.id] = vars["content"]
            return vars["content"]
        raise AssertionError(f"unexpected query: {query}")


def _legacy_run(run_id: str, content: str) -> Dict[str, Any]:
    return {"run_id": run_id, "agent_id": "agent-1", "status": "COMPLETED", "content": content, "created_at": 1}


def _new_db() -> StubSurrealDb:
    session = {
        "id": RecordID("agno_sessions", "s7"),
        "user_id": "u1",
        "runs": [_legacy_run("r0", "stale-0"), _legacy_run("r1", "stale-1")],
    }
    return StubSurrealDb([session])


def test_migration_copies_every_legacy_run_once():
    db = _new_db()

    assert _migrate_surrealdb(db, "sessions", "agno_sessions") is True  # type: ignore[arg-type]

    assert set(db.runs) == {"r0", "r1"}
    assert db.runs["r0"]["run_data"]["content"] == "stale-0"


def test_migration_rerun_keeps_a_run_updated_after_the_first_run():
    db = _new_db()
    _migrate_surrealdb(db, "sessions", "agno_sessions")  # type: ignore[arg-type]

    db.runs["r0"]["run_data"]["content"] = "fresh-0"
    del db.queries[:]

    _migrate_surrealdb(db, "sessions", "agno_sessions")  # type: ignore[arg-type]

    assert db.runs["r0"]["run_data"]["content"] == "fresh-0"
    assert db.runs["r1"]["run_data"]["content"] == "stale-1"
    assert not [q for q in db.queries if q.startswith("CREATE")]


def test_migration_propagates_a_failed_existence_check():
    """A failed read must abort the migration (so the manager does not stamp it) instead of
    skipping the run; the adapter maps every SDK error to RuntimeError."""
    db = _new_db()
    db.fail_reads = True

    with pytest.raises(RuntimeError, match="Query execution error"):
        _migrate_surrealdb(db, "sessions", "agno_sessions")  # type: ignore[arg-type]

    assert db.runs == {}
