"""A raw ``agent_os:admin`` token scope must NOT confer admin under a managed-roles / ReBAC plane.

Regression for a cross-user isolation hole: ``caller_is_admin`` (which feeds
``assert_session_writable(is_admin=...)`` on every run endpoint) trusted a raw admin scope in
the token. Under a scope plane that is fine -- the token's scopes ARE the authority. Under a
managed-roles / ReBAC plane the token's scopes are inert (the store/engine decides), so a
validly-signed token carrying the literal ``agent_os:admin`` string could set ``is_admin=True``,
skip the cross-user session-ownership guard, and write a run into another user's session. The gate
must gate the admin scope on ``caller_scopes_are_authoritative``, mirroring ``get_scoped_user_id``.
"""

from types import SimpleNamespace

import pytest

pytest.importorskip("sqlalchemy")

from agno.os.authz.role_store import RoleStore  # noqa: E402
from agno.os.authz.scope_provider import ScopeAuthorizationProvider  # noqa: E402
from agno.os.middleware.user_scope import assert_session_writable, caller_is_admin  # noqa: E402


def _request(provider):
    """A caller whose token carries agent_os:admin, on an OS enforcing ``provider``."""
    app = SimpleNamespace(state=SimpleNamespace(authorization_provider=provider))
    state = SimpleNamespace(scopes=["agent_os:admin"], admin_scope=None, service_account_name=None)
    return SimpleNamespace(state=state, app=app)


def test_admin_scope_is_authority_only_under_a_scope_plane(tmp_path):
    # Scope plane: the token's scopes ARE the authority -> admin scope confers admin.
    assert caller_is_admin(_request(ScopeAuthorizationProvider())) is True

    # Managed-roles plane: the token's scopes are inert -> a raw admin scope does NOT confer admin.
    roles = RoleStore(db_url=f"sqlite:///{tmp_path}/roles.db")
    assert caller_is_admin(_request(roles.provider)) is False


@pytest.mark.asyncio
async def test_cross_user_session_write_is_refused_when_admin_scope_is_inert(tmp_path):
    """End-to-end of the guard: under managed roles, the admin-scope caller resolves to
    is_admin=False, so a run into a session owned by someone else is refused (404) instead of
    skipping the ownership check."""
    roles = RoleStore(db_url=f"sqlite:///{tmp_path}/roles.db")
    attacker_is_admin = caller_is_admin(_request(roles.provider))  # False, per the fix
    assert attacker_is_admin is False

    class _VictimSessionDb:
        # The session the attacker targets is owned by "victim".
        def get_session(self, session_id, session_type=None, deserialize=True, runs_limit=None):
            return {"user_id": "victim"}

    from fastapi import HTTPException

    # is_admin=False (the fixed resolution) -> the ownership guard bites.
    with pytest.raises(HTTPException) as exc:
        await assert_session_writable(_VictimSessionDb(), "victim-session", "attacker", is_admin=attacker_is_admin)
    assert exc.value.status_code == 404

    # Sanity: a genuine admin (is_admin=True) is still allowed through, as before.
    await assert_session_writable(_VictimSessionDb(), "victim-session", "attacker", is_admin=True)
