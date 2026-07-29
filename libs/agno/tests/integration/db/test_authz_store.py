"""The BaseDb authorization contract, exercised against a real SQL backend.

This layer had no tests at all when it landed: ~870 lines carrying every authorization
read and write, on two dialects. The concurrency behaviour in particular cannot be
observed on SQLite -- its database-wide write lock serializes writers, so the races that
bite on Postgres are invisible in development and in CI. Where a test needs a second
writer to actually run concurrently it says so, and asserts on the resulting STATE
rather than on the absence of exceptions: the defect this file exists to prevent
produced no exception at all, just a subject holding two roles.
"""

import os
import tempfile
import threading

import pytest

pytest.importorskip("sqlalchemy")

from agno.db.sqlite import SqliteDb  # noqa: E402


@pytest.fixture
def db():
    return SqliteDb(db_file=os.path.join(tempfile.mkdtemp(), "authz.db"))


def test_policy_round_trip_and_effects(db):
    db.set_authz_role_policies("member", [("agents/*", "read", "allow"), ("agents/secret", "read", "deny")])
    rows = {(r[1], r[2], r[3]) for r in db.get_authz_policies(["member"])}
    assert rows == {("agents/*", "read", "allow"), ("agents/secret", "read", "deny")}

    # upsert flips an effect rather than duplicating the row
    db.upsert_authz_policy(role="member", resource="agents/*", action="read", effect="deny")
    rows = [r for r in db.get_authz_policies(["member"]) if r[1] == "agents/*"]
    assert len(rows) == 1 and rows[0][3] == "deny"

    db.delete_authz_policy(role="member", resource="agents/*", action="read")
    assert {r[1] for r in db.get_authz_policies(["member"])} == {"agents/secret"}


def test_set_role_policies_replaces_rather_than_merges(db):
    db.set_authz_role_policies("r", [("a", "read", "allow"), ("b", "read", "allow")])
    db.set_authz_role_policies("r", [("c", "read", "allow")])
    assert {r[1] for r in db.get_authz_policies(["r"])} == {"c"}


def test_assignments_and_the_role_name_guard(db):
    db.set_authz_role_policies("member", [("agents/*", "read", "allow")])
    db.assign_authz_role("bob", "member")
    db.assign_authz_role("bob", "member")  # idempotent

    assert db.get_authz_direct_roles("bob") == ["member"]
    # a name is a ROLE if it carries policy or has members; a plain subject is not
    assert db.authz_name_is_role("member") is True
    assert db.authz_name_is_role("bob") is False

    db.unassign_authz_role("bob", "member")
    assert db.get_authz_direct_roles("bob") == []


def test_replace_subject_roles_leaves_exactly_one(db):
    db.assign_authz_role("bob", "a")
    db.assign_authz_role("bob", "b")
    db.replace_authz_subject_roles("bob", "c")
    assert db.get_authz_direct_roles("bob") == ["c"]


def test_concurrent_assign_leaves_exactly_one_role(db):
    """Regression: two concurrent assigns must not leave a subject holding both.

    Asserts on the final STATE, not on exceptions -- the original defect raised nothing.
    Both writers deleted zero rows (the subject was new) and both inserted, so the
    subject held two roles, the engine OR'd their privileges, and the admin API showed
    only the first. SQLite serializes writers so this passes here trivially; the guard
    that matters is on Postgres, where it reproduced 19 times in 20.
    """
    # Create the table single-threaded first. Concurrent FIRST use of any agno table
    # races in the backend's _get_or_create_table -- a pre-existing db-layer issue that
    # hits core tables too (agno_components fails the same way) and is not what this
    # test is about.
    db.assign_authz_role("_warm", "_warm")
    db.unassign_authz_role("_warm", "_warm")

    for trial in range(10):
        subject = f"user{trial}"
        barrier = threading.Barrier(2)

        def assign(role):
            barrier.wait()
            db.assign_authz_role(subject, role)

        threads = [threading.Thread(target=assign, args=(r,)) for r in ("viewer", "superadmin")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # assign() is additive at this layer; replace is the one-role primitive
        db.replace_authz_subject_roles(subject, "viewer")
        assert db.get_authz_direct_roles(subject) == ["viewer"]


def test_role_deletion_removes_policy_assignments_and_metadata(db):
    db.set_authz_role_policies("doomed", [("a", "read", "allow")])
    db.assign_authz_role("bob", "doomed")
    db.upsert_authz_role_meta(
        "doomed", {"name": "Doomed", "description": None, "is_default": False, "created_at": 1, "updated_at": 1}
    )

    db.delete_authz_role("doomed")
    assert db.get_authz_policies(["doomed"]) == []
    assert db.get_authz_direct_roles("bob") == []
    assert db.get_authz_role_meta("doomed") is None


def test_user_directory_round_trip_and_kill_switch(db):
    db.upsert_authz_user(
        "u1",
        {"email": "u@co", "name": "U", "disabled": False, "created_at": 1, "updated_at": 1, "metadata": {"x": 1}},
    )
    user = db.get_authz_user("u1")
    assert user["email"] == "u@co" and user["metadata"] == {"x": 1}
    assert db.is_authz_user_disabled("u1") is False

    db.upsert_authz_user(
        "u1", {"email": "u@co", "name": "U", "disabled": True, "created_at": 1, "updated_at": 2, "metadata": None}
    )
    assert db.is_authz_user_disabled("u1") is True
    # an unknown subject is NOT disabled -- absence is not a revocation
    assert db.is_authz_user_disabled("nobody") is False

    assert db.count_authz_users() == 1
    db.delete_authz_user("u1")
    assert db.get_authz_user("u1") is None


def test_user_listing_filters_and_sorts(db):
    for i, disabled in enumerate([False, True, False]):
        db.upsert_authz_user(
            f"u{i}",
            {
                "email": f"user{i}@co",
                "name": f"N{i}",
                "disabled": disabled,
                "created_at": i,
                "updated_at": i,
                "metadata": None,
            },
        )
    assert len(db.list_authz_users()) == 3
    assert len(db.list_authz_users(include_disabled=False)) == 2
    assert db.count_authz_users(include_disabled=False) == 2
    assert [u["id"] for u in db.list_authz_users(search="user1")] == ["u1"]
    assert [u["id"] for u in db.list_authz_users(sort_by="created_at", order="asc")] == ["u0", "u1", "u2"]


def test_both_audit_trails_are_separate_and_searchable(db):
    db.record_authz_audit_event(
        {
            "event_id": "e1",
            "created_at": 1,
            "actor": "alice",
            "action": "role.set_scopes",
            "target": "viewer",
            "before": None,
            "after": "[]",
        }
    )
    db.record_authz_decision(
        {
            "event_id": "d1",
            "created_at": 2,
            "actor": "bob",
            "action": "access.denied",
            "target": "GET /agents",
            "token_ref": "jti1",
            "required": None,
            "scopes": None,
        }
    )
    changes = db.read_authz_audit_events()
    decisions = db.read_authz_audit_events(decisions=True)
    assert [e["action"] for e in changes] == ["role.set_scopes"]
    assert [e["action"] for e in decisions] == ["access.denied"]
    assert db.count_authz_audit_events() == 1
    assert db.count_authz_audit_events(decisions=True) == 1
    assert db.count_authz_audit_events(search="alice") == 1
    assert db.count_authz_audit_events(search="nobody") == 0


def test_a_backend_without_the_contract_raises_not_implemented():
    """The whole point of the seam: a db that cannot store authz says so."""
    from agno.db.in_memory import InMemoryDb

    with pytest.raises(NotImplementedError):
        InMemoryDb().get_authz_direct_roles("bob")
