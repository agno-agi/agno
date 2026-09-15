"""Unit tests for the SuperGrok OAuth device flow (RFC 8628).

The poll state machine encodes RFC 8628 section 3.5. The pending/slow_down
path was not exercised in the live run (approval preceded the first poll), so
those cases encode the RFC and the observed interval of 5 seconds [A3].
"""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qsl

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.xai import oauth
from agno.models.xai.oauth import (
    REFRESH_MARGIN_SECONDS,
    XAI_DEVICE_CODE_URL,
    XAI_OAUTH_CLIENT_ID,
    XAI_OAUTH_ISSUER,
    XAI_OAUTH_SCOPE,
    XAI_TOKEN_URL,
    XAITokenManager,
)

EXPIRED_MESSAGE = "The SuperGrok sign-in code expired (30 minutes). Start the login again."


def _manager(handler, **kwargs) -> XAITokenManager:
    return XAITokenManager(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


# ---------------------------------------------------------------------------
# Constants block (live-verified endpoint, client, scope, and margin values)
# ---------------------------------------------------------------------------


def test_constants_match_live_verified_values():
    assert XAI_OAUTH_ISSUER == "https://auth.x.ai"
    assert XAI_DEVICE_CODE_URL == "https://auth.x.ai/oauth2/device/code"
    assert XAI_TOKEN_URL == "https://auth.x.ai/oauth2/token"
    assert XAI_OAUTH_CLIENT_ID == "b1a00492-073a-47ea-816f-4c329264a828"
    assert XAI_OAUTH_SCOPE == "openid profile email offline_access grok-cli:access api:access"
    assert REFRESH_MARGIN_SECONDS == 300


# ---------------------------------------------------------------------------
# T1: device start - request fields, response parse, defaults
# ---------------------------------------------------------------------------


def test_start_device_login_sends_client_id_and_scope_only(device_response):
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=device_response)

    info = _manager(handler).start_device_login()

    request = captured[0]
    assert str(request.url) == XAI_DEVICE_CODE_URL
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    # Device grant: client_id and scope only - no PKCE, no state
    assert dict(parse_qsl(request.content.decode())) == {"client_id": XAI_OAUTH_CLIENT_ID, "scope": XAI_OAUTH_SCOPE}

    assert info.device_code == "device-code-1"
    assert info.user_code == "ABCD-1234"
    assert info.verification_uri == "https://auth.x.ai/activate"
    assert info.verification_uri_complete == "https://auth.x.ai/activate?user_code=ABCD-1234"
    assert info.expires_in == 1800
    assert info.interval == 5


def test_start_device_login_defaults_when_fields_absent():
    minimal = {
        "device_code": "device-code-1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://auth.x.ai/activate",
        "verification_uri_complete": "https://auth.x.ai/activate?user_code=ABCD-1234",
    }

    info = _manager(lambda request: httpx.Response(200, json=minimal)).start_device_login()

    assert info.expires_in == 1800
    assert info.interval == 5


def test_start_device_login_falls_back_when_uri_complete_absent():
    # RFC 8628 section 3.3.1 makes verification_uri_complete OPTIONAL; absence
    # falls back to the plain URI instead of KeyError
    minimal = {
        "device_code": "device-code-1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://auth.x.ai/activate",
        "expires_in": 1800,
        "interval": 5,
    }

    info = _manager(lambda request: httpx.Response(200, json=minimal)).start_device_login()

    assert info.verification_uri_complete == "https://auth.x.ai/activate"


async def test_astart_device_login_parses_response(device_response):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=device_response))
    ) as client:
        info = await XAITokenManager(async_http_client=client).astart_device_login()

    assert info.device_code == "device-code-1"
    assert info.expires_in == 1800
    assert info.interval == 5


# ---------------------------------------------------------------------------
# T2: poll state machine (RFC 8628 section 3.5)
# ---------------------------------------------------------------------------


def _sequence_handler(responses):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    return handler, calls


def test_poll_request_fields(token_response):
    handler, calls = _sequence_handler([httpx.Response(200, json=token_response)])

    _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    request = calls[0]
    assert str(request.url) == XAI_TOKEN_URL
    assert dict(parse_qsl(request.content.decode())) == {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": "device-code-1",
        "client_id": XAI_OAUTH_CLIENT_ID,
    }


def test_poll_pending_then_success(token_response):
    handler, calls = _sequence_handler(
        [
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(200, json=token_response),
        ]
    )

    with patch("agno.models.xai.oauth.time.sleep") as mock_sleep:
        token = _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert token["access_token"] == "access-token-1"
    assert len(calls) == 3
    assert [call.args[0] for call in mock_sleep.call_args_list] == [5, 5]


def test_poll_slow_down_adds_five_seconds(token_response):
    handler, calls = _sequence_handler(
        [
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(400, json={"error": "slow_down"}),
            httpx.Response(200, json=token_response),
        ]
    )

    with patch("agno.models.xai.oauth.time.sleep") as mock_sleep:
        token = _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert token["access_token"] == "access-token-1"
    # RFC 8628 section 3.5: slow_down mandates interval += 5
    assert [call.args[0] for call in mock_sleep.call_args_list] == [5, 10]


def test_poll_access_denied_is_terminal():
    handler, calls = _sequence_handler([httpx.Response(400, json={"error": "access_denied"})])

    with pytest.raises(ModelAuthenticationError) as exc_info:
        _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert exc_info.value.message == "SuperGrok sign-in was denied in the browser."
    assert len(calls) == 1


def test_poll_expired_token_is_terminal():
    handler, calls = _sequence_handler([httpx.Response(400, json={"error": "expired_token"})])

    with pytest.raises(ModelAuthenticationError) as exc_info:
        _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert exc_info.value.message == EXPIRED_MESSAGE
    assert len(calls) == 1


def test_poll_unknown_error_carries_raw_body():
    body = {"error": "pizza_error", "error_description": "the oven is off"}
    response = httpx.Response(400, json=body)
    handler, calls = _sequence_handler([response])

    with pytest.raises(ModelAuthenticationError) as exc_info:
        _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    # The complete raw body is appended, not just the parsed error code
    assert response.text in exc_info.value.message
    assert len(calls) == 1


def test_poll_200_with_error_body_raises_clean():
    # An HTTP 200 carrying an error body must surface as a clean auth error,
    # not a KeyError from envelope construction
    handler, calls = _sequence_handler([httpx.Response(200, json={"error": "server_error"})])

    with pytest.raises(ModelAuthenticationError, match="missing access_token"):
        _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert len(calls) == 1


def test_poll_non_json_error_is_terminal():
    handler, calls = _sequence_handler([httpx.Response(500, text="upstream exploded")])

    with pytest.raises(ModelAuthenticationError, match="upstream exploded"):
        _manager(handler).poll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert len(calls) == 1


async def test_apoll_pending_then_success(token_response):
    responses = [
        httpx.Response(400, json={"error": "authorization_pending"}),
        httpx.Response(200, json=token_response),
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        manager = XAITokenManager(async_http_client=client)
        with patch("agno.models.xai.oauth.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            token = await manager.apoll_for_token("device-code-1", interval=5, deadline=10_000_000_000)

    assert token["access_token"] == "access-token-1"
    assert [call.args[0] for call in mock_sleep.call_args_list] == [5]


# ---------------------------------------------------------------------------
# T3: poll deadline (device grant expires after expires_in seconds)
# ---------------------------------------------------------------------------


def test_poll_past_deadline_is_terminal(fake_clock):
    handler, calls = _sequence_handler([httpx.Response(400, json={"error": "authorization_pending"})])
    manager = _manager(handler, now_fn=fake_clock)

    with patch("agno.models.xai.oauth.time.sleep") as mock_sleep:
        mock_sleep.side_effect = lambda seconds: fake_clock.advance(1000)
        with pytest.raises(ModelAuthenticationError) as exc_info:
            manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    assert exc_info.value.message == EXPIRED_MESSAGE
    # Advancing 1000s per sleep against an 1800s deadline permits exactly two
    # pre-deadline polls; none may happen after the deadline passes
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Transport timeout: httpx defaults to 5s, which is too short for a live IdP
# ---------------------------------------------------------------------------


def test_the_manager_defaults_to_a_thirty_second_timeout():
    assert XAITokenManager().timeout == 30.0


def test_the_sync_form_post_applies_the_managers_timeout(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, data=None):
            return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(oauth.httpx, "Client", FakeClient)
    oauth.XAITokenManager(timeout=12.5)._post_form("https://auth.example.invalid/token", {})

    assert captured["timeout"] == 12.5


async def test_the_async_form_post_applies_the_managers_timeout(monkeypatch):
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data=None):
            return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(oauth.httpx, "AsyncClient", FakeAsyncClient)
    await oauth.XAITokenManager(timeout=12.5)._apost_form("https://auth.example.invalid/token", {})

    assert captured["timeout"] == 12.5
