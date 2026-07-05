"""S3: with ``validate=False`` (unverified dev mode) and ``authorization=True``, a
token that cannot be decoded must NOT leave RBAC dormant. The decode-failure
fall-through has to mark ``authorization_enabled`` and an empty scope set so a garbage
token is treated exactly like a valid zero-scope token -- otherwise malformed input
gets MORE access than well-formed input, because every RBAC gate reads
``request.state.authorization_enabled`` (default False) and skips enforcement.
"""

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agno.os.middleware import JWTMiddleware


@pytest.fixture
def state_client():
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(request: Request):
        # "UNSET" distinguishes "attribute never set" from an explicit None identity.
        return {
            "authenticated": getattr(request.state, "authenticated", None),
            "authorization_enabled": getattr(request.state, "authorization_enabled", None),
            "scopes": getattr(request.state, "scopes", None),
            "user_id": getattr(request.state, "user_id", "UNSET"),
        }

    # Unverified dev mode with RBAC requested. No verification key needed (validate=False).
    app.add_middleware(JWTMiddleware, validate=False, authorization=True)
    return TestClient(app)


def _unsigned_token(scopes):
    # validate=False decodes without verifying the signature, so any secret works.
    return jwt.encode({"sub": "u", "scopes": scopes}, "unused", algorithm="HS256")


class TestValidateFalseFailsClosed:
    def test_garbage_token_enables_rbac_with_empty_scopes(self, state_client):
        resp = state_client.get("/whoami", headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The fix: RBAC is active (not dormant) and the caller carries no scopes.
        assert body["authorization_enabled"] is True
        assert body["scopes"] == []
        assert body["authenticated"] is False
        # Identity is pinned to None (no stale id leaks in), so user-isolation scopes by owner.
        assert body["user_id"] is None

    def test_garbage_token_matches_valid_empty_scope_token(self, state_client):
        garbage = state_client.get("/whoami", headers={"Authorization": "Bearer not-a-jwt"}).json()
        valid_empty = state_client.get("/whoami", headers={"Authorization": f"Bearer {_unsigned_token([])}"}).json()
        # Garbage input must not be more permissive than a valid zero-scope token.
        assert garbage["authorization_enabled"] == valid_empty["authorization_enabled"]
        assert garbage["scopes"] == valid_empty["scopes"] == []

    def test_valid_scoped_token_still_carries_its_scopes(self, state_client):
        body = state_client.get(
            "/whoami", headers={"Authorization": f"Bearer {_unsigned_token(['agents:read'])}"}
        ).json()
        assert body["authenticated"] is True
        assert body["authorization_enabled"] is True
        assert body["scopes"] == ["agents:read"]


class TestValidateFalseEnforcesScopesOnFallThrough:
    """The fall-through must run the SAME scope gate as the success path, so a malformed
    token is denied on scope-protected routes -- including routes gated only by the
    middleware's _check_scopes (memory/knowledge/sessions/metrics), which have no
    downstream dependency to catch them."""

    def test_garbage_token_denied_on_scope_gated_route(self, state_client):
        # /memories requires memories:read in the default scope map; a garbage token holds
        # no scopes, so the middleware denies it (403) before the request is routed.
        resp = state_client.get("/memories", headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 403, resp.text

    def test_garbage_matches_valid_empty_scope_token_on_scope_gated_route(self, state_client):
        garbage = state_client.get("/memories", headers={"Authorization": "Bearer not-a-jwt"})
        valid_empty = state_client.get("/memories", headers={"Authorization": f"Bearer {_unsigned_token([])}"})
        # Malformed input must be no more permissive than a valid zero-scope token.
        assert garbage.status_code == valid_empty.status_code == 403

    def test_garbage_token_allowed_on_unmapped_route(self, state_client):
        # An un-mapped path requires no scope, so it stays reachable -- matching a valid
        # zero-scope token (no over-denial).
        resp = state_client.get("/whoami", headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 200
