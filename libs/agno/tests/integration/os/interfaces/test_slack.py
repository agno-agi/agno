import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.run.agent import RunOutput


@pytest.fixture
def test_agent():
    """Create a test agent for Slack."""
    return Agent(name="test-slack-agent", instructions="You are a helpful assistant.")


@pytest.fixture
def test_client(test_agent: Agent):
    """Create a FastAPI test client with Slack interface."""
    slack_interface = Slack(agent=test_agent, prefix="/slack")
    agent_os = AgentOS(agents=[test_agent], interfaces=[slack_interface])
    app = agent_os.get_app()
    return TestClient(app)


def create_slack_signature(body: bytes, timestamp: str, secret: str) -> str:
    """Create a valid Slack signature for testing."""
    import hashlib
    import hmac

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    signature = "v0=" + hmac.new(secret.encode("utf-8"), sig_basestring.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature


@pytest.fixture
def slack_signing_secret():
    """Test Slack signing secret."""
    return "test_signing_secret_12345"


def test_slack_message_event(test_agent: Agent, test_client: TestClient, slack_signing_secret: str):
    """Test processing of Slack message event."""
    # Use current timestamp for the request
    current_timestamp = str(int(time.time()))
    ts_value = f"{current_timestamp}.123456"
    
    mock_output = RunOutput(
        run_id="test-run-123",
        session_id=ts_value,
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Hello! This is a test response.",
    )

    with patch("agno.os.interfaces.slack.security.SLACK_SIGNING_SECRET", slack_signing_secret):
        with patch("agno.os.interfaces.slack.security.time.time", return_value=int(current_timestamp)):
            with patch("agno.os.interfaces.slack.router.SlackTools") as mock_slack_tools:
                # Mock SlackTools to avoid requiring SLACK_TOKEN
                mock_slack_instance = MagicMock()
                mock_slack_tools.return_value = mock_slack_instance
                
                with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
                    mock_arun.return_value = mock_output

                    event_data = {
                        "token": "test_token",
                        "team_id": "T123456",
                        "api_app_id": "A123456",
                        "event": {
                            "type": "message",
                            "text": "Hello, bot!",
                            "user": "U123456",
                            "ts": ts_value,
                            "channel": "D123456",  # Use DM channel (starts with D)
                        },
                        "type": "event_callback",
                        "event_id": "Ev123456",
                        "event_time": int(current_timestamp),
                    }

                    body = json.dumps(event_data).encode("utf-8")
                    signature = create_slack_signature(body, current_timestamp, slack_signing_secret)

                    response = test_client.post(
                        "/slack/events",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Slack-Request-Timestamp": current_timestamp,
                            "X-Slack-Signature": signature,
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "ok"

                    # Give background task time to execute
                    time.sleep(0.1)

                    # Verify agent was called with correct parameters
                    mock_arun.assert_called_once()
                    call_args = mock_arun.call_args
                    assert call_args.args[0] == "Hello, bot!"  # First positional arg is the input
                    assert call_args.kwargs.get("user_id") == "U123456"
                    assert call_args.kwargs.get("session_id") == ts_value


def test_slack_app_mention_event(test_agent: Agent, test_client: TestClient, slack_signing_secret: str):
    """Test processing of Slack app_mention event."""
    # Use current timestamp for the request
    current_timestamp = str(int(time.time()))
    ts_value = f"{current_timestamp}.654321"
    
    mock_output = RunOutput(
        run_id="test-run-456",
        session_id=ts_value,
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Hello! I was mentioned.",
    )

    with patch("agno.os.interfaces.slack.security.SLACK_SIGNING_SECRET", slack_signing_secret):
        with patch("agno.os.interfaces.slack.security.time.time", return_value=int(current_timestamp)):
            with patch("agno.os.interfaces.slack.router.SlackTools") as mock_slack_tools:
                # Mock SlackTools to avoid requiring SLACK_TOKEN
                mock_slack_instance = MagicMock()
                mock_slack_tools.return_value = mock_slack_instance
                
                with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
                    mock_arun.return_value = mock_output

                    event_data = {
                        "token": "test_token",
                        "team_id": "T123456",
                        "api_app_id": "A123456",
                        "event": {
                            "type": "app_mention",
                            "text": "<@U987654> Hello, bot!",
                            "user": "U123456",
                            "ts": ts_value,
                            "channel": "C123456",
                        },
                        "type": "event_callback",
                        "event_id": "Ev123457",
                        "event_time": int(current_timestamp),
                    }

                    body = json.dumps(event_data).encode("utf-8")
                    signature = create_slack_signature(body, current_timestamp, slack_signing_secret)

                    response = test_client.post(
                        "/slack/events",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Slack-Request-Timestamp": current_timestamp,
                            "X-Slack-Signature": signature,
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "ok"

                    # Give background task time to execute
                    time.sleep(0.1)

                    # Verify agent was called with correct parameters
                    mock_arun.assert_called_once()
                    call_args = mock_arun.call_args
                    assert call_args.args[0] == "<@U987654> Hello, bot!"  # First positional arg is the input
                    assert call_args.kwargs.get("user_id") == "U123456"
                    assert call_args.kwargs.get("session_id") == ts_value


def test_slack_message_event_with_thread(test_agent: Agent, test_client: TestClient, slack_signing_secret: str):
    """Test processing of Slack message event in a thread."""
    # Use current timestamp for the request
    current_timestamp = str(int(time.time()))
    thread_ts = f"{current_timestamp}.111111"
    ts_value = f"{current_timestamp}.222222"
    
    mock_output = RunOutput(
        run_id="test-run-789",
        session_id=thread_ts,
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="This is a threaded response.",
    )

    with patch("agno.os.interfaces.slack.security.SLACK_SIGNING_SECRET", slack_signing_secret):
        with patch("agno.os.interfaces.slack.security.time.time", return_value=int(current_timestamp)):
            with patch("agno.os.interfaces.slack.router.SlackTools") as mock_slack_tools:
                # Mock SlackTools to avoid requiring SLACK_TOKEN
                mock_slack_instance = MagicMock()
                mock_slack_tools.return_value = mock_slack_instance
                
                with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
                    mock_arun.return_value = mock_output

                    event_data = {
                        "token": "test_token",
                        "team_id": "T123456",
                        "api_app_id": "A123456",
                        "event": {
                            "type": "message",
                            "text": "Reply in thread",
                            "user": "U123456",
                            "ts": ts_value,
                            "thread_ts": thread_ts,
                            "channel": "D123456",  # Use DM channel (starts with D)
                        },
                        "type": "event_callback",
                        "event_id": "Ev123458",
                        "event_time": int(current_timestamp),
                    }

                    body = json.dumps(event_data).encode("utf-8")
                    signature = create_slack_signature(body, current_timestamp, slack_signing_secret)

                    response = test_client.post(
                        "/slack/events",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Slack-Request-Timestamp": current_timestamp,
                            "X-Slack-Signature": signature,
                        },
                    )

                    assert response.status_code == 200

                    # Give background task time to execute
                    time.sleep(0.1)

                    # Verify agent was called with thread_ts as session_id
                    mock_arun.assert_called_once()
                    call_args = mock_arun.call_args
                    assert call_args.kwargs.get("session_id") == thread_ts


def test_slack_bot_event_ignored(test_client: TestClient, slack_signing_secret: str):
    """Test that bot events are ignored and not processed."""
    # Use current timestamp for the request
    current_timestamp = str(int(time.time()))
    ts_value = f"{current_timestamp}.333333"
    
    with patch("agno.os.interfaces.slack.security.SLACK_SIGNING_SECRET", slack_signing_secret):
        with patch("agno.os.interfaces.slack.security.time.time", return_value=int(current_timestamp)):
            event_data = {
                "token": "test_token",
                "team_id": "T123456",
                "api_app_id": "A123456",
                "event": {
                    "type": "message",
                    "text": "Bot message",
                    "bot_id": "B123456",
                    "ts": ts_value,
                    "channel": "C123456",
                },
                "type": "event_callback",
                "event_id": "Ev123459",
                "event_time": int(current_timestamp),
            }

            body = json.dumps(event_data).encode("utf-8")
            signature = create_slack_signature(body, current_timestamp, slack_signing_secret)

            response = test_client.post(
                "/slack/events",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": current_timestamp,
                    "X-Slack-Signature": signature,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            # Bot events should be logged but not processed


def test_slack_app_mention_with_event_ts_fallback(
    test_agent: Agent, test_client: TestClient, slack_signing_secret: str
):
    """Test app_mention event uses event_ts as fallback when ts is missing."""
    # Use current timestamp for the request
    current_timestamp = str(int(time.time()))
    event_ts_value = f"{current_timestamp}.999999"
    
    mock_output = RunOutput(
        run_id="test-run-999",
        session_id=event_ts_value,
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Response using event_ts fallback.",
    )

    with patch("agno.os.interfaces.slack.security.SLACK_SIGNING_SECRET", slack_signing_secret):
        with patch("agno.os.interfaces.slack.security.time.time", return_value=int(current_timestamp)):
            with patch("agno.os.interfaces.slack.router.SlackTools") as mock_slack_tools:
                # Mock SlackTools to avoid requiring SLACK_TOKEN
                mock_slack_instance = MagicMock()
                mock_slack_tools.return_value = mock_slack_instance
                
                with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
                    mock_arun.return_value = mock_output

                    event_data = {
                        "token": "test_token",
                        "team_id": "T123456",
                        "api_app_id": "A123456",
                        "event": {
                            "type": "app_mention",
                            "text": "<@U987654> Test",
                            "user": "U123456",
                            "event_ts": event_ts_value,
                            "channel": "C123456",
                        },
                        "type": "event_callback",
                        "event_id": "Ev123460",
                        "event_time": int(current_timestamp),
                    }

                    body = json.dumps(event_data).encode("utf-8")
                    signature = create_slack_signature(body, current_timestamp, slack_signing_secret)

                    response = test_client.post(
                        "/slack/events",
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Slack-Request-Timestamp": current_timestamp,
                            "X-Slack-Signature": signature,
                        },
                    )

                    assert response.status_code == 200

                    # Give background task time to execute
                    time.sleep(0.1)

                    # Verify agent was called with event_ts as session_id
                    mock_arun.assert_called_once()
                    call_args = mock_arun.call_args
                    assert call_args.kwargs.get("session_id") == event_ts_value
