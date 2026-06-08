"""Unit tests verifying that DB exceptions propagate from storage wrapper functions.

Previously read_session / aread_session / upsert_session / aupsert_session swallowed
all exceptions and returned None, making a transient DB failure indistinguishable from
"session not found".  This caused read_or_create_session to silently create an empty
session and lose all prior chat history.

These tests confirm the wrappers now let DB exceptions propagate while still returning
None for the genuine "not found" case.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agno.agent._storage import aread_session, aupsert_session, read_session, upsert_session
from agno.agent.agent import Agent
from agno.session import AgentSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_with_db(db: MagicMock) -> Agent:
    agent = Agent.__new__(Agent)
    agent.__dict__["db"] = db
    return agent


# ---------------------------------------------------------------------------
# read_session
# ---------------------------------------------------------------------------


def test_read_session_propagates_db_exception():
    """A DB error must NOT be swallowed; it must propagate to the caller."""
    db = MagicMock()
    db.get_session.side_effect = RuntimeError("connection timeout")
    agent = _make_agent_with_db(db)

    with pytest.raises(RuntimeError, match="connection timeout"):
        read_session(agent, session_id="sess-1")


def test_read_session_returns_none_when_not_found():
    """Genuine 'not found' (DB returns None) must still yield None."""
    db = MagicMock()
    db.get_session.return_value = None
    agent = _make_agent_with_db(db)

    result = read_session(agent, session_id="sess-missing")
    assert result is None


def test_read_session_raises_when_db_not_initialized():
    """Absence of a configured DB must raise ValueError, not swallow silently."""
    agent = _make_agent_with_db(None)

    with pytest.raises(ValueError, match="Db not initialized"):
        read_session(agent, session_id="sess-1")


# ---------------------------------------------------------------------------
# aread_session
# ---------------------------------------------------------------------------


def test_aread_session_propagates_db_exception():
    db = MagicMock()
    db.get_session.side_effect = RuntimeError("lock contention")
    agent = _make_agent_with_db(db)

    with patch("agno.agent._init.has_async_db", return_value=False):
        with pytest.raises(RuntimeError, match="lock contention"):
            asyncio.get_event_loop().run_until_complete(aread_session(agent, session_id="sess-1"))


def test_aread_session_returns_none_when_not_found():
    db = MagicMock()
    db.get_session.return_value = None
    agent = _make_agent_with_db(db)

    with patch("agno.agent._init.has_async_db", return_value=False):
        result = asyncio.get_event_loop().run_until_complete(aread_session(agent, session_id="sess-missing"))
    assert result is None


def test_aread_session_raises_when_db_not_initialized():
    agent = _make_agent_with_db(None)

    with pytest.raises(ValueError, match="Db not initialized"):
        asyncio.get_event_loop().run_until_complete(aread_session(agent, session_id="sess-1"))


# ---------------------------------------------------------------------------
# upsert_session
# ---------------------------------------------------------------------------


def test_upsert_session_propagates_db_exception():
    db = MagicMock()
    db.upsert_session.side_effect = IOError("disk full")
    agent = _make_agent_with_db(db)

    session = MagicMock(spec=AgentSession)
    with pytest.raises(IOError, match="disk full"):
        upsert_session(agent, session=session)


def test_upsert_session_raises_when_db_not_initialized():
    agent = _make_agent_with_db(None)
    session = MagicMock(spec=AgentSession)

    with pytest.raises(ValueError, match="Db not initialized"):
        upsert_session(agent, session=session)


# ---------------------------------------------------------------------------
# aupsert_session
# ---------------------------------------------------------------------------


def test_aupsert_session_propagates_db_exception():
    db = MagicMock()
    db.upsert_session.side_effect = IOError("write timeout")
    agent = _make_agent_with_db(db)

    session = MagicMock(spec=AgentSession)
    with patch("agno.agent._init.has_async_db", return_value=False):
        with pytest.raises(IOError, match="write timeout"):
            asyncio.get_event_loop().run_until_complete(aupsert_session(agent, session=session))


def test_aupsert_session_raises_when_db_not_initialized():
    agent = _make_agent_with_db(None)
    session = MagicMock(spec=AgentSession)

    with pytest.raises(ValueError, match="Db not initialized"):
        asyncio.get_event_loop().run_until_complete(aupsert_session(agent, session=session))
