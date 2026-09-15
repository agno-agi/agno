"""Integration tests for the atomic run-field patch on real Postgres.

Proves the property the fresh-read mitigation could not: concurrent status
writes to DIFFERENT runs of the SAME session both land (row lock serializes
them), and attempt fencing rejects stale writers.
"""

import asyncio
import uuid

import pytest

from agno.db.postgres import AsyncPostgresDb
from agno.run.status_persist import RunPersistOutcome

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _pg_available() -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", 5532), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="Postgres not available on localhost:5532")


@pytest.fixture()
def db() -> AsyncPostgresDb:
    # Unique RUNS table too: its FK binds to the session table name at
    # creation time, so a shared default runs table would reference a
    # previous test's dropped session table
    suffix = uuid.uuid4().hex[:8]
    return AsyncPostgresDb(
        db_url=DB_URL, session_table=f"test_atomic_{suffix}", runs_table=f"test_atomic_runs_{suffix}"
    )


@pytest.fixture(autouse=True)
def cleanup_table(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.runs_table_name}"'))
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.session_table_name}"'))
    engine.dispose()


async def seed_session(db: AsyncPostgresDb, session_id: str, run_ids):
    """v3 substrate: session row + one runs-table row per run (the old seed
    wrote a sessions.runs blob, a column the denormalized schema dropped)."""
    import time as _time

    table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
    runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        async with sess.begin():
            await sess.execute(
                table.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    created_at=int(_time.time()),
                )
            )
            for i, rid in enumerate(run_ids):
                await sess.execute(
                    runs_table.insert().values(
                        run_id=rid,
                        session_id=session_id,
                        run_type="agent",
                        status="PENDING",
                        run_index=i,
                        run_data={"run_id": rid, "status": "PENDING"},
                        created_at=int(_time.time()),
                    )
                )


async def get_runs(db: AsyncPostgresDb, session_id: str):
    from sqlalchemy import select

    runs_table = await db._get_table(table_type="runs")
    async with db.async_session_factory() as sess:
        rows = (
            await sess.execute(
                select(runs_table.c.run_data)
                .where(runs_table.c.session_id == session_id)
                .order_by(runs_table.c.run_index)
            )
        ).fetchall()
        return {dict(r[0])["run_id"]: dict(r[0]) for r in rows}


class TestAtomicRunPatch:
    @pytest.mark.asyncio
    async def test_concurrent_writes_to_sibling_runs_both_land(self, db):
        """The lost-update the whole-blob save suffered: N concurrent writers
        patching DIFFERENT runs of one session must all land."""
        run_ids = [f"r{i}" for i in range(6)]
        await seed_session(db, "s1", run_ids)

        results = await asyncio.gather(*[db.update_run_in_session("s1", rid, {"status": "RUNNING"}) for rid in run_ids])
        assert all(r is RunPersistOutcome.UPDATED for r in results)

        runs = await get_runs(db, "s1")
        assert all(runs[rid]["status"] == "RUNNING" for rid in run_ids), runs

    @pytest.mark.asyncio
    async def test_attempt_fencing_rejects_stale_writer(self, db):
        await seed_session(db, "s1", ["r1"])
        # Attempt 2 (the live reclaimed execution) writes first
        result = await db.update_run_in_session("s1", "r1", {"status": "COMPLETED"}, expected_attempt=2)
        assert result is RunPersistOutcome.UPDATED
        # The zombie from attempt 1 arrives late: fenced out, typed as such
        stale = await db.update_run_in_session("s1", "r1", {"status": "ERROR"}, expected_attempt=1)
        assert stale is RunPersistOutcome.STALE_ATTEMPT
        runs = await get_runs(db, "s1")
        assert runs["r1"]["status"] == "COMPLETED"
        assert runs["r1"]["queue_attempt"] == 2

    @pytest.mark.asyncio
    async def test_missing_run_or_session_is_typed_missing(self, db):
        await seed_session(db, "s1", ["r1"])
        assert await db.update_run_in_session("s1", "nope", {"status": "ERROR"}) is RunPersistOutcome.MISSING
        assert await db.update_run_in_session("no-session", "r1", {"status": "ERROR"}) is RunPersistOutcome.MISSING

    @pytest.mark.asyncio
    async def test_terminal_row_refuses_conflicting_status(self, db):
        """COMPLETED survives a late CANCELLED write and CANCELLED survives a
        late ERROR write - typed TERMINAL_REFUSED, so the caller knows the
        refusal is final and never re-tries it through the unfenced
        whole-session fallback."""
        await seed_session(db, "s1", ["r1", "r2"])
        assert await db.update_run_in_session("s1", "r1", {"status": "COMPLETED"}) is RunPersistOutcome.UPDATED
        refused = await db.update_run_in_session("s1", "r1", {"status": "CANCELLED"})
        assert refused is RunPersistOutcome.TERMINAL_REFUSED

        assert await db.update_run_in_session("s1", "r2", {"status": "CANCELLED"}) is RunPersistOutcome.UPDATED
        refused = await db.update_run_in_session("s1", "r2", {"status": "ERROR"})
        assert refused is RunPersistOutcome.TERMINAL_REFUSED

        runs = await get_runs(db, "s1")
        assert runs["r1"]["status"] == "COMPLETED"
        assert runs["r2"]["status"] == "CANCELLED"

        # Same-status re-write is not a conflict (idempotent terminal write)
        assert await db.update_run_in_session("s1", "r1", {"status": "COMPLETED"}) is RunPersistOutcome.UPDATED

    @pytest.mark.asyncio
    async def test_transition_fallback_cannot_clobber_completed_row(self, db):
        """End-to-end original-bug path: a COMPLETED row + a late unfenced
        CANCELLED transition. The primitive refuses (TERMINAL_REFUSED); the
        old ambiguous False sent apersist_run_transition's whole-session
        fallback - which has no terminal guard - to overwrite the row."""
        from types import SimpleNamespace

        from agno.run.agent import RunOutput
        from agno.run.base import RunStatus
        from agno.run.status_persist import apersist_run_transition

        completed = RunOutput(run_id="r1", session_id="s1", status=RunStatus.completed, content="the real output")
        table = await db._get_table(table_type="sessions", create_table_if_not_found=True)
        runs_table = await db._get_table(table_type="runs", create_table_if_not_found=True)
        import time as _time

        async with db.async_session_factory() as sess:
            async with sess.begin():
                await sess.execute(
                    table.insert().values(
                        session_id="s1",
                        session_type="agent",
                        created_at=int(_time.time()),
                    )
                )
                await sess.execute(
                    runs_table.insert().values(
                        run_id="r1",
                        session_id="s1",
                        run_type="agent",
                        status=RunStatus.completed.value,
                        run_index=0,
                        run_data=completed.to_dict(),
                        created_at=int(_time.time()),
                    )
                )

        late = RunOutput(run_id="r1", session_id="s1", status=RunStatus.cancelled)
        await apersist_run_transition(SimpleNamespace(db=db), "agent", "s1", late)

        runs = await get_runs(db, "s1")
        assert runs["r1"]["status"] == RunStatus.completed.value, "terminal row must survive the late transition"
        assert runs["r1"]["content"] == "the real output"

    @pytest.mark.asyncio
    async def test_sync_adapter_outcome_parity(self, db):
        """The sync PostgresDb primitive must speak the same typed outcomes
        as the async twin (worker deployments mix both via the thread
        adapter)."""
        from agno.db.postgres import PostgresDb

        await seed_session(db, "s1", ["r1"])
        sync_db = PostgresDb(db_url=DB_URL, session_table=db.session_table_name, runs_table=db.runs_table_name)

        def call(**kwargs):
            return sync_db.update_run_in_session(**kwargs)

        assert (
            await asyncio.to_thread(call, session_id="s1", run_id="r1", fields={"status": "COMPLETED"})
        ) is RunPersistOutcome.UPDATED
        assert (
            await asyncio.to_thread(call, session_id="s1", run_id="r1", fields={"status": "ERROR"})
        ) is RunPersistOutcome.TERMINAL_REFUSED
        assert (
            await asyncio.to_thread(call, session_id="s1", run_id="r1", fields={"status": "ERROR"}, expected_attempt=1)
        ) is RunPersistOutcome.TERMINAL_REFUSED
        assert (
            await asyncio.to_thread(call, session_id="s1", run_id="nope", fields={"status": "ERROR"})
        ) is RunPersistOutcome.MISSING


class TestStatusCasingNormalization:
    """The indexed status column stores the canonical uppercase
    RunStatus.value and get_runs filters it case-sensitively. A caller
    passing "completed" verbatim used to produce a row invisible to that
    reader (and a run_data status RunOutput.from_dict cannot parse)."""

    @pytest.mark.asyncio
    async def test_lowercase_status_stored_canonical_async(self, db):
        from sqlalchemy import select

        from agno.run.base import RunStatus

        await seed_session(db, "s1", ["r1"])
        outcome = await db.update_run_in_session("s1", "r1", {"status": "completed"})
        assert outcome is RunPersistOutcome.UPDATED

        runs_table = await db._get_table(table_type="runs")
        async with db.async_session_factory() as sess:
            row = (
                await sess.execute(
                    select(runs_table.c.status, runs_table.c.run_data).where(runs_table.c.run_id == "r1")
                )
            ).fetchone()
        assert row[0] == "COMPLETED", f"status column stored {row[0]!r} - case-sensitive readers miss it"
        assert dict(row[1])["status"] == "COMPLETED"

        rows, total = await db.get_runs(session_id="s1", status=RunStatus.completed, deserialize=False)
        assert total == 1 and rows[0]["run_id"] == "r1", "the canonical reader path must see the write"

    @pytest.mark.asyncio
    async def test_lowercase_status_stored_canonical_sync(self, db):
        from sqlalchemy import select

        from agno.db.postgres import PostgresDb

        await seed_session(db, "s1", ["r1"])
        sync_db = PostgresDb(db_url=DB_URL, session_table=db.session_table_name, runs_table=db.runs_table_name)
        outcome = await asyncio.to_thread(
            sync_db.update_run_in_session, session_id="s1", run_id="r1", fields={"status": "completed"}
        )
        assert outcome is RunPersistOutcome.UPDATED

        runs_table = await db._get_table(table_type="runs")
        async with db.async_session_factory() as sess:
            row = (await sess.execute(select(runs_table.c.status).where(runs_table.c.run_id == "r1"))).fetchone()
        assert row[0] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_terminal_guard_sees_through_casing(self, db):
        """A lowercase terminal write must still arm the terminal guard for
        the next writer: "completed" then "ERROR" refuses."""
        await seed_session(db, "s1", ["r1"])
        assert await db.update_run_in_session("s1", "r1", {"status": "completed"}) is RunPersistOutcome.UPDATED
        assert await db.update_run_in_session("s1", "r1", {"status": "ERROR"}) is RunPersistOutcome.TERMINAL_REFUSED
