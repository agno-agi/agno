"""Per-request DB query budget for managed-roles authorization.

Pins the number of DB round-trips a single request's authz checks make, so a change
that reintroduces the per-call table re-resolution (an existence query + a schema
reflection before every authz query -- the bulk of the old cost) fails loudly.

The dominant fix is caching the resolved authz Table objects (db adapter); with it,
a steady-state request that resolves roles + policies and runs the kill-switch check
is a handful of small indexed reads, memoized so the route gate and the per-resource
gate share one resolution.
"""

import os
import tempfile

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import event  # noqa: E402

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os.authz._request_scope import request_scope  # noqa: E402
from agno.os.authz.provider import AuthorizationContext  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.authz.user_store import ManagedUserStore  # noqa: E402


def _count_authz_queries():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)  # ONE shared db, exactly how AgentOS adopts it for both stores
    roles = ManagedRoleStore(db=db)
    roles.set_role_scopes("viewer", ["agents:*:read", "workflows:*:run"])
    roles.assign("alice", "viewer")
    users = ManagedUserStore(db=db)
    users.upsert("alice", email="a@co")
    provider = roles.provider

    n = {"c": 0}

    @event.listens_for(db.db_engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, ctx, many):  # noqa: ANN001
        if any(t in statement for t in ("authz_users", "authz_grouping", "authz_policy")):
            n["c"] += 1

    ctx = AuthorizationContext(
        principal_id="alice", scopes=[], claims={}, resource_type="agents", resource_id="a1", action="read"
    )

    # Warm the process once (first-ever table resolution), like a live worker after boot.
    with request_scope():
        users.is_disabled("alice")
        provider.check(ctx)

    n["c"] = 0
    with request_scope():  # one steady-state request: kill-switch + route gate + per-resource gate
        assert users.is_disabled("alice") is False
        assert provider.check(ctx) is True
        assert provider.check(ctx) is True  # second gate: memoized, no new resolution
    return n["c"]


def test_per_request_authz_query_budget():
    count = _count_authz_queries()
    # Before the table-object cache this was ~14 (every authz call re-ran an existence
    # check + reflection). Budget of 6 pins the fix; the real reads are the kill-switch,
    # the subject/role-collision guard, the subject's roles (+ one nesting probe), and the
    # policies -- all indexed, and memoized once across both gates.
    assert count <= 6, f"per-request authz queries regressed to {count} (expected <= 6)"
