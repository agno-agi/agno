from unittest.mock import patch

import pytest

from .conftest import (
    build_app,
    make_agent_mock,
    make_async_client_mock,
    make_signed_request,
    make_slack_mock,
    wait_for_call,
)


@pytest.mark.asyncio
async def test_default_drops_all_bot_events():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "hello from a bot",
                "bot_id": "B_OTHER_BOT",
                "channel": "C123",
                "ts": "1708123456.000100",
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_opt_in_allows_peer_agent_messages():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")
    mock_slack.client.auth_test.return_value = {"bot_id": "B_SELF", "user_id": "U_SELF_BOT"}

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "authorizations": [{"user_id": "U_SELF_BOT"}],
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel_type": "channel",
                "text": "hello from peer bot",
                "bot_id": "B_OTHER_BOT",
                "channel": "C123",
                "ts": "1708123456.000100",
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    await wait_for_call(agent_mock.arun)
    agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_opt_in_drops_own_messages_by_bot_id():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")
    mock_slack.client.auth_test.return_value = {"bot_id": "B_SELF"}

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "api_app_id": "A_SELF",
            "authorizations": [{"user_id": "U_SELF_BOT"}],
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel_type": "channel",
                "text": "my own message",
                "bot_id": "B_SELF",
                "channel": "C123",
                "ts": "1708123456.000100",
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_opt_in_drops_own_messages_by_bot_user_id():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")
    mock_slack.client.auth_test.return_value = {"user_id": "U_SELF_BOT"}

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "api_app_id": "A_SELF",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "my own message",
                "user": "U_SELF_BOT",
                "channel": "C123",
                "ts": "1708123456.000100",
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_opt_in_allows_peer_webhook_bot_with_only_bot_id():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")
    mock_slack.client.auth_test.return_value = {"bot_id": "B_SELF"}

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "api_app_id": "A_SELF",
            "authorizations": [{"user_id": "U_SELF_BOT"}],
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel_type": "channel",
                "text": "webhook message",
                "bot_id": "B_WEBHOOK",
                "channel": "C123",
                "ts": "1708123456.000100",
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    await wait_for_call(agent_mock.arun)
    agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_opt_in_allows_peer_by_user_id_mismatch():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")
    mock_slack.client.auth_test.return_value = {"bot_id": "B_SELF", "user_id": "U_SELF_BOT"}

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "channel",
                "text": "message from other user",
                "user": "U_OTHER",
                "channel": "C123",
                "ts": "1708123456.000100",
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    await wait_for_call(agent_mock.arun)
    agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_lifecycle_subtypes_still_dropped_with_opt_in():
    agent_mock = make_agent_mock()
    mock_slack = make_slack_mock(token="xoxb-test")

    with (
        patch("agno.os.interfaces.slack.router.verify_slack_signature", return_value=True),
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()),
    ):
        app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
        from fastapi.testclient import TestClient

        client = TestClient(app)
        body = {
            "type": "event_callback",
            "api_app_id": "A_SELF",
            "authorizations": [{"user_id": "U_SELF_BOT"}],
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "channel_type": "channel",
                "channel": "C123",
                "ts": "1708123456.000100",
                "message": {"text": "edited", "user": "U_OTHER"},
            },
        }
        resp = make_signed_request(client, body)

    assert resp.status_code == 200
    agent_mock.arun.assert_not_called()
