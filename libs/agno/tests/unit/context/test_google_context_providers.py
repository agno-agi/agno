from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agno.context.calendar import GoogleCalendarContextProvider
from agno.context.gmail import GmailContextProvider
from agno.context.mode import ContextMode
from agno.tools.google.auth import AuthConfig

DEFAULT_GOOGLE_API_TIMEOUT = 120.0


@pytest.fixture(autouse=True)
def clean_google_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_TIMEOUT", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_DELEGATED_USER", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)


@pytest.fixture
def mock_valid_creds():
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    return creds


# ============================================================================
# GMAIL CONTEXT PROVIDER TESTS
# ============================================================================


def test_gmail_init_with_auth_config():
    auth = AuthConfig(http_timeout=60.0)
    provider = GmailContextProvider(
        auth=auth,
        id="gmail",
        read=True,
        write=False,
    )
    assert provider._auth is auth
    assert provider.id == "gmail"
    assert provider.read is True
    assert provider.write is False


def test_gmail_requires_delegated_user_for_service_account(tmp_path, monkeypatch):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text('{"type": "service_account"}')
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))

    with pytest.raises(ValueError, match="delegated_user"):
        GmailContextProvider()


def test_gmail_with_delegated_user_succeeds(tmp_path, monkeypatch):
    sa_file = tmp_path / "sa.json"
    sa_file.write_text('{"type": "service_account"}')
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(sa_file))
    monkeypatch.setenv("GOOGLE_DELEGATED_USER", "user@example.com")

    provider = GmailContextProvider()
    assert provider._delegated_user == "user@example.com"


def test_gmail_status_returns_status_object(tmp_path):
    token_file = tmp_path / "token.json"
    provider = GmailContextProvider(token_path=str(token_file))
    status = provider.status()
    assert hasattr(status, "ok")
    assert hasattr(status, "detail")


def test_gmail_default_mode_creates_query_tool():
    auth = AuthConfig()
    provider = GmailContextProvider(auth=auth, mode=ContextMode.default)
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "query_gmail" in tool_names


def test_gmail_write_mode_creates_update_tool():
    auth = AuthConfig()
    provider = GmailContextProvider(auth=auth, mode=ContextMode.default, write=True)
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "query_gmail" in tool_names
    assert "update_gmail" in tool_names


def test_gmail_instructions_include_provider_name():
    provider = GmailContextProvider()
    instructions = provider.instructions()
    assert "Gmail" in instructions or "gmail" in instructions.lower()


# ============================================================================
# GMAIL TOOLKIT TIMEOUT TESTS
# ============================================================================


def test_gmail_toolkit_inherits_auth_timeout():
    auth = AuthConfig(http_timeout=45.0)
    provider = GmailContextProvider(auth=auth)
    toolkit = provider._build_read_toolkit()
    assert toolkit._get_http_timeout() == 45.0


def test_gmail_toolkit_uses_default_timeout():
    provider = GmailContextProvider()
    toolkit = provider._build_read_toolkit()
    assert toolkit._get_http_timeout() == DEFAULT_GOOGLE_API_TIMEOUT


def test_gmail_toolkit_respects_env_timeout(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_TIMEOUT", "90")
    provider = GmailContextProvider()
    toolkit = provider._build_read_toolkit()
    assert toolkit._get_http_timeout() == 90.0


# ============================================================================
# CALENDAR CONTEXT PROVIDER TESTS
# ============================================================================


def test_calendar_init_with_auth_config():
    auth = AuthConfig(http_timeout=120.0)
    provider = GoogleCalendarContextProvider(
        auth=auth,
        id="calendar",
        read=True,
        write=False,
    )
    assert provider._auth is auth
    assert provider.id == "calendar"


def test_calendar_status_returns_status_object(tmp_path):
    token_file = tmp_path / "token.json"
    provider = GoogleCalendarContextProvider(token_path=str(token_file))
    status = provider.status()
    assert hasattr(status, "ok")
    assert hasattr(status, "detail")


def test_calendar_default_mode_creates_query_tool():
    auth = AuthConfig()
    provider = GoogleCalendarContextProvider(auth=auth, mode=ContextMode.default)
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "query_calendar" in tool_names


def test_calendar_write_mode_creates_update_tool():
    auth = AuthConfig()
    provider = GoogleCalendarContextProvider(auth=auth, mode=ContextMode.default, write=True)
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "update_calendar" in tool_names


# ============================================================================
# CALENDAR TOOLKIT TIMEOUT TESTS
# ============================================================================


def test_calendar_toolkit_inherits_auth_timeout():
    auth = AuthConfig(http_timeout=30.0)
    provider = GoogleCalendarContextProvider(auth=auth)
    toolkit = provider._build_read_toolkit()
    assert toolkit._get_http_timeout() == 30.0


def test_calendar_toolkit_uses_default_timeout():
    provider = GoogleCalendarContextProvider()
    toolkit = provider._build_read_toolkit()
    assert toolkit._get_http_timeout() == DEFAULT_GOOGLE_API_TIMEOUT


# ============================================================================
# SHARED AUTH CONFIG TESTS
# ============================================================================


def test_gmail_and_calendar_share_auth_config():
    auth = AuthConfig(http_timeout=75.0)

    gmail = GmailContextProvider(auth=auth)
    calendar = GoogleCalendarContextProvider(auth=auth)

    gmail_toolkit = gmail._build_read_toolkit()
    calendar_toolkit = calendar._build_read_toolkit()

    assert gmail_toolkit._get_http_timeout() == 75.0
    assert calendar_toolkit._get_http_timeout() == 75.0
    assert gmail_toolkit._auth is auth
    assert calendar_toolkit._auth is auth


def test_auth_config_scope_aggregation():
    auth = AuthConfig()

    gmail = GmailContextProvider(auth=auth)
    gmail._build_read_toolkit()

    calendar = GoogleCalendarContextProvider(auth=auth)
    calendar._build_read_toolkit()

    all_scopes = auth.scopes
    gmail_scopes_present = any("gmail" in s for s in all_scopes)
    calendar_scopes_present = any("calendar" in s for s in all_scopes)

    assert gmail_scopes_present
    assert calendar_scopes_present


# ============================================================================
# ASYNC STATUS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_gmail_astatus_returns_status(tmp_path):
    token_file = tmp_path / "token.json"
    provider = GmailContextProvider(token_path=str(token_file))
    status = await provider.astatus()
    assert hasattr(status, "ok")
    assert hasattr(status, "detail")


@pytest.mark.asyncio
async def test_calendar_astatus_returns_status(tmp_path):
    token_file = tmp_path / "token.json"
    provider = GoogleCalendarContextProvider(token_path=str(token_file))
    status = await provider.astatus()
    assert hasattr(status, "ok")
    assert hasattr(status, "detail")


# ============================================================================
# BUILD SERVICE TIMEOUT TESTS
# ============================================================================


def test_gmail_toolkit_builds_service_with_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=15.0)
    provider = GmailContextProvider(auth=auth)
    toolkit = provider._build_read_toolkit()

    with (
        patch("httplib2.Http") as mock_http_cls,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build"),
    ):
        toolkit._build_service(mock_valid_creds)
        mock_http_cls.assert_called_with(timeout=15.0)


def test_calendar_toolkit_builds_service_with_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=25.0)
    provider = GoogleCalendarContextProvider(auth=auth)
    toolkit = provider._build_read_toolkit()

    with (
        patch("httplib2.Http") as mock_http_cls,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build"),
    ):
        toolkit._build_service(mock_valid_creds)
        mock_http_cls.assert_called_with(timeout=25.0)


# ============================================================================
# MODE RESOLUTION TESTS
# ============================================================================


def test_gmail_tools_mode_returns_toolkit():
    auth = AuthConfig()
    provider = GmailContextProvider(auth=auth, mode=ContextMode.tools)
    tools = provider.get_tools()
    assert len(tools) >= 1
    assert hasattr(tools[0], "functions") or hasattr(tools[0], "name")


def test_gmail_agent_mode_returns_query_tool():
    auth = AuthConfig()
    provider = GmailContextProvider(auth=auth, mode=ContextMode.agent)
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert "query_gmail" in tool_names


def test_calendar_tools_mode_returns_toolkit():
    auth = AuthConfig()
    provider = GoogleCalendarContextProvider(auth=auth, mode=ContextMode.tools)
    tools = provider.get_tools()
    assert len(tools) >= 1


# ============================================================================
# REGRESSION TESTS
# ============================================================================


def test_gmail_write_toolkit_has_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=50.0)
    provider = GmailContextProvider(auth=auth, write=True)
    write_toolkit = provider._build_write_toolkit()

    assert write_toolkit._get_http_timeout() == 50.0

    with (
        patch("httplib2.Http") as mock_http_cls,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build"),
    ):
        write_toolkit._build_service(mock_valid_creds)
        mock_http_cls.assert_called_with(timeout=50.0)


def test_calendar_write_toolkit_has_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=35.0)
    provider = GoogleCalendarContextProvider(auth=auth, write=True)
    write_toolkit = provider._build_write_toolkit()

    assert write_toolkit._get_http_timeout() == 35.0
