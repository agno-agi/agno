import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import RunEvent

from .conftest import build_app, make_signed_request, make_slack_mock, make_stream_mock


def _make_streaming_agent(chunks=None):
    agent = AsyncMock()
    agent.name = "Test Agent"

    async def _arun_stream(*args, **kwargs):
        for c in chunks or []:
            yield c

    agent.arun = _arun_stream
    return agent


def _content_chunk(text):
    return Mock(
        event=RunEvent.run_content.value, content=text, tool=None, images=None, videos=None, audio=None, files=None
    )


def _streaming_body(user="U_HUMAN", channel="C123", thread_ts=None, text="hello"):
    ts = thread_ts or str(time.time())
    return {
        "type": "event_callback",
        "team_id": "T123",
        "authorizations": [{"user_id": "B_BOT"}],
        "event": {
            "type": "message",
            "channel_type": "im",
            "text": text,
            "user": user,
            "channel": channel,
            "ts": str(float(ts) + 1),
            "thread_ts": ts,
        },
    }


async def _wait_stream_stop(mock_stream, timeout=5.0):
    elapsed = 0.0
    while not mock_stream.stop.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


class TestStreamingHappyPath:
    @pytest.mark.asyncio
    async def test_status_set_and_stream_created(self):
        agent = _make_streaming_agent(chunks=[])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            body = _streaming_body()
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            await _wait_stream_stop(mock_stream)
            status_calls = mock_client.assistant_threads_setStatus.call_args_list
            assert len(status_calls) >= 1
            assert status_calls[0].kwargs.get("status") == "Thinking..."
            mock_client.chat_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_content_appended_to_stream(self):
        agent = _make_streaming_agent(chunks=[_content_chunk("Hello "), _content_chunk("world")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            resp = make_signed_request(client, _streaming_body())
            assert resp.status_code == 200

            await _wait_stream_stop(mock_stream)
            # stream.append called for plan_update + text flushes
            append_calls = mock_stream.append.call_args_list
            text_calls = [c for c in append_calls if c.kwargs.get("markdown_text")]
            assert len(text_calls) >= 1
            mock_stream.stop.assert_called_once()


class TestRecipientUserId:
    @pytest.mark.asyncio
    async def test_human_user_not_bot(self):
        agent = _make_streaming_agent(chunks=[_content_chunk("hi")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            resp = make_signed_request(client, _streaming_body(user="U_HUMAN"))
            assert resp.status_code == 200

            await _wait_stream_stop(mock_stream)
            call_kwargs = mock_client.chat_stream.call_args.kwargs
            assert call_kwargs["recipient_user_id"] == "U_HUMAN"
            assert call_kwargs["recipient_team_id"] == "T123"


class TestStreamingFallbacks:
    @pytest.mark.asyncio
    async def test_no_thread_ts_still_streams_using_event_ts(self):
        agent = AsyncMock()
        agent.arun = AsyncMock(
            return_value=Mock(
                status="OK",
                content="fallback",
                reasoning_content=None,
                images=None,
                files=None,
                videos=None,
                audio=None,
            )
        )
        agent.name = "Test Agent"
        mock_slack = make_slack_mock(token="xoxb-test")

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            ts = str(time.time())
            body = {
                "type": "event_callback",
                "team_id": "T123",
                "authorizations": [{"user_id": "B_BOT"}],
                "event": {
                    "type": "message",
                    "channel_type": "im",
                    "text": "no thread",
                    "user": "U123",
                    "channel": "C123",
                    "ts": ts,
                },
            }
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            elapsed = 0.0
            while not agent.arun.called and elapsed < 5.0:
                await asyncio.sleep(0.1)
                elapsed += 0.1
            agent.arun.assert_called_once()

    @pytest.mark.asyncio
    async def test_null_response_stream_clears_status(self):
        agent = AsyncMock()
        agent.arun = None  # entity returns None
        agent.name = "Test Agent"
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            resp = make_signed_request(client, _streaming_body())
            assert resp.status_code == 200
            await asyncio.sleep(1.0)
            # Status should be cleared (empty string) since response_stream is None
            status_calls = mock_client.assistant_threads_setStatus.call_args_list
            clear_calls = [c for c in status_calls if c.kwargs.get("status") == ""]
            assert len(clear_calls) >= 1

    @pytest.mark.asyncio
    async def test_exception_cleanup(self):
        agent = AsyncMock()
        agent.name = "Test Agent"

        async def _exploding_stream(*args, **kwargs):
            yield _content_chunk("partial")
            raise RuntimeError("mid-stream crash")

        agent.arun = _exploding_stream
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            resp = make_signed_request(client, _streaming_body())
            assert resp.status_code == 200

            await asyncio.sleep(2.0)
            # Stream should be stopped on error
            mock_stream.stop.assert_called()
            # Status should be cleared
            status_calls = mock_client.assistant_threads_setStatus.call_args_list
            clear_calls = [c for c in status_calls if c.kwargs.get("status") == ""]
            assert len(clear_calls) >= 1
            # Fallback message sent
            mock_slack.send_message_thread.assert_called()


class TestStreamingTitle:
    @pytest.mark.asyncio
    async def test_title_set_on_first_content(self):
        agent = _make_streaming_agent(chunks=[_content_chunk("Hello")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            resp = make_signed_request(client, _streaming_body())
            assert resp.status_code == 200

            await _wait_stream_stop(mock_stream)
            mock_client.assistant_threads_setTitle.assert_called_once()

    @pytest.mark.asyncio
    async def test_title_not_set_twice(self):
        agent = _make_streaming_agent(chunks=[_content_chunk("Hello "), _content_chunk("world")])
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_stream = make_stream_mock()
        mock_client = AsyncMock()
        mock_client.assistant_threads_setStatus = AsyncMock()
        mock_client.assistant_threads_setTitle = AsyncMock()
        mock_client.chat_stream = AsyncMock(return_value=mock_stream)

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            resp = make_signed_request(client, _streaming_body())
            assert resp.status_code == 200

            await _wait_stream_stop(mock_stream)
            assert mock_client.assistant_threads_setTitle.call_count == 1


class TestThreadStarted:
    @pytest.mark.asyncio
    async def test_default_prompts(self):
        agent = _make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setSuggestedPrompts = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"channel_id": "C123", "thread_ts": "1234.5678"},
                },
            }
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            await asyncio.sleep(1.0)
            mock_client.assistant_threads_setSuggestedPrompts.assert_called_once()
            call_kwargs = mock_client.assistant_threads_setSuggestedPrompts.call_args.kwargs
            assert len(call_kwargs["prompts"]) == 2

    @pytest.mark.asyncio
    async def test_custom_prompts(self):
        agent = _make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setSuggestedPrompts = AsyncMock()
        custom = [{"title": "Custom", "message": "Do X"}]

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False, suggested_prompts=custom)
            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {"channel_id": "C123", "thread_ts": "1234.5678"},
                },
            }
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            await asyncio.sleep(1.0)
            call_kwargs = mock_client.assistant_threads_setSuggestedPrompts.call_args.kwargs
            assert call_kwargs["prompts"] == custom

    @pytest.mark.asyncio
    async def test_missing_channel_returns_early(self):
        agent = _make_streaming_agent()
        mock_slack = make_slack_mock(token="xoxb-test")
        mock_client = AsyncMock()
        mock_client.assistant_threads_setSuggestedPrompts = AsyncMock()

        with (
            patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
            patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
            patch("slack_sdk.web.async_client.AsyncWebClient", return_value=mock_client),
        ):
            app = build_app(agent, streaming=True, reply_to_mentions_only=False)
            client = TestClient(app)
            body = {
                "type": "event_callback",
                "event": {
                    "type": "assistant_thread_started",
                    "assistant_thread": {},
                },
            }
            resp = make_signed_request(client, body)
            assert resp.status_code == 200

            await asyncio.sleep(0.5)
            mock_client.assistant_threads_setSuggestedPrompts.assert_not_called()
