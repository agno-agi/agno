"""PostgreSQL regression coverage for deleting runs from a legacy blob."""

import uuid

import pytest
from sqlalchemy import create_engine, select, text

from agno.db.postgres import PostgresDb

pytest.importorskip("psycopg")

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


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
        pytest.skip(f"Postgres server not reachable at {DB_URL}")

    schema = f"delete_runs_legacy_{uuid.uuid4().hex[:8]}"
    database = PostgresDb(db_url=DB_URL, db_schema=schema)
    database._get_table(table_type="sessions", create_table_if_not_found=True)
    with database.Session() as sess, sess.begin():
        sess.execute(text(f'ALTER TABLE "{schema}".agno_sessions ADD COLUMN runs JSONB'))
    database._invalidate_table_cache(database.session_table_name)

    yield database

    database.Session.remove()
    with database.db_engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    database.db_engine.dispose()


def test_delete_runs_scrubs_legacy_blob_in_configured_schema(db):
    sessions = db._get_table(table_type="sessions")
    with db.Session() as sess, sess.begin():
        sess.execute(
            sessions.insert().values(
                session_id="s1",
                session_type="agent",
                runs=[{"run_id": "drop"}, {"run_id": "keep"}],
                created_at=1,
                updated_at=1,
            )
        )

    db.delete_runs(["drop"])

    with db.Session() as sess:
        assert sess.execute(select(sessions.c.runs)).scalar_one() == [{"run_id": "keep"}]
