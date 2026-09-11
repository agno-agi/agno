"""Authorization(audit=...) is a single switch for BOTH audit trails.

There are two trails: the CHANGE log (who edited roles/users -> authz_audit), which the STORES emit
to their own sink, and the DECISION log (every allow/deny -> authz_decisions), which the OS records
via app.state.authz_audit. Wiring the same sink in two places is a footgun (QA turned off one and
was surprised the other kept going). Authorization(audit=sink) feeds both, while an explicit sink
passed to a store of your own still wins there.
"""

import pytest

pytest.importorskip("sqlalchemy")

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization  # noqa: E402
from agno.os.authz.audit import DbAuditSink  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.authz.user_store import ManagedUserStore  # noqa: E402
from agno.os.config import UserDirectoryConfig  # noqa: E402

SECRET = "audit-switch-secret-at-least-256-bits-xxxxxxxxxx"


def _db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "os.db"))


def _os(db, roles, users, audit=False):
    return AgentOS(
        id="audit-os",
        agents=[Agent(id="a", name="R", db=InMemoryDb())],
        db=db,
        user_directory=UserDirectoryConfig(user_store=users),  # directory is top-level now
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", role_store=roles, audit=audit),
    )


def test_single_audit_switch_feeds_change_and_decision_trails(tmp_path):
    db = _db(tmp_path)
    sink = DbAuditSink(db=db)
    roles, users = ManagedRoleStore(db=db), ManagedUserStore(db=db)
    app = _os(db, roles, users, audit=sink).get_app()

    assert getattr(app.state, "authz_audit", None) is sink  # decision trail
    assert roles._audit is sink  # role change trail
    assert users._audit is sink  # directory change trail


def test_explicit_store_sink_wins_over_the_switch(tmp_path):
    db = _db(tmp_path)
    top, explicit = DbAuditSink(db=db), DbAuditSink(db=db)
    roles = ManagedRoleStore(db=db, audit=explicit)  # explicit on the store
    users = ManagedUserStore(db=db)  # no explicit -> should adopt the switch
    app = _os(db, roles, users, audit=top).get_app()

    assert getattr(app.state, "authz_audit", None) is top  # the switch feeds the decision trail
    assert roles._audit is explicit  # store keeps its own
    assert users._audit is top  # the one without an explicit sink adopts the switch


def test_no_audit_leaves_both_trails_off(tmp_path):
    db = _db(tmp_path)
    roles, users = ManagedRoleStore(db=db), ManagedUserStore(db=db)
    app = _os(db, roles, users).get_app()

    assert getattr(app.state, "authz_audit", None) is None
    assert roles._audit is None
    assert users._audit is None
