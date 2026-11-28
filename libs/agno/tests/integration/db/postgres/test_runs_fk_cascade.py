"""Regression tests for reviewer comment #20 on PR #8350.

``agno_runs.session_id`` is a FOREIGN KEY into the sessions table with
``ON DELETE CASCADE``. These tests verify against a real Postgres (docker
``pgvector`` on :5532) that:

1. The FK constraint is actually created on the runs table.
2. Deleting a session cascades — the runs disappear atomically at the DB
   layer without any application-level cleanup call.
3. Inserting a run with an unknown ``session_id`` is rejected.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine, text

from agno.db.postgres.postgres import PostgresDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

TEST_SCHEMA = "fk_cascade_test"


@pytest.fixture
def pg_db():
    try:
        engine = create_engine("postgresql+psycopg://ai:ai@localhost:5532/ai")
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres unavailable on localhost:5532")

    with engine.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        c.commit()

    db = PostgresDb(
        db_engine=engine,
        db_schema=TEST_SCHEMA,
        session_table="sess",
        memory_table="mem",
        metrics_table="mtx",
        eval_table="ev",
        knowledge_table="kn",
    )
    # Sessions must exist before runs (FK)
    db._get_table("sessions", create_table_if_not_found=True)
    db._get_table("runs", create_table_if_not_found=True)

    yield db

    with engine.connect() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        c.commit()


class TestFkConstraintExists:
    def test_agno_runs_has_fk_to_sessions_with_cascade(self, pg_db: PostgresDb):
        """The FK constraint is emitted and matches the expected shape."""
        with pg_db.db_engine.connect() as c:
            # ``::regclass`` collides with SQLAlchemy's ``:param`` syntax,
            # so inline the schema-qualified name directly (safe — no user
            # input, TEST_SCHEMA is a test constant).
            rows = c.execute(
                text(
                    f"""
                    SELECT conname, pg_get_constraintdef(oid) AS def
                    FROM pg_constraint
                    WHERE conrelid = '{TEST_SCHEMA}.{pg_db.runs_table_name}'::regclass AND contype = 'f'
                    """
                )
            ).fetchall()

        fk_defs = [defn for _, defn in rows]
        assert any(
            "FOREIGN KEY (session_id)" in defn
            and f"REFERENCES {TEST_SCHEMA}.sess(session_id)" in defn
            and "ON DELETE CASCADE" in defn
            for defn in fk_defs
        ), f"expected session_id FK with ON DELETE CASCADE; got {fk_defs}"


class TestCascadeDeleteAtDbLayer:
    def _seed(self, db: PostgresDb, session_id: str, n_runs: int):
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

    def test_deleting_session_removes_its_runs(self, pg_db: PostgresDb):
        self._seed(pg_db, "s1", 3)

        _, total_before = pg_db.get_runs(session_id="s1", deserialize=False)
        assert total_before == 3

        pg_db.delete_session(session_id="s1")

        _, total_after = pg_db.get_runs(session_id="s1", deserialize=False)
        assert total_after == 0, "CASCADE should have removed all runs when the session was deleted"

    def test_deleting_session_leaves_other_sessions_runs_intact(self, pg_db: PostgresDb):
        self._seed(pg_db, "s1", 2)
        self._seed(pg_db, "s2", 2)

        pg_db.delete_session(session_id="s1")

        _, s1 = pg_db.get_runs(session_id="s1", deserialize=False)
        _, s2 = pg_db.get_runs(session_id="s2", deserialize=False)
        assert s1 == 0
        assert s2 == 2, "cascade must scope to the deleted session only"

    def test_raw_sql_delete_session_also_cascades(self, pg_db: PostgresDb):
        """Even a raw SQL delete (bypassing the app's delete_session helper)
        triggers CASCADE — this is the whole point of DB-level enforcement."""
        self._seed(pg_db, "s1", 3)

        with pg_db.db_engine.connect() as c:
            c.execute(text(f"DELETE FROM {TEST_SCHEMA}.sess WHERE session_id = 's1'"))
            c.commit()

        _, remaining = pg_db.get_runs(session_id="s1", deserialize=False)
        assert remaining == 0


class TestInsertRunWithUnknownSessionFails:
    def test_orphan_run_insert_is_rejected(self, pg_db: PostgresDb):
        """Attempting to insert a run whose session_id doesn't exist must
        fail at the DB layer — no orphan rows possible."""
        with pytest.raises(Exception) as exc:
            pg_db.upsert_run(
                run=RunOutput(
                    run_id="orphan",
                    agent_id="a1",
                    session_id="does-not-exist",
                    status=RunStatus.completed,
                ),
                session_id="does-not-exist",
                user_id="u1",
                run_index=0,
            )
        # Postgres error message contains "foreign key"
        assert "foreign key" in str(exc.value).lower() or "violates" in str(exc.value).lower()
