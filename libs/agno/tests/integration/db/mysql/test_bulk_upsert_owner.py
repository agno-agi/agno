"""``upsert_sessions`` must apply the same owner check as ``upsert_session``.

The single-row upsert refuses to update a stored session whose ``user_id``
differs from the incoming one, which is what backs ``user_isolation=True`` on
AgentOS. MySQL's ``ON DUPLICATE KEY UPDATE`` has no ``WHERE`` clause, so the
bulk path had no such check: a batch carrying another user's ``session_id``
reassigned the stored row to the new user and overwrote its data.
"""

from agno.db.base import SessionType
from agno.session import AgentSession


def _session(user_id, marker: str, session_id: str = "owner-check") -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id="a1",
        user_id=user_id,
        session_data={"owner": marker},
        created_at=1000,
        updated_at=1000,
    )


def _stored(db, session_id: str = "owner-check"):
    return db.get_session(session_id=session_id, session_type=SessionType.AGENT)


def test_bulk_upsert_does_not_reassign_another_users_session(mysql_db):
    mysql_db.upsert_sessions([_session("alice", "alice-data")])

    accepted = mysql_db.upsert_sessions([_session("bob", "bob-data")])

    stored = _stored(mysql_db)
    assert accepted == []
    assert stored.user_id == "alice"
    assert stored.session_data["owner"] == "alice-data"


def test_bulk_upsert_still_updates_the_owners_own_session(mysql_db):
    mysql_db.upsert_sessions([_session("alice", "v1")])

    accepted = mysql_db.upsert_sessions([_session("alice", "v2")])

    assert [s.session_id for s in accepted] == ["owner-check"]
    assert _stored(mysql_db).session_data["owner"] == "v2"


def test_bulk_upsert_can_claim_an_unowned_session(mysql_db):
    """An unowned session (user_id IS NULL) can be claimed by anyone."""
    mysql_db.upsert_sessions([_session(None, "anon")])

    accepted = mysql_db.upsert_sessions([_session("bob", "bob-data")])

    assert [s.user_id for s in accepted] == ["bob"]
    assert _stored(mysql_db).user_id == "bob"


def test_anonymous_write_cannot_take_over_an_owned_session(mysql_db):
    mysql_db.upsert_sessions([_session("alice", "alice-data")])

    accepted = mysql_db.upsert_sessions([_session(None, "anon")])

    stored = _stored(mysql_db)
    assert accepted == []
    assert stored.user_id == "alice"
    assert stored.session_data["owner"] == "alice-data"


def test_bulk_upsert_with_duplicate_id_keeps_the_first_owner(mysql_db):
    """One batch carrying the same id under two owners must not hand the row
    to the last writer."""
    accepted = mysql_db.upsert_sessions([_session("alice", "alice-data"), _session("bob", "bob-data")])

    assert [s.user_id for s in accepted] == ["alice"]
    assert _stored(mysql_db).user_id == "alice"


def test_bulk_upsert_only_drops_the_mismatched_sessions(mysql_db):
    """A rejected session must not stop the rest of the batch landing."""
    mysql_db.upsert_sessions([_session("alice", "alice-data", session_id="s1")])

    accepted = mysql_db.upsert_sessions(
        [
            _session("bob", "takeover", session_id="s1"),
            _session("bob", "bobs-own", session_id="s2"),
        ]
    )

    assert [s.session_id for s in accepted] == ["s2"]
    assert _stored(mysql_db, "s1").user_id == "alice"
    assert _stored(mysql_db, "s2").user_id == "bob"
