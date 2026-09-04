"""Saving an AgentSession must not depend on session_data being populated.

Regression test for #9390: ``POST /sessions`` stores ``session_data=None`` when
neither ``session_state`` nor ``session_name`` is supplied, so the first run
against such a session was silently dropped instead of being persisted with
``RUNNING`` status. ``Team``'s equivalent savers never had this condition.
"""

import os
import tempfile
import time

import pytest

from agno.agent import Agent
from agno.agent._session import asave_session, save_session
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


@pytest.fixture
def sqlite_db():
    from agno.db.sqlite.sqlite import SqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


def _session_created_by_the_sessions_api(db) -> AgentSession:
    """Mirror what POST /sessions writes with no session_state or name."""
    db.upsert_session(
        AgentSession(
            session_id="s1",
            agent_id="my-agent",
            user_id="u",
            created_at=int(time.time()),
        )
    )
    session = db.get_session(session_id="s1")
    assert session.session_data is None
    return session


def _running_run() -> RunOutput:
    return RunOutput(
        run_id="r1",
        session_id="s1",
        agent_id="my-agent",
        status=RunStatus.running,
    )


def test_save_session_persists_run_when_session_data_is_none(sqlite_db):
    agent = Agent(id="my-agent", db=sqlite_db)
    session = _session_created_by_the_sessions_api(sqlite_db)
    session.upsert_run(run=_running_run())

    save_session(agent, session=session)

    stored = sqlite_db.get_session(session_id="s1")
    assert [run.status for run in stored.runs] == [RunStatus.running]


async def test_asave_session_persists_run_when_session_data_is_none(sqlite_db):
    agent = Agent(id="my-agent", db=sqlite_db)
    session = _session_created_by_the_sessions_api(sqlite_db)
    session.upsert_run(run=_running_run())

    await asave_session(agent, session=session)

    stored = sqlite_db.get_session(session_id="s1")
    assert [run.status for run in stored.runs] == [RunStatus.running]
