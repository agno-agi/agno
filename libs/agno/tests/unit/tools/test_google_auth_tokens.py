from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def mock_creds():
    creds = Mock()
    creds.token = "access_token"
    creds.refresh_token = "refresh_token"
    creds.token_uri = "https://oauth2.googleapis.com/token"
    creds.client_id = "client_id"
    creds.client_secret = "client_secret"
    creds.expiry = None
    return creds


# ============================================================================
# load_token_from_db TESTS
# ============================================================================


def test_load_token_returns_none_when_db_not_implemented():
    from agno.tools.google.auth.tokens import load_token_from_db

    mock_db = Mock()
    mock_db.get_auth_token.side_effect = NotImplementedError

    row, creds = load_token_from_db(mock_db, None)

    assert row is None
    assert creds is None


def test_load_token_returns_none_when_not_found():
    from agno.tools.google.auth.tokens import load_token_from_db

    mock_db = Mock()
    mock_db.get_auth_token.return_value = None

    row, creds = load_token_from_db(mock_db, None)

    assert row is None
    assert creds is None


def test_load_token_returns_none_when_token_data_empty():
    from agno.tools.google.auth.tokens import load_token_from_db

    mock_db = Mock()
    mock_db.get_auth_token.return_value = {"token_data": None}

    row, creds = load_token_from_db(mock_db, None)

    assert row is None
    assert creds is None


def test_load_token_unencrypted():
    from agno.tools.google.auth.tokens import load_token_from_db

    mock_db = Mock()
    mock_db.get_auth_token.return_value = {
        "token_data": {
            "token": "access_token_123",
            "refresh_token": "refresh_token_456",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client_id",
            "client_secret": "client_secret",
        },
        "granted_scopes": ["https://mail.google.com/"],
    }

    mock_creds = Mock()
    mock_creds.token = "access_token_123"

    with (
        patch("agno.utils.encryption.is_encrypted", return_value=False),
        patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_creds),
    ):
        row, creds = load_token_from_db(mock_db, None)

    assert row is not None
    assert creds is not None
    assert creds.token == "access_token_123"


def test_load_token_decrypts_encrypted():
    from agno.tools.google.auth.tokens import load_token_from_db

    mock_db = Mock()
    mock_db.get_auth_token.return_value = {
        "token_data": {"encrypted": "base64data"},
        "granted_scopes": ["https://mail.google.com/"],
    }

    decrypted_data = {
        "token": "decrypted_access",
        "refresh_token": "decrypted_refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client_id",
        "client_secret": "client_secret",
    }

    mock_creds = Mock()
    mock_creds.token = "decrypted_access"

    with (
        patch("agno.utils.encryption.is_encrypted", return_value=True),
        patch("agno.utils.encryption.decrypt_dict", return_value=decrypted_data),
        patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_creds),
    ):
        row, creds = load_token_from_db(mock_db, "encryption_key")

    assert creds.token == "decrypted_access"


def test_load_token_warns_on_unencrypted_with_key():
    from agno.tools.google.auth.tokens import load_token_from_db

    mock_db = Mock()
    mock_db.get_auth_token.return_value = {
        "token_data": {
            "token": "plaintext_token",
            "refresh_token": "refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "id",
            "client_secret": "secret",
        },
        "granted_scopes": [],
    }

    mock_creds = Mock()
    mock_creds.token = "plaintext_token"

    with (
        patch("agno.utils.encryption.is_encrypted", return_value=False),
        patch("agno.tools.google.auth.tokens.log_warning") as mock_warn,
        patch("google.oauth2.credentials.Credentials.from_authorized_user_info", return_value=mock_creds),
    ):
        row, creds = load_token_from_db(mock_db, "encryption_key")

    mock_warn.assert_called_once()
    assert "unencrypted" in mock_warn.call_args[0][0].lower()


# ============================================================================
# save_token_to_db TESTS
# ============================================================================


def test_save_token_encrypt_true_requires_key(mock_creds):
    from agno.tools.google.auth.tokens import save_token_to_db

    mock_db = Mock()

    with patch("agno.tools.google.auth.tokens.log_warning") as mock_warn:
        result = save_token_to_db(
            mock_db,
            mock_creds,
            ["scope1"],
            encryption_key=None,
            encrypt_tokens=True,
        )

    assert result is False
    mock_warn.assert_called_once()
    assert "encryption required" in mock_warn.call_args[0][0].lower()
    mock_db.upsert_auth_token.assert_not_called()


def test_save_token_encrypt_true_with_key(mock_creds):
    from agno.tools.google.auth.tokens import save_token_to_db

    mock_db = Mock()
    mock_db.upsert_auth_token.return_value = True

    with patch("agno.utils.encryption.encrypt_dict", return_value={"encrypted": "data"}) as mock_encrypt:
        result = save_token_to_db(
            mock_db,
            mock_creds,
            ["scope1"],
            encryption_key="my_key",
            encrypt_tokens=True,
        )

    assert result is True
    mock_encrypt.assert_called_once()
    call_args = mock_db.upsert_auth_token.call_args[0][0]
    assert call_args["token_data"] == {"encrypted": "data"}


def test_save_token_encrypt_false_plaintext(mock_creds):
    from agno.tools.google.auth.tokens import save_token_to_db

    mock_db = Mock()
    mock_db.upsert_auth_token.return_value = True

    with patch("agno.tools.google.auth.tokens.log_warning") as mock_warn:
        result = save_token_to_db(
            mock_db,
            mock_creds,
            ["scope1"],
            encryption_key=None,
            encrypt_tokens=False,
        )

    assert result is True
    mock_warn.assert_called_once()
    assert "without encryption" in mock_warn.call_args[0][0].lower()

    call_args = mock_db.upsert_auth_token.call_args[0][0]
    assert call_args["token_data"]["token"] == "access_token"
    assert call_args["token_data"]["refresh_token"] == "refresh_token"


def test_save_token_encrypt_false_ignores_key(mock_creds):
    from agno.tools.google.auth.tokens import save_token_to_db

    mock_db = Mock()
    mock_db.upsert_auth_token.return_value = True

    with patch("agno.tools.google.auth.tokens.log_warning"):
        result = save_token_to_db(
            mock_db,
            mock_creds,
            ["scope1"],
            encryption_key="some_key",
            encrypt_tokens=False,
        )

    assert result is True
    call_args = mock_db.upsert_auth_token.call_args[0][0]
    assert "token" in call_args["token_data"]
    assert call_args["token_data"]["token"] == "access_token"


def test_save_token_correct_provider_and_service(mock_creds):
    from agno.tools.google.auth.tokens import save_token_to_db

    mock_db = Mock()
    mock_db.upsert_auth_token.return_value = True

    with patch("agno.tools.google.auth.tokens.log_warning"):
        save_token_to_db(
            mock_db,
            mock_creds,
            ["scope1", "scope2"],
            encryption_key=None,
            encrypt_tokens=False,
        )

    call_args = mock_db.upsert_auth_token.call_args[0][0]
    assert call_args["provider"] == "google"
    assert call_args["service"] == "google"
    assert call_args["user_id"] is None
    assert call_args["granted_scopes"] == ["scope1", "scope2"]


# ============================================================================
# delete_token_from_db TESTS
# ============================================================================


def test_delete_token_calls_db_method():
    from agno.tools.google.auth.tokens import delete_token_from_db

    mock_db = Mock()
    mock_db.delete_auth_token.return_value = True

    result = delete_token_from_db(mock_db)

    assert result is True
    mock_db.delete_auth_token.assert_called_once_with("google", None, "google")


def test_delete_token_returns_false_on_not_implemented():
    from agno.tools.google.auth.tokens import delete_token_from_db

    mock_db = Mock()
    mock_db.delete_auth_token.side_effect = NotImplementedError

    with patch("agno.tools.google.auth.tokens.log_warning") as mock_warn:
        result = delete_token_from_db(mock_db)

    assert result is False
    mock_warn.assert_called_once()


def test_delete_token_returns_false_on_exception():
    from agno.tools.google.auth.tokens import delete_token_from_db

    mock_db = Mock()
    mock_db.delete_auth_token.side_effect = Exception("DB error")

    result = delete_token_from_db(mock_db)

    assert result is False
