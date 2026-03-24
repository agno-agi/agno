import json
from unittest.mock import MagicMock, Mock, patch
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
def mock_credentials():
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    return mock_creds


def test_google_auth_init():
    ga = GoogleAuth(client_id="my-id")
    assert ga.client_id == "my-id"
    assert ga._services == {}
    assert "authenticate_google" in ga.functions


def test_google_auth_init_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    ga = GoogleAuth()
    assert ga.client_id == "env-id"


def test_google_auth_custom_redirect_uri():
    ga = GoogleAuth(client_id="id", redirect_uri="https://myapp.com/callback")
    assert ga.redirect_uri == "https://myapp.com/callback"


def test_google_auth_default_redirect_uri_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://env.example.com/callback")
    ga = GoogleAuth(client_id="id")
    assert ga.redirect_uri == "https://env.example.com/callback"


def test_register_service(google_auth):
    google_auth.register_service("gmail", ["scope1", "scope2"])
    assert google_auth._services["gmail"] == ["scope1", "scope2"]


def test_register_multiple_services(google_auth):
    google_auth.register_service("gmail", GmailTools.DEFAULT_SCOPES)
    google_auth.register_service("calendar", GoogleCalendarTools.DEFAULT_SCOPES)
    assert len(google_auth._services) == 2
    assert "gmail" in google_auth._services
    assert "calendar" in google_auth._services


def test_authenticate_google_combined_url(google_auth):
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

    result = json.loads(google_auth.authenticate_google(services=["gmail", "calendar"]))

    assert "url" in result
    parsed = urlparse(result["url"])
    params = parse_qs(parsed.query)

    scope_str = params["scope"][0]
    assert "gmail.readonly" in scope_str
    assert "gmail.modify" in scope_str
    assert "calendar" in scope_str


def test_authenticate_google_includes_oauth_params(google_auth):
    google_auth.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])

    result = json.loads(google_auth.authenticate_google(services=["gmail"]))
    parsed = urlparse(result["url"])
    params = parse_qs(parsed.query)

    assert params["client_id"] == ["test-client-id"]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["include_granted_scopes"] == ["true"]


def test_authenticate_google_single_service(google_auth):
    google_auth.register_service("calendar", ["https://www.googleapis.com/auth/calendar"])

    result = json.loads(google_auth.authenticate_google(services=["calendar"]))

    assert "url" in result
    assert "calendar" in result["url"]
    assert result["message"] == "Connect calendar"


def test_authenticate_google_unknown_service(google_auth):
    google_auth.register_service("gmail", ["scope1"])

    result = json.loads(google_auth.authenticate_google(services=["sheets"]))

    assert "error" in result
    assert "gmail" in result["error"]


def test_authenticate_google_partial_unknown(google_auth):
    google_auth.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])

    result = json.loads(google_auth.authenticate_google(services=["gmail", "drive"]))
    assert "url" in result
    assert "gmail.readonly" in result["url"]


def test_shared_creds_same_object(mock_credentials):
    gmail = GmailTools(creds=mock_credentials)
    cal = GoogleCalendarTools(creds=mock_credentials)
    assert gmail.creds is cal.creds
    assert gmail.creds is mock_credentials


def test_shared_creds_skips_auth(mock_credentials):
    gmail = GmailTools(creds=mock_credentials)
    with patch("agno.tools.google.gmail.build") as mock_build:
        mock_build.return_value = MagicMock()
        with patch.object(gmail, "_auth") as mock_auth:
            gmail.get_latest_emails(count=1)
            mock_auth.assert_not_called()


def test_auth_error_returns_json():
    gmail = GmailTools()
    gmail.creds = Mock(valid=False)
    gmail.service = None
    with patch.object(gmail, "_auth", side_effect=RuntimeError("token expired")):
        result = gmail.get_latest_emails(count=1)
    data = json.loads(result)
    assert "error" in data
    assert "authentication failed" in data["error"].lower()


def test_no_authenticate_google_on_toolkit():
    gmail = GmailTools()
    assert "authenticate_google" not in gmail.functions


def test_backward_compat_custom_token_path():
    gmail = GmailTools(token_path="token_gmail.json")
    assert gmail.token_path == "token_gmail.json"


def test_backward_compat_custom_scopes():
    custom = ["https://www.googleapis.com/auth/gmail.readonly"]
    gmail = GmailTools(
        scopes=custom,
        include_tools=["get_latest_emails"],
    )
    assert gmail.scopes == custom
