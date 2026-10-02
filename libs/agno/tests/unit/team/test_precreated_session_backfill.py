import time

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.base import SessionType
from agno.session import TeamSession
from agno.team._storage import _aread_or_create_session, _read_or_create_session
from agno.team.team import Team


def _seed_precreated_session(db: InMemoryDb) -> None:
    db.upsert_session(
        TeamSession(
            session_id="precreated",
            team_id="team-1",
            created_at=int(time.time()),
            team_data=None,
            session_data=None,
        )
    )


def test_read_or_create_backfills_precreated_team_session():
    db = InMemoryDb()
    _seed_precreated_session(db)
    team = Team(id="team-1", name="Test Team", members=[], db=db, telemetry=False)

    session = _read_or_create_session(team, session_id="precreated")
    team.save_session(session=session)

    assert session.team_data == {"name": "Test Team", "team_id": "team-1"}
    assert session.session_data == {}
    stored_session = db.get_session("precreated", session_type=SessionType.TEAM)
    assert stored_session.team_data == session.team_data
    assert stored_session.session_data == session.session_data


@pytest.mark.asyncio
async def test_aread_or_create_backfills_precreated_team_session():
    db = InMemoryDb()
    _seed_precreated_session(db)
    team = Team(id="team-1", name="Test Team", members=[], db=db, telemetry=False)

    session = await _aread_or_create_session(team, session_id="precreated")
    await team.asave_session(session=session)

    assert session.team_data == {"name": "Test Team", "team_id": "team-1"}
    assert session.session_data == {}
    stored_session = db.get_session("precreated", session_type=SessionType.TEAM)
    assert stored_session.team_data == session.team_data
    assert stored_session.session_data == session.session_data
