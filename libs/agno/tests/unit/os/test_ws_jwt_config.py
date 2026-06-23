"""Unit tests for the WebSocket JWT config resolver.

Covers the manual-setup gap: when a user does
``app.add_middleware(JWTMiddleware, ...)`` instead of going through
``AgentOS(authorization=True)``, ``app.state.jwt_validator`` is only set
lazily during HTTP dispatch. The FIRST WebSocket connection arriving before
any HTTP request would otherwise silently fall through to ``requires_auth=False``.

``resolve_ws_jwt_config`` bridges that gap by walking ``app.user_middleware``
to find a ``JWTMiddleware`` entry and building a validator from its kwargs.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from agno.os.middleware.jwt import JWTMiddleware
from agno.os.scopes import AgentOSScope
from agno.os.utils import resolve_ws_jwt_config


def _make_fake_app(*, state_attrs: dict[str, Any] | None = None, middleware_entries: list | None = None):
    """Build a stand-in FastAPI app object exposing only what the resolver reads."""
    state = SimpleNamespace(**(state_attrs or {}))
    app = MagicMock()
    app.state = state
    app.user_middleware = middleware_entries or []
    return app


class TestResolveWsJwtConfigAgentOSPath:
    """When AgentOS pre-populates app.state, the resolver returns those values."""

    def test_returns_state_values_when_validator_already_set(self):
        validator = MagicMock(name="validator")
        app = _make_fake_app(
            state_attrs={
                "jwt_validator": validator,
                "jwt_verify_audience": True,
                "jwt_audience": "my-os",
                "admin_scope": "custom:admin",
                "user_isolation_enabled": True,
            }
        )

        cfg = resolve_ws_jwt_config(app)

        assert cfg["validator"] is validator
        assert cfg["verify_audience"] is True
        assert cfg["audience"] == "my-os"
        assert cfg["admin_scope"] == "custom:admin"
        assert cfg["user_isolation"] is True
        assert cfg["auth_required"] is True

    def test_state_attrs_default_when_unset(self):
        validator = MagicMock(name="validator")
        app = _make_fake_app(state_attrs={"jwt_validator": validator})

        cfg = resolve_ws_jwt_config(app)

        assert cfg["validator"] is validator
        assert cfg["verify_audience"] is False
        assert cfg["audience"] is None
        assert cfg["admin_scope"] is None
        # user_isolation must default to False even when the validator is set
        # - this is the opt-in safety net for legacy deployments.
        assert cfg["user_isolation"] is False
        assert cfg["auth_required"] is True


class TestResolveWsJwtConfigManualSetupPath:
    """When app.state.jwt_validator is unset, walk user_middleware."""

    def test_returns_none_when_no_jwt_middleware(self):
        app = _make_fake_app(middleware_entries=[])

        cfg = resolve_ws_jwt_config(app)

        assert cfg["validator"] is None
        assert cfg["verify_audience"] is False
        assert cfg["audience"] is None
        assert cfg["user_isolation"] is False

    def test_builds_validator_from_jwt_middleware_kwargs(self):
        # Simulate what Starlette stores in user_middleware
        entry = SimpleNamespace(
            cls=JWTMiddleware,
            kwargs={
                "verification_keys": ["test-secret"],
                "algorithm": "HS256",
                "verify_audience": True,
                "audience": "manual-os",
                "admin_scope": "ops:admin",
                "user_isolation": True,
            },
        )
        app = _make_fake_app(middleware_entries=[entry])

        cfg = resolve_ws_jwt_config(app)

        assert cfg["validator"] is not None
        assert cfg["verify_audience"] is True
        assert cfg["audience"] == "manual-os"
        assert cfg["admin_scope"] == "ops:admin"
        assert cfg["user_isolation"] is True
        assert cfg["auth_required"] is True

        # The resolver must cache results on app.state for subsequent calls
        # and for the HTTP middleware that will run later.
        assert app.state.jwt_validator is cfg["validator"]
        assert app.state.jwt_verify_audience is True
        assert app.state.jwt_audience == "manual-os"
        assert app.state.admin_scope == "ops:admin"
        assert app.state.user_isolation_enabled is True

    def test_user_isolation_defaults_false_when_kwargs_omit_it(self):
        """Manual setups that don't pass user_isolation must default to False."""
        entry = SimpleNamespace(
            cls=JWTMiddleware,
            kwargs={
                "verification_keys": ["k"],
                "algorithm": "HS256",
            },
        )
        app = _make_fake_app(middleware_entries=[entry])

        cfg = resolve_ws_jwt_config(app)

        assert cfg["user_isolation"] is False
        assert app.state.user_isolation_enabled is False

    def test_lazy_validator_can_validate_token(self):
        """The lazily-constructed validator must actually verify tokens."""
        from datetime import UTC, datetime, timedelta

        import jwt

        entry = SimpleNamespace(
            cls=JWTMiddleware,
            kwargs={
                "verification_keys": ["lazy-secret"],
                "algorithm": "HS256",
            },
        )
        app = _make_fake_app(middleware_entries=[entry])

        cfg = resolve_ws_jwt_config(app)
        assert cfg["validator"] is not None

        token = jwt.encode(
            {
                "sub": "user-1",
                "scopes": ["agents:read"],
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "iat": datetime.now(UTC),
            },
            "lazy-secret",
            algorithm="HS256",
        )
        payload = cfg["validator"].validate_token(token)
        assert payload["sub"] == "user-1"

    def test_falls_back_to_deprecated_secret_key(self):
        """JWTMiddleware still supports the legacy secret_key kwarg; the WS
        resolver must include it in verification_keys when no other keys are
        provided. Otherwise the FIRST WS connection on a manual setup using
        secret_key cannot validate tokens."""
        from datetime import UTC, datetime, timedelta

        import jwt

        entry = SimpleNamespace(
            cls=JWTMiddleware,
            kwargs={
                # No verification_keys, only the deprecated secret_key.
                "secret_key": "legacy-shared-secret",
                "algorithm": "HS256",
            },
        )
        app = _make_fake_app(middleware_entries=[entry])

        cfg = resolve_ws_jwt_config(app)
        assert cfg["validator"] is not None

        token = jwt.encode(
            {
                "sub": "u",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "iat": datetime.now(UTC),
            },
            "legacy-shared-secret",
            algorithm="HS256",
        )
        payload = cfg["validator"].validate_token(token)
        assert payload["sub"] == "u"

    def test_does_not_cache_admin_scope_when_kwargs_omits_it(self):
        entry = SimpleNamespace(
            cls=JWTMiddleware,
            kwargs={
                "verification_keys": ["k"],
                "algorithm": "HS256",
            },
        )
        app = _make_fake_app(middleware_entries=[entry])
        cfg = resolve_ws_jwt_config(app)

        # The resolver leaves admin_scope unset on app.state; downstream code
        # is expected to fall back to AgentOSScope.ADMIN.value.
        assert cfg["admin_scope"] is None
        assert getattr(app.state, "admin_scope", None) is None


class TestResolveWsJwtConfigEdgeCases:
    def test_app_without_state_returns_blank(self):
        app = MagicMock(spec=[])  # no state attribute
        cfg = resolve_ws_jwt_config(app)
        assert cfg["validator"] is None
        assert cfg["auth_required"] is False

    def test_does_not_match_unrelated_middleware(self):
        """A non-JWT middleware entry must not be treated as JWT."""

        class OtherMiddleware:
            pass

        entry = SimpleNamespace(cls=OtherMiddleware, kwargs={})
        app = _make_fake_app(middleware_entries=[entry])

        cfg = resolve_ws_jwt_config(app)
        assert cfg["validator"] is None
        assert cfg["auth_required"] is False

    def test_broken_validator_returns_auth_required_true(self):
        """When JWTMiddleware is configured but the validator cannot be
        constructed (e.g. bad JWKS path), the resolver must signal that
        auth was intended so the WS endpoint rejects rather than silently
        falling through to unauthenticated mode."""
        entry = SimpleNamespace(
            cls=JWTMiddleware,
            kwargs={
                # jwks_file pointing to a non-existent path triggers an
                # exception inside JWTValidator construction.
                "jwks_file": "/nonexistent/bad/path.json",
                "algorithm": "RS256",
            },
        )
        app = _make_fake_app(middleware_entries=[entry])

        cfg = resolve_ws_jwt_config(app)

        assert cfg["validator"] is None
        assert cfg["auth_required"] is True


class TestAdminScopeDefault:
    """Sanity check: default admin scope is the agent_os:admin sentinel."""

    def test_default_admin_scope_value(self):
        assert AgentOSScope.ADMIN.value == "agent_os:admin"


class TestManualSetupHttpFirstPreservesWsConfig:
    """Regression: manual ``app.add_middleware(JWTMiddleware, ...)`` setups
    cache JWT auth config on ``app.state`` lazily inside the middleware's
    ``dispatch``. If an HTTP request fires before a WebSocket connection,
    ``dispatch`` must cache ALL the WS-relevant fields together — not just
    ``jwt_validator`` — otherwise ``resolve_ws_jwt_config`` returns early on
    the AgentOS-path branch and silently drops ``verify_audience``,
    ``audience``, ``admin_scope`` and ``user_isolation``.
    """

    @pytest.fixture
    def manual_setup(self):
        from agno.os.middleware.jwt import JWTMiddleware

        # Construct the middleware exactly the way ``app.add_middleware`` would
        # instantiate it. ``app=None`` is fine because we never invoke the
        # next-app callable here — we only exercise the state-caching prelude.
        middleware = JWTMiddleware(
            app=None,
            verification_keys=["test-secret"],
            algorithm="HS256",
            verify_audience=True,
            audience="manual-os",
            admin_scope="ops:admin",
            user_isolation=True,
        )
        return middleware

    @pytest.mark.asyncio
    async def test_dispatch_caches_full_ws_config_then_resolver_preserves_it(self, manual_setup):
        from datetime import UTC, datetime, timedelta
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        import jwt

        token = jwt.encode(
            {
                "sub": "u",
                "scopes": [],
                "aud": "manual-os",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            "test-secret",
            algorithm="HS256",
        )
        request = MagicMock()
        request.url = SimpleNamespace(path="/some/path")
        request.method = "GET"
        request.headers = {"Authorization": f"Bearer {token}", "origin": None}
        request.cookies = {}
        # The real FastAPI app object — that's what user_middleware is
        # attached to. We need a stand-in with both ``state`` and the empty
        # ``user_middleware`` list the resolver walks if app.state is bare.
        fake_app = MagicMock()
        fake_app.state = SimpleNamespace()
        fake_app.user_middleware = []
        request.app = fake_app

        from agno.os.middleware.jwt import JWTMiddleware as _MwClass  # noqa: F401

        # Make the request.state writable like real Starlette state.
        class _State:
            pass

        request.state = _State()

        call_next = AsyncMock(return_value=MagicMock(status_code=200))
        await manual_setup.dispatch(request, call_next)

        # All the WS-relevant fields must now be on app.state, not just the validator.
        assert fake_app.state.jwt_validator is manual_setup.validator
        assert fake_app.state.jwt_verify_audience is True
        assert fake_app.state.jwt_audience == "manual-os"
        assert fake_app.state.admin_scope == "ops:admin"
        assert fake_app.state.user_isolation_enabled is True

        # A subsequent WebSocket connection routes through resolve_ws_jwt_config.
        # It must take the AgentOS-path (validator already on app.state) and
        # return the full set of values rather than silently defaulting.
        cfg = resolve_ws_jwt_config(fake_app)
        assert cfg["validator"] is manual_setup.validator
        assert cfg["verify_audience"] is True
        assert cfg["audience"] == "manual-os"
        assert cfg["admin_scope"] == "ops:admin"
        assert cfg["user_isolation"] is True
