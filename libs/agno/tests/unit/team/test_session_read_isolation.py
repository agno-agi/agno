from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.models.openai import OpenAIChat
from agno.session.team import TeamSession
from agno.team.team import Team


def _make_team_session(session_id: str, user_id: Optional[str] = None) -> TeamSession:
    return TeamSession(session_id=session_id, team_id="test-team", user_id=user_id)


def _scoped_get_session(owner_user_id: str, session: TeamSession):
    def _lookup(session_id: str, session_type=None, user_id: Optional[str] = None, **kwargs):
        if session_id == session.session_id:
            if user_id is None or user_id == owner_user_id:
                return session
        return None

    return _lookup


# --- Layer 1: _read_session / _aread_session ---


def test_read_session_passes_user_id_to_db():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.get_session = MagicMock(return_value=None)

    team._read_session(session_id="s1", user_id="alice")

    team.db.get_session.assert_called_once()
    call_kwargs = team.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


def test_read_session_none_user_id_passes_none():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.get_session = MagicMock(return_value=None)

    team._read_session(session_id="s1")

    call_kwargs = team.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] is None


@pytest.mark.asyncio
async def test_aread_session_passes_user_id_to_db():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = AsyncMock()
    team.db.get_session = AsyncMock(return_value=None)

    await team._aread_session(session_id="s1", user_id="alice")

    team.db.get_session.assert_called_once()
    call_kwargs = team.db.get_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


# --- Layer 2: _read_or_create_session / _aread_or_create_session ---


def test_read_or_create_session_passes_user_id_through():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = team._read_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"
    assert result.session_id == "s1"

    result = team._read_or_create_session(session_id="s1", user_id="alice")
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aread_or_create_session_passes_user_id_async_branch():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = AsyncMock()
    team.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    with patch.object(type(team), "_has_async_db", return_value=True):
        result = await team._aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


@pytest.mark.asyncio
async def test_aread_or_create_session_passes_user_id_sync_fallback():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = await team._aread_or_create_session(session_id="s1", user_id="bob")
    assert result.user_id == "bob"


def test_cached_session_not_returned_to_wrong_user():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[], cache_session=True)
    team.db = MagicMock()
    team.db.get_session = MagicMock(return_value=None)

    alice_result = team._read_or_create_session(session_id="s1", user_id="alice")
    assert alice_result.user_id == "alice"
    assert team._cached_session is not None

    bob_result = team._read_or_create_session(session_id="s1", user_id="bob")
    assert bob_result.user_id == "bob"
    assert bob_result is not alice_result


def test_cached_session_returned_when_user_id_none():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[], cache_session=True)
    team.db = MagicMock()
    team.db.get_session = MagicMock(return_value=None)

    result1 = team._read_or_create_session(session_id="s1", user_id=None)
    assert team._cached_session is not None

    result2 = team._read_or_create_session(session_id="s1", user_id=None)
    assert result2 is result1


# --- Layer 3: get_session / aget_session ---


def test_get_session_passes_user_id_to_read_session():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = team.get_session(session_id="s1", user_id="alice")
    assert result is not None
    assert result.user_id == "alice"

    result = team.get_session(session_id="s1", user_id="bob")
    assert result is None


def test_get_session_defaults_user_id_from_self():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[], user_id="alice")
    team.db = MagicMock()
    team.db.get_session = MagicMock(side_effect=_scoped_get_session("alice", alice_session))

    result = team.get_session(session_id="s1")
    assert result is not None
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aget_session_passes_user_id():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = AsyncMock()
    team.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    with patch.object(type(team), "_has_async_db", return_value=True):
        result = await team.aget_session(session_id="s1", user_id="alice")
    assert result is not None
    assert result.user_id == "alice"


@pytest.mark.asyncio
async def test_aget_session_defaults_user_id_from_self():
    alice_session = _make_team_session("s1", user_id="alice")
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[], user_id="alice")
    team.db = AsyncMock()
    team.db.get_session = AsyncMock(side_effect=_scoped_get_session("alice", alice_session))

    with patch.object(type(team), "_has_async_db", return_value=True):
        result = await team.aget_session(session_id="s1")
    assert result is not None
    assert result.user_id == "alice"


# --- Layer 4: delete_session / adelete_session ---


def test_delete_session_passes_user_id_to_db():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.delete_session = MagicMock()

    team.delete_session(session_id="s1", user_id="alice")

    team.db.delete_session.assert_called_once_with(session_id="s1", user_id="alice")


def test_delete_session_none_user_id_acts_as_wildcard():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.delete_session = MagicMock()

    team.delete_session(session_id="s1")

    team.db.delete_session.assert_called_once_with(session_id="s1", user_id=None)


@pytest.mark.asyncio
async def test_adelete_session_passes_user_id_to_db():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = AsyncMock()
    team.db.delete_session = AsyncMock()

    await team.adelete_session(session_id="s1", user_id="alice")

    team.db.delete_session.assert_called_once_with(session_id="s1", user_id="alice")


@pytest.mark.asyncio
async def test_adelete_session_none_user_id_acts_as_wildcard():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = AsyncMock()
    team.db.delete_session = AsyncMock()

    await team.adelete_session(session_id="s1")

    team.db.delete_session.assert_called_once_with(session_id="s1", user_id=None)


@pytest.mark.asyncio
async def test_adelete_session_passes_user_id_async_branch():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = AsyncMock()
    team.db.delete_session = AsyncMock()

    with patch.object(type(team), "_has_async_db", return_value=True):
        await team.adelete_session(session_id="s1", user_id="alice")

    team.db.delete_session.assert_called_once_with(session_id="s1", user_id="alice")


# --- Layer 5: save_session ---


def test_save_session_warns_on_upsert_rejection():
    team = Team(model=OpenAIChat(id="gpt-4o"), members=[])
    team.db = MagicMock()
    team.db.upsert_session = MagicMock(return_value=None)

    session = _make_team_session("s1", user_id="alice")
    session.session_data = {"session_state": {}}

    with patch("agno.team._storage.log_warning") as mock_warn:
        team.save_session(session=session)
        mock_warn.assert_called_once()
        assert "not persisted" in mock_warn.call_args[0][0]
