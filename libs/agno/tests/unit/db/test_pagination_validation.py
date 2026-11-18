"""Regression tests for reviewer comment #13 on PR #8350.

Every ``get_*`` method's pagination block is guarded by::

    if limit is not None:
        if page is not None:
            OFFSET ...

which means a caller who passes ``page=5`` but forgets ``limit`` gets **all
rows** back — a silent bug that hides the caller's mistake and surfaces the
wrong data. The fix: raise ``ValueError`` at the pagination boundary via
``agno.db.utils.validate_pagination``.

These tests cover the shared helper (unit) and the JsonDb integration
(the read path actually invokes it).
"""

from __future__ import annotations

import tempfile

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.db.json.json_db import JsonDb
from agno.db.utils import validate_pagination


class TestValidatePagination:
    def test_both_none_is_ok(self):
        validate_pagination(None, None)

    def test_limit_without_page_is_ok(self):
        validate_pagination(10, None)

    def test_limit_and_page_is_ok(self):
        validate_pagination(10, 1)
        validate_pagination(10, 5)

    def test_page_without_limit_raises(self):
        with pytest.raises(ValueError, match="page.*without.*limit"):
            validate_pagination(None, 2)

    def test_page_zero_raises(self):
        with pytest.raises(ValueError, match="1-indexed"):
            validate_pagination(10, 0)

    def test_negative_page_raises(self):
        with pytest.raises(ValueError, match="1-indexed"):
            validate_pagination(10, -1)


class TestJsonDbPaginationIntegration:
    """The shared validate is only useful if adapters actually call it — this
    guards the wiring for the doc adapter we can exercise locally."""

    def _seeded_db(self) -> JsonDb:
        tmp = tempfile.mkdtemp()
        db = JsonDb(db_path=tmp)
        for i in range(5):
            db.upsert_run(
                run={"run_id": f"r{i}", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED"},
                session_id="s1",
                user_id="u1",
                run_index=i,
            )
        return db

    def test_get_runs_page_without_limit_raises(self):
        db = self._seeded_db()
        with pytest.raises(ValueError, match="page.*without.*limit"):
            db.get_runs(page=2)

    def test_get_runs_valid_pagination_still_works(self):
        db = self._seeded_db()
        rows, total = db.get_runs(limit=2, page=1, deserialize=False)
        assert total == 5
        assert [r["run_id"] for r in rows] == ["r0", "r1"]

        rows2, _ = db.get_runs(limit=2, page=2, deserialize=False)
        assert [r["run_id"] for r in rows2] == ["r2", "r3"]

    def test_get_runs_no_pagination_returns_all(self):
        db = self._seeded_db()
        rows, total = db.get_runs(deserialize=False)
        assert total == 5
        assert len(rows) == 5

    def test_get_runs_limit_without_page_returns_first_n(self):
        db = self._seeded_db()
        rows, _ = db.get_runs(limit=3, deserialize=False)
        assert [r["run_id"] for r in rows] == ["r0", "r1", "r2"]


class TestSharedApplyPaginationHelpers:
    """The adapter-shared ``apply_pagination`` helpers must also reject
    ``page`` without ``limit`` — they're the choke point for redis, valkey,
    dynamo, firestore reads. Skipped when the native driver isn't installed."""

    def test_dynamo_apply_pagination_raises(self):
        try:
            from agno.db.dynamo.utils import apply_pagination
        except ImportError:
            pytest.skip("boto3 not installed")

        with pytest.raises(ValueError, match="page.*without.*limit"):
            apply_pagination([{"a": 1}, {"a": 2}], page=1)

    def test_redis_apply_pagination_raises(self):
        try:
            from agno.db.redis.utils import apply_pagination
        except ImportError:
            pytest.skip("redis not installed")

        with pytest.raises(ValueError, match="page.*without.*limit"):
            apply_pagination([{"a": 1}], page=2)

    def test_valkey_apply_pagination_raises(self):
        try:
            from agno.db.valkey.utils import apply_pagination
        except ImportError:
            pytest.skip("valkey not installed")

        with pytest.raises(ValueError, match="page.*without.*limit"):
            apply_pagination([{"a": 1}], page=3)

    def test_firestore_apply_pagination_to_records_raises(self):
        try:
            from agno.db.firestore.utils import apply_pagination_to_records
        except ImportError:
            pytest.skip("google-cloud-firestore not installed")

        with pytest.raises(ValueError, match="page.*without.*limit"):
            apply_pagination_to_records([{"a": 1}], page=1)


class TestSqlAdaptersRejectPageWithoutLimit:
    """Reviewer flagged every SQL adapter's ``get_*`` method for this bug.
    We validate at the entry of every paginated read across all SQL adapters
    — parity check to make sure a future contributor can't drop the guard
    from one adapter unnoticed."""

    @pytest.mark.parametrize(
        "module_path,class_name,method_name",
        [
            # Every (adapter, paginated read) pair we injected the guard into.
            # Each entry catches a distinct file × method combination — if any
            # regresses (someone deletes validate_pagination), that row fails.
            ("agno.db.postgres.postgres", "PostgresDb", "get_runs"),
            ("agno.db.postgres.postgres", "PostgresDb", "get_sessions"),
            ("agno.db.postgres.postgres", "PostgresDb", "get_user_memories"),
            ("agno.db.postgres.postgres", "PostgresDb", "get_knowledge_contents"),
            ("agno.db.postgres.postgres", "PostgresDb", "get_eval_runs"),
            ("agno.db.sqlite.sqlite", "SqliteDb", "get_runs"),
            ("agno.db.sqlite.sqlite", "SqliteDb", "get_sessions"),
            ("agno.db.sqlite.sqlite", "SqliteDb", "get_user_memories"),
            ("agno.db.mysql.mysql", "MySQLDb", "get_runs"),
            ("agno.db.mysql.mysql", "MySQLDb", "get_sessions"),
            ("agno.db.singlestore.singlestore", "SingleStoreDb", "get_runs"),
            ("agno.db.singlestore.singlestore", "SingleStoreDb", "get_sessions"),
        ],
    )
    def test_method_contains_validate_pagination_call(self, module_path: str, class_name: str, method_name: str):
        """Structural check: the method source contains the guard. Runs
        without any DB or native drivers — just a source inspection."""
        try:
            module = __import__(module_path, fromlist=[class_name])
        except ImportError as e:
            pytest.skip(f"driver missing for {class_name}: {e}")
        import inspect

        cls = getattr(module, class_name)
        method = getattr(cls, method_name)
        source = inspect.getsource(method)
        assert "validate_pagination(limit, page)" in source, (
            f"{class_name}.{method_name} must call validate_pagination(limit, page) "
            "so callers passing `page` without `limit` get a ValueError instead "
            "of silently receiving page 1 / everything."
        )


class TestPostgresGetRunsPageWithoutLimitRaises:
    """E2E integration: docker pgvector on :5532 — proves the guard actually
    fires against the real adapter, not just that the source contains the call."""

    def test_raises_against_real_postgres(self):
        try:
            from sqlalchemy import create_engine, text

            from agno.db.postgres.postgres import PostgresDb
        except ImportError:
            pytest.skip("psycopg not installed")

        try:
            engine = create_engine("postgresql+psycopg://ai:ai@localhost:5532/ai")
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception:
            pytest.skip("Postgres unavailable on localhost:5532")

        # Clean slate
        with engine.connect() as c:
            c.execute(text("DROP SCHEMA IF EXISTS pagination_test CASCADE"))
            c.commit()

        db = PostgresDb(
            db_engine=engine,
            db_schema="pagination_test",
            session_table="sess",
            memory_table="mem",
            metrics_table="mtx",
            eval_table="ev",
            knowledge_table="kn",
        )
        db._get_table("sessions", create_table_if_not_found=True)
        db._get_table("runs", create_table_if_not_found=True)

        try:
            with pytest.raises(ValueError, match="page.*without.*limit"):
                db.get_runs(session_id="s1", page=2, deserialize=False)
        finally:
            with engine.connect() as c:
                c.execute(text("DROP SCHEMA IF EXISTS pagination_test CASCADE"))
                c.commit()


class TestInMemoryDbPaginationBackwardCompat:
    """InMemoryDb pagination is not routed through validate_pagination in
    this pass (kept to avoid changing behavior beyond what the reviewer
    flagged). This documents the current behavior — remove/adjust if a
    later pass ports the InMemoryDb read path over."""

    def test_in_memory_page_without_limit_currently_silent(self):
        """Not asserting a raise here — this is a placeholder documenting the
        current state so a future contributor sees the follow-up scope."""
        db = InMemoryDb()
        from agno.run.agent import RunOutput
        from agno.run.base import RunStatus
        from agno.session.agent import AgentSession

        s = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        s.upsert_run(RunOutput(run_id="r0", agent_id="a1", session_id="s1", status=RunStatus.completed))
        db.upsert_session(s)

        # InMemoryDb currently doesn't validate — this call succeeds today.
        # If a future change routes it through validate_pagination, invert
        # this assertion.
        db.get_runs(page=2)
