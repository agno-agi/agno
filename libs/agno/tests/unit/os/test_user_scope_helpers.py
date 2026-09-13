"""Unit tests for the user-scope helpers in ``agno.os.middleware.user_scope``.

These replace the adapter-focused tests that lived in the deleted
``test_user_scoped_db.py``. The behaviours the adapter used to provide —
JWT sub injection on user-scoped reads, coercion on writes, admin bypass,
isolation-flag short-circuit — are now expressed as explicit calls to the
helpers in routers, so the unit tests follow the helpers.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
from agno.os.auth import INTERNAL_SCHEDULER_USER_ID
from agno.os.middleware.user_scope import (
    apply_scope_to_kwargs,
    assert_session_writable,
    enforce_owner_on_entity,
    get_scoped_user_id,
    get_scoped_user_id_for_ws,
    resolve_db_and_scope,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    user_id=None,
    scopes=None,
    admin_scope=None,
    user_isolation_enabled=True,
):
    """Build a stand-in FastAPI request whose ``.state`` matches what the
    JWT middleware would populate.

    Each test sets only the attributes it cares about so missing attributes
    behave like genuine ``AttributeError``\\ s (not silently truthy
    MagicMock auto-attrs) — that matches what real production requests
    look like when a claim was absent.
    """
    request = MagicMock()
    request.state = MagicMock()
    request.state.user_isolation_enabled = user_isolation_enabled
    if user_id is not None:
        request.state.user_id = user_id
    else:
        del request.state.user_id
    if scopes is not None:
        request.state.scopes = scopes
    else:
        del request.state.scopes
    if admin_scope is not None:
        request.state.admin_scope = admin_scope
    else:
        # Drop the attribute entirely so the helper falls back to the
        # configured default rather than picking up MagicMock's auto-attr.
        del request.state.admin_scope
    return request


# ---------------------------------------------------------------------------
# get_scoped_user_id
# ---------------------------------------------------------------------------


class TestGetScopedUserId:
    """The strict scoping function — only returns a user_id when isolation
    is on AND the caller is a non-admin authenticated user."""

    def test_regular_user_returns_user_id(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        assert get_scoped_user_id(request) == "user-123"

    def test_admin_returns_none(self):
        request = _make_request(user_id="admin-user", scopes=["agent_os:admin"])
        assert get_scoped_user_id(request) is None

    def test_admin_with_other_scopes_returns_none(self):
        """Admin scope wins regardless of other scopes present."""
        request = _make_request(user_id="admin-user", scopes=["agents:read", "agent_os:admin", "sessions:read"])
        assert get_scoped_user_id(request) is None

    def test_no_user_id_fails_closed(self):
        """An identity-less caller under isolation is denied, not left unscoped."""
        request = _make_request(user_id=None, scopes=[])
        with pytest.raises(HTTPException) as exc:
            get_scoped_user_id(request)
        assert exc.value.status_code == 403

    def test_no_user_id_returns_none_when_isolation_off(self):
        request = _make_request(user_id=None, scopes=[], user_isolation_enabled=False)
        assert get_scoped_user_id(request) is None

    def test_no_scopes_returns_user_id(self):
        request = _make_request(user_id="user-123", scopes=None)
        assert get_scoped_user_id(request) == "user-123"

    def test_empty_scopes_returns_user_id(self):
        request = _make_request(user_id="user-123", scopes=[])
        assert get_scoped_user_id(request) == "user-123"

    def test_custom_admin_scope_honoured(self):
        request = _make_request(
            user_id="admin-user",
            scopes=["custom:admin"],
            admin_scope="custom:admin",
        )
        assert get_scoped_user_id(request) is None

    def test_default_admin_scope_ignored_when_custom_configured(self):
        """Once a custom admin scope is set, the default must NOT grant bypass."""
        request = _make_request(
            user_id="user-123",
            scopes=["agent_os:admin"],
            admin_scope="custom:admin",
        )
        assert get_scoped_user_id(request) == "user-123"

    def test_off_by_default_short_circuits_to_none(self):
        """``user_isolation=False`` must return None even for non-admin JWT users."""
        request = _make_request(
            user_id="user-123",
            scopes=["agents:read"],
            user_isolation_enabled=False,
        )
        assert get_scoped_user_id(request) is None

    def test_missing_user_isolation_attr_short_circuits_to_none(self):
        """Legacy deployments that don't set the flag at all must default to
        the safe "no isolation" branch."""
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        del request.state.user_isolation_enabled
        assert get_scoped_user_id(request) is None


class TestSchedulerOwnerHeader:
    """The scheduler sentinel scopes to the owner the executor forwards; other callers' headers are ignored."""

    @staticmethod
    def _with_header(request, owner):
        request.headers = {SCHEDULE_OWNER_HEADER: owner}
        return request

    def test_sentinel_scopes_to_the_forwarded_owner(self):
        request = self._with_header(_make_request(user_id=INTERNAL_SCHEDULER_USER_ID, scopes=[]), "alice")
        assert get_scoped_user_id(request) == "alice"

    def test_sentinel_without_a_forwarded_owner_is_unscoped(self):
        """An unowned (system) schedule forwards no owner."""
        request = _make_request(user_id=INTERNAL_SCHEDULER_USER_ID, scopes=[])
        request.headers = {}
        assert get_scoped_user_id(request) is None

    def test_header_is_ignored_for_a_normal_caller(self):
        request = self._with_header(_make_request(user_id="bob", scopes=["agents:read"]), "alice")
        assert get_scoped_user_id(request) == "bob"

    def test_header_is_ignored_for_an_admin(self):
        request = self._with_header(_make_request(user_id="admin-user", scopes=["agent_os:admin"]), "alice")
        assert get_scoped_user_id(request) is None


class TestServiceAccountSelfScoping:
    """D1: service-account (``sa:``) principals always self-scope to the data they
    created, even when ``user_isolation`` is off, unless the token carries admin.
    This keeps a default PAT from reading every user's history while leaving an
    admin-minted debugging escape hatch."""

    def test_sa_self_scopes_when_isolation_off(self):
        request = _make_request(
            user_id="sa:bot",
            scopes=["sessions:read", "agents:run"],
            user_isolation_enabled=False,
        )
        assert get_scoped_user_id(request) == "sa:bot"

    def test_sa_self_scopes_when_isolation_on(self):
        request = _make_request(user_id="sa:bot", scopes=["sessions:read"], user_isolation_enabled=True)
        assert get_scoped_user_id(request) == "sa:bot"

    def test_sa_with_admin_reads_across_users(self):
        request = _make_request(
            user_id="sa:bot",
            scopes=["agent_os:admin"],
            user_isolation_enabled=False,
        )
        assert get_scoped_user_id(request) is None

    def test_sa_with_admin_reads_across_users_isolation_on(self):
        # The admin escape hatch must also work with user_isolation enabled, not only off.
        request = _make_request(
            user_id="sa:bot",
            scopes=["agent_os:admin"],
            user_isolation_enabled=True,
        )
        assert get_scoped_user_id(request) is None

    def test_human_user_still_unscoped_when_isolation_off(self):
        """The self-scoping is scoped to sa: principals — humans keep legacy behaviour."""
        request = _make_request(user_id="alice", scopes=["sessions:read"], user_isolation_enabled=False)
        assert get_scoped_user_id(request) is None


# ---------------------------------------------------------------------------
# apply_scope_to_kwargs
# ---------------------------------------------------------------------------


class TestApplyScopeToKwargs:
    """Dict-spread wrapper around ``get_scoped_user_id`` + ``fallback_user_id``.

    Contract: when ``user_isolation`` is on and the caller is a non-admin
    authenticated user, the JWT sub is injected as ``user_id``. Otherwise
    (admin / unscoped / no JWT) the caller-supplied ``fallback_user_id`` is
    honoured — preserving the legacy "pass the query param through" behaviour.
    """

    def test_strict_path_injects_user_id(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        out = apply_scope_to_kwargs(request, {"limit": 10, "page": 1})
        assert out == {"limit": 10, "page": 1, "user_id": "user-123"}

    def test_caller_supplied_user_id_overridden_when_isolation_on(self):
        """With isolation on, a non-admin caller cannot spoof ``user_id``."""
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        out = apply_scope_to_kwargs(request, {"user_id": "attacker"})
        assert out["user_id"] == "user-123"

    def test_isolation_off_uses_fallback_user_id(self):
        """With isolation OFF the JWT sub is intentionally NOT forced — the
        caller-supplied query param wins. This pins the documented "opt-in
        means opt-in" contract: turning isolation off restores legacy
        unscoped behaviour."""
        request = _make_request(
            user_id="jwt_alice",
            scopes=["agents:read"],
            user_isolation_enabled=False,
        )
        out = apply_scope_to_kwargs(request, fallback_user_id="query-id")
        assert out["user_id"] == "query-id"

    def test_admin_falls_back_to_query_param(self):
        """Admins keep act-on-behalf via the query param even with isolation on."""
        request = _make_request(user_id="admin-user", scopes=["agent_os:admin"])
        out = apply_scope_to_kwargs(request, fallback_user_id="filter-by-this")
        assert out["user_id"] == "filter-by-this"

    def test_no_jwt_no_fallback_omits_user_id(self):
        """When there's nothing to inject, ``user_id`` stays absent so the
        downstream DB call sees the same shape it would have before."""
        request = _make_request(user_id=None, scopes=[], user_isolation_enabled=False)
        out = apply_scope_to_kwargs(request, {"limit": 5})
        assert "user_id" not in out
        assert out == {"limit": 5}

    def test_identity_less_caller_under_isolation_raises(self):
        """The fail-closed 403 propagates through the helpers, not just the getter."""
        request = _make_request(user_id=None, scopes=[])
        with pytest.raises(HTTPException) as exc:
            apply_scope_to_kwargs(request, {"limit": 5})
        assert exc.value.status_code == 403

    def test_none_kwargs_returns_dict(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        out = apply_scope_to_kwargs(request, None)
        assert out == {"user_id": "user-123"}

    def test_caller_kwargs_not_mutated_in_place(self):
        """Helper must not mutate the caller's dict (it returns a new one)."""
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        source = {"limit": 1}
        apply_scope_to_kwargs(request, source)
        assert source == {"limit": 1}


# ---------------------------------------------------------------------------
# resolve_db_and_scope
# ---------------------------------------------------------------------------


class TestResolveDbAndScope:
    """Combined DB lookup + user_id resolution. Backed by ``get_db`` so the
    tests exercise the same dispatch path used in production routers."""

    @pytest.mark.asyncio
    async def test_returns_db_and_scoped_user(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        db = MagicMock()
        dbs = {"only": [db]}
        resolved_db, resolved_uid = await resolve_db_and_scope(request, dbs)
        assert resolved_db is db
        assert resolved_uid == "user-123"

    @pytest.mark.asyncio
    async def test_admin_falls_back_to_query_param(self):
        request = _make_request(user_id="admin-user", scopes=["agent_os:admin"])
        db = MagicMock()
        dbs = {"only": [db]}
        resolved_db, resolved_uid = await resolve_db_and_scope(request, dbs, fallback_user_id="alice")
        assert resolved_db is db
        assert resolved_uid == "alice"

    @pytest.mark.asyncio
    async def test_no_jwt_returns_fallback(self):
        request = _make_request(user_id=None, scopes=[], user_isolation_enabled=False)
        db = MagicMock()
        dbs = {"only": [db]}
        _, resolved_uid = await resolve_db_and_scope(request, dbs, fallback_user_id="from-query")
        assert resolved_uid == "from-query"

    @pytest.mark.asyncio
    async def test_isolation_off_uses_fallback_user_id(self):
        """With isolation OFF the helper does NOT force the JWT sub — the
        caller-supplied query param wins. Same contract as
        ``apply_scope_to_kwargs``: opt-in means opt-in."""
        request = _make_request(
            user_id="jwt_alice",
            scopes=["agents:read"],
            user_isolation_enabled=False,
        )
        db = MagicMock()
        dbs = {"only": [db]}
        _, resolved_uid = await resolve_db_and_scope(request, dbs, fallback_user_id="query-id")
        assert resolved_uid == "query-id"


# ---------------------------------------------------------------------------
# enforce_owner_on_entity
# ---------------------------------------------------------------------------


class _Entity:
    """Mutable stand-in for Session / UserMemory / Trace upsert payloads."""

    def __init__(self, user_id=None):
        self.user_id = user_id


class _ImmutableEntity:
    """Carrier that can't have ``user_id`` overwritten — e.g. a frozen dataclass
    or a namedtuple-shaped struct. The helper must log a warning rather than
    crash the request."""

    __slots__ = ("user_id",)

    def __init__(self, user_id):
        object.__setattr__(self, "user_id", user_id)

    def __setattr__(self, name, value):  # type: ignore[override]
        raise AttributeError("immutable")


class TestEnforceOwnerOnEntity:
    """Write-side coercion used by session / memory upsert routes."""

    def test_noop_when_isolation_disabled(self):
        request = _make_request(
            user_id="jwt_alice",
            scopes=["agents:read"],
            user_isolation_enabled=False,
        )
        entity = _Entity(user_id="anyone")
        enforce_owner_on_entity(request, entity, kind="session")
        # No isolation in force → entity is left alone.
        assert entity.user_id == "anyone"

    def test_noop_for_admin(self):
        request = _make_request(user_id="admin-user", scopes=["agent_os:admin"])
        entity = _Entity(user_id="not-the-admin")
        enforce_owner_on_entity(request, entity, kind="session")
        assert entity.user_id == "not-the-admin"

    def test_noop_when_no_jwt(self):
        request = _make_request(user_id=None, scopes=[], user_isolation_enabled=False)
        entity = _Entity(user_id="someone")
        enforce_owner_on_entity(request, entity, kind="session")
        assert entity.user_id == "someone"

    def test_coerces_mismatched_user_id(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        entity = _Entity(user_id="user-EVIL")
        enforce_owner_on_entity(request, entity, kind="session")
        assert entity.user_id == "user-123"

    def test_coerces_unset_user_id(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        entity = _Entity(user_id=None)
        enforce_owner_on_entity(request, entity, kind="memory")
        assert entity.user_id == "user-123"

    def test_idempotent_when_matching(self):
        request = _make_request(user_id="user-123", scopes=["agents:read"])
        entity = _Entity(user_id="user-123")
        enforce_owner_on_entity(request, entity, kind="memory")
        assert entity.user_id == "user-123"

    def test_warns_on_mismatch(self, monkeypatch):
        """Patch ``log_warning`` to capture invocations directly.

        ``log_warning`` is a module-level wrapper around Agno's own logger
        (``propagate=False``), and other tests in the broader suite mutate
        that logger's config in ways pytest's ``caplog`` can't reliably
        observe. Patching the symbol the helper actually calls is the
        sturdiest way to assert the message content without coupling to
        logger state-bleed across files.
        """
        from agno.os.middleware import user_scope as user_scope_mod

        calls: list[str] = []

        def _capture(msg, *args, **_kwargs):
            calls.append(msg if not args else (msg % args))

        monkeypatch.setattr(user_scope_mod, "log_warning", _capture)

        request = _make_request(user_id="user-123", scopes=["agents:read"])
        entity = _Entity(user_id="user-EVIL")
        enforce_owner_on_entity(request, entity, kind="session")

        assert any("user-EVIL" in m and "user-123" in m for m in calls), f"expected a coercion warning, got: {calls}"

    def test_immutable_carrier_does_not_raise(self, monkeypatch):
        from agno.os.middleware import user_scope as user_scope_mod

        calls: list[str] = []

        def _capture(msg, *args, **_kwargs):
            calls.append(msg if not args else (msg % args))

        monkeypatch.setattr(user_scope_mod, "log_warning", _capture)

        request = _make_request(user_id="user-123", scopes=["agents:read"])
        entity = _ImmutableEntity(user_id="anything")
        # Must not raise — frozen dataclasses or other immutable carriers
        # are a known footgun; the helper is expected to warn and move on.
        enforce_owner_on_entity(request, entity, kind="session")
        assert any("unable to coerce" in m for m in calls)


class TestGetScopedUserIdFromParts:
    """The WebSocket handlers have no Request, so they scope from explicit auth
    flags. This must match get_scoped_user_id's precedence exactly."""

    def test_regular_user_scopes_only_when_isolation_on(self):
        assert (
            get_scoped_user_id_for_ws("user-123", jwt_enabled=True, is_admin=False, user_isolation_enabled=True)
            == "user-123"
        )
        assert (
            get_scoped_user_id_for_ws("user-123", jwt_enabled=True, is_admin=False, user_isolation_enabled=False)
            is None
        )

    def test_admin_is_unscoped(self):
        assert (
            get_scoped_user_id_for_ws("user-123", jwt_enabled=True, is_admin=True, user_isolation_enabled=True) is None
        )

    def test_sa_self_scopes_regardless_of_isolation(self):
        # Regression: over the WS a service account was unscoped when isolation was off.
        assert (
            get_scoped_user_id_for_ws("sa:bot", jwt_enabled=True, is_admin=False, user_isolation_enabled=False)
            == "sa:bot"
        )
        assert (
            get_scoped_user_id_for_ws("sa:bot", jwt_enabled=True, is_admin=False, user_isolation_enabled=True)
            == "sa:bot"
        )

    def test_sa_with_admin_reads_across_users(self):
        assert (
            get_scoped_user_id_for_ws("sa:bot", jwt_enabled=True, is_admin=True, user_isolation_enabled=False) is None
        )

    def test_no_user_id_fails_closed_under_isolation(self):
        # An identity-less token under isolation must 403 like the REST helper,
        # not fall through to unscoped (which would skip the run-ownership gates).
        with pytest.raises(HTTPException) as exc:
            get_scoped_user_id_for_ws(None, jwt_enabled=True, is_admin=False, user_isolation_enabled=True)
        assert exc.value.status_code == 403

        with pytest.raises(HTTPException):
            get_scoped_user_id_for_ws("", jwt_enabled=True, is_admin=False, user_isolation_enabled=True)

    def test_no_user_id_is_unscoped_when_isolation_off(self):
        assert get_scoped_user_id_for_ws(None, jwt_enabled=True, is_admin=False, user_isolation_enabled=False) is None
        assert get_scoped_user_id_for_ws(None, jwt_enabled=False, is_admin=False, user_isolation_enabled=True) is None


class TestAssertSessionWritable:
    """Pins the ownership predicate the run routes apply before dispatching."""

    def _db(self, row):
        db = MagicMock()
        db.get_session = MagicMock(return_value=row)
        return db

    @pytest.mark.asyncio
    async def test_missing_session_is_allowed(self):
        db = self._db(None)
        await assert_session_writable(db, "s1", "user-a", session_type=SessionType.AGENT)

    @pytest.mark.asyncio
    async def test_owner_is_allowed(self):
        db = self._db({"user_id": "user-a"})
        await assert_session_writable(db, "s1", "user-a", session_type=SessionType.AGENT)

    @pytest.mark.asyncio
    async def test_unowned_session_is_allowed(self):
        # The shared-session case the storage predicate already admits.
        db = self._db({"user_id": None})
        await assert_session_writable(db, "s1", "user-a", session_type=SessionType.AGENT)

    @pytest.mark.asyncio
    async def test_foreign_session_raises_404(self):
        db = self._db({"user_id": "user-b"})
        with pytest.raises(HTTPException) as exc:
            await assert_session_writable(db, "s1", "user-a", session_type=SessionType.AGENT)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Session not found"

    @pytest.mark.asyncio
    async def test_foreign_session_never_raises_403(self):
        db = self._db({"user_id": "user-b"})
        with pytest.raises(HTTPException) as exc:
            await assert_session_writable(db, "s1", "user-a")
        assert exc.value.status_code != 403

    @pytest.mark.asyncio
    async def test_identity_less_caller_into_owned_session_raises_404(self):
        # An implementation that short-circuits on ``user_id is None`` passes every
        # other case here and still leaks.
        db = self._db({"user_id": "user-b"})
        with pytest.raises(HTTPException) as exc:
            await assert_session_writable(db, "s1", None)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_identity_less_caller_into_unowned_session_is_allowed(self):
        # Dev mode and the eval suite ride this branch, not a None short-circuit.
        db = self._db({"user_id": None})
        await assert_session_writable(db, "s1", None)

    @pytest.mark.asyncio
    async def test_admin_bypasses(self):
        db = self._db({"user_id": "user-b"})
        await assert_session_writable(db, "s1", "user-a", is_admin=True)
        db.get_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_db_is_allowed(self):
        await assert_session_writable(None, "s1", "user-a")

    @pytest.mark.asyncio
    async def test_blank_session_id_is_allowed(self):
        db = self._db({"user_id": "user-b"})
        await assert_session_writable(db, "", "user-a")
        await assert_session_writable(db, None, "user-a")
        db.get_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_probe_does_not_filter_by_user_id(self):
        # The probe must be unscoped or it can never see a foreign owner.
        db = self._db({"user_id": "user-a"})
        await assert_session_writable(db, "s1", "user-a")
        kwargs = db.get_session.call_args.kwargs
        assert kwargs.get("user_id") is None

    @pytest.mark.asyncio
    async def test_probe_is_bounded(self):
        db = self._db({"user_id": "user-a"})
        await assert_session_writable(db, "s1", "user-a")
        kwargs = db.get_session.call_args.kwargs
        assert kwargs["runs_limit"] == 1
        assert kwargs["deserialize"] is False

    @pytest.mark.asyncio
    async def test_async_db_is_awaited(self):
        db = MagicMock(spec=AsyncBaseDb)
        db.get_session = AsyncMock(return_value={"user_id": "user-b"})
        with pytest.raises(HTTPException) as exc:
            await assert_session_writable(db, "s1", "user-a")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_remote_db_is_skipped(self):
        from agno.remote.base import RemoteDb

        db = MagicMock(spec=RemoteDb)
        await assert_session_writable(db, "s1", "user-a")
        db.get_session.assert_not_called()
