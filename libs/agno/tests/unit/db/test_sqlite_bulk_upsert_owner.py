"""``upsert_sessions`` must apply the same owner check as ``upsert_session``.

The single-row upsert refuses to update a stored session whose ``user_id``
differs from the incoming one. The SQLite bulk path had no such predicate, so a
batch containing another user's ``session_id`` reassigned the stored row to the
new user and overwrote its data. Postgres already carries the predicate on its
bulk statement; this brings ``SqliteDb`` and ``AsyncSqliteDb`` in line.
"""

from __future__ import annotations

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.session.agent import AgentSession


def _session(user_id: str, marker: str) -> AgentSession:
    return AgentSession(
        session_id="shared",
        agent_id="a1",
        user_id=user_id,
        session_data={"session_state": {"owner": marker}},
        created_at=1000,
        updated_at=1000,
    )


def test_bulk_upsert_does_not_reassign_another_users_session(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    assert db.upsert_sessions([_session("alice", "alice-data")]) != []

    accepted = db.upsert_sessions([_session("bob", "bob-data")])

    stored = db.get_session("shared")
    assert accepted == []
    assert stored.user_id == "alice"
    assert stored.session_data["session_state"] == {"owner": "alice-data"}


def test_bulk_upsert_still_updates_the_owners_own_session(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    db.upsert_sessions([_session("alice", "v1")])

    accepted = db.upsert_sessions([_session("alice", "v2")])

    assert [s.session_id for s in accepted] == ["shared"]
    assert db.get_session("shared").session_data["session_state"] == {"owner": "v2"}


def test_bulk_upsert_with_duplicate_id_returns_the_accepted_session(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))

    accepted = db.upsert_sessions([_session("alice", "alice-data"), _session("bob", "bob-data")])

    assert [session.user_id for session in accepted] == ["alice"]
    assert db.get_session("shared").user_id == "alice"


@pytest.mark.asyncio
async def test_async_bulk_upsert_does_not_reassign_another_users_session(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "t.db"))
    await db.upsert_sessions([_session("alice", "alice-data")])

    accepted = await db.upsert_sessions([_session("bob", "bob-data")])

    stored = await db.get_session("shared")
    assert accepted == []
    assert stored.user_id == "alice"
    assert stored.session_data["session_state"] == {"owner": "alice-data"}
