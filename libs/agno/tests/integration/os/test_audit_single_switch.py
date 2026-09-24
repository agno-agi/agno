"""Authorization(audit=...) is the single switch for BOTH audit trails.

The object owns the decision trail (every allow/deny) and its own role-change trail, and AgentOS
hands the same sink to the user directory for its change trail. The directory has no audit knob
of its own: audit has one owner. No sink -> both trails stay off. These pin the wiring so a
one-line switch never quietly leaves half the audit off.
"""

import pytest

pytest.importorskip("sqlalchemy")

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import (
    Authorization,  # noqa: E402
    UserDirectory,  # noqa: E402
)
from agno.os.authz.audit import DbAuditSink  # noqa: E402

SECRET = "audit-switch-secret-at-least-256-bits-xxxxxxxxxx"


def _db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "os.db"))


def _roles(db, **kw):
    return Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", **kw)


def _os(db, roles, users):
    return AgentOS(
        id="audit-os",
        agents=[Agent(id="a", name="R", db=InMemoryDb())],
        db=db,
        user_directory=users,  # directory is top-level now
        authorization=roles,
    )


def test_single_audit_switch_feeds_change_and_decision_trails(tmp_path):
    db = _db(tmp_path)
    sink = DbAuditSink(db=db)
    roles, users = _roles(db, audit=sink), UserDirectory(db=db)
    app = _os(db, roles, users).get_app()

    assert getattr(app.state, "authz_audit", None) is sink  # decision trail
    assert roles.audit_sink is sink  # role change trail
    assert users._audit is sink  # directory change trail


def test_the_directory_records_its_changes_through_the_switch(tmp_path):
    db = _db(tmp_path)
    sink = DbAuditSink(db=db)
    roles, users = _roles(db, audit=sink), UserDirectory(db=db)
    _os(db, roles, users).get_app()

    users.upsert("bob", actor="alice")
    users.set_disabled("bob", True, actor="alice")
    actions = [(e["action"], e["target"], e["actor"]) for e in sink.read(limit=10)]
    assert ("user.created", "bob", "alice") in actions
    assert ("user.disabled", "bob", "alice") in actions


def test_no_audit_leaves_both_trails_off(tmp_path):
    db = _db(tmp_path)
    roles, users = _roles(db), UserDirectory(db=db)
    app = _os(db, roles, users).get_app()

    assert getattr(app.state, "authz_audit", None) is None
    assert roles.audit_sink is None
    assert users._audit is None
