import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.google.auth import GoogleAuth
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools


@pytest.fixture
def google_auth():
    return GoogleAuth(client_id="test-client-id")


@pytest.fixture
def mock_creds():
    creds = Mock(spec=Credentials)
    creds.valid = True
    creds.expired = False
    return creds


# ---------------------------------------------------------------------------
# GoogleAuth initialization
# ---------------------------------------------------------------------------


def test_google_auth_init():
    ga = GoogleAuth(client_id="my-id")
    assert ga.client_id == "my-id"
    assert ga._services == {}
    assert "connect_google" in ga.functions


def test_google_auth_init_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    ga = GoogleAuth()
    assert ga.client_id == "env-id"


def test_google_auth_custom_redirect_uri():
    ga = GoogleAuth(client_id="id", redirect_uri="https://myapp.com/callback")
    assert ga.redirect_uri == "https://myapp.com/callback"


# ---------------------------------------------------------------------------
# Service registration
# ---------------------------------------------------------------------------


def test_register_service(google_auth):
    google_auth.register_service("gmail", ["scope1", "scope2"])
    assert google_auth._services["gmail"] == ["scope1", "scope2"]


def test_gmail_registers_with_google_auth(google_auth):
    GmailTools(google_auth=google_auth)
    assert "gmail" in google_auth._services
    assert google_auth._services["gmail"] == GmailTools.DEFAULT_SCOPES


def test_calendar_registers_with_google_auth(google_auth):
    GoogleCalendarTools(google_auth=google_auth)
    assert "calendar" in google_auth._services


def test_multi_toolkit_registration(google_auth):
    GmailTools(google_auth=google_auth)
    GoogleCalendarTools(google_auth=google_auth)
    assert len(google_auth._services) == 2
    assert "gmail" in google_auth._services
    assert "calendar" in google_auth._services


# ---------------------------------------------------------------------------
# Combined URL generation
# ---------------------------------------------------------------------------


def test_connect_google_combined_url(google_auth):
    google_auth.register_service(
        "gmail",
        [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
    )
    google_auth.register_service(
        "calendar",
        [
            "https://www.googleapis.com/auth/calendar",
        ],
    )

    result = json.loads(google_auth.connect_google(services=["gmail", "calendar"]))

    assert "url" in result
    parsed = urlparse(result["url"])
    params = parse_qs(parsed.query)

    # All 3 scopes present in the URL
    scope_str = params["scope"][0]
    assert "gmail.readonly" in scope_str
    assert "gmail.modify" in scope_str
    assert "calendar" in scope_str


def test_connect_google_includes_oauth_params(google_auth):
    google_auth.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])

    result = json.loads(google_auth.connect_google(services=["gmail"]))
    parsed = urlparse(result["url"])
    params = parse_qs(parsed.query)

    assert params["client_id"] == ["test-client-id"]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["include_granted_scopes"] == ["true"]


def test_connect_google_single_service(google_auth):
    google_auth.register_service("calendar", ["https://www.googleapis.com/auth/calendar"])

    result = json.loads(google_auth.connect_google(services=["calendar"]))

    assert "url" in result
    assert "calendar" in result["url"]
    assert result["message"] == "Connect calendar"


def test_connect_google_unknown_service(google_auth):
    google_auth.register_service("gmail", ["scope1"])

    result = json.loads(google_auth.connect_google(services=["sheets"]))

    assert "error" in result
    assert "gmail" in result["error"]


def test_connect_google_partial_unknown(google_auth):
    google_auth.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])

    # "drive" not registered, "gmail" is — should still generate URL with gmail scopes
    result = json.loads(google_auth.connect_google(services=["gmail", "drive"]))
    assert "url" in result
    assert "gmail.readonly" in result["url"]


# ---------------------------------------------------------------------------
# Per-toolkit connect_google exclusion
# ---------------------------------------------------------------------------


def test_no_per_toolkit_connect_google_with_google_auth(google_auth):
    gmail = GmailTools(google_auth=google_auth)
    # GoogleAuth handles connect_google centrally — toolkit should NOT register its own
    assert "connect_google" not in gmail.functions


def test_per_toolkit_connect_google_with_oauth_redirect_url():
    gmail = GmailTools(oauth_redirect_url="https://example.com/oauth")
    assert "connect_google" in gmail.functions


def test_no_connect_google_without_either():
    gmail = GmailTools()
    assert "connect_google" not in gmail.functions


# ---------------------------------------------------------------------------
# Auth decorator error routing
# ---------------------------------------------------------------------------


def test_auth_error_mentions_connect_google_with_google_auth(google_auth):
    # creds=None → _auth() will be called → will fail → should mention connect_google
    gmail = GmailTools(google_auth=google_auth)
    result = gmail.get_latest_emails(count=1)
    data = json.loads(result)
    assert "connect_google" in data["error"]
    assert "gmail" in data["error"]


def test_auth_error_mentions_connect_google_with_oauth_redirect_url():
    gmail = GmailTools(oauth_redirect_url="https://example.com")
    result = gmail.get_latest_emails(count=1)
    data = json.loads(result)
    assert "connect_google" in data["error"]


def test_auth_error_plain_without_google_auth():
    gmail = GmailTools()
    result = gmail.get_latest_emails(count=1)
    data = json.loads(result)
    assert "error" in data
    # Should NOT mention connect_google — no server-side auth configured
    assert "connect_google" not in data["error"]


# ---------------------------------------------------------------------------
# Shared credentials identity
# ---------------------------------------------------------------------------


def test_shared_creds_same_object(mock_creds, google_auth):
    gmail = GmailTools(creds=mock_creds, google_auth=google_auth)
    cal = GoogleCalendarTools(creds=mock_creds, google_auth=google_auth)
    # Both toolkit instances hold the same Credentials reference
    assert gmail.creds is cal.creds
    assert gmail.creds is mock_creds


def test_shared_creds_skips_auth(mock_creds, google_auth):
    from unittest.mock import MagicMock, patch

    gmail = GmailTools(creds=mock_creds, google_auth=google_auth)
    with patch("agno.tools.google.gmail.build") as mock_build:
        mock_build.return_value = MagicMock()
        with patch.object(gmail, "_auth") as mock_auth:
            gmail.get_latest_emails(count=1)
            # _auth() should NOT be called — creds.valid is True
            mock_auth.assert_not_called()


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_backward_compat_no_google_auth():
    gmail = GmailTools(token_path="token_gmail.json")
    assert gmail.google_auth is None
    assert gmail.token_path == "token_gmail.json"


def test_backward_compat_no_oauth_redirect_url():
    gmail = GmailTools()
    assert gmail.oauth_redirect_url is None
    assert gmail.google_auth is None


def test_backward_compat_custom_scopes_still_work():
    custom = ["https://www.googleapis.com/auth/gmail.readonly"]
    gmail = GmailTools(
        scopes=custom,
        include_tools=["get_latest_emails"],
    )
    assert gmail.scopes == custom
