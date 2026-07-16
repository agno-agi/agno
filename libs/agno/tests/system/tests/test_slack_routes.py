"""
System Tests for Slack Interface Routes.

Tests both local and remote agents/teams/workflows through the Slack interface.
Note: These tests mock Slack webhook signatures since we don't have actual Slack credentials.

Run with: pytest test_slack_routes.py -v --tb=short
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Dict

import httpx
import pytest

from .test_utils import REQUEST_TIMEOUT, generate_jwt_token


def generate_slack_signature(body: bytes, timestamp: str, signing_secret: str) -> str:
    """Generate a valid Slack signature for testing.

    Args:
        body: Request body bytes
        timestamp: Unix timestamp string
        signing_secret: Slack signing secret

    Returns:
        Slack signature string
    """
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    signature = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )
    return signature


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"U{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture(scope="module")
def test_channel_id() -> str:
    """Generate a unique channel ID for testing."""
    return f"C{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


@pytest.fixture(scope="module")
def slack_signing_secret() -> str:
    """Get the Slack signing secret from environment or use test default."""
    return os.getenv("SLACK_SIGNING_SECRET", "test-signing-secret")


def make_slack_request(
    client: httpx.Client,
    endpoint: str,
    body: Dict[str, Any],
    signing_secret: str,
) -> httpx.Response:
    """Make a properly signed Slack webhook request.

    Args:
        client: HTTP client
        endpoint: API endpoint
        body: Request body
        signing_secret: Slack signing secret

    Returns:
        HTTP response
    """
    body_bytes = json.dumps(body).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = generate_slack_signature(body_bytes, timestamp, signing_secret)

    return client.post(
        endpoint,
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": signature,
        },
    )


# =============================================================================
# Slack Interface Tests - URL Verification
# =============================================================================


class TestSlackURLVerification:
    """Test Slack URL verification challenge."""

    def test_slack_url_verification_local_agent(self, client: httpx.Client, slack_signing_secret: str):
        """Test Slack URL verification for local agent interface."""
        challenge = str(uuid.uuid4())
        body = {"type": "url_verification", "challenge": challenge}

        response = make_slack_request(
            client,
            "/slack/local/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == challenge

    def test_slack_url_verification_remote_agent(self, client: httpx.Client, slack_signing_secret: str):
        """Test Slack URL verification for remote agent interface."""
        challenge = str(uuid.uuid4())
        body = {"type": "url_verification", "challenge": challenge}

        response = make_slack_request(
            client,
            "/slack/remote/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == challenge

    def test_slack_url_verification_team(self, client: httpx.Client, slack_signing_secret: str):
        """Test Slack URL verification for team interface."""
        challenge = str(uuid.uuid4())
        body = {"type": "url_verification", "challenge": challenge}

        response = make_slack_request(
            client,
            "/slack/team/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == challenge

    def test_slack_url_verification_workflow(self, client: httpx.Client, slack_signing_secret: str):
        """Test Slack URL verification for workflow interface."""
        challenge = str(uuid.uuid4())
        body = {"type": "url_verification", "challenge": challenge}

        response = make_slack_request(
            client,
            "/slack/workflow/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["challenge"] == challenge


# =============================================================================
# Slack Interface Tests - Event Handling
# =============================================================================


class TestSlackEventHandling:
    """Test Slack event handling for agents, teams, and workflows."""

    def test_slack_event_local_agent(
        self, client: httpx.Client, slack_signing_secret: str, test_user_id: str, test_channel_id: str
    ):
        """Test Slack event handling for local agent (DM)."""
        ts = str(time.time())
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "Hello agent",
                "user": test_user_id,
                "channel": test_channel_id,
                "ts": ts,
            },
        }

        response = make_slack_request(
            client,
            "/slack/local/events",
            body,
            slack_signing_secret,
        )

        # Event should be acknowledged immediately (processing happens in background)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_slack_event_remote_agent(
        self, client: httpx.Client, slack_signing_secret: str, test_user_id: str, test_channel_id: str
    ):
        """Test Slack event handling for remote agent (DM)."""
        ts = str(time.time())
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "Hello remote agent",
                "user": test_user_id,
                "channel": test_channel_id,
                "ts": ts,
            },
        }

        response = make_slack_request(
            client,
            "/slack/remote/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_slack_event_team(
        self, client: httpx.Client, slack_signing_secret: str, test_user_id: str, test_channel_id: str
    ):
        """Test Slack event handling for team (app mention)."""
        ts = str(time.time())
        body = {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@BOTID> What is 2 + 2?",
                "user": test_user_id,
                "channel": test_channel_id,
                "ts": ts,
            },
        }

        response = make_slack_request(
            client,
            "/slack/team/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_slack_event_workflow(
        self, client: httpx.Client, slack_signing_secret: str, test_user_id: str, test_channel_id: str
    ):
        """Test Slack event handling for workflow (DM)."""
        ts = str(time.time())
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "Run workflow",
                "user": test_user_id,
                "channel": test_channel_id,
                "ts": ts,
            },
        }

        response = make_slack_request(
            client,
            "/slack/workflow/events",
            body,
            slack_signing_secret,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_slack_ignores_bot_events(
        self, client: httpx.Client, slack_signing_secret: str, test_user_id: str, test_channel_id: str
    ):
        """Test that bot events are ignored."""
        ts = str(time.time())
        body = {
            "type": "event_callback",
            "event": {
                "type": "message",
                "channel_type": "im",
                "text": "Bot message",
                "bot_id": "B123456",
                "channel": test_channel_id,
                "ts": ts,
            },
        }

        response = make_slack_request(
            client,
            "/slack/local/events",
            body,
            slack_signing_secret,
        )

        # Should still return ok but not process
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


# =============================================================================
# Slack Interface Tests - Security
# =============================================================================


class TestSlackSecurity:
    """Test Slack security measures."""

    def test_slack_missing_headers(self, client: httpx.Client):
        """Test that requests without Slack headers are rejected."""
        response = client.post(
            "/slack/local/events",
            json={"type": "url_verification", "challenge": "test"},
        )
        assert response.status_code == 400
        data = response.json()
        assert "Missing Slack headers" in data["detail"]

    def test_slack_invalid_signature(self, client: httpx.Client):
        """Test that requests with invalid signature are rejected."""
        body = json.dumps({"type": "url_verification", "challenge": "test"})
        timestamp = str(int(time.time()))

        response = client.post(
            "/slack/local/events",
            content=body.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": "v0=invalid_signature",
            },
        )
        assert response.status_code == 403
        data = response.json()
        assert "Invalid signature" in data["detail"]
