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

    with patch.object(type(agent), "_has_async_db", return_value=True):
        result = await agent._aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


@pytest.mark.asyncio
async def test_aread_or_create_session_passes_user_id_sync_fallback():
    alice_session = _make_session("s1", user_id="alice")
    agent = Agent(model=OpenAIChat(id="gpt-4o"))
    # Sync DB (no async methods) triggers the sync fallback branch
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = await agent._aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


def test_cached_session_not_returned_to_wrong_user():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), cache_session=True)
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(return_value=None)

    # Alice creates and caches a session
    alice_result = agent._read_or_create_session(session_id="s1", user_id="alice")
    assert alice_result.user_id == "alice"
    assert agent._cached_session is not None

    # Bob requests the same session_id — should NOT get Alice's cached session
    bob_result = agent._read_or_create_session(session_id="s1", user_id="bob")
    assert bob_result.user_id == "bob"
    assert bob_result is not alice_result


def test_cached_session_returned_when_user_id_none():
    agent = Agent(model=OpenAIChat(id="gpt-4o"), cache_session=True)
    agent.db = MagicMock()
    agent.db.get_session = MagicMock(return_value=None)

    # Non-RBAC: user_id=None creates and caches session
    result1 = agent._read_or_create_session(session_id="s1", user_id=None)
    assert agent._cached_session is not None

    # Second call with user_id=None should return cached session
    result2 = agent._read_or_create_session(session_id="s1", user_id=None)
    assert result2 is result1
