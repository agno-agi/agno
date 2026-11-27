"""Integration tests for the atomic eval-run patch on real Postgres.

Proves the queue fence on a background eval suite run: a stale attempt's write is rejected, a newer one lands,
and a finished row refuses a conflicting status.
"""

import uuid

import pytest

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.evals import EvalRunRecord, EvalType
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
    return AsyncPostgresDb(db_url=DB_URL, eval_table=f"test_eval_fence_{uuid.uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def cleanup_table(db):
    yield
    import sqlalchemy

    engine = sqlalchemy.create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text(f'DROP TABLE IF EXISTS {db.db_schema}."{db.eval_table_name}"'))
    engine.dispose()


def suite_data(status: str):
    return {"summary": {"total": 1, "passed": int(status == "PASS"), "failed": 0, "status": status}, "cases": []}


async def seed_eval_run(db: AsyncPostgresDb, run_id: str):
    await db.create_eval_run(
        EvalRunRecord(run_id=run_id, eval_type=EvalType.SUITE, eval_data=suite_data("RUNNING"), eval_input={})
    )


async def get_eval_data(db: AsyncPostgresDb, run_id: str):
    eval_run = await db.get_eval_run(run_id, deserialize=False)
    return eval_run["eval_data"]  # type: ignore


class TestAtomicEvalRunPatch:
    @pytest.mark.asyncio
    async def test_same_attempt_updates_and_stamps(self, db):
        await seed_eval_run(db, "e1")
        result = await db.update_eval_run_data_in_attempt("e1", suite_data("RUNNING"), expected_attempt=1)
        assert result is RunPersistOutcome.UPDATED
        assert (await get_eval_data(db, "e1"))["queue_attempt"] == 1

    @pytest.mark.asyncio
    async def test_attempt_fencing_rejects_stale_writer(self, db):
        await seed_eval_run(db, "e1")
        # Attempt 2 (the live reclaimed execution) writes first
        assert await db.update_eval_run_data_in_attempt("e1", suite_data("PASS"), expected_attempt=2) is (
            RunPersistOutcome.UPDATED
        )
        # The zombie from attempt 1 arrives late: fenced out, typed as such
        stale = await db.update_eval_run_data_in_attempt("e1", suite_data("FAIL"), expected_attempt=1)
        assert stale is RunPersistOutcome.STALE_ATTEMPT
        eval_data = await get_eval_data(db, "e1")
        assert eval_data["summary"]["status"] == "PASS"
        assert eval_data["queue_attempt"] == 2

    @pytest.mark.asyncio
    async def test_newer_attempt_updates(self, db):
        await seed_eval_run(db, "e1")
        await db.update_eval_run_data_in_attempt("e1", suite_data("RUNNING"), expected_attempt=1)
        result = await db.update_eval_run_data_in_attempt("e1", suite_data("RUNNING"), expected_attempt=2)
        assert result is RunPersistOutcome.UPDATED
        assert (await get_eval_data(db, "e1"))["queue_attempt"] == 2

    @pytest.mark.asyncio
    async def test_missing_eval_run_is_typed_missing(self, db):
        await seed_eval_run(db, "e1")
        result = await db.update_eval_run_data_in_attempt("nope", suite_data("ERROR"), expected_attempt=1)
        assert result is RunPersistOutcome.MISSING
        assert await db.get_eval_run("nope") is None

    @pytest.mark.asyncio
    async def test_terminal_row_refuses_conflicting_status(self, db):
        await seed_eval_run(db, "e1")
        await db.update_eval_run_data_in_attempt("e1", suite_data("PASS"), expected_attempt=1)
        result = await db.update_eval_run_data_in_attempt("e1", suite_data("RUNNING"), expected_attempt=1)
        assert result is RunPersistOutcome.TERMINAL_REFUSED
        assert (await get_eval_data(db, "e1"))["summary"]["status"] == "PASS"
