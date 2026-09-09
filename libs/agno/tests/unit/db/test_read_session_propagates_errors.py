"""Regression tests for the read-error swallowing incident.

The team + agent ``_read_session`` / ``read_session`` helpers used to catch
every exception, log a warning, and return ``None``. Callers could not
distinguish "row doesn't exist" from "read failed". A transient Postgres
failover in production returned no rows for existing sessions; the caller
saw ``None``, created a fresh empty session with the same id, and the next
write overwrote the row's metadata -- the incident wiped six weeks of
conversation history for one team session.

These tests lock in the fix: read errors now propagate. ``None`` only means
the row genuinely doesn't exist.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agno.agent._storage import aread_session, read_session
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.team._storage import _aread_session, _read_session


class _SimulatedFailover(Exception):
    """Distinctive error to prove the exception surfaced unchanged."""


@pytest.fixture
def failing_agent():
    agent = MagicMock()
    agent.db = MagicMock()
    agent.db.get_session.side_effect = _SimulatedFailover("simulated failover")
    return agent


@pytest.fixture
def failing_team():
    team = MagicMock()
    team.db = MagicMock()
    team.db.get_session.side_effect = _SimulatedFailover("simulated failover")
    return team


class TestReadSessionPropagatesErrors:
    def test_agent_read_session_reraises(self, failing_agent):
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            read_session(failing_agent, session_id="s1")

    def test_agent_read_session_returns_none_when_row_missing(self):
        agent = MagicMock()
        agent.db = MagicMock()
        agent.db.get_session.return_value = None
        assert read_session(agent, session_id="missing") is None

    def test_agent_read_session_returns_session_when_present(self):
        agent = MagicMock()
        agent.db = MagicMock()
        stored = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        agent.db.get_session.return_value = stored
        assert read_session(agent, session_id="s1") is stored

    def test_team_read_session_reraises(self, failing_team):
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            _read_session(failing_team, session_id="s1")

    def test_team_read_session_returns_none_when_row_missing(self):
        team = MagicMock()
        team.db = MagicMock()
        team.db.get_session.return_value = None
        assert _read_session(team, session_id="missing") is None

    def test_team_read_session_returns_session_when_present(self):
        team = MagicMock()
        team.db = MagicMock()
        stored = TeamSession(session_id="s1", team_id="t1", user_id="u1")
        team.db.get_session.return_value = stored
        assert _read_session(team, session_id="s1") is stored


class TestAsyncReadSessionPropagatesErrors:
    @pytest.mark.asyncio
    async def test_agent_aread_session_reraises_sync_db(self, failing_agent):
        from unittest.mock import patch

        with patch("agno.agent._init.has_async_db", return_value=False):
            with pytest.raises(_SimulatedFailover, match="simulated failover"):
                await aread_session(failing_agent, session_id="s1")

    @pytest.mark.asyncio
    async def test_agent_aread_session_reraises_async_db(self):
        from unittest.mock import patch

        async def _boom(**_kwargs):
            raise _SimulatedFailover("simulated failover")

        agent = MagicMock()
        agent.db = MagicMock()
        agent.db.get_session = _boom

        with patch("agno.agent._init.has_async_db", return_value=True):
            with pytest.raises(_SimulatedFailover, match="simulated failover"):
                await aread_session(agent, session_id="s1")

    @pytest.mark.asyncio
    async def test_team_aread_session_reraises_sync_db(self, failing_team):
        from unittest.mock import patch

        with patch("agno.team._init._has_async_db", return_value=False):
            with pytest.raises(_SimulatedFailover, match="simulated failover"):
                await _aread_session(failing_team, session_id="s1")

    @pytest.mark.asyncio
    async def test_team_aread_session_reraises_async_db(self):
        from unittest.mock import patch

        async def _boom(**_kwargs):
            raise _SimulatedFailover("simulated failover")

        team = MagicMock()
        team.db = MagicMock()
        team.db.get_session = _boom

        with patch("agno.team._init._has_async_db", return_value=True):
            with pytest.raises(_SimulatedFailover, match="simulated failover"):
                await _aread_session(team, session_id="s1")


class TestWorkflowReadSessionPropagatesErrors:
    """Workflow has its own _read_session / _aread_session methods on the Workflow
    class (not a module-level helper). Same fix applied there."""

    def _make_workflow(self, get_session_side_effect=None, get_session_return=None, has_async=False):
        from unittest.mock import MagicMock

        wf = MagicMock()
        wf.db = MagicMock()
        wf._has_async_db.return_value = has_async
        if get_session_side_effect is not None:
            if has_async:

                async def _boom(**_kwargs):
                    raise get_session_side_effect

                wf.db.get_session = _boom
            else:
                wf.db.get_session.side_effect = get_session_side_effect
        else:
            if has_async:

                async def _ok(**_kwargs):
                    return get_session_return

                wf.db.get_session = _ok
            else:
                wf.db.get_session.return_value = get_session_return
        return wf

    def test_sync_read_reraises(self):
        from agno.workflow.workflow import Workflow

        wf = self._make_workflow(get_session_side_effect=_SimulatedFailover("simulated failover"))
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            Workflow._read_session(wf, session_id="s1")

    def test_sync_read_returns_none_when_row_missing(self):
        from agno.workflow.workflow import Workflow

        wf = self._make_workflow(get_session_return=None)
        assert Workflow._read_session(wf, session_id="missing") is None

    def test_sync_read_returns_session_when_present(self):
        from agno.workflow.workflow import Workflow

        stored = WorkflowSession(session_id="s1", workflow_id="w1", user_id="u1")
        wf = self._make_workflow(get_session_return=stored)
        assert Workflow._read_session(wf, session_id="s1") is stored

    @pytest.mark.asyncio
    async def test_async_read_reraises_sync_db(self):
        from agno.workflow.workflow import Workflow

        wf = self._make_workflow(get_session_side_effect=_SimulatedFailover("simulated failover"), has_async=False)
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            await Workflow._aread_session(wf, session_id="s1")

    @pytest.mark.asyncio
    async def test_async_read_reraises_async_db(self):
        from agno.workflow.workflow import Workflow

        wf = self._make_workflow(get_session_side_effect=_SimulatedFailover("simulated failover"), has_async=True)
        with pytest.raises(_SimulatedFailover, match="simulated failover"):
            await Workflow._aread_session(wf, session_id="s1")


class TestDbNotInitialized:
    """Db missing is a programmer error and should raise, not silently return None."""

    def test_agent_read_session_raises_without_db(self):
        agent = MagicMock()
        agent.db = None
        with pytest.raises(ValueError, match="Db not initialized"):
            read_session(agent, session_id="s1")

    def test_team_read_session_raises_without_db(self):
        team = MagicMock()
        team.db = None
        with pytest.raises(ValueError, match="Db not initialized"):
            _read_session(team, session_id="s1")

    @pytest.mark.asyncio
    async def test_agent_aread_session_raises_without_db(self):
        agent = MagicMock()
        agent.db = None
        with pytest.raises(ValueError, match="Db not initialized"):
            await aread_session(agent, session_id="s1")

    @pytest.mark.asyncio
    async def test_team_aread_session_raises_without_db(self):
        team = MagicMock()
        team.db = None
        with pytest.raises(ValueError, match="Db not initialized"):
            await _aread_session(team, session_id="s1")
