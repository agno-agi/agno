"""Metrics calculation must not bind one SQL parameter per session (#10643)."""

import sqlite3
import sys
import tempfile
import time

import pytest
from sqlalchemy import event, insert

from agno.db.sqlite.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="Connection.setlimit needs Python 3.11")

VARIABLE_LIMIT = 100


@pytest.fixture
def sqlite_db():
    db = SqliteDb(db_file=f"{tempfile.mkdtemp()}/metrics.db")
    db._get_table("sessions", create_table_if_not_found=True)
    db._get_table("runs", create_table_if_not_found=True)
    return db


def test_metrics_sessions_query_scales_past_bind_variable_limit(sqlite_db: SqliteDb):
    now = int(time.time())
    sqlite_db.upsert_session(AgentSession(session_id="with-run", agent_id="a1", created_at=now, updated_at=now))
    sqlite_db.upsert_run(
        run=RunOutput(
            run_id="r1",
            agent_id="a1",
            session_id="with-run",
            status=RunStatus.completed,
            model="gpt-4o",
            model_provider="OpenAI",
        ),
        session_id="with-run",
        run_index=0,
    )
    sessions_table = sqlite_db._get_table("sessions")
    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(
            insert(sessions_table),
            [
                {"session_id": f"s{i}", "session_type": "agent", "created_at": now, "updated_at": now}
                for i in range(VARIABLE_LIMIT * 2)
            ],
        )

    @event.listens_for(sqlite_db.db_engine, "connect")
    def lower_variable_limit(dbapi_connection, _):
        dbapi_connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, VARIABLE_LIMIT)

    sqlite_db.db_engine.dispose()

    sessions = sqlite_db._get_all_sessions_for_metrics_calculation()

    assert len(sessions) == VARIABLE_LIMIT * 2 + 1
    with_run = next(s for s in sessions if s["session_id"] == "with-run")
    assert with_run["runs"] == [{"model": "gpt-4o", "model_provider": "OpenAI"}]
