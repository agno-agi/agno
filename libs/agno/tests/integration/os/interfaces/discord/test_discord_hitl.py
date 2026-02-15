from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from .conftest import (
    RecordingSession,
    make_agent_response,
    make_component_click,
    make_discord_app,
    make_paused_response,
    make_slash_command,
    post_interaction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_calls(session: RecordingSession, method: str) -> list[tuple[str, str, dict]]:
    return [c for c in session.calls if c[0] == method]


# ===========================================================================
# Class 10: TestHITLFlow (P0)
# ===========================================================================


class TestHITLFlow:
    def test_confirm_flow(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_confirm"))
        continued = make_agent_response(content="Tool executed successfully")
        mock_agent.acontinue_run = AsyncMock(return_value=continued)

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        # Step 1: Slash command triggers HITL pause
        resp = post_interaction(client, make_slash_command())
        assert resp.json()["type"] == 5

        # Step 2: User clicks Confirm
        resp = post_interaction(client, make_component_click("hitl:run_confirm:confirm"))
        assert resp.status_code == 200

        # Agent.acontinue_run should have been called
        mock_agent.acontinue_run.assert_called_once()
        call_kwargs = mock_agent.acontinue_run.call_args.kwargs
        run_response = call_kwargs["run_response"]
        # The tool should be marked as confirmed
        assert run_response.tools_requiring_confirmation[0].confirmed is True

    def test_cancel_flow(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_cancel"))
        continued = make_agent_response(content="Cancelled")
        mock_agent.acontinue_run = AsyncMock(return_value=continued)

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        post_interaction(client, make_slash_command())
        post_interaction(client, make_component_click("hitl:run_cancel:cancel"))

        mock_agent.acontinue_run.assert_called_once()
        call_kwargs = mock_agent.acontinue_run.call_args.kwargs
        run_response = call_kwargs["run_response"]
        assert run_response.tools_requiring_confirmation[0].confirmed is False

    def test_button_custom_ids(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_btns"))

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)
        post_interaction(client, make_slash_command())

        # Buttons sent via PATCH (edit_original) with components
        patches = _get_calls(recording_session, "PATCH")
        assert len(patches) >= 1

        components = patches[0][2]["json"].get("components", [])
        assert len(components) == 1
        buttons = components[0]["components"]
        custom_ids = [b["custom_id"] for b in buttons]
        assert "hitl:run_btns:confirm" in custom_ids
        assert "hitl:run_btns:cancel" in custom_ids

    def test_component_uses_own_token(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_token"))
        continued = make_agent_response(content="Done")
        mock_agent.acontinue_run = AsyncMock(return_value=continued)

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        # Command uses "interaction_token"
        post_interaction(client, make_slash_command(token="original_token"))

        # Clear recorded calls so we only see component-triggered ones
        recording_session.calls.clear()

        # Component click uses "component_token"
        post_interaction(client, make_component_click("hitl:run_token:confirm", token="comp_token_xyz"))

        # All webhook calls after the component should use comp_token_xyz
        all_urls = [c[1] for c in recording_session.calls if c[0] in ("POST", "PATCH")]
        assert any("comp_token_xyz" in url for url in all_urls)
        assert not any("original_token" in url for url in all_urls)


# ===========================================================================
# Class 11: TestHITLSecurity (P0)
# ===========================================================================


class TestHITLSecurity:
    def test_unauthorized_user_rejected(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_sec"))

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        # User1 triggers command
        post_interaction(client, make_slash_command(user_id="user1"))

        # User2 clicks confirm — should be rejected
        recording_session.calls.clear()
        post_interaction(client, make_component_click("hitl:run_sec:confirm", user_id="user2"))

        mock_agent.acontinue_run.assert_not_called()

        # Ephemeral rejection sent (flags=64)
        posts = _get_calls(recording_session, "POST")
        ephemeral = [c for c in posts if c[2].get("json", {}).get("flags") == 64]
        assert len(ephemeral) >= 1
        assert "original requester" in str(ephemeral[0][2]["json"]["content"]).lower()

    def test_original_user_accepted(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_auth"))
        mock_agent.acontinue_run = AsyncMock(return_value=make_agent_response(content="OK"))

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        # User1 triggers and confirms
        post_interaction(client, make_slash_command(user_id="user1"))
        post_interaction(client, make_component_click("hitl:run_auth:confirm", user_id="user1"))

        mock_agent.acontinue_run.assert_called_once()


# ===========================================================================
# Class 12: TestHITLExpiry (P1)
# ===========================================================================


class TestHITLExpiry:
    def test_expired_entry(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_exp"))

        with patch("agno.os.interfaces.discord.router.time") as mock_time:
            mock_time.time.return_value = 1000.0

            app = make_discord_app(mock_agent)
            client = TestClient(app, raise_server_exceptions=False)

            # Command creates HITL entry at t=1000
            post_interaction(client, make_slash_command())

            # Advance 16 minutes past TTL
            mock_time.time.return_value = 1000.0 + 16 * 60
            recording_session.calls.clear()

            # User clicks confirm — entry should be expired
            post_interaction(client, make_component_click("hitl:run_exp:confirm"))

        mock_agent.acontinue_run.assert_not_called()
        posts = _get_calls(recording_session, "POST")
        assert any("expired" in str(c[2]).lower() for c in posts)

    def test_double_click(self, mock_agent, recording_session):
        mock_agent.arun = AsyncMock(return_value=make_paused_response(run_id="run_dbl"))
        mock_agent.acontinue_run = AsyncMock(return_value=make_agent_response(content="Done"))

        app = make_discord_app(mock_agent)
        client = TestClient(app, raise_server_exceptions=False)

        # Trigger and first click
        post_interaction(client, make_slash_command())
        post_interaction(client, make_component_click("hitl:run_dbl:confirm"))

        # Second click — entry already removed
        recording_session.calls.clear()
        post_interaction(client, make_component_click("hitl:run_dbl:confirm"))

        # acontinue_run called only once (first click)
        assert mock_agent.acontinue_run.call_count == 1
        posts = _get_calls(recording_session, "POST")
        assert any("expired" in str(c[2]).lower() or "handled" in str(c[2]).lower() for c in posts)
