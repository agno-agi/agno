"""Tests for Google toolkit timeout and _build_google_service refactor.

Verifies:
1. _get_http_timeout() priority: AuthConfig > env > default
2. _build_google_service() wires httplib2.Http -> AuthorizedHttp -> build
3. All toolkits use the helper (no duplicated transport construction)
4. Drive quota_project_id still works
5. Slides dual services both get timeout
6. Sheets create_duplicate_sheet uses timeout-aware Drive service
"""

import ast
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.google.auth import AuthConfig
from agno.tools.google.base import DEFAULT_GOOGLE_API_TIMEOUT, GoogleToolkit
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.drive import GoogleDriveTools
from agno.tools.google.gmail import GmailTools
from agno.tools.google.sheets import GoogleSheetsTools
from agno.tools.google.slides import GoogleSlidesTools


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


class TestGetHttpTimeout:
    def test_auth_config_has_highest_priority(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_TIMEOUT", "99")
        auth = AuthConfig(http_timeout=7.5)
        tools = GmailTools(auth=auth)
        assert tools._get_http_timeout() == 7.5

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_TIMEOUT", "12.25")
        tools = GmailTools()
        assert tools._get_http_timeout() == 12.25

    def test_default_when_env_missing(self):
        tools = GmailTools()
        assert tools._get_http_timeout() == DEFAULT_GOOGLE_API_TIMEOUT

    @pytest.mark.parametrize("invalid_env", ["abc", "", "not-a-number"])
    def test_default_when_env_invalid(self, monkeypatch, invalid_env):
        monkeypatch.setenv("GOOGLE_API_TIMEOUT", invalid_env)
        tools = GmailTools()
        assert tools._get_http_timeout() == DEFAULT_GOOGLE_API_TIMEOUT

    @pytest.mark.parametrize("timeout_value", [0, 0.5, 30.0, 120])
    def test_float_and_zero_timeout_passthrough(self, timeout_value):
        auth = AuthConfig(http_timeout=timeout_value)
        tools = GmailTools(auth=auth)
        assert tools._get_http_timeout() == timeout_value


class TestBuildGoogleService:
    def test_constructs_timeout_aware_authorized_http(self, mock_valid_creds):
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

    def test_base_build_service_uses_toolkit_api_metadata(self, mock_valid_creds):
        # Gmail, Calendar, Sheets should use api_name/api_version from class
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


class TestDriveBuildService:
    def test_applies_quota_project_before_transport(self, mock_valid_creds):
        quota_creds = MagicMock()
        mock_valid_creds.with_quota_project.return_value = quota_creds

        tools = GoogleDriveTools(quota_project_id="billing-proj")

        with (
            patch("httplib2.Http") as mock_httplib2,
            patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http,
            patch("googleapiclient.discovery.build"),
        ):
            tools._build_service(mock_valid_creds)

            mock_valid_creds.with_quota_project.assert_called_once_with("billing-proj")
            mock_auth_http.assert_called_once()
            assert mock_auth_http.call_args[0][0] is quota_creds

    def test_reads_quota_project_from_env(self, monkeypatch, mock_valid_creds):
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

    def test_preserves_original_creds_reference(self, mock_valid_creds):
        quota_creds = MagicMock()
        mock_valid_creds.with_quota_project.return_value = quota_creds

        tools = GoogleDriveTools(quota_project_id="billing-proj")
        original_creds = mock_valid_creds

        with (
            patch("httplib2.Http"),
            patch("google_auth_httplib2.AuthorizedHttp"),
            patch("googleapiclient.discovery.build"),
        ):
            tools._build_service(mock_valid_creds)
            # Original creds object not mutated
            assert mock_valid_creds is original_creds

    def test_without_quota_project_method_still_builds(self):
        # Creds without with_quota_project attribute
        simple_creds = MagicMock(spec=[])
        tools = GoogleDriveTools(quota_project_id="billing-proj")

        with (
            patch("httplib2.Http"),
            patch("google_auth_httplib2.AuthorizedHttp") as mock_auth_http,
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            tools._build_service(simple_creds)
            # Should still build with original creds
            mock_auth_http.assert_called_once()
            mock_build.assert_called_once()


class TestSlidesBuildService:
    def test_builds_slides_and_drive_with_same_timeout(self, mock_valid_creds):
        auth = AuthConfig(http_timeout=6.0)
        tools = GoogleSlidesTools(auth=auth)

        with (
            patch("httplib2.Http") as mock_httplib2,
            patch("google_auth_httplib2.AuthorizedHttp"),
            patch("googleapiclient.discovery.build") as mock_build,
        ):
            result = tools._build_service(mock_valid_creds)

            # Two Http instances created, both with same timeout
            assert mock_httplib2.call_count == 2
            for call in mock_httplib2.call_args_list:
                assert call[1]["timeout"] == 6.0

            # Builds both slides and drive
            assert mock_build.call_count == 2
            api_calls = [(c[0][0], c[0][1]) for c in mock_build.call_args_list]
            assert ("slides", "v1") in api_calls
            assert ("drive", "v3") in api_calls

            # Returns slides service
            assert result == mock_build.return_value

    def test_sets_both_service_attributes(self, mock_valid_creds):
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


class TestSheetsDuplicateTimeout:
    def test_duplicate_builds_drive_service_with_helper(self, mock_valid_creds):
        tools = GoogleSheetsTools()
        tools.creds = mock_valid_creds
        tools.scopes = ["https://www.googleapis.com/auth/spreadsheets"]

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

            # Drive service built with timeout
            mock_httplib2.assert_called()
            assert mock_httplib2.call_args[1]["timeout"] == DEFAULT_GOOGLE_API_TIMEOUT
            mock_build.assert_called_with("drive", "v3", http=mock_build.call_args[1]["http"])


class TestNoDirectTransportConstruction:
    """Static analysis to ensure no toolkit reimplements transport construction."""

    @pytest.fixture
    def google_tools_dir(self):
        # Navigate from test file to google tools directory
        import agno.tools.google.drive as drive_mod
        return Path(drive_mod.__file__).parent

    def test_drive_does_not_import_httplib2_or_authorized_http(self, google_tools_dir):
        source = (google_tools_dir / "drive.py").read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httplib2", "drive.py should not import httplib2"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "httplib2", "drive.py should not import from httplib2"
                assert node.module != "google_auth_httplib2", "drive.py should not import from google_auth_httplib2"

    def test_slides_does_not_import_httplib2_or_authorized_http(self, google_tools_dir):
        source = (google_tools_dir / "slides.py").read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httplib2", "slides.py should not import httplib2"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "httplib2", "slides.py should not import from httplib2"
                assert node.module != "google_auth_httplib2", "slides.py should not import from google_auth_httplib2"

    def test_sheets_does_not_import_httplib2_or_authorized_http(self, google_tools_dir):
        source = (google_tools_dir / "sheets.py").read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "httplib2", "sheets.py should not import httplib2"
            if isinstance(node, ast.ImportFrom):
                assert node.module != "httplib2", "sheets.py should not import from httplib2"
                assert node.module != "google_auth_httplib2", "sheets.py should not import from google_auth_httplib2"


class TestMultiToolkitSharedAuth:
    def test_all_toolkits_build_with_same_timeout(self, mock_valid_creds):
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

                # Every Http instance should have timeout=8.0
                for call in mock_httplib2.call_args_list:
                    assert call[1]["timeout"] == 8.0

    def test_services_are_independent_objects(self, mock_valid_creds):
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

            # All services are unique objects
            assert len(set(id(s) for s in services)) == len(services)


class TestRegressions:
    def test_sheets_duplicate_drive_service_has_timeout(self, mock_valid_creds):
        """Regression: sheets.py line 296 previously used build() without timeout."""
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

            # Drive service MUST use timeout=3.0
            assert mock_httplib2.call_args[1]["timeout"] == 3.0

    def test_slides_companion_drive_has_timeout(self, mock_valid_creds):
        """Regression: slides.py drive_service must use timeout."""
        auth = AuthConfig(http_timeout=5.0)
        tools = GoogleSlidesTools(auth=auth)

        with (
            patch("httplib2.Http") as mock_httplib2,
            patch("google_auth_httplib2.AuthorizedHttp"),
            patch("googleapiclient.discovery.build"),
        ):
            tools._build_service(mock_valid_creds)

            # Both calls should have timeout=5.0
            assert mock_httplib2.call_count == 2
            for call in mock_httplib2.call_args_list:
                assert call[1]["timeout"] == 5.0

    def test_drive_quota_project_and_timeout_both_apply(self, mock_valid_creds):
        """Regression: Drive must apply both quota_project AND timeout."""
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

    def test_all_toolkits_use_http_not_credentials_build_arg(self, mock_valid_creds):
        """Regression: All build() calls must use http=, not credentials=."""
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
                assert "http" in call_kwargs, f"{toolkit.__class__.__name__} must use http="
                assert "credentials" not in call_kwargs, f"{toolkit.__class__.__name__} must not use credentials="
