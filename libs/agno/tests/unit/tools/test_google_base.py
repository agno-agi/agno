import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.google.auth import AuthConfig
from agno.tools.google.base import GoogleToolkit
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.sheets import GoogleSheetsTools
from agno.tools.google.slides import GoogleSlidesTools

DEFAULT_GOOGLE_API_TIMEOUT = 120.0


class _FakeGoogleToolkit(GoogleToolkit):
    api_name = "fake"
    api_version = "v1"
    google_service_name = "fake"
    default_scopes = ["scope1"]


def _make_toolkit(db=None, *, scopes=None, encrypt_tokens=False, token_encryption_key=None, auth=None):
    if auth is None:
        auth = AuthConfig(db=db, encrypt_tokens=encrypt_tokens, token_encryption_key=token_encryption_key)
        auth.service_account_path = None
    toolkit = _FakeGoogleToolkit(auth=auth, scopes=scopes if scopes is not None else ["scope1"])
    toolkit.creds = None
    return toolkit


def _make_creds(*, valid=True, expired=False, refresh_token="refresh_token", scopes=("scope1",)):
    creds = MagicMock()
    creds.valid = valid
    creds.expired = expired
    creds.refresh_token = refresh_token
    creds.scopes = list(scopes)
    creds.granted_scopes = list(scopes)
    return creds


@pytest.fixture
def mock_valid_creds():
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture(autouse=True)
def clean_google_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_TIMEOUT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_QUOTA_PROJECT_ID", raising=False)


# ============================================================================
# _has_required_scopes TESTS
# ============================================================================


def test_has_required_scopes_all_granted():
    toolkit = _make_toolkit(scopes=["scope1", "scope2"])
    creds = _make_creds(scopes=["scope1", "scope2", "extra_scope"])

    assert toolkit._has_required_scopes(creds) is True


def test_has_required_scopes_missing():
    toolkit = _make_toolkit(scopes=["scope1", "scope2", "scope3"])
    creds = _make_creds(scopes=["scope1"])

    with patch("agno.tools.google.base.log_warning"):
        assert toolkit._has_required_scopes(creds) is False


def test_has_required_scopes_logs_warning():
    toolkit = _make_toolkit(scopes=["scope1", "scope2"])
    creds = _make_creds(scopes=["scope1"])

    with patch("agno.tools.google.base.log_warning") as mock_warn:
        toolkit._has_required_scopes(creds)

    mock_warn.assert_called_once()
    msg = mock_warn.call_args[0][0]
    assert "scope2" in msg
    assert "missing scopes" in msg.lower()


def test_has_required_scopes_empty_required():
    toolkit = _make_toolkit(scopes=[])
    creds = _make_creds(scopes=["any_scope"])

    assert toolkit._has_required_scopes(creds) is True


def test_has_required_scopes_none_on_creds():
    toolkit = _make_toolkit(scopes=["scope1"])
    creds = MagicMock()
    creds.scopes = None

    with patch("agno.tools.google.base.log_warning"):
        assert toolkit._has_required_scopes(creds) is False


# ============================================================================
# _get_http_timeout TESTS
# ============================================================================


def test_get_http_timeout_auth_config_priority(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_TIMEOUT", "99")
    auth = AuthConfig(http_timeout=7.5)
    tools = GmailTools(auth=auth)
    assert tools._get_http_timeout() == 7.5


def test_get_http_timeout_env_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_TIMEOUT", "12.25")
    tools = GmailTools()
    assert tools._get_http_timeout() == 12.25


def test_get_http_timeout_default():
    tools = GmailTools()
    assert tools._get_http_timeout() == DEFAULT_GOOGLE_API_TIMEOUT


@pytest.mark.parametrize("invalid_env", ["abc", "", "not-a-number"])
def test_get_http_timeout_invalid_env_uses_default(monkeypatch, invalid_env):
    monkeypatch.setenv("GOOGLE_API_TIMEOUT", invalid_env)
    tools = GmailTools()
    assert tools._get_http_timeout() == DEFAULT_GOOGLE_API_TIMEOUT


@pytest.mark.parametrize("timeout_value", [0, 0.5, 30.0, 120])
def test_get_http_timeout_float_passthrough(timeout_value):
    auth = AuthConfig(http_timeout=timeout_value)
    tools = GmailTools(auth=auth)
    assert tools._get_http_timeout() == timeout_value


# ============================================================================
# _build_google_service TESTS
# ============================================================================


def test_build_google_service_constructs_timeout_aware_http(mock_valid_creds):
    auth = AuthConfig(http_timeout=4.0)
    tools = GmailTools(auth=auth)

    with (
        patch("httplib2.Http") as mock_http_cls,
        patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http_cls,
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        mock_http_instance = MagicMock()
        mock_http_cls.return_value = mock_http_instance
        mock_auth_http_instance = MagicMock()
        mock_auth_http_cls.return_value = mock_auth_http_instance

        tools._build_google_service("gmail", "v1", mock_valid_creds)

        mock_http_cls.assert_called_once_with(timeout=4.0)
        mock_auth_http_cls.assert_called_once_with(mock_valid_creds, http=mock_http_instance)
        mock_build.assert_called_once_with("gmail", "v1", http=mock_auth_http_instance)


def test_build_service_uses_toolkit_api_metadata(mock_valid_creds):
    test_cases = [
        (GmailTools, "gmail", "v1"),
        (GoogleCalendarTools, "calendar", "v3"),
        (GoogleSheetsTools, "sheets", "v4"),
    ]

    for toolkit_cls, expected_api, expected_version in test_cases:
        tools = toolkit_cls()
        with (
            patch("httplib2.Http"),
            patch("google_auth_httplib2.AuthorizedHttp"),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            tools._build_service(mock_valid_creds)
            mock_build.assert_called_once()
            call_args = mock_build.call_args
            assert call_args[0][0] == expected_api
            assert call_args[0][1] == expected_version
            assert "http" in call_args[1]


# ============================================================================
# DRIVE _build_service TESTS (quota_project_id)
# ============================================================================


def test_drive_build_service_applies_quota_project(mock_valid_creds):
    quota_creds = MagicMock()
    mock_valid_creds.with_quota_project.return_value = quota_creds

    tools = GoogleDriveTools(quota_project_id="billing-proj")

    with (
        patch("httplib2.Http"),
        patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http,
        patch("googleapiclient.discovery.build"),
    ):
        tools._build_service(mock_valid_creds)

        mock_valid_creds.with_quota_project.assert_called_once_with("billing-proj")
        mock_auth_http.assert_called_once()
        assert mock_auth_http.call_args[0][0] is quota_creds


def test_drive_build_service_reads_quota_from_env(monkeypatch, mock_valid_creds):
    monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT_ID", "env-billing-proj")
    quota_creds = MagicMock()
    mock_valid_creds.with_quota_project.return_value = quota_creds

    tools = GoogleDriveTools()

    with (
        patch("httplib2.Http"),
        patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http,
        patch("googleapiclient.discovery.build"),
    ):
        tools._build_service(mock_valid_creds)

        mock_valid_creds.with_quota_project.assert_called_once_with("env-billing-proj")
        assert mock_auth_http.call_args[0][0] is quota_creds


def test_drive_build_service_without_quota_method(mock_valid_creds):
    simple_creds = MagicMock(spec=[])
    tools = GoogleDriveTools(quota_project_id="billing-proj")

    with (
        patch("httplib2.Http"),
        patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http,
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        tools._build_service(simple_creds)
        mock_auth_http.assert_called_once()
        mock_build.assert_called_once()


# ============================================================================
# SLIDES _build_service TESTS (dual services)
# ============================================================================


def test_slides_build_service_both_with_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=6.0)
    tools = GoogleSlidesTools(auth=auth)

    with (
        patch("httplib2.Http") as mock_httplib2,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        result = tools._build_service(mock_valid_creds)

        assert mock_httplib2.call_count == 2
        for call in mock_httplib2.call_args_list:
            assert call[1]["timeout"] == 6.0

        assert mock_build.call_count == 2
        api_calls = [(c[0][0], c[0][1]) for c in mock_build.call_args_list]
        assert ("slides", "v1") in api_calls
        assert ("drive", "v3") in api_calls

        assert result == mock_build.return_value


def test_slides_build_service_sets_both_attributes(mock_valid_creds):
    tools = GoogleSlidesTools()

    with (
        patch("httplib2.Http"),
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        mock_build.side_effect = [MagicMock(name="slides_svc"), MagicMock(name="drive_svc")]
        tools._build_service(mock_valid_creds)

        assert tools.slides_service is not None
        assert tools.drive_service is not None
        assert tools.slides_service != tools.drive_service


# ============================================================================
# SHEETS create_duplicate TESTS (drive service timeout)
# ============================================================================


def test_sheets_duplicate_uses_timeout_aware_drive(mock_valid_creds):
    tools = GoogleSheetsTools()
    tools.creds = mock_valid_creds
    tools.scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

    mock_sheets_service = MagicMock()
    mock_sheets_service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "properties": {"title": "Test Sheet"}
    }
    tools._service = mock_sheets_service

    with (
        patch("httplib2.Http") as mock_httplib2,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        mock_drive_service = MagicMock()
        mock_drive_service.files.return_value.copy.return_value.execute.return_value = {"id": "new-id"}
        mock_build.return_value = mock_drive_service

        tools.create_duplicate_sheet("source-id")

        mock_httplib2.assert_called()
        assert mock_httplib2.call_args[1]["timeout"] == DEFAULT_GOOGLE_API_TIMEOUT


# ============================================================================
# MULTI-TOOLKIT SHARED AUTH TESTS
# ============================================================================


def test_all_toolkits_build_with_same_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=8.0)

    toolkits = [
        GmailTools(auth=auth),
        GoogleCalendarTools(auth=auth),
        GoogleDriveTools(auth=auth),
        GoogleSlidesTools(auth=auth),
        GoogleSheetsTools(auth=auth),
    ]

    with (
        patch("httplib2.Http") as mock_httplib2,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build"),
    ):
        for toolkit in toolkits:
            mock_httplib2.reset_mock()
            toolkit._build_service(mock_valid_creds)

            for call in mock_httplib2.call_args_list:
                assert call[1]["timeout"] == 8.0


def test_services_are_independent_objects(mock_valid_creds):
    auth = AuthConfig()
    call_count = [0]

    def unique_service(*args, **kwargs):
        call_count[0] += 1
        return MagicMock(name=f"service_{call_count[0]}")

    toolkits = [
        GmailTools(auth=auth),
        GoogleCalendarTools(auth=auth),
        GoogleDriveTools(auth=auth),
        GoogleSheetsTools(auth=auth),
    ]

    with (
        patch("httplib2.Http"),
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build", side_effect=unique_service),
    ):
        services = []
        for toolkit in toolkits:
            svc = toolkit._build_service(mock_valid_creds)
            services.append(svc)

        assert len(set(id(s) for s in services)) == len(services)


# ============================================================================
# STATIC ANALYSIS TESTS (no direct transport imports)
# ============================================================================


@pytest.fixture
def google_tools_dir():
    import agno.tools.google.drive as drive_mod

    return Path(drive_mod.__file__).parent


def test_drive_no_direct_httplib2_import(google_tools_dir):
    source = (google_tools_dir / "drive.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "httplib2"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "httplib2"
            assert node.module != "google_auth_httplib2"


def test_slides_no_direct_httplib2_import(google_tools_dir):
    source = (google_tools_dir / "slides.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "httplib2"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "httplib2"
            assert node.module != "google_auth_httplib2"


def test_sheets_no_direct_httplib2_import(google_tools_dir):
    source = (google_tools_dir / "sheets.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "httplib2"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "httplib2"
            assert node.module != "google_auth_httplib2"


# ============================================================================
# REGRESSION TESTS
# ============================================================================


def test_regression_sheets_duplicate_drive_has_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=3.0)
    tools = GoogleSheetsTools(auth=auth)
    tools.creds = mock_valid_creds
    tools.scopes = ["https://www.googleapis.com/auth/drive"]

    mock_sheets_service = MagicMock()
    mock_sheets_service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "properties": {"title": "Test"}
    }
    tools._service = mock_sheets_service

    with (
        patch("httplib2.Http") as mock_httplib2,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        mock_drive = MagicMock()
        mock_drive.files.return_value.copy.return_value.execute.return_value = {"id": "x"}
        mock_build.return_value = mock_drive

        tools.create_duplicate_sheet("src")

        assert mock_httplib2.call_args[1]["timeout"] == 3.0


def test_regression_slides_companion_drive_has_timeout(mock_valid_creds):
    auth = AuthConfig(http_timeout=5.0)
    tools = GoogleSlidesTools(auth=auth)

    with (
        patch("httplib2.Http") as mock_httplib2,
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build"),
    ):
        tools._build_service(mock_valid_creds)

        assert mock_httplib2.call_count == 2
        for call in mock_httplib2.call_args_list:
            assert call[1]["timeout"] == 5.0


def test_regression_drive_quota_and_timeout_both_apply(mock_valid_creds):
    auth = AuthConfig(http_timeout=11.0)
    quota_creds = MagicMock()
    mock_valid_creds.with_quota_project.return_value = quota_creds

    tools = GoogleDriveTools(auth=auth, quota_project_id="proj")

    with (
        patch("httplib2.Http") as mock_httplib2,
        patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http,
        patch("googleapiclient.discovery.build"),
    ):
        tools._build_service(mock_valid_creds)

        mock_valid_creds.with_quota_project.assert_called_once_with("proj")
        mock_httplib2.assert_called_once_with(timeout=11.0)
        assert mock_auth_http.call_args[0][0] is quota_creds


def test_regression_all_toolkits_use_http_not_credentials(mock_valid_creds):
    toolkits = [
        GmailTools(),
        GoogleCalendarTools(),
        GoogleDriveTools(),
        GoogleSheetsTools(),
    ]

    with (
        patch("httplib2.Http"),
        patch("google_auth_httplib2.AuthorizedHttp"),
        patch("googleapiclient.discovery.build") as mock_build,
    ):
        for toolkit in toolkits:
            mock_build.reset_mock()
            toolkit._build_service(mock_valid_creds)

            call_kwargs = mock_build.call_args[1]
            assert "http" in call_kwargs
            assert "credentials" not in call_kwargs


# ============================================================================
# _resolve_creds SHARED AUTH TESTS
# ============================================================================


def test_resolve_creds_returns_shared_auth_creds():
    auth = AuthConfig()
    shared_creds = _make_creds(valid=True, scopes=["scope1"])
    auth.creds = shared_creds

    toolkit = _make_toolkit(auth=auth, scopes=["scope1"])
    toolkit.creds = None

    result = toolkit._resolve_creds()

    assert result is shared_creds


def test_resolve_creds_skips_invalid_shared_creds():
    auth = AuthConfig()
    invalid_creds = _make_creds(valid=False, scopes=["scope1"])
    auth.creds = invalid_creds

    toolkit = _make_toolkit(auth=auth, scopes=["scope1"])
    toolkit.creds = None

    with (
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google_auth_oauthlib.flow.InstalledAppFlow") as mock_flow,
    ):
        mock_path.return_value.exists.return_value = False
        mock_flow.from_client_config.return_value.run_local_server.return_value = None
        result = toolkit._resolve_creds()

    assert result is not invalid_creds


# ============================================================================
# _resolve_creds INSTANCE CREDS TESTS
# ============================================================================


def test_resolve_creds_returns_instance_creds():
    toolkit = _make_toolkit(scopes=["scope1"])
    instance_creds = _make_creds(valid=True, scopes=["scope1"])
    toolkit.creds = instance_creds

    result = toolkit._resolve_creds()

    assert result is instance_creds


def test_resolve_creds_skips_instance_creds_missing_scopes():
    toolkit = _make_toolkit(scopes=["scope1", "scope2"])
    instance_creds = _make_creds(valid=True, scopes=["scope1"])
    toolkit.creds = instance_creds

    with (
        patch("agno.tools.google.base.log_warning"),
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google_auth_oauthlib.flow.InstalledAppFlow") as mock_flow,
    ):
        mock_path.return_value.exists.return_value = False
        mock_flow.from_client_config.return_value.run_local_server.return_value = None
        result = toolkit._resolve_creds()

    assert result is not instance_creds


# ============================================================================
# _resolve_creds DB LOOKUP TESTS
# ============================================================================


def test_resolve_creds_loads_from_db():
    db = MagicMock()
    toolkit = _make_toolkit(db)

    row = {"granted_scopes": ["scope1"], "token_data": {"token": "t"}}
    creds = _make_creds()

    with patch(
        "agno.tools.google.auth.tokens.load_token_from_db",
        return_value=(row, creds),
    ) as mock_load:
        result = toolkit._resolve_creds()

    assert result is creds
    mock_load.assert_called_once()


def test_resolve_creds_returns_valid_db_creds():
    db = MagicMock()
    toolkit = _make_toolkit(db)

    row = {"granted_scopes": ["scope1"], "token_data": {"token": "t"}}
    creds = _make_creds(valid=True, expired=False)

    with patch(
        "agno.tools.google.auth.tokens.load_token_from_db",
        return_value=(row, creds),
    ):
        result = toolkit._resolve_creds()

    assert result is creds


def test_resolve_creds_skips_db_creds_missing_scopes():
    db = MagicMock()
    toolkit = _make_toolkit(db, scopes=["scope1", "scope2"])

    row = {"granted_scopes": ["scope1"], "token_data": {"token": "t"}}
    creds = _make_creds(valid=True, scopes=["scope1"])

    with (
        patch("agno.tools.google.auth.tokens.load_token_from_db", return_value=(row, creds)),
        patch("agno.tools.google.base.log_warning") as mock_warn,
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google_auth_oauthlib.flow.InstalledAppFlow") as mock_flow,
    ):
        mock_path.return_value.exists.return_value = False
        mock_flow.from_client_config.return_value.run_local_server.return_value = None
        result = toolkit._resolve_creds()

    assert result is not creds
    warnings = " ".join(str(c.args[0]) for c in mock_warn.call_args_list)
    assert "scope2" in warnings


# ============================================================================
# _resolve_creds REFRESH FAILURE TESTS
# ============================================================================


def test_resolve_creds_refresh_failure_logs_warning():
    db = MagicMock()
    toolkit = _make_toolkit(db)

    row = {"granted_scopes": ["scope1"], "token_data": {"token": "t"}}
    creds = _make_creds(valid=True, expired=True, refresh_token="refresh_token")
    creds.refresh.side_effect = Exception("network down")

    flow = MagicMock()
    flow.run_local_server.return_value = None

    with (
        patch("agno.tools.google.auth.tokens.load_token_from_db", return_value=(row, creds)),
        patch("agno.tools.google.auth.tokens.save_token_to_db") as mock_save,
        patch("agno.tools.google.base.log_warning") as mock_warn,
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google_auth_oauthlib.flow.InstalledAppFlow") as mock_flow_cls,
    ):
        mock_path.return_value.exists.return_value = False
        mock_flow_cls.from_client_config.return_value = flow
        mock_flow_cls.from_client_secrets_file.return_value = flow

        result = toolkit._resolve_creds()

    mock_save.assert_not_called()
    assert result is None
    messages = " ".join(str(call.args[0]) for call in mock_warn.call_args_list)
    assert "token refresh failed" in messages.lower()


def test_resolve_creds_refresh_saves_with_encrypt_flag():
    db = MagicMock()
    toolkit = _make_toolkit(db, encrypt_tokens=True, token_encryption_key="enc_key")

    row = {"granted_scopes": ["scope1"], "token_data": {"token": "t"}}
    creds = _make_creds(valid=True, expired=True, refresh_token="refresh_token")

    with (
        patch("agno.tools.google.auth.tokens.load_token_from_db", return_value=(row, creds)),
        patch("agno.tools.google.auth.tokens.save_token_to_db") as mock_save,
    ):
        result = toolkit._resolve_creds()

    assert result is creds
    creds.refresh.assert_called_once()
    mock_save.assert_called_once()
    save_args = mock_save.call_args[0]
    assert save_args[0] is db
    assert save_args[1] is creds
    assert save_args[3] == "enc_key"
    assert save_args[4] is True


def test_resolve_creds_encrypt_false_forwarded():
    db = MagicMock()
    toolkit = _make_toolkit(db, encrypt_tokens=False)

    row = {"granted_scopes": ["scope1"], "token_data": {"token": "t"}}
    creds = _make_creds(valid=True, expired=True, refresh_token="refresh_token")

    with (
        patch("agno.tools.google.auth.tokens.load_token_from_db", return_value=(row, creds)),
        patch("agno.tools.google.auth.tokens.save_token_to_db") as mock_save,
    ):
        toolkit._resolve_creds()

    assert mock_save.call_args[0][4] is False


# ============================================================================
# _resolve_creds FILE FALLBACK TESTS
# ============================================================================


def test_resolve_creds_loads_from_file():
    toolkit = _make_toolkit(scopes=["scope1"])
    file_creds = _make_creds(valid=True, scopes=["scope1"])

    with (
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google.oauth2.credentials.Credentials.from_authorized_user_file") as mock_load,
    ):
        mock_path.return_value.exists.return_value = True
        mock_load.return_value = file_creds

        result = toolkit._resolve_creds()

    assert result is file_creds


def test_resolve_creds_refreshes_expired_file_creds():
    toolkit = _make_toolkit(scopes=["scope1"])
    file_creds = _make_creds(valid=False, expired=True, scopes=["scope1"])

    def refresh_side_effect(request):
        file_creds.valid = True
        file_creds.expired = False

    file_creds.refresh.side_effect = refresh_side_effect

    with (
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google.oauth2.credentials.Credentials.from_authorized_user_file") as mock_load,
    ):
        token_path = MagicMock()
        token_path.exists.return_value = True
        creds_path = MagicMock()
        creds_path.exists.return_value = False
        mock_path.side_effect = [token_path, creds_path]
        mock_load.return_value = file_creds

        result = toolkit._resolve_creds()

    file_creds.refresh.assert_called_once()
    assert result is file_creds


def test_resolve_creds_falls_through_no_file():
    toolkit = _make_toolkit(scopes=["scope1"])

    with (
        patch("agno.tools.google.base.Path") as mock_path,
        patch("google_auth_oauthlib.flow.InstalledAppFlow") as mock_flow,
    ):
        mock_path.return_value.exists.return_value = False
        mock_flow.from_client_config.return_value.run_local_server.return_value = None

        result = toolkit._resolve_creds()

    assert result is None


# ============================================================================
# _resolve_creds SERVICE ACCOUNT TESTS
# ============================================================================


def test_resolve_creds_uses_service_account():
    auth = AuthConfig(service_account_path="/path/to/sa.json")
    toolkit = _make_toolkit(auth=auth, scopes=["scope1"])
    toolkit.creds = None

    sa_creds = _make_creds(valid=True, scopes=["scope1"])

    with patch("google.oauth2.service_account.Credentials.from_service_account_file") as mock_sa:
        mock_sa.return_value = sa_creds
        result = toolkit._resolve_creds()

    mock_sa.assert_called_once_with("/path/to/sa.json", scopes=["scope1"])
    assert result is sa_creds


def test_resolve_creds_service_account_with_delegated_user():
    auth = AuthConfig(
        service_account_path="/path/to/sa.json",
        delegated_user="admin@example.com",
    )
    toolkit = _make_toolkit(auth=auth, scopes=["scope1"])
    toolkit.creds = None

    base_creds = MagicMock()
    delegated_creds = _make_creds(valid=True, scopes=["scope1"])
    base_creds.with_subject.return_value = delegated_creds

    with (
        patch("google.oauth2.service_account.Credentials.from_service_account_file") as mock_sa,
        patch.object(toolkit, "_make_auth_request"),
    ):
        mock_sa.return_value = base_creds
        result = toolkit._resolve_creds()

    base_creds.with_subject.assert_called_once_with("admin@example.com")
    assert result is delegated_creds


# ============================================================================
# AUTH CONFIG + LEGACY PARAM CONFLICT TESTS
# ============================================================================


def test_raises_auth_and_service_account_path_conflict():
    auth = AuthConfig()

    with pytest.raises(ValueError, match="Cannot use both auth= and legacy params"):
        _FakeGoogleToolkit(auth=auth, service_account_path="/path/to/sa.json")


def test_raises_auth_and_delegated_user_conflict():
    auth = AuthConfig()

    with pytest.raises(ValueError, match="Cannot use both auth= and legacy params"):
        _FakeGoogleToolkit(auth=auth, delegated_user="admin@example.com")
