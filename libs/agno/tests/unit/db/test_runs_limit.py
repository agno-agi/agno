"""Tests for the SQL "fetch only the most recent N runs" read optimization.

``get_session(runs_limit=N)`` attaches only the most recent N context-relevant
runs instead of the whole history. It must:
- be migration-safe: work identically for fully-migrated sessions (runs in the
  ``agno_runs`` table), un-migrated sessions (legacy ``runs`` blob only), and
  sessions with no runs table yet;
- reproduce ``get_messages``' pre-slice filtering (drop member sub-runs and
  terminal-skip statuses) so the bounded window matches full-load-then-slice;
- be byte-for-byte equivalent to the old behavior when ``runs_limit`` is None.

Also covers ``get_sessions(include_runs=False)`` (list views skip runs) and the
``get_session_messages`` wiring.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from typing import List, Tuple

from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _ids(runs) -> List[str]:
    return [r.run_id if hasattr(r, "run_id") else r.get("run_id") for r in (runs or [])]


def _make_migrated_db(specs: List[Tuple[str, str, str]]) -> SqliteDb:
    """specs: list of (run_id, status, parent_run_id). Session row written first
    (FK), then one agno_runs row per spec."""
    db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
    sess = AgentSession(session_id="s1", agent_id="a1")
    for rid, status, parent in specs:
        sess.upsert_run(RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status), parent_run_id=parent))
    db.upsert_session(sess)
    for i, (rid, status, parent) in enumerate(specs):
        db.upsert_run(
            RunOutput(run_id=rid, agent_id="a1", status=RunStatus(status), parent_run_id=parent),
            session_id="s1",
            user_id=None,
            run_index=i,
        )
    return db


def _make_unmigrated_db(specs: List[Tuple[str, str, str]]) -> SqliteDb:
    """A pre-v3 database: sessions table with a legacy ``runs`` blob, no runs table."""
    dbf = tempfile.mktemp(suffix=".db")
    con = sqlite3.connect(dbf)
    con.execute(
        """CREATE TABLE agno_sessions (session_id TEXT PRIMARY KEY, session_type TEXT, user_id TEXT,
        agent_id TEXT, team_id TEXT, workflow_id TEXT, session_data TEXT, agent_data TEXT, team_data TEXT,
        workflow_data TEXT, metadata TEXT, summary TEXT, runs TEXT, created_at INTEGER, updated_at INTEGER)"""
    )
    blob = [{"run_id": r, "agent_id": "a1", "status": s, "parent_run_id": p} for (r, s, p) in specs]
    con.execute(
        "INSERT INTO agno_sessions (session_id, session_type, agent_id, runs, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        ("s1", "agent", "a1", json.dumps(blob), 1000, 1000),
    )
    con.commit()
    con.close()
    return SqliteDb(db_file=dbf)


COMPLETED = [("r0", "COMPLETED", None), ("r1", "COMPLETED", None), ("r2", "COMPLETED", None)]


class TestRunsLimitMigrated:
    def test_returns_most_recent_n(self):
        db = _make_migrated_db(COMPLETED + [("r3", "COMPLETED", None), ("r4", "COMPLETED", None)])
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"]) == ["r3", "r4"]

    def test_none_is_full_history(self):
        db = _make_migrated_db(COMPLETED)
        assert _ids(db.get_session("s1", deserialize=False)["runs"]) == ["r0", "r1", "r2"]
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=None)["runs"]) == ["r0", "r1", "r2"]

    def test_limit_larger_than_history(self):
        db = _make_migrated_db(COMPLETED)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=10)["runs"]) == ["r0", "r1", "r2"]


class TestRunsLimitUnmigrated:
    def test_blob_fallback_returns_most_recent_n(self):
        db = _make_unmigrated_db(COMPLETED + [("r3", "COMPLETED", None), ("r4", "COMPLETED", None)])
        # Reads work before any migration, and honor the limit via blob slice.
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"]) == ["r3", "r4"]

    def test_blob_full_history_when_no_limit(self):
        db = _make_unmigrated_db(COMPLETED)
        assert _ids(db.get_session("s1", deserialize=False)["runs"]) == ["r0", "r1", "r2"]


class TestFilterBeforeSlice:
    # r2/r5 errored, r4 is a member run (parent set) — all excluded by get_messages
    # BEFORE the last-N slice, so the bounded query must exclude them too.
    SPECS = [
        ("r0", "COMPLETED", None),
        ("r1", "COMPLETED", None),
        ("r2", "ERROR", None),
        ("r3", "COMPLETED", None),
        ("r4", "COMPLETED", "r3"),
        ("r5", "ERROR", None),
    ]

    def test_migrated_excludes_member_and_skip_status(self):
        db = _make_migrated_db(self.SPECS)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"]) == ["r1", "r3"]

    def test_unmigrated_excludes_member_and_skip_status(self):
        db = _make_unmigrated_db(self.SPECS)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"]) == ["r1", "r3"]


class TestGetSessionsIncludeRuns:
    def test_include_runs_false_omits_runs(self):
        db = _make_migrated_db(COMPLETED)
        sessions, _ = db.get_sessions(deserialize=False, include_runs=False)
        assert sessions[0]["runs"] is None
        # Storage untouched — a single get_session still returns the runs.
        assert _ids(db.get_session("s1", deserialize=False)["runs"]) == ["r0", "r1", "r2"]

    def test_default_attaches_runs(self):
        db = _make_migrated_db(COMPLETED)
        sessions, _ = db.get_sessions(deserialize=False)
        assert _ids(sessions[0]["runs"]) == ["r0", "r1", "r2"]


class TestCapabilityFlag:
    def test_sqlite_supports_runs_limit(self):
        assert SqliteDb.supports_runs_limit is True


class TestSchemaHasNoBuilderBreakingMetadata:
    """MySQL/SingleStore table builders iterate every schema entry and access
    ``col_config["type"]``; a non-column key like ``__composite_indexes__`` would
    KeyError on table creation. Those adapters must not carry it (yet)."""

    def test_mysql_singlestore_runs_schema_is_columns_only(self):
        from agno.db.mysql.schemas import _get_run_table_schema as mysql_runs
        from agno.db.singlestore.schemas import _get_run_table_schema as singlestore_runs

        for schema in (mysql_runs(), singlestore_runs()):
            for name, cfg in schema.items():
                assert not name.startswith("__"), f"{name} would break the MySQL/SingleStore builder"
                assert "type" in cfg

    def test_postgres_sqlite_runs_schema_has_composite_index(self):
        from agno.db.postgres.schemas import _get_run_table_schema as pg_runs
        from agno.db.sqlite.schemas import _get_run_table_schema as sqlite_runs

        for schema in (pg_runs(), sqlite_runs()):
            idx = schema.get("__composite_indexes__", [])
            assert any(i["columns"] == ["session_id", "run_index"] for i in idx)


class TestBoundedHistoryGate:
    """_bounded_history_runs_limit decides when to push runs_limit to the DB."""

    def _agent(self, db=None):
        from agno.agent import Agent

        return Agent(id="ag1", db=db, session_id="s1")

    def test_positive_with_sql_db(self):
        from agno.agent._session import _bounded_history_runs_limit

        db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
        assert _bounded_history_runs_limit(self._agent(db), 3, None) == 3

    def test_nonpositive_falls_back(self):
        from agno.agent._session import _bounded_history_runs_limit

        db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
        assert _bounded_history_runs_limit(self._agent(db), 0, None) is None
        assert _bounded_history_runs_limit(self._agent(db), -1, None) is None

    def test_no_db_falls_back(self):
        from agno.agent._session import _bounded_history_runs_limit

        # cache_session-without-DB must not bound (would bypass the cache into "not found")
        assert _bounded_history_runs_limit(self._agent(None), 3, None) is None

    def test_custom_skip_statuses_falls_back(self):
        from agno.agent._session import _bounded_history_runs_limit

        db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
        assert _bounded_history_runs_limit(self._agent(db), 3, [RunStatus.error]) is None
