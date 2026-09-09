import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.os.settings import AgnoAPISettings

SIGNING_SECRET = "test-signing-secret"
OS_KEY = "test-os-security-key"


def _signed_headers(body_bytes: bytes, signing_secret: str = SIGNING_SECRET) -> dict:
    timestamp = str(int(time.time()))
    sig_base = f"v0:{timestamp}:{body_bytes.decode()}"
    signature = "v0=" + hmac.new(signing_secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
    }


@pytest.fixture
def agent_os_with_slack_and_key():
    agent = Agent(name="Test Agent", id="test-agent", telemetry=False)
    agent.arun = AsyncMock(
        return_value=Mock(
            status="OK", content="ok", reasoning_content=None, images=None, files=None, videos=None, audio=None
        )
    )

    mock_slack_tools = Mock()
    mock_slack_tools.send_message = Mock()
    mock_slack_tools.upload_file = Mock()
    mock_slack_tools.max_file_size = 1_073_741_824

    mock_async_web_client = AsyncMock()
    mock_async_web_client.users_info = AsyncMock(return_value={"ok": True, "user": {"id": "U123"}})

    settings = AgnoAPISettings(os_security_key=OS_KEY)
    slack = Slack(agent=agent, token="xoxb-test", signing_secret=SIGNING_SECRET, streaming=False)

    with (
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack_tools),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_async_web_client),
    ):
        agent_os = AgentOS(agents=[agent], interfaces=[slack], settings=settings, telemetry=False)
        app = agent_os.get_app()
        yield app, agent.arun


def test_config_requires_bearer_when_os_security_key_set(agent_os_with_slack_and_key):
    app, _ = agent_os_with_slack_and_key
    client = TestClient(app)

    resp = client.get("/config")
    assert resp.status_code == 401, f"Expected 401 on /config without Bearer, got {resp.status_code}"

    resp = client.get("/config", headers={"Authorization": f"Bearer {OS_KEY}"})
    assert resp.status_code == 200, f"Expected 200 on /config with valid Bearer, got {resp.status_code}: {resp.text}"


def test_slack_events_bypasses_os_security_key(agent_os_with_slack_and_key):
    app, arun_mock = agent_os_with_slack_and_key
    client = TestClient(app)

    body = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel_type": "im",
            "text": "hello",
            "user": "U456",
            "channel": "C123",
            "ts": str(time.time()),
        },
    }
    body_bytes = json.dumps(body).encode()

    resp = client.post("/slack/events", content=body_bytes, headers=_signed_headers(body_bytes))

    assert resp.status_code == 200, (
        f"Expected 200 on /slack/events with valid signature and NO Bearer (webhook should bypass "
        f"OS_SECURITY_KEY), got {resp.status_code}: {resp.text}"
    )


def test_slack_events_rejects_bad_signature(agent_os_with_slack_and_key):
    app, _ = agent_os_with_slack_and_key
    client = TestClient(app)

    body_bytes = b'{"type": "event_callback"}'
    bad_headers = _signed_headers(body_bytes, signing_secret="wrong-secret")

    resp = client.post("/slack/events", content=body_bytes, headers=bad_headers)

    assert resp.status_code == 403, f"Expected 403 from Slack signature check, got {resp.status_code}"
    assert "signature" in resp.text.lower()


def test_slack_url_verification_bypasses_os_security_key(agent_os_with_slack_and_key):
    app, _ = agent_os_with_slack_and_key
    client = TestClient(app)

    body = {"type": "url_verification", "challenge": "abc123"}
    body_bytes = json.dumps(body).encode()

    resp = client.post("/slack/events", content=body_bytes, headers=_signed_headers(body_bytes))

    assert resp.status_code == 200
    assert resp.json().get("challenge") == "abc123"


def test_env_var_os_security_key_does_not_block_slack(monkeypatch):
    """Simulate OS_SECURITY_KEY set in shell (.zshrc): should still let Slack webhooks through."""
    monkeypatch.setenv("OS_SECURITY_KEY", OS_KEY)

    agent = Agent(name="Env Test", id="env-test-agent", telemetry=False)
    agent.arun = AsyncMock(
        return_value=Mock(
            status="OK", content="ok", reasoning_content=None, images=None, files=None, videos=None, audio=None
        )
    )

    mock_slack_tools = Mock()
    mock_slack_tools.send_message = Mock()
    mock_slack_tools.upload_file = Mock()
    mock_slack_tools.max_file_size = 1_073_741_824
    mock_async_web_client = AsyncMock()
    mock_async_web_client.users_info = AsyncMock(return_value={"ok": True, "user": {"id": "U123"}})

    slack = Slack(agent=agent, token="xoxb-test", signing_secret=SIGNING_SECRET, streaming=False)

    with (
        patch("agno.os.interfaces.slack.router.SlackTools", return_value=mock_slack_tools),
        patch("agno.os.interfaces.slack.event_handler.AsyncWebClient", return_value=mock_async_web_client),
    ):
        agent_os = AgentOS(agents=[agent], interfaces=[slack], telemetry=False)
        assert agent_os.settings.os_security_key == OS_KEY, "Env var should have been picked up by AgnoAPISettings"

        app = agent_os.get_app()
        client = TestClient(app)

        resp = client.get("/config")
        assert resp.status_code == 401, "/config must be protected when OS_SECURITY_KEY is in env"

        body = {"type": "url_verification", "challenge": "env-test"}
        body_bytes = json.dumps(body).encode()
        resp = client.post("/slack/events", content=body_bytes, headers=_signed_headers(body_bytes))

        assert resp.status_code == 200, (
            f"With OS_SECURITY_KEY in env (simulating .zshrc), /slack/events should return 200 "
            f"for a valid signed request. Got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("challenge") == "env-test"
