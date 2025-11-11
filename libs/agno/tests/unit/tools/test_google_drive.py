from unittest.mock import MagicMock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.google_drive import GoogleDriveTools


@pytest.fixture
def mock_service():
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {
        "files": [{"id": "1", "name": "TestFile", "mimeType": "text/plain", "modifiedTime": "2025-09-17T12:00:00Z"}]
    }
    return service


@pytest.fixture
def mock_creds():
    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture
def drive_tools(mock_creds, mock_service):
    with (
        patch("agno.tools.google_drive.build") as mock_build,
        patch.object(GoogleDriveTools, "_auth", return_value=None),
    ):
        mock_build.return_value = mock_service
        # Provide an auth_port so the constructor doesn't fail during tests
        tools = GoogleDriveTools(creds=mock_creds, auth_port=5050, quota_project_id="test-project-id")
        tools.service = mock_service
        return tools


def test_list_files_success(drive_tools):
    files = drive_tools.list_files()
    assert isinstance(files, list)
    assert files[0]["name"] == "TestFile"


def test_list_files_error(drive_tools):
    drive_tools.service.files.return_value.list.side_effect = Exception("API error")
    files = drive_tools.list_files()
    assert files == []


def test_upload_file_success(tmp_path, drive_tools):
    # Create a temporary file to upload
    file_path = tmp_path / "test_upload.txt"
    file_path.write_text("hello world")
    mock_create = drive_tools.service.files.return_value.create
    mock_create.return_value.execute.return_value = {
        "id": "123",
        "name": "test_upload.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2025-09-17T12:00:00Z",
    }
    result = drive_tools.upload_file(file_path)
    assert result["name"] == "test_upload.txt"
    assert result["id"] == "123"


def test_upload_file_error(tmp_path, drive_tools):
    file_path = tmp_path / "test_upload.txt"
    file_path.write_text("hello world")
    mock_create = drive_tools.service.files.return_value.create
    mock_create.side_effect = Exception("Upload error")
    result = drive_tools.upload_file(file_path)
    assert result is None


def test_download_file_success(tmp_path, drive_tools):
    file_id = "abc123"
    dest_path = tmp_path / "downloaded.txt"
    # mock_get_media = drive_tools.service.files.return_value.get_media
    mock_downloader = MagicMock()
    # Simulate two chunks: first not done, second done
    mock_downloader.next_chunk.side_effect = [
        (MagicMock(progress=lambda: 0.5), False),
        (MagicMock(progress=lambda: 1.0), True),
    ]
    with patch("agno.tools.google_drive.MediaIoBaseDownload", return_value=mock_downloader):
        result = drive_tools.download_file(file_id, dest_path)
    assert result == dest_path
    assert dest_path.exists()


def test_download_file_error(tmp_path, drive_tools):
    file_id = "abc123"
    dest_path = tmp_path / "downloaded.txt"
    mock_get_media = drive_tools.service.files.return_value.get_media
    mock_get_media.side_effect = Exception("Download error")
    with patch("agno.tools.google_drive.MediaIoBaseDownload", return_value=MagicMock()):
        result = drive_tools.download_file(file_id, dest_path)
    assert result is None
