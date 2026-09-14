"""Transport-level behaviour of the Bolt-backed Slack routes.

Signature verification, URL verification, retry handling, own-bot filtering, and
acknowledgement of unknown interactions are Bolt or middleware concerns; these tests
drive them through the real FastAPI routes with signed requests.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from .conftest import (
    OWN_BOT_ID,
    OWN_BOT_USER_ID,
    SIGNING_SECRET,
    build_app,
    make_agent_mock,
    make_async_client_mock,
    make_signed_interaction,
    make_signed_request,
    post_raw,
    sign_headers,
    wait_for_call,
)


def _dm_event(event_id: str = "Ev1", text: str = "hello", user: str = "U123") -> dict:
    return {
        "type": "event_callback",
        "event_id": event_id,
        "team_id": "T123",
        "authorizations": [{"user_id": OWN_BOT_USER_ID}],
        "event": {
            "type": "message",
            "channel_type": "im",
            "text": text,
            "user": user,
            "channel": "C123",
            "ts": str(time.time()),
        },
    }


@pytest.mark.asyncio
async def test_url_verification_echoes_challenge():
    app = build_app(make_agent_mock())
    resp = await make_signed_request(app, {"type": "url_verification", "challenge": "abc123"})
    assert resp.status_code == 200
    assert resp.json() == {"challenge": "abc123"}


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_before_dispatch():
    agent_mock = make_agent_mock()
    app = build_app(agent_mock)
    resp = await make_signed_request(app, _dm_event(), signing_secret="wrong-secret")
    assert resp.status_code == 401
    await asyncio.sleep(0.1)
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_stale_timestamp_is_rejected():
    agent_mock = make_agent_mock()
    app = build_app(agent_mock)
    body_bytes = json.dumps(_dm_event()).encode()
    headers = sign_headers(body_bytes)
    # Re-sign with a timestamp outside Slack's five minute replay window
    stale_ts = str(int(time.time()) - 3600)
    headers["X-Slack-Request-Timestamp"] = stale_ts
    resp = await post_raw(app, "/events", body_bytes, headers)
    assert resp.status_code == 401
    await asyncio.sleep(0.1)
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_missing_signature_headers_are_rejected():
    app = build_app(make_agent_mock())
    body_bytes = json.dumps(_dm_event()).encode()
    resp = await post_raw(app, "/events", body_bytes, {"Content-Type": "application/json"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ssl_check_is_acknowledged():
    app = build_app(make_agent_mock())
    body_bytes = b"ssl_check=1&token=abc"
    headers = sign_headers(body_bytes)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    resp = await post_raw(app, "/events", body_bytes, headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_same_event_id_runs_once():
    agent_mock = make_agent_mock()
    with patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        first = await make_signed_request(app, _dm_event("Ev-dup"))
        retry = await make_signed_request(app, _dm_event("Ev-dup"), **{"X-Slack-Retry-Num": "1"})
        await wait_for_call(agent_mock.arun)
        await asyncio.sleep(0.1)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert agent_mock.arun.call_count == 1


@pytest.mark.asyncio
async def test_unseen_retry_is_processed():
    """A retry whose original delivery never arrived must still run."""
    agent_mock = make_agent_mock()
    with patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        resp = await make_signed_request(app, _dm_event("Ev-late"), **{"X-Slack-Retry-Num": "2"})
        await wait_for_call(agent_mock.arun)

    assert resp.status_code == 200
    agent_mock.arun.assert_called_once()


@pytest.mark.asyncio
async def test_distinct_event_ids_both_run():
    agent_mock = make_agent_mock()
    with patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=make_async_client_mock()):
        app = build_app(agent_mock, reply_to_mentions_only=False)
        await make_signed_request(app, _dm_event("Ev-a"))
        await make_signed_request(app, _dm_event("Ev-b"))
        deadline = time.time() + 5
        while agent_mock.arun.call_count < 2 and time.time() < deadline:
            await asyncio.sleep(0.05)

    assert agent_mock.arun.call_count == 2


@pytest.mark.asyncio
async def test_retry_without_event_id_is_dropped():
    agent_mock = make_agent_mock()
    app = build_app(agent_mock, reply_to_mentions_only=False)
    body = _dm_event()
    del body["event_id"]
    resp = await make_signed_request(app, body, **{"X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "http_timeout"})
    assert resp.status_code == 200
    await asyncio.sleep(0.1)
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_own_bot_message_is_dropped_by_transport():
    agent_mock = make_agent_mock()
    app = build_app(agent_mock, reply_to_mentions_only=False, respond_to_other_apps=True)
    body = _dm_event("Ev-own", user=OWN_BOT_USER_ID)
    body["event"]["bot_id"] = OWN_BOT_ID
    resp = await make_signed_request(app, body)
    assert resp.status_code == 200
    await asyncio.sleep(0.1)
    agent_mock.arun.assert_not_called()


@pytest.mark.asyncio
async def test_unhandled_event_type_is_acknowledged():
    app = build_app(make_agent_mock())
    body = _dm_event("Ev-react")
    body["event"] = {"type": "reaction_added", "user": "U123", "reaction": "thumbsup", "event_ts": "1.2"}
    resp = await make_signed_request(app, body)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unknown_action_is_acknowledged():
    app = build_app(make_agent_mock())
    payload = {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": "U123"},
        "channel": {"id": "C123"},
        "message": {"ts": "1.2"},
        "actions": [{"action_id": "some_other_app_button", "value": "x"}],
    }
    resp = await make_signed_interaction(app, payload)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_interaction_retry_is_dropped():
    from agno.os.interfaces.slack.ids import ACTION_SUBMIT

    app = build_app(make_agent_mock())
    payload = {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": "U123"},
        "channel": {"id": "C123"},
        "message": {"ts": "1.2", "thread_ts": "1.1", "blocks": []},
        "state": {"values": {}},
        "actions": [{"action_id": ACTION_SUBMIT, "block_id": "pause:run-1", "value": "run-1|"}],
    }
    with patch("agno.os.interfaces.slack.hitl.HITLHandler.handle_submit", new=AsyncMock()) as submit:
        resp = await make_signed_interaction(app, payload, **{"X-Slack-Retry-Num": "1"})
        await asyncio.sleep(0.1)

    assert resp.status_code == 200
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_interaction_dispatches_to_hitl_handler():
    from agno.os.interfaces.slack.ids import ACTION_SUBMIT

    app = build_app(make_agent_mock())
    payload = {
        "type": "block_actions",
        "team": {"id": "T123"},
        "user": {"id": "U123"},
        "channel": {"id": "C123"},
        "message": {"ts": "1.2", "thread_ts": "1.1", "blocks": []},
        "state": {"values": {}},
        "actions": [{"action_id": ACTION_SUBMIT, "block_id": "pause:run-1", "value": "run-1|"}],
    }
    with patch("agno.os.interfaces.slack.hitl.HITLHandler.handle_submit", new=AsyncMock()) as submit:
        resp = await make_signed_interaction(app, payload)
        await wait_for_call(submit)

    assert resp.status_code == 200
    submit.assert_called_once()
    assert submit.call_args.args[0]["actions"][0]["action_id"] == ACTION_SUBMIT


@pytest.mark.asyncio
async def test_signing_secret_from_constructor_is_enforced():
    agent_mock = make_agent_mock()
    app = build_app(agent_mock, signing_secret="my-secret")
    ok = await make_signed_request(app, {"type": "url_verification", "challenge": "x"}, signing_secret="my-secret")
    bad = await make_signed_request(app, {"type": "url_verification", "challenge": "x"}, signing_secret=SIGNING_SECRET)
    assert ok.status_code == 200
    assert bad.status_code == 401
