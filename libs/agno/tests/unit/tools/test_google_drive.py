import json
from unittest.mock import MagicMock, patch

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from agno.tools.google.drive import GoogleDriveTools


@pytest.fixture
def mock_creds():
    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture
def mock_service():
    service = MagicMock()
    files = service.files.return_value
    files.list.return_value.execute.return_value = {
        "files": [{"id": "1", "name": "TestFile", "mimeType": "text/plain", "modifiedTime": "2025-09-17T12:00:00Z"}]
    }
    return service


@pytest.fixture
def drive_tools(mock_creds, mock_service):
    with (
        patch("agno.tools.google.drive.build") as mock_build,
        patch.object(GoogleDriveTools, "_auth", return_value=None),
    ):
        mock_build.return_value = mock_service
        tools = GoogleDriveTools(creds=mock_creds, auth_port=5050)
        tools.service = mock_service
        return tools


def test_search_files_success(drive_tools):
    result = json.loads(drive_tools.search_files(query="name contains 'test'"))
    assert result["count"] == 1
    assert result["files"][0]["name"] == "TestFile"
    assert "trashed=false" in result["query"]


def test_search_files_trashed_auto(drive_tools):
    result = json.loads(drive_tools.search_files(query="name contains 'x'"))
    assert result["query"] == "(name contains 'x') and trashed=false"


def test_search_files_include_trashed(mock_creds, mock_service):
    # include_trashed=True skips the trashed=false filter
    tools = GoogleDriveTools(creds=mock_creds, include_trashed=True)
    tools.service = mock_service
    result = json.loads(tools.search_files(query="name contains 'x'"))
    assert result["query"] == "name contains 'x'"


def test_search_files_no_query(drive_tools):
    result = json.loads(drive_tools.search_files())
    assert result["query"] == "trashed=false"


def test_search_files_error(drive_tools):
    drive_tools.service.files.return_value.list.side_effect = Exception("API error")
    result = json.loads(drive_tools.search_files())
    assert "error" in result


def test_list_files_delegates(drive_tools):
    result = json.loads(drive_tools.list_files())
    assert "files" in result
    assert "query" in result


def test_list_files_success(drive_tools):
    result = json.loads(drive_tools.list_files())
    assert result["files"][0]["name"] == "TestFile"


def test_read_file_google_doc(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "doc1",
        "name": "My Doc",
        "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2025-01-01T00:00:00Z",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:
        # Write content into the buffer that MediaIoBaseDownload receives
        def capture_buffer(buf, req):
            buf.write(b"Hello from Google Docs")
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(drive_tools.read_file("doc1"))

    assert result["exportMimeType"] is not None
    assert result["exportMimeType"] == "text/plain"
    assert result["content"] == "Hello from Google Docs"
    assert result["file"]["name"] == "My Doc"
    # Verify export_media was called, not export
    drive_tools.service.files.return_value.export_media.assert_called_once()


def test_read_file_google_sheet(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "sheet1",
        "name": "Data",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "modifiedTime": "2025-01-01T00:00:00Z",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:

        def capture_buffer(buf, req):
            buf.write(b"col1,col2\na,b")
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(drive_tools.read_file("sheet1"))

    assert result["exportMimeType"] is not None
    assert result["exportMimeType"] == "text/csv"
    assert "col1" in result["content"]


def test_read_file_regular(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "f1",
        "name": "readme.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2025-01-01T00:00:00Z",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:

        def capture_buffer(buf, req):
            buf.write(b"plain text content")
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(drive_tools.read_file("f1"))

    assert result["exportMimeType"] is None
    assert result["content"] == "plain text content"
    assert result["exportMimeType"] is None


def test_read_file_max_read_size_rejected(drive_tools):
    drive_tools.max_read_size = 100
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "big1",
        "name": "huge.bin",
        "mimeType": "application/octet-stream",
        "size": "50000",
    }
    result = json.loads(drive_tools.read_file("big1"))
    assert "error" in result
    assert "exceeds max_read_size" in result["error"]


def test_read_file_max_read_size_allowed(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "small1",
        "name": "tiny.txt",
        "mimeType": "text/plain",
        "size": "5",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:

        def capture_buffer(buf, req):
            buf.write(b"hello")
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(drive_tools.read_file("small1"))
    assert result["content"] == "hello"


def test_read_file_unsupported_workspace(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "d1",
        "name": "Drawing",
        "mimeType": "application/vnd.google-apps.drawing",
        "modifiedTime": "2025-01-01T00:00:00Z",
    }
    result = json.loads(drive_tools.read_file("d1"))
    assert "error" in result
    assert "Cannot read" in result["error"]


def test_read_file_large_export_passes_through(drive_tools):
    # Drive API enforces 10MB export limit server-side (HTTP 403), not client-side
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "big1",
        "name": "Huge Doc",
        "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2025-01-01T00:00:00Z",
    }
    big_content = b"x" * (11 * 1024 * 1024)
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:

        def capture_buffer(buf, req):
            buf.write(big_content)
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(drive_tools.read_file("big1"))

    assert "content" in result
    assert result["contentLength"] == len(big_content)


def test_upload_file_success(tmp_path, drive_tools):
    file_path = tmp_path / "test_upload.txt"
    file_path.write_text("hello world")
    drive_tools.service.files.return_value.create.return_value.execute.return_value = {
        "id": "123",
        "name": "test_upload.txt",
        "mimeType": "text/plain",
    }
    result = json.loads(drive_tools.upload_file(file_path))
    assert result["name"] == "test_upload.txt"
    assert result["id"] == "123"


def test_upload_file_error(tmp_path, drive_tools):
    file_path = tmp_path / "test_upload.txt"
    file_path.write_text("hello world")
    drive_tools.service.files.return_value.create.side_effect = Exception("Upload error")
    result = json.loads(drive_tools.upload_file(file_path))
    assert "error" in result


def test_upload_file_missing(drive_tools):
    result = json.loads(drive_tools.upload_file("/nonexistent/path.txt"))
    assert "error" in result
    assert "does not exist" in result["error"]


def test_download_file_success(tmp_path, drive_tools):
    drive_tools.download_dir = tmp_path
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "abc123",
        "name": "file.txt",
        "mimeType": "text/plain",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.side_effect = [
        (MagicMock(progress=lambda: 0.5), False),
        (MagicMock(progress=lambda: 1.0), True),
    ]
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader):
        result = json.loads(drive_tools.download_file("abc123"))
    assert result["status"] == "downloaded"
    assert result["fileId"] == "abc123"
    assert "file.txt" in result["path"]


def test_download_file_error(tmp_path, drive_tools):
    drive_tools.download_dir = tmp_path
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "abc123",
        "name": "file.txt",
        "mimeType": "text/plain",
    }
    drive_tools.service.files.return_value.get_media.side_effect = Exception("Download error")
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=MagicMock()):
        result = json.loads(drive_tools.download_file("abc123"))
    assert "error" in result


def test_init_scope_inference_readonly(mock_creds):
    with (
        patch("agno.tools.google.drive.build"),
        patch.object(GoogleDriveTools, "_auth", return_value=None),
    ):
        tools = GoogleDriveTools(creds=mock_creds, upload_file=False)
    assert "https://www.googleapis.com/auth/drive.readonly" in tools.scopes
    assert "https://www.googleapis.com/auth/drive.file" not in tools.scopes


def test_init_scope_inference_write(mock_creds):
    with (
        patch("agno.tools.google.drive.build"),
        patch.object(GoogleDriveTools, "_auth", return_value=None),
    ):
        tools = GoogleDriveTools(creds=mock_creds, upload_file=True)
    assert "https://www.googleapis.com/auth/drive.readonly" in tools.scopes
    assert "https://www.googleapis.com/auth/drive.file" in tools.scopes


def test_service_account_auth():
    with (
        patch("agno.tools.google.drive.build"),
        patch("agno.tools.google.drive.ServiceAccountCredentials") as mock_sa,
        patch("agno.tools.google.drive.Request"),
    ):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_sa.from_service_account_file.return_value = mock_creds
        mock_creds.with_subject.return_value = mock_creds

        tools = GoogleDriveTools(service_account_path="/fake/sa.json", delegated_user="user@example.com")
        tools._auth()

        mock_sa.from_service_account_file.assert_called_once()
        mock_creds.with_subject.assert_called_once_with("user@example.com")


# ---------------------------------------------------------------------------
# Helper: _normalize_query
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_init_read_scope_mismatch(mock_creds):
    # A scope that's not in any of read/write/full candidates
    with (
        patch("agno.tools.google.drive.build"),
        patch.object(GoogleDriveTools, "_auth", return_value=None),
        pytest.raises(ValueError, match="read scope"),
    ):
        GoogleDriveTools(creds=mock_creds, scopes=["https://www.googleapis.com/auth/gmail.readonly"], read_file=True)


def test_init_write_scope_mismatch(mock_creds):
    with (
        patch("agno.tools.google.drive.build"),
        patch.object(GoogleDriveTools, "_auth", return_value=None),
        pytest.raises(ValueError, match="write scope"),
    ):
        GoogleDriveTools(
            creds=mock_creds,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
            upload_file=True,
            list_files=False,
            search_files=False,
            read_file=False,
        )


# ---------------------------------------------------------------------------
# authenticate decorator error path
# ---------------------------------------------------------------------------


def test_auth_failure_returns_json(mock_creds, mock_service):
    with (
        patch("agno.tools.google.drive.build") as mock_build,
        patch.object(GoogleDriveTools, "_auth", side_effect=RuntimeError("token expired")),
    ):
        mock_build.return_value = mock_service
        tools = GoogleDriveTools(creds=mock_creds, auth_port=5050)
        tools.creds = MagicMock(valid=False)
        tools.service = None
        result = json.loads(tools.search_files())
    assert "error" in result
    assert "authentication failed" in result["error"].lower()


# ---------------------------------------------------------------------------
# HttpError branches
# ---------------------------------------------------------------------------


def _make_http_error(status=404, reason="Not Found"):
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp, b"error")


def test_search_files_http_error(drive_tools):
    drive_tools.service.files.return_value.list.side_effect = _make_http_error(403, "Forbidden")
    result = json.loads(drive_tools.search_files())
    assert "error" in result
    assert "Google Drive API error" in result["error"]


def test_read_file_http_error_export_limit(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "doc1",
        "name": "Doc",
        "mimeType": "application/vnd.google-apps.document",
    }
    resp = MagicMock()
    resp.status = 403
    resp.reason = "exportSizeLimitExceeded"
    drive_tools.service.files.return_value.export_media.side_effect = HttpError(resp, b"exportSizeLimitExceeded")
    result = json.loads(drive_tools.read_file("doc1"))
    assert "error" in result
    assert "Google Drive API error" in result["error"]


def test_upload_file_http_error(tmp_path, drive_tools):
    file_path = tmp_path / "test.txt"
    file_path.write_text("data")
    drive_tools.service.files.return_value.create.side_effect = _make_http_error(500, "Server Error")
    result = json.loads(drive_tools.upload_file(file_path))
    assert "Google Drive API error" in result["error"]


def test_download_file_http_error(tmp_path, drive_tools):
    drive_tools.download_dir = tmp_path
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "bad",
        "name": "file.txt",
        "mimeType": "text/plain",
    }
    drive_tools.service.files.return_value.get_media.side_effect = _make_http_error(404)
    result = json.loads(drive_tools.download_file("bad"))
    assert "Google Drive API error" in result["error"]


# ---------------------------------------------------------------------------
# search_files edge cases
# ---------------------------------------------------------------------------


def test_search_files_max_results_zero(drive_tools):
    result = json.loads(drive_tools.search_files(max_results=0))
    assert "error" in result
    assert "max_results" in result["error"]


def test_search_files_empty_results(drive_tools):
    drive_tools.service.files.return_value.list.return_value.execute.return_value = {"files": []}
    result = json.loads(drive_tools.search_files())
    assert result["count"] == 0
    assert result["files"] == []


def test_search_files_next_page_token(drive_tools):
    drive_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "1"}],
        "nextPageToken": "token123",
    }
    result = json.loads(drive_tools.search_files())
    assert result["nextPageToken"] == "token123"


def test_search_files_page_token_passed(drive_tools):
    drive_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "2"}],
    }
    drive_tools.search_files(query="name='x'", page_token="abc123")
    call_kwargs = drive_tools.service.files.return_value.list.call_args
    assert call_kwargs[1]["pageToken"] == "abc123"


# ---------------------------------------------------------------------------
# read_file: Slides export + no truncation
# ---------------------------------------------------------------------------


def test_read_file_google_slides(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "slide1",
        "name": "Presentation",
        "mimeType": "application/vnd.google-apps.presentation",
        "modifiedTime": "2025-01-01T00:00:00Z",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:

        def capture_buffer(buf, req):
            buf.write(b"Slide content here")
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(drive_tools.read_file("slide1"))

    assert result["exportMimeType"] is not None
    assert result["exportMimeType"] == "text/plain"
    assert result["content"] == "Slide content here"


# ---------------------------------------------------------------------------
# upload_file: directory path rejection
# ---------------------------------------------------------------------------


def test_upload_file_mime_auto_detected(tmp_path, drive_tools):
    file_path = tmp_path / "data.csv"
    file_path.write_text("a,b,c")
    drive_tools.service.files.return_value.create.return_value.execute.return_value = {
        "id": "csv1",
        "name": "data.csv",
        "mimeType": "text/csv",
    }
    with patch("agno.tools.google.drive.MediaFileUpload") as mock_upload:
        drive_tools.upload_file(file_path)
        assert mock_upload.call_args[1]["mimetype"] == "text/csv"


def test_upload_file_unknown_extension_fallback(tmp_path, drive_tools):
    file_path = tmp_path / "data.xyz123"
    file_path.write_text("unknown")
    drive_tools.service.files.return_value.create.return_value.execute.return_value = {
        "id": "unk1",
        "name": "data.xyz123",
    }
    with patch("agno.tools.google.drive.MediaFileUpload") as mock_upload:
        drive_tools.upload_file(file_path)
        assert mock_upload.call_args[1]["mimetype"] == "application/octet-stream"


def test_upload_file_directory_rejected(tmp_path, drive_tools):
    result = json.loads(drive_tools.upload_file(tmp_path))
    assert "error" in result
    assert "does not exist or is not a file" in result["error"]


# ---------------------------------------------------------------------------
# download_file: nested directory creation
# ---------------------------------------------------------------------------


def test_download_file_uses_download_dir(tmp_path, drive_tools):
    drive_tools.download_dir = tmp_path
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "abc123",
        "name": "report.pdf",
        "mimeType": "application/pdf",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader):
        result = json.loads(drive_tools.download_file("abc123"))
    assert result["status"] == "downloaded"
    assert result["path"] == str(tmp_path / "report.pdf")


# ---------------------------------------------------------------------------
# Async variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_search_files(drive_tools):
    result = json.loads(await drive_tools.asearch_files(query="name='test'"))
    assert "files" in result
    assert "trashed=false" in result["query"]


@pytest.mark.asyncio
async def test_async_list_files(drive_tools):
    result = json.loads(await drive_tools.alist_files())
    assert "files" in result


@pytest.mark.asyncio
async def test_async_read_file(drive_tools):
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "f1",
        "name": "readme.txt",
        "mimeType": "text/plain",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader) as mock_dl:

        def capture_buffer(buf, req):
            buf.write(b"async content")
            return mock_downloader

        mock_dl.side_effect = capture_buffer
        result = json.loads(await drive_tools.aread_file("f1"))
    assert result["content"] == "async content"


@pytest.mark.asyncio
async def test_async_upload_file(tmp_path, drive_tools):
    file_path = tmp_path / "upload.txt"
    file_path.write_text("hello")
    drive_tools.service.files.return_value.create.return_value.execute.return_value = {
        "id": "u1",
        "name": "upload.txt",
    }
    result = json.loads(await drive_tools.aupload_file(file_path))
    assert result["id"] == "u1"


@pytest.mark.asyncio
async def test_async_download_file(tmp_path, drive_tools):
    drive_tools.download_dir = tmp_path
    drive_tools.service.files.return_value.get.return_value.execute.return_value = {
        "id": "abc",
        "name": "file.txt",
        "mimeType": "text/plain",
    }
    mock_downloader = MagicMock()
    mock_downloader.next_chunk.return_value = (MagicMock(), True)
    with patch("agno.tools.google.drive.MediaIoBaseDownload", return_value=mock_downloader):
        result = json.loads(await drive_tools.adownload_file("abc"))
    assert result["status"] == "downloaded"
    assert "file.txt" in result["path"]


# ---------------------------------------------------------------------------
# Service account: no delegated user (Drive doesn't require it)
# ---------------------------------------------------------------------------


def test_service_account_no_delegated_user():
    with (
        patch("agno.tools.google.drive.build"),
        patch("agno.tools.google.drive.ServiceAccountCredentials") as mock_sa,
        patch("agno.tools.google.drive.Request"),
        patch.dict("os.environ", {"GOOGLE_DELEGATED_USER": ""}, clear=False),
    ):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_sa.from_service_account_file.return_value = mock_creds

        tools = GoogleDriveTools(service_account_path="/fake/sa.json")
        tools._auth()

        mock_sa.from_service_account_file.assert_called_once()
        mock_creds.with_subject.assert_not_called()
