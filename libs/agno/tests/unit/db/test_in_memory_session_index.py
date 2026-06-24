"""Tests for InMemoryDb's session_id index.

The index makes get/upsert/rename O(matches) instead of O(total sessions). These
tests pin its correctness: an index-consistency invariant is asserted after every
mutation, and a randomized op sequence is compared against a brute-force scan.
"""

import random
from copy import deepcopy

from agno.db.in_memory import InMemoryDb
from agno.session.agent import AgentSession


def _sess(session_id: str, agent_id: str = "a1", user_id=None) -> AgentSession:
    return AgentSession(session_id=session_id, agent_id=agent_id, user_id=user_id, runs=[])


def _assert_index_consistent(db: InMemoryDb) -> None:
    """The index must always equal a freshly-built session_id -> positions map."""
    expected: dict[str, list[int]] = {}
    for pos, sd in enumerate(db._sessions):
        sid = sd.get("session_id")
        if sid is not None:
            expected.setdefault(sid, []).append(pos)
    assert db._session_index == expected


def test_get_upsert_delete_rename_with_index():
    db = InMemoryDb()
    db.upsert_session(_sess("s1", user_id="u1"))
    db.upsert_session(_sess("s2", user_id="u2"))
    _assert_index_consistent(db)

    got = db.get_session("s1", user_id="u1")
    assert got is not None and got.session_id == "s1"
    assert db.get_session("s1", user_id="other") is None  # user_id filter
    assert db.get_session("missing") is None

    # Update (same session_id + agent) must not duplicate, index unchanged.
    db.upsert_session(_sess("s1", user_id="u1"))
    assert len(db._sessions) == 2
    assert db._session_index["s1"] == [0]
    _assert_index_consistent(db)

    # Rename keeps the position/id; index stays valid.
    renamed = db.rename_session("s2", None, "renamed", user_id="u2")
    assert renamed is not None
    _assert_index_consistent(db)

    # Delete rebuilds positions -> index rebuilt.
    assert db.delete_session("s1") is True
    assert db.get_session("s1") is None
    assert db.get_session("s2", user_id="u2") is not None
    _assert_index_consistent(db)


def test_delete_sessions_keeps_index_consistent():
    db = InMemoryDb()
    for i in range(5):
        db.upsert_session(_sess(f"s{i}"))
    db.delete_sessions(["s1", "s3"])
    assert {sd["session_id"] for sd in db._sessions} == {"s0", "s2", "s4"}
    _assert_index_consistent(db)
    assert db.get_session("s1") is None
    assert db.get_session("s2") is not None


def test_parity_with_full_scan_under_random_ops():
    db = InMemoryDb()
    rng = random.Random(20260624)
    ids = [f"s{i}" for i in range(6)]

    for _ in range(300):
        op = rng.choice(["upsert", "delete", "delete_many", "get", "rename"])
        sid = rng.choice(ids)
        if op == "upsert":
            db.upsert_session(_sess(sid, user_id=rng.choice([None, "u1", "u2"])))
        elif op == "delete":
            db.delete_session(sid, user_id=rng.choice([None, "u1"]))
        elif op == "delete_many":
            db.delete_sessions(rng.sample(ids, 2))
        elif op == "rename":
            db.rename_session(sid, None, f"name-{rng.randint(0, 9)}")
        else:  # get -> must match a brute-force scan of _sessions (original semantics)
            uid = rng.choice([None, "u1", "u2"])
            got = db.get_session(sid, user_id=uid, deserialize=False)
            ref = next(
                (deepcopy(s) for s in db._sessions if s.get("session_id") == sid and (uid is None or s.get("user_id") == uid)),
                None,
            )
            assert got == ref, (sid, uid)
        _assert_index_consistent(db)
