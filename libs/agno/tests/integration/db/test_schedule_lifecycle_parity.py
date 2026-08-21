"""Parametrized cross-backend schedule lifecycle contract tests.

One suite over table creation, the atomic-claim primitive and the ``user_id``
read filter, run against every backend that ships schedules. SQLite always runs;
Postgres and Mongo need ``AGNO_TEST_POSTGRES_URL`` / ``AGNO_TEST_MONGO_URL`` and
skip otherwise.
"""

import time
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator

import pytest


def _make_schedule(**overrides) -> dict:
    now = int(time.time())
    d = {
        "id": str(uuid.uuid4()),
        "name": f"test-schedule-{uuid.uuid4().hex[:6]}",
        "description": "Lifecycle contract test schedule",
        "method": "POST",
        "endpoint": "/agents/a1/runs",
        "payload": None,
        "cron_expr": "0 9 * * *",
        "timezone": "UTC",
        "timeout_seconds": 3600,
        "max_retries": 0,
        "retry_delay_seconds": 60,
        "enabled": True,
        # Due now by default, so claim_due_schedule picks the row up immediately
        "next_run_at": now - 1,
        "locked_by": None,
        "locked_at": None,
        "user_id": None,
        "created_at": now,
        "updated_at": None,
    }
    d.update(overrides)
    return d


# --- Backend constructors -------------------------------------------------


@contextmanager
def _sqlite_db() -> Iterator:
    import os
    import tempfile

    from agno.db.sqlite import SqliteDb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        yield SqliteDb(session_table="test_sessions", db_file=db_path)
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


@contextmanager
def _postgres_db() -> Iterator:
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("psycopg")
    import os

    url = os.getenv("AGNO_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("AGNO_TEST_POSTGRES_URL not set; skipping postgres lifecycle parity test")

    from agno.db.postgres import PostgresDb

    suffix = uuid.uuid4().hex[:8]
    db = PostgresDb(
        db_url=url,
        session_table=f"test_sessions_{suffix}",
        schedules_table=f"test_schedules_{suffix}",
        schedule_runs_table=f"test_schedule_runs_{suffix}",
    )
    try:
        yield db
    finally:
        try:
            db.drop_all()  # type: ignore[attr-defined]
        except Exception:
            pass


@contextmanager
def _mongo_db() -> Iterator:
    pytest.importorskip("pymongo")
    import os

    url = os.getenv("AGNO_TEST_MONGO_URL")
    if not url:
        pytest.skip("AGNO_TEST_MONGO_URL not set; skipping mongo lifecycle parity test")

    from agno.db.mongo import MongoDb

    db_name = f"agno_test_{uuid.uuid4().hex[:8]}"
    db = MongoDb(db_url=url, db_name=db_name)
    try:
        yield db
    finally:
        try:
            db._client.drop_database(db_name)  # type: ignore[attr-defined]
        except Exception:
            pass


BACKENDS: list[tuple[str, Callable]] = [
    ("sqlite", _sqlite_db),
    ("postgres", _postgres_db),
    ("mongo", _mongo_db),
]


# --- Lifecycle contract assertions ----------------------------------------


@pytest.mark.parametrize("name, ctx_factory", BACKENDS, ids=[n for n, _ in BACKENDS])
class TestScheduleLifecycleContract:
    """Each backend that ships schedule support must satisfy this contract."""

    def test_table_creation_does_not_raise(self, name: str, ctx_factory: Callable):
        """Touching the schedules table for the first time must auto-create it."""
        with ctx_factory() as db:
            data = _make_schedule()
            db.create_schedule(data)  # implicit table create

            assert db.get_schedule(data["id"])["id"] == data["id"]

    def test_claim_release_cycle(self, name: str, ctx_factory: Callable):
        """A due, unlocked schedule must be claim-able, then release-able, then claim-able again."""
        with ctx_factory() as db:
            data = _make_schedule()
            db.create_schedule(data)

            claimed = db.claim_due_schedule(worker_id="worker-1")
            assert claimed is not None, f"{name}: first claim returned None"
            assert claimed["id"] == data["id"]
            assert claimed["locked_by"] == "worker-1"

            assert db.release_schedule(data["id"]) is True

            claimed_again = db.claim_due_schedule(worker_id="worker-2")
            assert claimed_again is not None, f"{name}: re-claim after release returned None"
            assert claimed_again["locked_by"] == "worker-2"

    def test_double_claim_is_serialised(self, name: str, ctx_factory: Callable):
        """Two consecutive claims must never return the same schedule — catches
        optimistic-claim primitives with TOCTOU bugs."""
        with ctx_factory() as db:
            a = _make_schedule()
            db.create_schedule(a)

            first = db.claim_due_schedule(worker_id="worker-1")
            second = db.claim_due_schedule(worker_id="worker-2")

            assert first is not None, f"{name}: first claim was None"
            # None is fine (the only due schedule was already locked); the same id is not
            if second is not None:
                assert second["id"] != first["id"], (
                    f"{name}: two concurrent claims returned the SAME schedule — "
                    f"claim primitive is not serialising correctly"
                )

    def test_user_isolation_on_user_facing_reads(self, name: str, ctx_factory: Callable):
        """A scoped ``get_schedule`` must not surface another user's schedule, even by id."""
        with ctx_factory() as db:
            alice_sched = _make_schedule(user_id="alice")
            db.create_schedule(alice_sched)

            assert db.get_schedule(alice_sched["id"], user_id="alice") is not None
            assert db.get_schedule(alice_sched["id"], user_id="bob") is None
            # Unscoped read is the admin / RBAC-off view
            assert db.get_schedule(alice_sched["id"]) is not None
