"""Unit tests for GoogleDriveTools class."""

from unittest.mock import MagicMock, Mock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.googledrive import GoogleDriveTools


@pytest.fixture
def mock_credentials():
    """Mock Google OAuth2 credentials."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    return mock_creds


@pytest.fixture
def mock_drive_service():
    """Mock Google Drive API service."""
    return MagicMock()


@pytest.fixture
def drive_tools(mock_credentials, mock_drive_service):
    """Create GoogleDriveTools instance with mocked service."""
    with patch("agno.tools.googledrive.build") as mock_build:
        mock_build.return_value = mock_drive_service
        tools = GoogleDriveTools(creds_path=None, token_path=None)
        tools.creds = mock_credentials  # inject mock creds
        tools.service = mock_drive_service
        return tools


def test_list_files(drive_tools, mock_drive_service):
    """Test listing files."""
    mock_drive_service.files().list().execute.return_value = {"files": [{"id": "1", "name": "test.txt"}]}
    result = drive_tools.list_files()
    assert result["files"][0]["name"] == "test.txt"


def test_search_files(drive_tools, mock_drive_service):
    """Test searching files."""
    mock_drive_service.files().list().execute.return_value = {"files": [{"id": "1", "name": "report.doc"}]}
    result = drive_tools.search_files(query="name contains 'report'")
    assert any("report" in f["name"] for f in result["files"])


def test_get_file_info(drive_tools, mock_drive_service):
    """Test retrieving file info."""
    mock_drive_service.files().get().execute.return_value = {"id": "1", "name": "info.txt"}
    result = drive_tools.get_file_info(file_id="1")
    assert result["name"] == "info.txt"


def test_upload_file(drive_tools, mock_drive_service, tmp_path):
    """Test uploading a file."""
    # Create temp file
    file_path = tmp_path / "upload.txt"
    file_path.write_text("content")

    mock_drive_service.files().create().execute.return_value = {"id": "123", "name": "upload.txt"}
    result = drive_tools.upload_file(local_path=str(file_path))
    assert result["name"] == "upload.txt"


def test_download_file(drive_tools, mock_drive_service, tmp_path):
    """Test downloading a file."""
    mock_request = MagicMock()
    mock_drive_service.files().get_media.return_value = mock_request

    # Patch MediaIoBaseDownload to simulate progress
    with patch("googleapiclient.http.MediaIoBaseDownload") as mock_downloader_cls:
        mock_downloader = MagicMock()
        mock_downloader.next_chunk.side_effect = [(MagicMock(progress=lambda: 1.0), True)]
        mock_downloader_cls.return_value = mock_downloader

        result = drive_tools.download_file(file_id="1", destination_path=str(tmp_path / "dl.txt"))
        assert "downloaded" in result["message"]


def test_create_folder(drive_tools, mock_drive_service):
    """Test creating a folder."""
    mock_drive_service.files().create().execute.return_value = {"id": "f123", "name": "NewFolder"}
    result = drive_tools.create_folder("NewFolder")
    assert result["name"] == "NewFolder"


def test_delete_file_soft(drive_tools, mock_drive_service):
    """Test moving file to trash."""
    result = drive_tools.delete_file(file_id="abc123", permanent=False)
    mock_drive_service.files().update.assert_called_once()
    assert "Trash" in result["message"]


def test_delete_file_permanent(drive_tools, mock_drive_service):
    """Test hard delete of file."""
    result = drive_tools.delete_file(file_id="abc123", permanent=True)
    mock_drive_service.files().delete.assert_called_once()
    assert "permanently" in result["message"]
