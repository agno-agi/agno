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
    # authenticate_google requires a state signing secret; provide a test-only value
    return GoogleAuth(client_id="test-client-id", state_secret="test-state-secret")


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

    result = json.loads(google_auth.authenticate_google())

    assert "url" in result
    parsed = urlparse(result["url"])
    params = parse_qs(parsed.query)

    scope_str = params["scope"][0]
    assert "gmail.readonly" in scope_str
    assert "gmail.modify" in scope_str
    assert "calendar" in scope_str


def test_authenticate_google_includes_oauth_params(google_auth):
    google_auth.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])

    result = json.loads(google_auth.authenticate_google())
    parsed = urlparse(result["url"])
    params = parse_qs(parsed.query)

    assert params["client_id"] == ["test-client-id"]
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    # Default is False (privacy-first); see test_include_granted_scopes_opt_in for True case
    assert params["include_granted_scopes"] == ["false"]


def test_include_granted_scopes_opt_in(tmp_path):
    from agno.db.sqlite.sqlite import SqliteDb

    ga = GoogleAuth(
        client_id="id",
        state_secret="secret",
        db=SqliteDb(db_file=str(tmp_path / "t.db")),
        include_granted_scopes=True,
    )
    ga.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])
    result = json.loads(ga.authenticate_google())
    params = parse_qs(urlparse(result["url"]).query)
    assert params["include_granted_scopes"] == ["true"]


def test_authenticate_google_single_service(google_auth):
    google_auth.register_service("calendar", ["https://www.googleapis.com/auth/calendar"])

    result = json.loads(google_auth.authenticate_google())

    assert "url" in result
    assert "calendar" in result["url"]
    assert result["message"] == "Connect calendar"


def test_authenticate_google_no_services_registered(google_auth):
    # New API: error when no services registered
    result = json.loads(google_auth.authenticate_google())
    assert "error" in result
    assert "No Google services registered" in result["error"]


def test_shared_creds_same_object(mock_credentials):
    gmail = GmailTools(creds=mock_credentials)
    cal = GoogleCalendarTools(creds=mock_credentials)
    # Stateless: explicit creds stored in _explicit_creds, both share same reference
    assert gmail._explicit_creds is cal._explicit_creds
    assert gmail._explicit_creds is mock_credentials


def test_shared_creds_skips_auth(mock_credentials):
    gmail = GmailTools(creds=mock_credentials)
    with patch("agno.tools.google.gmail.build") as mock_build:
        mock_build.return_value = MagicMock()
        # Stateless: _resolve_creds returns _explicit_creds directly when valid
        with patch.object(gmail, "_resolve_creds", return_value=mock_credentials) as mock_resolve:
            gmail.get_latest_emails(count=1)
            mock_resolve.assert_called_once()


def test_auth_error_returns_json():
    gmail = GmailTools()
    # Stateless: decorator catches _resolve_creds errors and returns JSON
    with patch.object(gmail, "_resolve_creds", side_effect=RuntimeError("token expired")):
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


def test_get_token_db_reads_agent_db_without_mutating_toolkit(tmp_path):
    # store_token_in_db opt-in path: agent.db resolves via injection, toolkit stays clean
    from agno.db.sqlite.sqlite import SqliteDb
    from agno.tools.google.auth import get_token_db

    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Mock(db=db)
    gmail = GmailTools(store_token_in_db=True)

    assert gmail._db is None
    assert get_token_db(gmail, agent=agent) is db
    assert gmail._db is None


def test_get_token_db_with_coordinator_uses_agent_db_without_mutation(tmp_path):
    # Coordinator path: GoogleAuth(db=None) + GmailTools(google_auth=...) + agent.db
    from agno.db.sqlite.sqlite import SqliteDb
    from agno.tools.google.auth import get_token_db

    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Mock(db=db)
    ga = GoogleAuth(client_id="id", state_secret="s")
    gmail = GmailTools(google_auth=ga)

    assert ga._db is None
    assert gmail._db is None
    assert get_token_db(gmail, agent=agent) is db
    assert ga._db is None
    assert gmail._db is None


def test_authenticate_google_with_agent_db(tmp_path):
    # authenticate_google now uses the db passed to constructor or from agent
    from agno.db.sqlite.sqlite import SqliteDb

    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    ga = GoogleAuth(client_id="id", state_secret="s", db=db)
    ga.register_service("gmail", ["https://www.googleapis.com/auth/gmail.readonly"])

    result = json.loads(ga.authenticate_google())
    assert "url" in result
    assert ga._db is db
