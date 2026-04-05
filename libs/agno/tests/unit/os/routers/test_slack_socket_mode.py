"""
Unit tests for the Slack Socket Mode transport.

Tests cover:
- _make_handler: event dispatch, ACK behaviour, bot filtering, subtype filtering
- start_socket_mode: connection lifecycle (connect / close / import guard)
- Slack.astart() / Slack.start(): token resolution, error conditions
"""
import asyncio
import os
from typing import Any
from unittest.mock import ANY, AsyncMock, Mock, patch

import pytest

from agno.os.interfaces.slack._processing import ProcessingConfig, build_processing_config
from agno.os.interfaces.slack.socket_mode import _make_handler, start_socket_mode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(streaming: bool = True) -> ProcessingConfig:
    agent = AsyncMock()
    agent.name = "Test Agent"
    agent.id = "test-agent"
    with patch("agno.os.interfaces.slack._processing.SlackTools"):
        return build_processing_config(agent=agent, token="xoxb-test", streaming=streaming)


def _events_api_req(event: dict, envelope_id: str = "env-001") -> Mock:
    req = Mock()
    req.type = "events_api"
    req.envelope_id = envelope_id
    req.payload = {"event": event}
    return req


def _msg(**kwargs: Any) -> dict:
    return {
        "type": "message",
        "channel_type": "im",
        "text": "hello",
        "user": "U123",
        "channel": "C123",
        "ts": "1234567890.000001",
        **kwargs,
    }


# ---------------------------------------------------------------------------
# ACK behaviour
# ---------------------------------------------------------------------------


class TestSocketModeHandlerAck:
    """The handler must ACK every request before doing any processing."""

    @pytest.mark.asyncio
    async def test_acks_events_api_request(self):
        client = AsyncMock()
        req = _events_api_req(_msg())

        with patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock):
            await _make_handler(_make_config())(client, req)
            await asyncio.sleep(0)

        client.send_socket_mode_response.assert_called_once()
        response_obj = client.send_socket_mode_response.call_args.args[0]
        assert response_obj.envelope_id == "env-001"

    @pytest.mark.asyncio
    async def test_acks_non_events_api_request(self):
        """Handler ACKs even when it has nothing to dispatch."""
        client = AsyncMock()
        req = Mock(type="slash_commands", envelope_id="env-002")

        await _make_handler(_make_config())(client, req)

        client.send_socket_mode_response.assert_called_once()
        response_obj = client.send_socket_mode_response.call_args.args[0]
        assert response_obj.envelope_id == "env-002"

    @pytest.mark.asyncio
    async def test_acks_before_dispatching(self):
        """ACK must happen even when the downstream handler raises."""
        client = AsyncMock()
        req = _events_api_req(_msg())

        with patch(
            "agno.os.interfaces.slack.socket_mode.stream_slack_response",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            # The task raised but ACK already happened
            await _make_handler(_make_config())(client, req)
            await asyncio.sleep(0.05)

        client.send_socket_mode_response.assert_called_once()


# ---------------------------------------------------------------------------
# Event routing
# ---------------------------------------------------------------------------


class TestSocketModeHandlerRouting:
    """Handler dispatches events to the correct processing function."""

    @pytest.mark.asyncio
    async def test_message_routes_to_stream_when_streaming(self):
        client = AsyncMock()
        req = _events_api_req(_msg())

        with (
            patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream,
            patch("agno.os.interfaces.slack.socket_mode.process_slack_event", new_callable=AsyncMock) as mock_process,
        ):
            await _make_handler(_make_config(streaming=True))(client, req)
            await asyncio.sleep(0)

        mock_stream.assert_called_once_with(req.payload, ANY)
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_routes_to_process_when_not_streaming(self):
        client = AsyncMock()
        req = _events_api_req(_msg())

        with (
            patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream,
            patch("agno.os.interfaces.slack.socket_mode.process_slack_event", new_callable=AsyncMock) as mock_process,
        ):
            await _make_handler(_make_config(streaming=False))(client, req)
            await asyncio.sleep(0)

        mock_process.assert_called_once_with(req.payload, ANY)
        mock_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_started_routes_to_handle_thread_started(self):
        client = AsyncMock()
        event = {"type": "assistant_thread_started", "assistant_thread": {"channel_id": "C1", "thread_ts": "t1"}}
        req = _events_api_req(event)

        with patch(
            "agno.os.interfaces.slack.socket_mode.handle_thread_started", new_callable=AsyncMock
        ) as mock_handle:
            await _make_handler(_make_config(streaming=True))(client, req)
            await asyncio.sleep(0)

        mock_handle.assert_called_once_with(event, ANY)

    @pytest.mark.asyncio
    async def test_thread_started_not_dispatched_when_not_streaming(self):
        """assistant_thread_started falls through to process_slack_event when streaming=False."""
        client = AsyncMock()
        event = {"type": "assistant_thread_started", "assistant_thread": {"channel_id": "C1", "thread_ts": "t1"}}
        req = _events_api_req(event)

        with (
            patch("agno.os.interfaces.slack.socket_mode.handle_thread_started", new_callable=AsyncMock) as mock_handle,
            patch("agno.os.interfaces.slack.socket_mode.process_slack_event", new_callable=AsyncMock),
        ):
            await _make_handler(_make_config(streaming=False))(client, req)
            await asyncio.sleep(0)

        mock_handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_events_api_type_not_dispatched(self):
        client = AsyncMock()
        req = Mock(type="slash_commands", envelope_id="env-003")

        with (
            patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream,
            patch("agno.os.interfaces.slack.socket_mode.process_slack_event", new_callable=AsyncMock) as mock_process,
        ):
            await _make_handler(_make_config())(client, req)
            await asyncio.sleep(0)

        mock_stream.assert_not_called()
        mock_process.assert_not_called()


# ---------------------------------------------------------------------------
# Bot self-loop prevention and subtype filtering
# ---------------------------------------------------------------------------


class TestSocketModeHandlerFiltering:
    """Handler must not dispatch bot events or ignored subtypes."""

    @pytest.mark.asyncio
    async def test_bot_id_suppresses_dispatch(self):
        client = AsyncMock()
        req = _events_api_req(_msg(bot_id="B123"))

        with patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream:
            await _make_handler(_make_config())(client, req)
            await asyncio.sleep(0)

        mock_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_nested_message_bot_id_suppresses_dispatch(self):
        """message_changed events carry bot_id inside event.message, not at the top level."""
        client = AsyncMock()
        event = _msg(subtype="message_changed")
        event["message"] = {"bot_id": "B123", "text": "edited"}
        req = _events_api_req(event)

        with patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream:
            await _make_handler(_make_config())(client, req)
            await asyncio.sleep(0)

        mock_stream.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subtype",
        ["bot_message", "bot_add", "bot_remove", "bot_enable", "bot_disable", "message_changed", "message_deleted"],
    )
    async def test_ignored_subtype_suppresses_dispatch(self, subtype: str):
        client = AsyncMock()
        req = _events_api_req(_msg(subtype=subtype))

        with patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream:
            await _make_handler(_make_config())(client, req)
            await asyncio.sleep(0)

        mock_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_share_subtype_not_filtered(self):
        """file_share is NOT in IGNORED_SUBTYPES — file messages should be processed."""
        client = AsyncMock()
        req = _events_api_req(_msg(subtype="file_share"))

        with patch("agno.os.interfaces.slack.socket_mode.stream_slack_response", new_callable=AsyncMock) as mock_stream:
            await _make_handler(_make_config(streaming=True))(client, req)
            await asyncio.sleep(0)

        mock_stream.assert_called_once()


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestStartSocketMode:
    """Tests for the start_socket_mode connection lifecycle."""

    async def _run_briefly(self, coro):
        """Start a coroutine, let it run one tick, then cancel and await cleanup."""
        task = asyncio.create_task(coro)
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_creates_client_with_app_token(self):
        config = _make_config()
        mock_socket = AsyncMock()
        mock_socket.socket_mode_request_listeners = []

        with patch("agno.os.interfaces.slack.socket_mode.SocketModeClient", return_value=mock_socket) as mock_cls:
            await self._run_briefly(start_socket_mode(config, "xapp-test-token"))

        mock_cls.assert_called_once_with(app_token="xapp-test-token", web_client=ANY)

    @pytest.mark.asyncio
    async def test_registers_exactly_one_handler(self):
        config = _make_config()
        mock_socket = AsyncMock()
        mock_socket.socket_mode_request_listeners = []

        with patch("agno.os.interfaces.slack.socket_mode.SocketModeClient", return_value=mock_socket):
            await self._run_briefly(start_socket_mode(config, "xapp-test"))

        assert len(mock_socket.socket_mode_request_listeners) == 1
        assert callable(mock_socket.socket_mode_request_listeners[0])

    @pytest.mark.asyncio
    async def test_calls_connect(self):
        config = _make_config()
        mock_socket = AsyncMock()
        mock_socket.socket_mode_request_listeners = []

        with patch("agno.os.interfaces.slack.socket_mode.SocketModeClient", return_value=mock_socket):
            await self._run_briefly(start_socket_mode(config, "xapp-test"))

        mock_socket.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_close_on_cancellation(self):
        config = _make_config()
        mock_socket = AsyncMock()
        mock_socket.socket_mode_request_listeners = []

        with patch("agno.os.interfaces.slack.socket_mode.SocketModeClient", return_value=mock_socket):
            await self._run_briefly(start_socket_mode(config, "xapp-test"))

        mock_socket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_import_error_when_not_installed(self):
        config = _make_config()

        with patch("agno.os.interfaces.slack.socket_mode.SocketModeClient", None):
            with pytest.raises(ImportError, match="slack-sdk"):
                await start_socket_mode(config, "xapp-test")


# ---------------------------------------------------------------------------
# Slack.astart() / Slack.start()
# ---------------------------------------------------------------------------


class TestSlackAstart:
    """Tests for the Slack class socket mode entry points."""

    def _slack(self, **kwargs):
        from agno.os.interfaces.slack import Slack

        agent = AsyncMock()
        agent.name = "Test Agent"
        return Slack(agent=agent, **kwargs)

    @pytest.mark.asyncio
    async def test_raises_without_socket_mode_flag(self):
        with pytest.raises(RuntimeError, match="socket_mode=True"):
            await self._slack(socket_mode=False).astart()

    @pytest.mark.asyncio
    async def test_raises_when_no_app_token_anywhere(self):
        slack = self._slack(socket_mode=True)
        env = {k: v for k, v in os.environ.items() if k != "SLACK_APP_TOKEN"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError, match="App-Level Token"):
                await slack.astart()

    @pytest.mark.asyncio
    async def test_reads_app_token_from_env(self):
        slack = self._slack(socket_mode=True)

        with (
            patch.dict("os.environ", {"SLACK_APP_TOKEN": "xapp-from-env"}),
            patch("agno.os.interfaces.slack.socket_mode.start_socket_mode", new_callable=AsyncMock) as mock_start,
            patch("agno.os.interfaces.slack._processing.SlackTools"),
        ):
            await slack.astart()

        _config, token = mock_start.call_args.args
        assert token == "xapp-from-env"

    @pytest.mark.asyncio
    async def test_explicit_app_token_takes_precedence_over_env(self):
        slack = self._slack(socket_mode=True, app_token="xapp-explicit")

        with (
            patch.dict("os.environ", {"SLACK_APP_TOKEN": "xapp-from-env"}),
            patch("agno.os.interfaces.slack.socket_mode.start_socket_mode", new_callable=AsyncMock) as mock_start,
            patch("agno.os.interfaces.slack._processing.SlackTools"),
        ):
            await slack.astart()

        _config, token = mock_start.call_args.args
        assert token == "xapp-explicit"

    def test_start_is_sync_wrapper_around_astart(self):
        """start() should call asyncio.run(astart()) and complete without blocking."""
        slack = self._slack(socket_mode=True, app_token="xapp-test")

        with (
            patch("agno.os.interfaces.slack.socket_mode.start_socket_mode", new_callable=AsyncMock) as mock_start,
            patch("agno.os.interfaces.slack._processing.SlackTools"),
        ):
            slack.start()

        mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_astart_passes_correct_config_to_start_socket_mode(self):
        """Config built by astart() should reflect the Slack instance's settings."""
        slack = self._slack(
            socket_mode=True,
            app_token="xapp-test",
            streaming=False,
            reply_to_mentions_only=False,
        )

        with (
            patch("agno.os.interfaces.slack.socket_mode.start_socket_mode", new_callable=AsyncMock) as mock_start,
            patch("agno.os.interfaces.slack._processing.SlackTools"),
        ):
            await slack.astart()

        config, _token = mock_start.call_args.args
        assert config.streaming is False
        assert config.reply_to_mentions_only is False
