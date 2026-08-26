from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.db.base import BaseDb


def _build_teams_interface(env=None):
    """MagicMock(spec=BaseDb) so ``isinstance(db, BaseDb)`` succeeds without
    implementing BaseDb's ~50 abstract methods."""
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


# === Happy path ===


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


# === Missing ref / no history ===


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


# === Which session's reference an alert uses ===


def _conv_ref(conv_id):
    return {"service_url": "https://svc", "conversation_id": conv_id, "bot_identity": {"id": "28:bot"}}


def _write_session(db, session_id, created_at, conv_id=None):
    from agno.session.agent import AgentSession

    db.upsert_sessions(
        [
            AgentSession(
                session_id=session_id,
                user_id="user-1",
                agent_id="agent-1",
                created_at=created_at,
                updated_at=created_at,
                session_data={"teams_conversation_ref": _conv_ref(conv_id)} if conv_id else None,
            )
        ],
        preserve_updated_at=True,
    )


@pytest.mark.asyncio
async def test_alert_uses_the_newest_session_that_carries_a_ref(tmp_path):
    """`/new` starts a session with no conversation reference on it. Until the
    user's next message the only reference that can be delivered to sits on the
    session before it."""
    from agno.db.sqlite import SqliteDb
    from agno.os.interfaces.teams import MicrosoftTeams

    db = SqliteDb(db_file=str(tmp_path / "alerts.db"))
    stub_agent = SimpleNamespace(id="agent-1", name="Stub", db=db)
    send_target = "agno.os.interfaces.teams.teams.send_teams_message_async"

    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    ):
        teams = MicrosoftTeams(agent=stub_agent)

        _write_session(db, "teams:agent-1:user-1", 1_700_000_000, conv_id="conv-A")
        with patch(send_target, new_callable=AsyncMock) as mock_send:
            assert await teams.asend_alert(user_id="user-1", text="one") is True
        assert mock_send.call_args.kwargs["conversation_id"] == "conv-A"

        # `/new`: newest session, and it carries no reference yet
        _write_session(db, "teams:agent-1:user-1:0a1b2c3d", 1_700_000_060)
        with patch(send_target, new_callable=AsyncMock) as mock_send:
            assert await teams.asend_alert(user_id="user-1", text="two") is True
        assert mock_send.call_args.kwargs["conversation_id"] == "conv-A"

        # the user's next inbound message lands a reference on the new session
        _write_session(db, "teams:agent-1:user-1:0a1b2c3d", 1_700_000_060, conv_id="conv-B")
        with patch(send_target, new_callable=AsyncMock) as mock_send:
            assert await teams.asend_alert(user_id="user-1", text="three") is True
        # the ref moved with the conversation; it did not stay pinned to the old one
        assert mock_send.call_args.kwargs["conversation_id"] == "conv-B"

        # a user with no reference anywhere is still False, with nothing sent
        with patch(send_target, new_callable=AsyncMock) as mock_send:
            assert await teams.asend_alert(user_id="user-2", text="four") is False
        mock_send.assert_not_called()


# === Guardrails: no DB / lookup errors / async DB ===


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
    """A clean boolean, so a batch of alerts does not abort mid-way."""
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(side_effect=RuntimeError("db down"))
        with patch("agno.os.interfaces.teams.teams.send_teams_message_async", new_callable=AsyncMock) as mock_send:
            ok = await teams.asend_alert(user_id="user-1", text="hi")
        assert ok is False
        mock_send.assert_not_called()
    finally:
        env_patch.stop()


# === Team / Workflow entity binding ===


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


# === AsyncBaseDb path — asend_alert must await get_sessions when the db is async ===


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


# === Constructor validation ===


def test_microsoft_teams_requires_entity():
    from agno.os.interfaces.teams import MicrosoftTeams

    with pytest.raises(ValueError, match="requires an agent, team, or workflow"):
        MicrosoftTeams()


# === send_alert — blocking wrapper around asend_alert ===


def test_sync_send_alert_delegates_to_async():
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


# === Bot-token reuse across alerts ===


def _counting_post(token_fetches, activity_posts):
    """Stand in for the token endpoint and the Bot Connector, counting logins."""
    import httpx

    async def fake_post(self, url, data=None, headers=None, json=None):
        url_s = str(url)
        req = httpx.Request("POST", url_s)
        if "login.microsoftonline.com" in url_s:
            token_fetches.append(url_s)
            return httpx.Response(200, request=req, json={"access_token": "tok", "expires_in": 3600})
        activity_posts.append(json)
        return httpx.Response(201, request=req, json={"id": "out-1"})

    return fake_post


@pytest.mark.asyncio
async def test_two_alerts_reuse_one_bot_token():
    """The cached token lives on TeamsConfig, so a per-call config re-authenticates."""
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(return_value=[_make_session_with_ref()])
        token_fetches: list = []
        activity_posts: list = []
        with patch("httpx.AsyncClient.post", new=_counting_post(token_fetches, activity_posts)):
            assert await teams.asend_alert(user_id="user-1", text="one") is True
            assert await teams.asend_alert(user_id="user-1", text="two") is True
        assert len(activity_posts) == 2
        assert len(token_fetches) == 1
    finally:
        env_patch.stop()


def test_two_sync_alerts_reuse_one_bot_token():
    """Same for the sync wrapper — it shares the interface's config too."""
    teams, agent, env_patch = _build_teams_interface()
    try:
        agent.db.get_sessions = MagicMock(return_value=[_make_session_with_ref()])
        token_fetches: list = []
        activity_posts: list = []
        with patch("httpx.AsyncClient.post", new=_counting_post(token_fetches, activity_posts)):
            assert teams.send_alert(user_id="user-1", text="one") is True
            assert teams.send_alert(user_id="user-1", text="two") is True
        assert len(activity_posts) == 2
        assert len(token_fetches) == 1
    finally:
        env_patch.stop()
