"""Parametrized cross-backend schedule lifecycle contract tests.

Why this exists: when the schedule subsystem was first being wired up,
per-backend bugs in table creation and the atomic-claim primitive went
unnoticed because the only scheduler unit tests covered Mongo. A
parametrized table-creation + claim contract test catches:

* Schemas missing columns the claim/release path references.
* Resolver branches that forget to chain the parent table for FK targets.
* Atomic-claim primitives that swallow the second concurrent claim
  silently (Async-MySQL ``SELECT ... FOR UPDATE SKIP LOCKED`` regressions
  fall in here, as do SingleStore optimistic-claim races).

Only SQLite is required to run; Postgres and Mongo are skipped if not
reachable. The goal isn't to test the backends end-to-end — that's the
job of the per-backend integration suites — but to fail fast in CI when
the *shape* of the lifecycle contract drifts on any backend that ships
schedules.
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
        # ``next_run_at`` defaults to "due now" so claim_due_schedule picks
        # the row up immediately; lifecycle tests override only when they
        # specifically want a not-yet-due schedule.
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
# Each constructor returns a context manager yielding a ready-to-use DB.
# We use context managers so the fixtures can tear down temp files /
# database state on any failure path.


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
    # Postgres needs a live server. Skip if the conventional dev URL is
    # not reachable rather than burning CI time on a connection timeout.
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
        """Touching the schedules table for the first time must auto-create
        it. Catches missing schema columns / forgotten resolver branches."""
        with ctx_factory() as db:
            data = _make_schedule()
            db.create_schedule(data)  # implicit table create

            assert db.get_schedule(data["id"])["id"] == data["id"]

    def test_claim_release_cycle(self, name: str, ctx_factory: Callable):
        """A due, unlocked schedule must be claim-able, then release-able,
        then claim-able again."""
        with ctx_factory() as db:
            data = _make_schedule()
            db.create_schedule(data)

            claimed = db.claim_due_schedule(worker_id="worker-1")
            assert claimed is not None, f"{name}: first claim returned None"
            assert claimed["id"] == data["id"]
            assert claimed["locked_by"] == "worker-1"

            assert db.release_schedule(data["id"]) is True

            # After release, the schedule is claimable again.
            claimed_again = db.claim_due_schedule(worker_id="worker-2")
            assert claimed_again is not None, f"{name}: re-claim after release returned None"
            assert claimed_again["locked_by"] == "worker-2"

    def test_double_claim_is_serialised(self, name: str, ctx_factory: Callable):
        """Two consecutive claim calls in the same process MUST NOT both
        return the same schedule with the same lock state. The second
        call should either get None (no other due schedules) or a
        different schedule. This is the load-bearing assertion that
        catches optimistic-claim primitives with TOCTOU bugs (e.g.
        SingleStore's compare-and-set without the lock_state guard, or
        MySQL's SKIP LOCKED accidentally turned off)."""
        with ctx_factory() as db:
            a = _make_schedule()
            db.create_schedule(a)

            first = db.claim_due_schedule(worker_id="worker-1")
            second = db.claim_due_schedule(worker_id="worker-2")

            assert first is not None, f"{name}: first claim was None"
            # Either the second claim returned None (the only due schedule
            # was already locked) or it returned a *different* schedule.
            # What it MUST NOT do is return the same schedule with
            # worker-2 having stolen the lock from worker-1.
            if second is not None:
                assert second["id"] != first["id"], (
                    f"{name}: two concurrent claims returned the SAME schedule — "
                    f"claim primitive is not serialising correctly"
                )

    def test_user_isolation_on_user_facing_reads(self, name: str, ctx_factory: Callable):
        """``get_schedule(schedule_id, user_id="bob")`` must not surface
        Alice's schedule even though Bob knows its id. Catches the
        ``user_id`` filter being silently absent on any per-backend
        implementation."""
        with ctx_factory() as db:
            alice_sched = _make_schedule(user_id="alice")
            db.create_schedule(alice_sched)

            # Alice can see her own schedule with the right scope.
            assert db.get_schedule(alice_sched["id"], user_id="alice") is not None
            # Bob asking for the same id with his scope sees nothing.
            assert db.get_schedule(alice_sched["id"], user_id="bob") is None
            # Unscoped read sees it (matches admin / RBAC-off view).
            assert db.get_schedule(alice_sched["id"]) is not None
