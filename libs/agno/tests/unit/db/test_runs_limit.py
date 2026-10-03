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

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.json.json_db import JsonDb
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


class TestRunIndexBackfill:
    """run_index is nullable; a run first persisted without one (e.g. a background/
    continue save) used to store NULL, which has no position and broke ORDER BY
    run_index. upsert_run now backfills a monotonic MAX+1 so ordering stays correct
    -- even for two runs sharing a second-resolution created_at, where created_at
    alone cannot disambiguate them."""

    def _db(self) -> SqliteDb:
        db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
        sess = AgentSession(session_id="s1", agent_id="a1")
        for rid in ("r0", "r1"):
            sess.upsert_run(RunOutput(run_id=rid, agent_id="a1", status=RunStatus.completed))
        db.upsert_session(sess)
        return db

    def test_missing_index_is_backfilled_monotonically(self):
        db = self._db()
        # Neither run carries a run_index; each must be assigned the next integer.
        db.upsert_run(RunOutput(run_id="r0", agent_id="a1", status=RunStatus.completed), session_id="s1", user_id=None)
        db.upsert_run(RunOutput(run_id="r1", agent_id="a1", status=RunStatus.completed), session_id="s1", user_id=None)
        rows, _ = db.get_runs(session_id="s1", deserialize=False)
        by_id = {r["run_id"]: r["run_index"] for r in rows}
        assert by_id == {"r0": 0, "r1": 1}
        assert all(r["run_index"] is not None for r in rows)

    def test_same_second_null_index_orders_correctly(self):
        # Codex regression: r0 indexed 0; r1 arrives with NO index in the SAME
        # created_at second. Backfill gives r1 index 1 (inserted later => newest),
        # so runs_limit=1 returns r1 -- created_at alone could not decide this.
        db = self._db()
        r0 = RunOutput(run_id="r0", agent_id="a1", status=RunStatus.completed)
        r0.created_at = 1000
        db.upsert_run(r0, session_id="s1", user_id=None, run_index=0)
        r1 = RunOutput(run_id="r1", agent_id="a1", status=RunStatus.completed)
        r1.created_at = 1000
        db.upsert_run(r1, session_id="s1", user_id=None)  # no run_index -> backfilled to 1

        assert _ids(db.get_session("s1", deserialize=False, runs_limit=1)["runs"]) == ["r1"]
        assert _ids(db.get_session("s1", deserialize=False)["runs"]) == ["r0", "r1"]

    def test_existing_null_index_is_backfilled_on_next_write(self):
        # A row persisted by pre-fix code with a NULL run_index gets filled in the
        # next time it is written (e.g. a status change), via COALESCE in the
        # conflict clause -- a non-null index is never overwritten.
        db = self._db()
        db.upsert_run(
            RunOutput(run_id="r0", agent_id="a1", status=RunStatus.completed),
            session_id="s1",
            user_id=None,
            run_index=0,
        )
        con = sqlite3.connect(db.db_file)
        con.execute(
            "INSERT INTO agno_runs (run_id, session_id, run_type, status, run_index, run_data, created_at) "
            "VALUES ('r1', 's1', 'agent', 'COMPLETED', NULL, '{\"run_id\": \"r1\"}', 1001)"
        )
        con.commit()
        con.close()

        # Re-upsert r1 (its NULL index must be backfilled); r0's index must be preserved.
        db.upsert_run(RunOutput(run_id="r1", agent_id="a1", status=RunStatus.completed), session_id="s1", user_id=None)

        rows, _ = db.get_runs(session_id="s1", deserialize=False)
        by_id = {r["run_id"]: r["run_index"] for r in rows}
        assert by_id["r0"] == 0
        assert by_id["r1"] is not None and by_id["r1"] >= 1


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


class TestSchemaHasNoBuilderBreakingMetadata:
    """Every SQL adapter must ship the (session_id, run_index) composite index so
    ``get_session(runs_limit=N)`` (WHERE session_id=? ORDER BY run_index DESC LIMIT N)
    is index-served. Postgres/SQLite declare it under ``__composite_indexes__``;
    MySQL/SingleStore builders pop ``_composite_indexes`` before iterating columns."""

    def test_mysql_singlestore_runs_schema_has_composite_index(self):
        from agno.db.mysql.schemas import _get_run_table_schema as mysql_runs
        from agno.db.singlestore.schemas import _get_run_table_schema as singlestore_runs

        for schema in (mysql_runs(), singlestore_runs()):
            idx = schema.get("_composite_indexes", [])
            assert any(i["columns"] == ["session_id", "run_index"] for i in idx)
            # Every remaining (column) entry must still be a real column config so the
            # builder's ``col_config["type"]`` access does not KeyError.
            for name, cfg in schema.items():
                if name.startswith("_"):
                    continue
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


_FILTER_SPECS = [
    ("r0", "COMPLETED", None),
    ("r1", "COMPLETED", None),
    ("r2", "ERROR", None),
    ("r3", "COMPLETED", None),
    ("r4", "COMPLETED", "r3"),
    ("r5", "ERROR", None),
]


def _make_inmemory(specs: List[Tuple[str, str, str]]) -> InMemoryDb:
    return _seed_adapter(InMemoryDb(), specs)


def _make_json(specs: List[Tuple[str, str, str]]) -> JsonDb:
    return _seed_adapter(JsonDb(db_path=tempfile.mkdtemp()), specs)


def _seed_adapter(db, specs: List[Tuple[str, str, str]]):
    """Write the session row then one run per spec, mirroring _make_migrated_db."""
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


@pytest.mark.parametrize("make_db", [_make_inmemory, _make_json], ids=["in_memory", "json"])
class TestRunsLimitAcrossAdapters:
    def test_returns_most_recent_n(self, make_db):
        db = make_db(COMPLETED + [("r3", "COMPLETED", None), ("r4", "COMPLETED", None)])
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"]) == ["r3", "r4"]

    def test_none_is_full_history(self, make_db):
        db = make_db(COMPLETED)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=None)["runs"]) == ["r0", "r1", "r2"]

    def test_limit_larger_than_history(self, make_db):
        db = make_db(COMPLETED)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=10)["runs"]) == ["r0", "r1", "r2"]

    def test_filter_before_slice(self, make_db):
        # last-2 of the context-relevant runs, NOT the last-2 rows.
        db = make_db(_FILTER_SPECS)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"]) == ["r1", "r3"]

    def test_filter_applies_even_when_limit_exceeds_count(self, make_db):
        # runs_limit larger than the filtered set: still filtered, just not truncated.
        db = make_db(_FILTER_SPECS)
        assert _ids(db.get_session("s1", deserialize=False, runs_limit=10)["runs"]) == ["r0", "r1", "r3"]


class TestRunsLimitNullRunIndex:
    """Regression for the NULL run_index ordering bug (COALESCE fix).

    ``run_index`` is nullable — a run first persisted without an explicit index
    (e.g. a background/continue-stream save) stores NULL. The bounded fast path
    orders by ``run_index DESC``; without ``COALESCE(run_index, 0)`` a NULL sorts
    to the wrong extreme (NULLS FIRST on Postgres, NULLS LAST on SQLite/MySQL), so
    ``runs_limit=N`` returned the *wrong* N runs — the oldest instead of the
    newest, differing per backend. The invariant these tests pin: the bounded
    fast path returns the SAME window as full-load-then-slice.
    """

    def _make_mixed_index_db(self) -> SqliteDb:
        """Session where the two newest runs have a NULL run_index (r0/r1 indexed,
        r2/r3 NULL), all with increasing created_at so the newest are unambiguous."""
        db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
        specs = [("r0", 0), ("r1", 1), ("r2", None), ("r3", None)]
        sess = AgentSession(session_id="s1", agent_id="a1")
        for rid, _ in specs:
            sess.upsert_run(RunOutput(run_id=rid, agent_id="a1", status=RunStatus("COMPLETED")))
        db.upsert_session(sess)
        for i, (rid, run_index) in enumerate(specs):
            run = RunOutput(run_id=rid, agent_id="a1", status=RunStatus("COMPLETED"))
            run.created_at = 1000 + i
            kwargs = {"session_id": "s1", "user_id": None}
            if run_index is not None:
                kwargs["run_index"] = run_index
            db.upsert_run(run, **kwargs)
        return db

    def test_bounded_matches_full_load_slice_with_null_index(self):
        db = self._make_mixed_index_db()
        full = _ids(db.get_session("s1", deserialize=False, runs_limit=None)["runs"])
        for n in (1, 2, 3):
            bounded = _ids(db.get_session("s1", deserialize=False, runs_limit=n)["runs"])
            # The bounded window must be exactly the last-N of the full history.
            assert bounded == full[-n:], f"runs_limit={n}: {bounded} != {full[-n:]}"

    def test_null_index_runs_are_not_dropped(self):
        # All four runs are context-relevant; a large limit must return every one,
        # so a NULL-index run is never silently dropped from the window.
        db = self._make_mixed_index_db()
        assert len(db.get_session("s1", deserialize=False, runs_limit=10)["runs"]) == 4


class TestRunsLimitPartialMigration:
    """Regression for the partial-migration branch: a session with runs in BOTH the
    ``agno_runs`` table AND a residual legacy ``runs`` blob (the state between running
    the v3 migration and dropping the legacy column). ``get_session(runs_limit=N)``
    must merge both, filter, and slice — never the indexed fast path."""

    def _make_partial_migration_db(self) -> SqliteDb:
        db = _make_migrated_db(COMPLETED)  # r0,r1,r2 in the runs table
        # The "both populated" state only exists on a DB migrated from v2, which keeps
        # the legacy ``runs`` column as a backup. A fresh v3 schema has no such column,
        # so recreate that transitional state: add the column, then seed a blob holding
        # an OLDER un-migrated run (r_old) plus r0 (already in the table -> dedup, table wins).
        blob = [
            {"run_id": "r_old", "agent_id": "a1", "status": "COMPLETED", "parent_run_id": None},
            {"run_id": "r0", "agent_id": "a1", "status": "COMPLETED", "parent_run_id": None},
        ]
        con = sqlite3.connect(db.db_file)
        con.execute("ALTER TABLE agno_sessions ADD COLUMN runs TEXT")
        con.execute("UPDATE agno_sessions SET runs = ? WHERE session_id = 's1'", (json.dumps(blob),))
        con.commit()
        con.close()
        return SqliteDb(db_file=db.db_file)

    def test_partial_migration_merges_before_slicing(self):
        db = self._make_partial_migration_db()
        # Both stores contribute (dedup drops the duplicate r0, table wins), so the
        # merged history contains all four distinct runs.
        full = _ids(db.get_session("s1", deserialize=False)["runs"])
        assert set(full) == {"r0", "r1", "r2", "r_old"}
        # Bounded read takes the last-N of that merged+filtered history — whatever the
        # merge order, the window must be its own suffix (never the fast path, which
        # would miss the blob-only run).
        bounded = _ids(db.get_session("s1", deserialize=False, runs_limit=2)["runs"])
        assert bounded == full[-2:]

    def test_partial_migration_no_run_lost(self):
        db = self._make_partial_migration_db()
        # A limit exceeding the count returns every distinct run, none dropped.
        got = _ids(db.get_session("s1", deserialize=False, runs_limit=10)["runs"])
        assert set(got) == {"r0", "r1", "r2", "r_old"}
