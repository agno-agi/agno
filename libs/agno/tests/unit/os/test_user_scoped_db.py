"""Tests for UserScopedDb, AsyncUserScopedDb wrappers, and get_scoped_user_id."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.db.base import SessionType
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.user_scoped_db import AsyncUserScopedDb, UserScopedDb


@pytest.fixture
def mock_db():
    """Create a mock BaseDb with all user-scoped methods."""
    db = MagicMock()
    db.id = "test-db"
    db.session_table_name = "sessions"
    db.culture_table_name = "culture"
    db.memory_table_name = "memories"
    db.metrics_table_name = "metrics"
    db.eval_table_name = "evals"
    db.knowledge_table_name = "knowledge"
    db.trace_table_name = "traces"
    db.span_table_name = "spans"
    return db


@pytest.fixture
def mock_async_db():
    """Create a mock AsyncBaseDb with all user-scoped methods."""
    db = AsyncMock()
    db.id = "test-async-db"
    db.session_table_name = "sessions"
    db.culture_table_name = "culture"
    db.memory_table_name = "memories"
    db.metrics_table_name = "metrics"
    db.eval_table_name = "evals"
    db.knowledge_table_name = "knowledge"
    db.trace_table_name = "traces"
    db.span_table_name = "spans"
    return db


class TestUserScopedDb:
    """Test sync UserScopedDb wrapper."""

    def test_user_id_injected_into_get_sessions(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_sessions(SessionType.AGENT, limit=10)
        mock_db.get_sessions.assert_called_once_with(session_type=SessionType.AGENT, limit=10, user_id="user-123")

    def test_user_id_injected_into_get_session(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_session("sess-1", SessionType.AGENT)
        mock_db.get_session.assert_called_once_with(
            session_id="sess-1", session_type=SessionType.AGENT, user_id="user-123"
        )

    def test_user_id_injected_into_delete_session(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.delete_session("sess-1")
        mock_db.delete_session.assert_called_once_with(session_id="sess-1", user_id="user-123")

    def test_user_id_injected_into_delete_sessions(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.delete_sessions(["sess-1", "sess-2"])
        mock_db.delete_sessions.assert_called_once_with(session_ids=["sess-1", "sess-2"], user_id="user-123")

    def test_user_id_injected_into_rename_session(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.rename_session("sess-1", SessionType.AGENT, "new-name")
        mock_db.rename_session.assert_called_once_with(
            session_id="sess-1", session_type=SessionType.AGENT, session_name="new-name", user_id="user-123"
        )

    def test_user_id_injected_into_get_traces(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_traces(agent_id="agent-1", limit=20)
        mock_db.get_traces.assert_called_once_with(agent_id="agent-1", limit=20, user_id="user-123")

    def test_user_id_injected_into_get_trace(self, mock_db):
        # Return a lightweight object with the matching user_id so the wrapper's
        # post-filter returns it. (On backends without user_id support the wrapper
        # falls back to this check to enforce isolation.)
        class Trace:
            def __init__(self, uid):
                self.user_id = uid

        mock_db.get_trace.return_value = Trace("user-123")
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_trace(trace_id="trace-1")
        mock_db.get_trace.assert_called_once_with(user_id="user-123", trace_id="trace-1")

    def test_user_id_injected_into_get_trace_stats(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_trace_stats(agent_id="agent-1")
        mock_db.get_trace_stats.assert_called_once_with(agent_id="agent-1", user_id="user-123")

    def test_user_id_injected_into_get_user_memories(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_user_memories(limit=10)
        mock_db.get_user_memories.assert_called_once_with(limit=10, user_id="user-123")

    def test_user_id_injected_into_get_user_memory(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_user_memory("mem-1")
        mock_db.get_user_memory.assert_called_once_with(memory_id="mem-1", user_id="user-123")

    def test_user_id_injected_into_delete_user_memory(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.delete_user_memory("mem-1")
        mock_db.delete_user_memory.assert_called_once_with(memory_id="mem-1", user_id="user-123")

    def test_user_id_injected_into_get_memory_topics(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_all_memory_topics()
        mock_db.get_all_memory_topics.assert_called_once_with(user_id="user-123")

    def test_user_id_injected_into_get_user_memory_stats(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_user_memory_stats()
        mock_db.get_user_memory_stats.assert_called_once_with(user_id="user-123")

    def test_user_id_overrides_caller_provided_value(self, mock_db):
        """The scoped wrapper should always use its own user_id, not the caller's."""
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_traces(user_id="user-EVIL")
        mock_db.get_traces.assert_called_once_with(user_id="user-123")

    def test_spans_not_user_scoped(self, mock_db):
        """Spans don't have user_id — should pass through without modification."""
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_spans(trace_id="trace-1")
        mock_db.get_spans.assert_called_once_with(trace_id="trace-1")

    def test_upsert_session_not_filtered(self, mock_db):
        """Writes should not inject user_id filter — the session object has its own."""
        session = MagicMock()
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.upsert_session(session)
        mock_db.upsert_session.assert_called_once_with(session)

    def test_upsert_session_coerces_mismatched_user_id(self, mock_db):
        """A session carrying a foreign user_id must be rewritten before the write."""

        class Sess:
            user_id = "user-EVIL"

        session = Sess()
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.upsert_session(session)
        assert session.user_id == "user-123"
        mock_db.upsert_session.assert_called_once_with(session)

    def test_upsert_user_memory_coerces_mismatched_user_id(self, mock_db):
        class Mem:
            user_id = "user-EVIL"

        memory = Mem()
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.upsert_user_memory(memory)
        assert memory.user_id == "user-123"
        mock_db.upsert_user_memory.assert_called_once_with(memory)

    def test_upsert_memories_coerces_each_entry(self, mock_db):
        class Mem:
            def __init__(self, uid):
                self.user_id = uid

        memories = [Mem("user-EVIL"), Mem(None), Mem("user-123")]
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.upsert_memories(memories)
        assert [m.user_id for m in memories] == ["user-123", "user-123", "user-123"]

    def test_passthrough_for_knowledge(self, mock_db):
        """Knowledge methods are not user-scoped — should pass through via __getattr__."""
        mock_db.get_knowledge_contents.return_value = ([], 0)
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_knowledge_contents(limit=10)
        mock_db.get_knowledge_contents.assert_called_once_with(limit=10)

    def test_passthrough_for_metrics(self, mock_db):
        mock_db.get_metrics.return_value = ([], 0)
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_metrics()
        mock_db.get_metrics.assert_called_once_with()

    def test_passthrough_for_eval_runs(self, mock_db):
        mock_db.get_eval_runs.return_value = ([], 0)
        scoped = UserScopedDb(mock_db, user_id="user-123")
        scoped.get_eval_runs(limit=5)
        mock_db.get_eval_runs.assert_called_once_with(limit=5)

    def test_user_id_property(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        assert scoped.user_id == "user-123"

    def test_db_id_exposed(self, mock_db):
        scoped = UserScopedDb(mock_db, user_id="user-123")
        assert scoped.id == "test-db"


class TestAsyncUserScopedDb:
    """Test async AsyncUserScopedDb wrapper."""

    @pytest.mark.asyncio
    async def test_user_id_injected_into_get_sessions(self, mock_async_db):
        scoped = AsyncUserScopedDb(mock_async_db, user_id="user-123")
        await scoped.get_sessions(SessionType.AGENT, limit=10)
        mock_async_db.get_sessions.assert_called_once_with(session_type=SessionType.AGENT, limit=10, user_id="user-123")

    @pytest.mark.asyncio
    async def test_user_id_injected_into_get_traces(self, mock_async_db):
        scoped = AsyncUserScopedDb(mock_async_db, user_id="user-123")
        await scoped.get_traces(agent_id="agent-1")
        mock_async_db.get_traces.assert_called_once_with(agent_id="agent-1", user_id="user-123")

    @pytest.mark.asyncio
    async def test_user_id_injected_into_get_user_memories(self, mock_async_db):
        scoped = AsyncUserScopedDb(mock_async_db, user_id="user-123")
        await scoped.get_user_memories(limit=10)
        mock_async_db.get_user_memories.assert_called_once_with(limit=10, user_id="user-123")

    @pytest.mark.asyncio
    async def test_user_id_overrides_caller(self, mock_async_db):
        scoped = AsyncUserScopedDb(mock_async_db, user_id="user-123")
        await scoped.get_traces(user_id="user-EVIL")
        mock_async_db.get_traces.assert_called_once_with(user_id="user-123")

    @pytest.mark.asyncio
    async def test_spans_not_user_scoped(self, mock_async_db):
        scoped = AsyncUserScopedDb(mock_async_db, user_id="user-123")
        await scoped.get_spans(trace_id="trace-1")
        mock_async_db.get_spans.assert_called_once_with(trace_id="trace-1")

    @pytest.mark.asyncio
    async def test_passthrough_for_knowledge(self, mock_async_db):
        mock_async_db.get_knowledge_contents.return_value = ([], 0)
        scoped = AsyncUserScopedDb(mock_async_db, user_id="user-123")
        await scoped.get_knowledge_contents(limit=10)
        mock_async_db.get_knowledge_contents.assert_called_once_with(limit=10)


class TestGetScopedUserId:
    """Test get_scoped_user_id admin bypass logic."""

    def _make_request(self, user_id=None, scopes=None, admin_scope=None):
        request = MagicMock()
        request.state = MagicMock()
        if user_id is not None:
            request.state.user_id = user_id
        else:
            # Simulate missing attribute
            del request.state.user_id
        if scopes is not None:
            request.state.scopes = scopes
        else:
            del request.state.scopes
        if admin_scope is not None:
            request.state.admin_scope = admin_scope
        else:
            # Simulate the attribute being absent so the helper falls back
            # to the default AgentOSScope.ADMIN value rather than picking up
            # MagicMock's auto-generated attribute.
            del request.state.admin_scope
        return request

    def test_regular_user_returns_user_id(self):
        request = self._make_request(user_id="user-123", scopes=["agents:read"])
        assert get_scoped_user_id(request) == "user-123"

    def test_admin_returns_none(self):
        """Admin users should bypass scoping (see all data)."""
        request = self._make_request(user_id="admin-user", scopes=["agent_os:admin"])
        assert get_scoped_user_id(request) is None

    def test_admin_with_other_scopes_returns_none(self):
        """Admin scope overrides regardless of other scopes present."""
        request = self._make_request(user_id="admin-user", scopes=["agents:read", "agent_os:admin", "sessions:read"])
        assert get_scoped_user_id(request) is None

    def test_no_user_id_returns_none(self):
        """No JWT user_id means no scoping."""
        request = self._make_request(user_id=None, scopes=[])
        assert get_scoped_user_id(request) is None

    def test_no_scopes_returns_user_id(self):
        """User with user_id but no scopes is still scoped (not admin)."""
        request = self._make_request(user_id="user-123", scopes=None)
        assert get_scoped_user_id(request) == "user-123"

    def test_empty_scopes_returns_user_id(self):
        request = self._make_request(user_id="user-123", scopes=[])
        assert get_scoped_user_id(request) == "user-123"

    def test_custom_admin_scope_honoured(self):
        """When JWTMiddleware is configured with a custom admin_scope, it must win."""
        request = self._make_request(
            user_id="admin-user",
            scopes=["custom:admin"],
            admin_scope="custom:admin",
        )
        assert get_scoped_user_id(request) is None

    def test_default_admin_scope_ignored_when_custom_configured(self):
        """The default agent_os:admin must NOT grant bypass once a custom one is set."""
        request = self._make_request(
            user_id="user-123",
            scopes=["agent_os:admin"],
            admin_scope="custom:admin",
        )
        assert get_scoped_user_id(request) == "user-123"
