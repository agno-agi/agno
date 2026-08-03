"""Tests for MicrosoftTeams.asend_alert / send_alert — the proactive-message path.

The alert flow is:
  1. Caller invokes teams.asend_alert(user_id, text) (or the sync send_alert wrapper)
  2. Class looks up user's latest session via entity.db
  3. Extracts teams_conversation_ref from session_data
  4. Calls send_teams_message_async with the saved fields

These tests mock the DB + the outbound helper so no real HTTP happens.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.base import BaseDb


def _build_teams_interface(env=None):
    """Build a MicrosoftTeams instance with a stub agent so we can exercise asend_alert
    without booting AgentOS. Patches env vars TeamsConfig.init would need.

    Uses MagicMock(spec=BaseDb) so `isinstance(db, BaseDb)` succeeds without
    having to implement BaseDb's ~50 abstract methods.
    """
    from unittest.mock import patch as _patch

    from agno.os.interfaces.teams import MicrosoftTeams

    fake_db = MagicMock(spec=BaseDb)
    stub_agent = SimpleNamespace(id="agent-1", name="Stub", db=fake_db)
    env_patch = _patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret", **(env or {})},
        clear=True,
    )
    env_patch.start()
    return MicrosoftTeams(agent=stub_agent), stub_agent, env_patch


def _make_session_with_ref(service_url="https://svc", conv_id="conv-1"):
    return SimpleNamespace(
        session_id="s-1",
        session_data={
            "teams_conversation_ref": {
                "service_url": service_url,
                "conversation_id": conv_id,
                "bot_identity": {"id": "28:bot", "name": "Bot"},
            }
        },
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_delivers_when_ref_saved():
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(return_value=[_make_session_with_ref()])
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="Regulatory update: ...")
        assert ok is True
        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["service_url"] == "https://svc"
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["message"] == "Regulatory update: ..."
        assert kwargs["bot_identity"] == {"id": "28:bot", "name": "Bot"}
        # No reply_to_activity_id — proactive messages must not be thread replies
        assert kwargs.get("reply_to_activity_id") is None
    finally:
        env_patch.stop()


# ---------------------------------------------------------------------------
# Missing ref / no history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_returns_false_when_no_sessions():
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(return_value=[])
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="never-chatted", text="hi")
        assert ok is False
        mock_send.assert_not_called()
    finally:
        env_patch.stop()


@pytest.mark.asyncio
async def test_send_alert_returns_false_when_session_has_no_ref():
    teams, agent, env_patch = _build_teams_interface()
    try:
        stale_session = SimpleNamespace(session_id="s-old", session_data={"other": "keys"})
        agent.db.get_sessions = MagicMock(return_value=[stale_session])
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="hi")
        assert ok is False
        mock_send.assert_not_called()
    finally:
        env_patch.stop()


# ---------------------------------------------------------------------------
# Guardrails: no DB / lookup errors / async DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_returns_false_when_entity_has_no_db():
    from unittest.mock import patch as _patch

    from agno.os.interfaces.teams import MicrosoftTeams

    stub_agent = SimpleNamespace(id="agent-1", name="Stub", db=None)
    with _patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    ):
        teams = MicrosoftTeams(agent=stub_agent)
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="hi")
        assert ok is False
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_alert_swallows_lookup_errors():
    """DB errors should log-and-return-False, not raise. Callers get a clean
    boolean; downstream code doesn't crash mid-batch of alerts."""
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(side_effect=RuntimeError("db down"))
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="hi")
        assert ok is False
        mock_send.assert_not_called()
    finally:
        env_patch.stop()


# ---------------------------------------------------------------------------
# Team / Workflow entity binding — proves _resolve_entity covers all 3 paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_works_with_team_entity():
    from unittest.mock import patch as _patch

    from agno.os.interfaces.teams import MicrosoftTeams

    fake_db = MagicMock(spec=BaseDb)
    fake_db.get_sessions = MagicMock(return_value=[_make_session_with_ref()])
    stub_team = SimpleNamespace(id="team-1", name="Squad", db=fake_db)
    with _patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    ):
        teams = MicrosoftTeams(team=stub_team)
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="alert")
        assert ok is True
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_alert_works_with_workflow_entity():
    from unittest.mock import patch as _patch

    from agno.os.interfaces.teams import MicrosoftTeams

    fake_db = MagicMock(spec=BaseDb)
    fake_db.get_sessions = MagicMock(return_value=[_make_session_with_ref()])
    stub_wf = SimpleNamespace(id="wf-1", name="Nightly", db=fake_db)
    with _patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    ):
        teams = MicrosoftTeams(workflow=stub_wf)
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="alert")
        assert ok is True
        mock_send.assert_awaited_once()


# ---------------------------------------------------------------------------
# AsyncBaseDb path — asend_alert must await get_sessions when the db is async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_awaits_async_db():
    from unittest.mock import patch as _patch

    from agno.db.base import AsyncBaseDb
    from agno.os.interfaces.teams import MicrosoftTeams

    fake_async_db = MagicMock(spec=AsyncBaseDb)
    fake_async_db.get_sessions = AsyncMock(return_value=[_make_session_with_ref()])
    stub_agent = SimpleNamespace(id="agent-1", name="Stub", db=fake_async_db)
    with _patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    ):
        teams = MicrosoftTeams(agent=stub_agent)
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="hi")
        assert ok is True
        fake_async_db.get_sessions.assert_awaited_once()
        mock_send.assert_awaited_once()


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_microsoft_teams_requires_entity():
    from agno.os.interfaces.teams import MicrosoftTeams

    with pytest.raises(ValueError, match="requires an agent, team, or workflow"):
        MicrosoftTeams()


# ---------------------------------------------------------------------------
# send_alert — blocking wrapper around asend_alert
# ---------------------------------------------------------------------------


def test_sync_send_alert_delegates_to_async():
    """The sync send_alert should run asend_alert to completion via asyncio.run
    and propagate the boolean result."""
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(return_value=[_make_session_with_ref()])
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = teams.send_alert(user_id="user-1", text="sync alert")
        assert ok is True
        mock_send.assert_awaited_once()
    finally:
        env_patch.stop()


def test_sync_send_alert_returns_false_on_missing_session():
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(return_value=[])
        ok = teams.send_alert(user_id="user-1", text="hi")
        assert ok is False
    finally:
        env_patch.stop()
