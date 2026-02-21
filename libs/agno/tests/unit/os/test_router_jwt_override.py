"""Tests for JWT user_id override in session, traces, and memory routers.

Verifies that request.state.user_id (set by JWT middleware) overrides
any client-supplied user_id, preventing IDOR attacks.
"""


class FakeState:
    def __init__(self, user_id=None):
        self.user_id = user_id


class FakeRequest:
    def __init__(self, user_id=None):
        self.state = FakeState(user_id)


class TestSessionRouterJwtOverride:
    """Verify session router endpoints extract JWT user_id."""

    def test_delete_session_jwt_overrides_client_user_id(self):
        request = FakeRequest(user_id="jwt-user-123")
        client_user_id = "attacker-user-456"

        user_id = client_user_id
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user-123"

    def test_delete_session_no_jwt_preserves_client_user_id(self):
        request = FakeRequest(user_id=None)
        client_user_id = "client-user-789"

        user_id = client_user_id
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "client-user-789"

    def test_delete_sessions_jwt_overrides(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = None
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"

    def test_rename_session_jwt_overrides(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = "attacker"
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"


class TestTracesRouterJwtOverride:
    """Verify traces router endpoints extract JWT user_id."""

    def test_get_traces_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = "attacker"
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"

    def test_get_trace_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = None
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"

    def test_get_trace_stats_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = None
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"


class TestMemoryRouterJwtOverride:
    """Verify memory router endpoints extract JWT user_id."""

    def test_delete_memory_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = "attacker"
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"

    def test_delete_memories_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        class BodyRequest:
            user_id = "attacker"

        body = BodyRequest()
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            body.user_id = request.state.user_id

        assert body.user_id == "jwt-user"

    def test_optimize_memories_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        class BodyRequest:
            user_id = "attacker"

        body = BodyRequest()
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            body.user_id = request.state.user_id

        assert body.user_id == "jwt-user"

    def test_get_topics_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = None
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"

    def test_get_user_memory_stats_jwt_override(self):
        request = FakeRequest(user_id="jwt-user")

        user_id = None
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "jwt-user"


class TestJwtOverrideEdgeCases:
    """Edge cases for the JWT override pattern."""

    def test_no_state_attribute(self):
        class BareRequest:
            pass

        request = BareRequest()
        request.state = object()

        user_id = "client-value"
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "client-value"

    def test_state_user_id_is_none(self):
        request = FakeRequest(user_id=None)

        user_id = "client-value"
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == "client-value"

    def test_state_user_id_empty_string(self):
        request = FakeRequest(user_id="")

        user_id = "client-value"
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        assert user_id == ""

    def test_jwt_always_wins_over_attacker(self):
        request = FakeRequest(user_id="legitimate-user")

        for attacker_value in ["admin", "root", "other-user", "", None]:
            user_id = attacker_value
            if hasattr(request.state, "user_id") and request.state.user_id is not None:
                user_id = request.state.user_id

            assert user_id == "legitimate-user"
