"""MySQL regression coverage for deleting runs from a legacy blob."""

import json
import uuid

import pytest
from sqlalchemy import create_engine, select, text

from agno.db.mysql import AsyncMySQLDb, MySQLDb
from agno.run.agent import RunOutput

pytest.importorskip("pymysql")
pytest.importorskip("asyncmy")

DB_URL = "mysql+pymysql://ai:ai@localhost:3306/ai"
ASYNC_DB_URL = "mysql+asyncmy://ai:ai@localhost:3306/ai"


def _server_reachable() -> bool:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture
def db():
    if not _server_reachable():
        pytest.skip(f"MySQL server not reachable at {DB_URL}")

    suffix = uuid.uuid4().hex[:8]
    database = MySQLDb(db_url=DB_URL, session_table=f"legacy_sessions_{suffix}", runs_table=f"legacy_runs_{suffix}")
    database._get_table(table_type="sessions", create_table_if_not_found=True)
    with database.Session() as sess, sess.begin():
        sess.execute(text(f"ALTER TABLE `{database.db_schema}`.`{database.session_table_name}` ADD COLUMN runs JSON"))
    database._invalidate_table_cache(database.session_table_name)

    yield database

    database.Session.remove()
    with database.db_engine.connect() as conn:
        for table_name in (database.runs_table_name, database.session_table_name):
            conn.execute(text(f"DROP TABLE IF EXISTS `{database.db_schema}`.`{table_name}`"))
        conn.commit()
    database.db_engine.dispose()


def _async_db(db) -> AsyncMySQLDb:
    return AsyncMySQLDb(db_url=ASYNC_DB_URL, session_table=db.session_table_name, runs_table=db.runs_table_name)


def _insert_legacy_session(db, run_ids):
    sessions = db._get_table(table_type="sessions")
    with db.Session() as sess, sess.begin():
        sess.execute(
            sessions.insert().values(
                session_id="s1",
                session_type="agent",
                runs=[{"run_id": run_id, "agent_id": "a1", "status": "COMPLETED"} for run_id in run_ids],
                created_at=1,
                updated_at=1,
            )
        )


def _blob_ids(db):
    sessions = db._get_table(table_type="sessions")
    with db.Session() as sess:
        raw = sess.execute(select(sessions.c.runs)).scalar_one()
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [run["run_id"] for run in raw]


def _refuse_blob_rewrites(db):
    # A trigger needs SUPER when binary logging is on; a CHECK that the two-run blob passes refuses any shrink.
    with db.Session() as sess, sess.begin():
        sess.execute(
            text(
                f"ALTER TABLE `{db.db_schema}`.`{db.session_table_name}` ADD CONSTRAINT `refuse_blob_rewrite` "
                "CHECK (runs IS NULL OR JSON_LENGTH(runs) >= 2)"
            )
        )


def test_delete_runs_scrubs_the_blob_before_any_run_row_exists(db):
    _insert_legacy_session(db, ["r0", "r1", "r2"])

    db.delete_runs(["r1"])

    assert _blob_ids(db) == ["r0", "r2"]


def test_delete_run_reports_a_blob_only_run_as_deleted(db):
    _insert_legacy_session(db, ["r0", "r1"])

    assert db.delete_run("r0") is True
    assert _blob_ids(db) == ["r1"]
    assert db.delete_run("r0") is False


def test_a_failed_scrub_rolls_back_the_row_delete(db):
    _insert_legacy_session(db, ["r0", "r1"])
    db.upsert_run(RunOutput(run_id="r2", agent_id="a1", session_id="s1"), session_id="s1")
    _refuse_blob_rewrites(db)

    with pytest.raises(Exception, match="refuse_blob_rewrite"):
        db.delete_runs(["r0", "r2"])

    assert _blob_ids(db) == ["r0", "r1"]
    assert db.get_run("r2") is not None


@pytest.mark.asyncio
async def test_async_delete_run_reports_a_blob_only_run_as_deleted(db):
    _insert_legacy_session(db, ["r0", "r1"])
    async_db = _async_db(db)
    try:
        assert await async_db.delete_run("r0") is True
        assert await async_db.delete_run("r0") is False
    finally:
        await async_db.db_engine.dispose()

    assert _blob_ids(db) == ["r1"]


@pytest.mark.asyncio
async def test_async_failed_scrub_raises_and_rolls_back_the_row_delete(db):
    _insert_legacy_session(db, ["r0", "r1"])
    db.upsert_run(RunOutput(run_id="r2", agent_id="a1", session_id="s1"), session_id="s1")
    _refuse_blob_rewrites(db)

    async_db = _async_db(db)
    try:
        with pytest.raises(Exception, match="refuse_blob_rewrite"):
            await async_db.delete_runs(["r0", "r2"])
        with pytest.raises(Exception, match="refuse_blob_rewrite"):
            await async_db.delete_run("r0")
    finally:
        await async_db.db_engine.dispose()

    assert _blob_ids(db) == ["r0", "r1"]
    assert db.get_run("r2") is not None
