from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.session.agent import AgentSession


def _make_session(session_id: str, user_id: Optional[str] = None) -> AgentSession:
    return AgentSession(session_id=session_id, agent_id="test-agent", user_id=user_id)


def _scoped_get_session(owner_user_id: str, session: AgentSession):
    def _lookup(session_id: str, session_type=None, user_id: Optional[str] = None, **kwargs):
        if session_id == session.session_id:
            if user_id is None or user_id == owner_user_id:
                return session
        return None

    return _lookup


# --- Layer 1: read_session / aread_session ---


def test_read_session_passes_user_id_to_db():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(return_value=None)

    agent._read_session(session_id="s1", user_id="alice")

    agent.db.get_session.assert_called_once()
    call_kwargs = agent.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


def test_read_session_none_user_id_passes_none():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(return_value=None)

    agent._read_session(session_id="s1")

    call_kwargs = agent.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] is None


@pytest.mark.asyncio
async def test_aread_session_passes_user_id_to_db():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = AsyncMock()
    agent.db.get_session = AsyncMock(return_value=None)

    await agent._aread_session(session_id="s1", user_id="alice")

    agent.db.get_session.assert_called_once()
    call_kwargs = agent.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


# --- Layer 2: read_or_create_session / aread_or_create_session ---


def test_read_or_create_session_passes_user_id_through():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    # Bob requests Alice's session_id — should NOT get Alice's session
    result = agent._read_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"
    assert result.session_id == "s1"

    # Alice requests her own session — should get it back
    result = agent._read_or_create_session(session_id="s1", user_id="alice")
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aread_or_create_session_passes_user_id_async_branch():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = AsyncMock()
    agent.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    with patch("agno.agent._init.has_async_db", return_value=True):
        result = await agent._aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


@pytest.mark.asyncio
async def test_aread_or_create_session_passes_user_id_sync_fallback():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    with patch("agno.agent._init.has_async_db", return_value=False):
        result = await agent._aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


def test_cached_session_not_returned_to_wrong_user():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), cache_session=True)
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(return_value=None)

    alice_result = agent._read_or_create_session(session_id="s1", user_id="alice")
    assert alice_result.user_id == "alice"
    assert agent._cached_session is not None

    bob_result = agent._read_or_create_session(session_id="s1", user_id="bob")
    assert bob_result.user_id == "bob"
    assert bob_result is not alice_result


def test_cached_session_returned_when_user_id_none():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), cache_session=True)
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(return_value=None)

    result1 = agent._read_or_create_session(session_id="s1", user_id=None)
    assert agent._cached_session is not None

    result2 = agent._read_or_create_session(session_id="s1", user_id=None)
    assert result2 is result1


# --- Layer 3: get_session / aget_session ---


def test_get_session_passes_user_id_to_read_session():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = agent.get_session(session_id="s1", user_id="alice")
    assert result is not None
    assert result.user_id == "alice"

    result = agent.get_session(session_id="s1", user_id="bob")
    assert result is None


def test_get_session_defaults_user_id_from_self():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"), user_id="alice")
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = agent.get_session(session_id="s1")
    assert result is not None
    assert result.user_id == "alice"


def test_get_session_no_user_id_acts_as_wildcard():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    # No user_id on agent or call → wildcard → returns session regardless of owner
    result = agent.get_session(session_id="s1")
    assert result is not None


def test_get_session_cache_respects_user_id():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"), cache_session=True)
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = agent.get_session(session_id="s1", user_id="alice")
    assert result is not None
    assert agent._cached_session is not None

    # Cached session should NOT be returned to bob
    result = agent.get_session(session_id="s1", user_id="bob")
    assert result is None


@pytest.mark.asyncio
async def test_aget_session_passes_user_id_to_aread_session():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = AsyncMock()
    agent.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    result = await agent.aget_session(session_id="s1", user_id="alice")
    assert result is not None
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aget_session_defaults_user_id_from_self():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"), user_id="alice")
    agent.db = AsyncMock()
    agent.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    result = await agent.aget_session(session_id="s1")
    assert result is not None
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aget_session_cache_respects_user_id():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"), cache_session=True)
    agent.db = AsyncMock()
    agent.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    result = await agent.aget_session(session_id="s1", user_id="alice")
    assert result is not None
    assert agent._cached_session is not None

    result = await agent.aget_session(session_id="s1", user_id="bob")
    assert result is None


# --- Layer 5: save_session ---


# --- Layer 4: delete_session / adelete_session ---


def test_delete_session_passes_user_id_to_db():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.delete_session = MagicMock()

    agent.delete_session(session_id="s1", user_id="alice")

    agent.db.delete_session.assert_called_once_with(session_id="s1", user_id="alice")


def test_delete_session_none_user_id_acts_as_wildcard():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.delete_session = MagicMock()

    agent.delete_session(session_id="s1")

    agent.db.delete_session.assert_called_once_with(session_id="s1", user_id=None)


@pytest.mark.asyncio
async def test_adelete_session_passes_user_id_to_db():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = AsyncMock()
    agent.db.delete_session = AsyncMock()

    await agent.adelete_session(session_id="s1", user_id="alice")

    agent.db.delete_session.assert_called_once_with(session_id="s1", user_id="alice")


@pytest.mark.asyncio
async def test_adelete_session_none_user_id_acts_as_wildcard():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = AsyncMock()
    agent.db.delete_session = AsyncMock()

    await agent.adelete_session(session_id="s1")

    agent.db.delete_session.assert_called_once_with(session_id="s1", user_id=None)


# --- Layer 5: save_session ---


def test_save_session_warns_on_upsert_rejection():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.upsert_session = MagicMock(return_value=None)

    session = _make_session("s1", user_id="alice")
    session.session_data = {"session_state": {}}

    with patch("agno.agent._storage.log_warning") as mock_warn:
        agent.save_session(session=session)
        mock_warn.assert_called_once()
        assert "not persisted" in mock_warn.call_args[0][0]


def test_save_session_logs_debug_on_success():
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    agent.db = MagicMock()
    agent.db.upsert_session = MagicMock(return_value=_make_session("s1", user_id="alice"))

    session = _make_session("s1", user_id="alice")
    session.session_data = {"session_state": {}}

    with (
        patch("agno.agent._storage.log_warning") as mock_warn,
        patch("agno.agent._storage.log_debug") as mock_debug,
    ):
        agent.save_session(session=session)
        mock_warn.assert_not_called()
        assert any("Created or updated" in str(c) for c in mock_debug.call_args_list)
