"""SQLite variant of the FK CASCADE regression tests (PR #8350 reviewer #20).

SQLite requires ``PRAGMA foreign_keys = ON`` for constraints to enforce —
these tests also verify the adapter sets that pragma on every connection.
Uses an in-memory (tempfile) SQLite DB, no external service needed.
"""

from __future__ import annotations

import tempfile
import time

import pytest
from sqlalchemy import text

from agno.db.sqlite.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest.fixture
def sqlite_db():
    tmp = tempfile.mkdtemp()
    db = SqliteDb(
        db_file=f"{tmp}/fk.db",
        session_table="sess",
        memory_table="mem",
        metrics_table="mtx",
        eval_table="ev",
        knowledge_table="kn",
    )
    db._get_table("sessions", create_table_if_not_found=True)
    db._get_table("runs", create_table_if_not_found=True)
    return db


class TestFkPragmaEnabled:
    def test_foreign_keys_pragma_is_on(self, sqlite_db: SqliteDb):
        """Adapter must enable ``PRAGMA foreign_keys = ON`` on every new
        connection — otherwise SQLite silently ignores FK constraints."""
        with sqlite_db.db_engine.connect() as c:
            result = c.execute(text("PRAGMA foreign_keys")).fetchone()
        assert result[0] == 1, (
            "PRAGMA foreign_keys must be ON — SQLite ignores FK constraints "
            "by default, so ON DELETE CASCADE won't fire without this pragma."
        )


class TestFkCascadeDeletesRuns:
    def _seed(self, db: SqliteDb, session_id: str, n_runs: int):
        now = int(time.time())
        db.upsert_session(
            AgentSession(
                session_id=session_id,
                agent_id="a1",
                user_id="u1",
                created_at=now,
                updated_at=now,
            )
        )
        for i in range(n_runs):
            db.upsert_run(
                run=RunOutput(
                    run_id=f"{session_id}-r{i}",
                    agent_id="a1",
                    session_id=session_id,
                    status=RunStatus.completed,
                ),
                session_id=session_id,
                user_id="u1",
                run_index=i,
            )

    def test_deleting_session_cascades_to_runs(self, sqlite_db: SqliteDb):
        self._seed(sqlite_db, "s1", 3)

        _, before = sqlite_db.get_runs(session_id="s1", deserialize=False)
        assert before == 3

        sqlite_db.delete_session(session_id="s1")

        _, after = sqlite_db.get_runs(session_id="s1", deserialize=False)
        assert after == 0

    def test_raw_sql_delete_session_also_cascades(self, sqlite_db: SqliteDb):
        self._seed(sqlite_db, "s1", 3)

        with sqlite_db.db_engine.connect() as c:
            c.execute(text("DELETE FROM sess WHERE session_id = 's1'"))
            c.commit()

        _, remaining = sqlite_db.get_runs(session_id="s1", deserialize=False)
        assert remaining == 0


class TestOrphanRunInsertRejected:
    def test_insert_run_for_unknown_session_fails(self, sqlite_db: SqliteDb):
        with pytest.raises(Exception) as exc:
            sqlite_db.upsert_run(
                run=RunOutput(
                    run_id="orphan",
                    agent_id="a1",
                    session_id="ghost",
                    status=RunStatus.completed,
                ),
                session_id="ghost",
                user_id="u1",
                run_index=0,
            )
        assert "foreign key" in str(exc.value).lower() or "constraint" in str(exc.value).lower()
