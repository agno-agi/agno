from unittest.mock import MagicMock, patch

import pytest

from agno.tools.google.auth import AuthConfig
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools


@pytest.fixture
def mock_creds():
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    return creds


# ============================================================================
# AUTHCONFIG INITIALIZATION TESTS
# ============================================================================


def test_auth_config_default_values(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_DELEGATED_USER", raising=False)
    monkeypatch.delenv("GOOGLE_HOSTED_DOMAIN", raising=False)
    monkeypatch.delenv("GOOGLE_TOKEN_ENCRYPTION_KEY", raising=False)

    auth = AuthConfig()

    assert auth.client_id is None
    assert auth.client_secret is None
    assert auth.service_account_path is None
    assert auth.delegated_user is None
    assert auth.hosted_domain is None
    assert auth.access_type == "offline"
    assert auth.prompt == "consent"
    assert auth.login_hint is None
    assert auth.include_granted_scopes is False
    assert auth.db is None
    assert auth.token_encryption_key is None
    assert auth.encrypt_tokens is True
    assert auth._scopes == set()
    assert auth._creds is None


def test_auth_config_env_var_defaults(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-client-secret")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "/path/to/sa.json")
    monkeypatch.setenv("GOOGLE_DELEGATED_USER", "admin@example.com")
    monkeypatch.setenv("GOOGLE_HOSTED_DOMAIN", "example.com")
    monkeypatch.setenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "secret-key")

    auth = AuthConfig()

    assert auth.client_id == "env-client-id"
    assert auth.client_secret == "env-client-secret"
    assert auth.service_account_path == "/path/to/sa.json"
    assert auth.delegated_user == "admin@example.com"
    assert auth.hosted_domain == "example.com"
    assert auth.token_encryption_key == "secret-key"


def test_auth_config_explicit_overrides_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_DELEGATED_USER", "env-user@example.com")

    auth = AuthConfig(
        client_id="explicit-id",
        delegated_user="explicit-user@example.com",
    )

    assert auth.client_id == "explicit-id"
    assert auth.delegated_user == "explicit-user@example.com"


def test_auth_config_oauth_flow_options():
    auth = AuthConfig(
        access_type="online",
        prompt="select_account",
        login_hint="user@example.com",
        include_granted_scopes=True,
        hosted_domain="mycompany.com",
    )

    assert auth.access_type == "online"
    assert auth.prompt == "select_account"
    assert auth.login_hint == "user@example.com"
    assert auth.include_granted_scopes is True
    assert auth.hosted_domain == "mycompany.com"


# ============================================================================
# SCOPE AGGREGATION TESTS
# ============================================================================


def test_register_scopes_single_toolkit():
    auth = AuthConfig()
    scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

    auth.register_scopes(scopes)

    assert set(auth.scopes) == set(scopes)


def test_register_scopes_multiple_toolkits():
    auth = AuthConfig()
    gmail_scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    calendar_scopes = [
        "https://www.googleapis.com/auth/calendar",
    ]

    auth.register_scopes(gmail_scopes)
    auth.register_scopes(calendar_scopes)

    expected = set(gmail_scopes + calendar_scopes)
    assert set(auth.scopes) == expected


def test_register_scopes_deduplicates():
    auth = AuthConfig()
    common_scope = "https://www.googleapis.com/auth/gmail.readonly"

    auth.register_scopes([common_scope])
    auth.register_scopes([common_scope, "https://www.googleapis.com/auth/calendar"])

    assert auth.scopes.count(common_scope) == 1
    assert len(auth.scopes) == 2


def test_scopes_property_returns_list():
    auth = AuthConfig()
    auth.register_scopes(["scope1", "scope2"])

    result = auth.scopes

    assert isinstance(result, list)
    assert set(result) == {"scope1", "scope2"}


# ============================================================================
# CREDS PROPERTY TESTS
# ============================================================================


def test_creds_default_none():
    auth = AuthConfig()
    assert auth.creds is None


def test_creds_setter():
    auth = AuthConfig()
    mock_creds = MagicMock()
    mock_creds.valid = True

    auth.creds = mock_creds

    assert auth.creds is mock_creds
    assert auth._creds is mock_creds


def test_creds_shared_across_reads():
    auth = AuthConfig()
    mock_creds = MagicMock()

    auth.creds = mock_creds
    read1 = auth.creds
    read2 = auth.creds

    assert read1 is read2 is mock_creds


# ============================================================================
# SHARED AUTH PATTERN TESTS
# ============================================================================


def test_shared_auth_aggregates_scopes(mock_creds):
    auth = AuthConfig()

    with patch("googleapiclient.discovery.build"):
        GmailTools(auth=auth, creds=mock_creds)
        GoogleCalendarTools(auth=auth, creds=mock_creds)

    aggregated = set(auth.scopes)
    assert set(GmailTools.default_scopes).issubset(aggregated)
    assert set(GoogleCalendarTools.default_scopes).issubset(aggregated)


def test_shared_auth_same_object(mock_creds):
    auth = AuthConfig()

    with patch("googleapiclient.discovery.build"):
        gmail = GmailTools(auth=auth, creds=mock_creds)
        cal = GoogleCalendarTools(auth=auth, creds=mock_creds)

    assert gmail._auth is auth
    assert cal._auth is auth


def test_no_shared_auth_creates_separate_configs(mock_creds):
    with patch("googleapiclient.discovery.build"):
        gmail = GmailTools(creds=mock_creds)
        cal = GoogleCalendarTools(creds=mock_creds)

    assert gmail._auth is not cal._auth


def test_shared_auth_creds_propagate(mock_creds):
    auth = AuthConfig()
    auth.creds = mock_creds

    with patch("googleapiclient.discovery.build"):
        gmail = GmailTools(auth=auth)
        cal = GoogleCalendarTools(auth=auth)

    assert gmail._auth.creds is mock_creds
    assert cal._auth.creds is mock_creds


def test_toolkit_auto_creates_auth_config(mock_creds):
    with patch("googleapiclient.discovery.build"):
        gmail = GmailTools(creds=mock_creds)

    assert gmail._auth is not None
    assert isinstance(gmail._auth, AuthConfig)
    assert set(GmailTools.default_scopes).issubset(set(gmail._auth.scopes))


def test_toolkit_params_passed_to_auth_config(mock_creds):
    with patch("googleapiclient.discovery.build"):
        gmail = GmailTools(
            creds=mock_creds,
            service_account_path="/path/to/sa.json",
            delegated_user="admin@example.com",
            login_hint="user@example.com",
        )

    assert gmail._auth.service_account_path == "/path/to/sa.json"
    assert gmail._auth.delegated_user == "admin@example.com"
    assert gmail._auth.login_hint == "user@example.com"


# ============================================================================
# DB TOKEN STORAGE TESTS
# ============================================================================


def test_db_param_stored():
    mock_db = MagicMock()
    auth = AuthConfig(db=mock_db)

    assert auth.db is mock_db


def test_db_default_none():
    auth = AuthConfig()
    assert auth.db is None


def test_token_encryption_key_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "my-secret-key")
    auth = AuthConfig()

    assert auth.token_encryption_key == "my-secret-key"


def test_token_encryption_key_explicit(monkeypatch):
    monkeypatch.setenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "env-key")
    auth = AuthConfig(token_encryption_key="explicit-key")

    assert auth.token_encryption_key == "explicit-key"


# ============================================================================
# ENCRYPT_TOKENS FLAG TESTS
# ============================================================================


def test_encrypt_tokens_defaults_true():
    auth = AuthConfig()
    assert auth.encrypt_tokens is True


def test_encrypt_tokens_can_be_disabled():
    auth = AuthConfig(encrypt_tokens=False)
    assert auth.encrypt_tokens is False


def test_encrypt_tokens_independent_of_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_TOKEN_ENCRYPTION_KEY", raising=False)

    auth_disabled = AuthConfig(encrypt_tokens=False)
    assert auth_disabled.encrypt_tokens is False
    assert auth_disabled.token_encryption_key is None

    auth_enabled = AuthConfig(encrypt_tokens=True, token_encryption_key="a-key")
    assert auth_enabled.encrypt_tokens is True
    assert auth_enabled.token_encryption_key == "a-key"


def test_encrypt_tokens_true_without_key_valid(monkeypatch):
    monkeypatch.delenv("GOOGLE_TOKEN_ENCRYPTION_KEY", raising=False)

    auth = AuthConfig(encrypt_tokens=True)

    assert auth.encrypt_tokens is True
    assert auth.token_encryption_key is None


# ============================================================================
# REPR TESTS
# ============================================================================


def test_scopes_not_in_repr():
    auth = AuthConfig()
    auth.register_scopes(["scope1", "scope2"])

    repr_str = repr(auth)

    assert "scope1" not in repr_str
    assert "scope2" not in repr_str


def test_creds_not_in_repr():
    auth = AuthConfig()
    mock = MagicMock()
    mock.__repr__ = MagicMock(return_value="MockCreds")
    auth.creds = mock

    repr_str = repr(auth)

    assert "MockCreds" not in repr_str


# ============================================================================
# MULTI-TOOLKIT SCENARIO TESTS
# ============================================================================


def test_gmail_calendar_drive_shared_auth(mock_creds):
    auth = AuthConfig()

    with patch("googleapiclient.discovery.build"):
        GmailTools(auth=auth, creds=mock_creds)
        GoogleCalendarTools(auth=auth, creds=mock_creds)
        GoogleDriveTools(auth=auth, creds=mock_creds)

    expected_scopes = (
        set(GmailTools.default_scopes)
        | set(GoogleCalendarTools.default_scopes)
        | {"https://www.googleapis.com/auth/drive.readonly"}
    )
    assert set(auth.scopes) == expected_scopes


def test_scope_order_independent(mock_creds):
    auth1 = AuthConfig()
    auth2 = AuthConfig()

    with patch("googleapiclient.discovery.build"):
        GmailTools(auth=auth1, creds=mock_creds)
        GoogleCalendarTools(auth=auth1, creds=mock_creds)

        GoogleCalendarTools(auth=auth2, creds=mock_creds)
        GmailTools(auth=auth2, creds=mock_creds)

    assert set(auth1.scopes) == set(auth2.scopes)
