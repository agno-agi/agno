import json
import time
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from agno.os.interfaces.discord.discord import Discord

# ---------------------------------------------------------------------------
# Ed25519 signing (real PyNaCl — NOT mocked)
# ---------------------------------------------------------------------------


def _make_ed25519_keypair():
    signing_key = SigningKey.generate()
    public_key_hex = signing_key.verify_key.encode().hex()
    return signing_key, public_key_hex


SIGNING_KEY, PUBLIC_KEY_HEX = _make_ed25519_keypair()


def sign_request(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    timestamp = str(int(time.time()))
    message = timestamp.encode() + body
    signature = SIGNING_KEY.sign(message).signature.hex()
    headers = {
        "Content-Type": "application/json",
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": timestamp,
    }
    return body, headers


# ---------------------------------------------------------------------------
# Recording aiohttp session — captures all outbound HTTP without making real calls
# ---------------------------------------------------------------------------


class _AsyncCtxManager:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        pass


class RecordingSession:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = False
        self._get_response_factory = None

    def _make_response(self, status=200, content_length=0, chunk_data=b""):
        resp = MagicMock()
        resp.raise_for_status = Mock()
        resp.status = status
        resp.content_length = content_length

        async def _iter_chunked(size):
            if chunk_data:
                yield chunk_data

        content_mock = MagicMock()
        content_mock.iter_chunked = _iter_chunked
        resp.content = content_mock
        return resp

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self._get_response_factory:
            resp = self._get_response_factory(url, kwargs)
        else:
            resp = self._make_response(content_length=1024, chunk_data=b"file-bytes")
        return _AsyncCtxManager(resp)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return _AsyncCtxManager(self._make_response())

    def patch(self, url, **kwargs):
        self.calls.append(("PATCH", url, kwargs))
        return _AsyncCtxManager(self._make_response())


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def make_slash_command(
    message: str = "Hello",
    user_id: str = "user1",
    channel_id: str = "channel1",
    guild_id: str = "guild1",
    application_id: str = "app123",
    token: str = "interaction_token",
    attachment: dict | None = None,
) -> dict:
    options: list[dict] = [{"name": "message", "value": message, "type": 3}]
    data: dict = {"name": "ask", "options": options}

    if attachment:
        att_id = attachment.get("id", "att123")
        options.append({"name": "file", "value": att_id, "type": 11})
        data["resolved"] = {"attachments": {str(att_id): attachment}}

    payload: dict = {
        "type": 2,
        "id": "1234",
        "application_id": application_id,
        "token": token,
        "channel_id": channel_id,
        "member": {"user": {"id": user_id}},
        "data": data,
    }
    if guild_id:
        payload["guild_id"] = guild_id
    return payload


def make_component_click(
    custom_id: str,
    user_id: str = "user1",
    application_id: str = "app123",
    token: str = "component_token",
) -> dict:
    return {
        "type": 3,
        "id": "5678",
        "application_id": application_id,
        "token": token,
        "guild_id": "guild1",
        "channel_id": "channel1",
        "member": {"user": {"id": user_id}},
        "data": {"custom_id": custom_id},
    }


def make_ping() -> dict:
    return {"type": 1}


# ---------------------------------------------------------------------------
# Agent response builder
# ---------------------------------------------------------------------------


def make_agent_response(**overrides):
    defaults = dict(
        status="OK",
        content="Hello from agent",
        reasoning_content=None,
        is_paused=False,
        run_id=None,
        tools_requiring_confirmation=None,
        images=None,
        files=None,
        videos=None,
        audio=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def make_paused_response(run_id="run123", tool_name="dangerous_tool"):
    mock_tool = MagicMock()
    mock_tool.tool_name = tool_name
    return make_agent_response(
        is_paused=True,
        run_id=run_id,
        tools_requiring_confirmation=[mock_tool],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def patch_public_key():
    from unittest.mock import patch

    with patch("agno.os.interfaces.discord.security.DISCORD_PUBLIC_KEY", PUBLIC_KEY_HEX):
        yield


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.arun = AsyncMock()
    agent.acontinue_run = AsyncMock()
    return agent


@pytest.fixture
def recording_session():
    return RecordingSession()


@pytest.fixture(autouse=True)
def patch_aiohttp_session(recording_session):
    from unittest.mock import patch as _patch

    with _patch("agno.os.interfaces.discord.router.aiohttp.ClientSession", return_value=recording_session):
        yield


def make_discord_app(mock_agent, **discord_kwargs):
    discord = Discord(agent=mock_agent, **discord_kwargs)
    app = FastAPI()
    app.include_router(discord.get_router())
    return app


@pytest.fixture
def discord_app(mock_agent):
    return make_discord_app(mock_agent)


@pytest.fixture
def client(discord_app):
    return TestClient(discord_app, raise_server_exceptions=False)


def post_interaction(client: TestClient, payload: dict, path="/discord/interactions"):
    body, headers = sign_request(payload)
    return client.post(path, content=body, headers=headers)
