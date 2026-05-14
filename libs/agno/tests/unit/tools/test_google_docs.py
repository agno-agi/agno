"""Unit tests for GoogleDocsTools."""

import json
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from agno.tools.google.docs import GoogleDocsTools


@pytest.fixture
def mock_credentials():
    creds = Mock(spec=Credentials)
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture
def mock_docs_service():
    service = MagicMock()
    documents = service.documents.return_value

    documents.create.return_value.execute.return_value = {
        "documentId": "doc-id-123",
        "title": "Test Doc",
    }
    documents.get.return_value.execute.return_value = {
        "documentId": "doc-id-123",
        "title": "Test Doc",
        "body": {
            "content": [
                {
                    "endIndex": 25,
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "Hello "}},
                            {"textRun": {"content": "world\n"}},
                        ]
                    },
                },
                {
                    "endIndex": 47,
                    "paragraph": {"elements": [{"textRun": {"content": "Second paragraph.\n"}}]},
                },
            ]
        },
    }
    documents.batchUpdate.return_value.execute.return_value = {
        "documentId": "doc-id-123",
        "replies": [{}],
    }
    return service


@pytest.fixture
def mock_drive_service():
    service = MagicMock()
    files = service.files.return_value
    files.delete.return_value.execute.return_value = {}
    return service


@pytest.fixture
def tools(mock_credentials, mock_docs_service, mock_drive_service):
    """Mirror test_google_drive.py — patch the contextvar reader so the
    `service` property returns the mocked dict for the duration of the test.
    All patches auto-restore on teardown."""
    mock_service_dict = {"docs": mock_docs_service, "drive": mock_drive_service}
    with (
        patch(
            "agno.tools.google.base.get_current_service",
            return_value=mock_service_dict,
        ),
        patch.object(GoogleDocsTools, "_resolve_creds", return_value=mock_credentials),
        patch.object(GoogleDocsTools, "_build_service", return_value=mock_service_dict),
    ):
        toolkit = GoogleDocsTools(creds=mock_credentials)
        yield toolkit


class TestInitialization:
    def test_class_attributes(self):
        assert GoogleDocsTools.api_name == "docs"
        assert GoogleDocsTools.api_version == "v1"
        assert GoogleDocsTools.google_service_name == "docs"
        assert "https://www.googleapis.com/auth/documents" in GoogleDocsTools.default_scopes

    def test_default_destructive_off(self, mock_credentials):
        with patch("agno.tools.google.docs.authenticate", lambda func: func):
            t = GoogleDocsTools(creds=mock_credentials)
        sync_names = {f.__name__ for f in t.tools if callable(f)}
        async_pair_names = {name for _, name in t._async_tools}
        # delete_document defaults to False - should not register in either set
        assert "delete_document" not in sync_names
        assert "delete_document" not in async_pair_names

    def test_all_flag_registers_everything(self, mock_credentials):
        with patch("agno.tools.google.docs.authenticate", lambda func: func):
            t = GoogleDocsTools(creds=mock_credentials, all=True)
        sync_names = {f.__name__ for f in t.tools if callable(f)}
        async_pair_names = {name for _, name in t._async_tools}
        for name in (
            "create_document",
            "get_document",
            "get_document_text",
            "batch_update",
            "append_text",
            "export_as_pdf",
            "delete_document",
        ):
            assert name in sync_names, f"Expected sync {name} in tools"
            assert name in async_pair_names, f"Expected async pair for {name} in _async_tools"


class TestCreateDocument:
    def test_success(self, tools, mock_docs_service):
        result = json.loads(tools.create_document(title="Test Doc"))
        assert result["documentId"] == "doc-id-123"
        assert result["title"] == "Test Doc"
        assert "docs.google.com" in result["url"]
        mock_docs_service.documents().create.assert_called_with(body={"title": "Test Doc"})

    def test_http_error(self, tools, mock_docs_service):
        mock_docs_service.documents().create.return_value.execute.side_effect = HttpError(
            resp=Mock(status=403), content=b"Forbidden"
        )
        result = json.loads(tools.create_document(title="x"))
        assert "error" in result

    def test_unexpected_exception(self, tools, mock_docs_service):
        mock_docs_service.documents().create.return_value.execute.side_effect = RuntimeError("boom")
        result = json.loads(tools.create_document(title="x"))
        assert "Unexpected error" in result["error"]


class TestGetDocument:
    def test_full_structure(self, tools):
        result = json.loads(tools.get_document(document_id="doc-id-123"))
        assert result["documentId"] == "doc-id-123"
        assert "body" in result


class TestGetDocumentText:
    def test_extracts_text(self, tools):
        result = json.loads(tools.get_document_text(document_id="doc-id-123"))
        assert result["documentId"] == "doc-id-123"
        assert result["title"] == "Test Doc"
        assert "Hello world" in result["text"]
        assert "Second paragraph." in result["text"]


class TestBatchUpdate:
    def test_success(self, tools, mock_docs_service):
        requests = [{"insertText": {"location": {"index": 1}, "text": "hi"}}]
        result = json.loads(tools.batch_update(document_id="doc-id-123", requests=requests))
        assert result["documentId"] == "doc-id-123"
        mock_docs_service.documents().batchUpdate.assert_called_with(
            documentId="doc-id-123", body={"requests": requests}
        )

    def test_empty_requests_rejected(self, tools):
        result = json.loads(tools.batch_update(document_id="doc-id-123", requests=[]))
        assert "error" in result


class TestAppendText:
    def test_uses_end_index_minus_one(self, tools, mock_docs_service):
        # The fixture's get response has elements ending at index 25 and 47.
        # append_text should insert at endIndex - 1 = 46.
        result = json.loads(tools.append_text(document_id="doc-id-123", text="appended"))
        assert result["inserted_at_index"] == 46
        # Verify the batchUpdate was called with the right insertText location
        call = mock_docs_service.documents().batchUpdate.call_args
        body = call.kwargs.get("body") or call.args[0] if not call.kwargs else call.kwargs["body"]
        assert body["requests"][0]["insertText"]["location"]["index"] == 46
        assert body["requests"][0]["insertText"]["text"] == "appended"

    def test_empty_text_rejected(self, tools):
        result = json.loads(tools.append_text(document_id="doc-id-123", text=""))
        assert "error" in result


class TestExportAsPdf:
    def test_writes_file(self, tools, mock_drive_service):
        # MediaIoBaseDownload constructor patched to a no-op that returns done=True
        with patch("agno.tools.google.docs.MediaIoBaseDownload") as mock_dl_cls:
            instance = mock_dl_cls.return_value
            instance.next_chunk.return_value = (None, True)
            with patch("builtins.open", mock_open()) as mocked_file:
                result = json.loads(tools.export_as_pdf(document_id="doc-id-123", output_path="/tmp/out.pdf"))
        assert result["output_path"] == "/tmp/out.pdf"
        assert result["bytes_written"] == 0  # empty buffer
        mocked_file.assert_called_with("/tmp/out.pdf", "wb")
        mock_drive_service.files().export_media.assert_called_with(fileId="doc-id-123", mimeType="application/pdf")


class TestDeleteDocument:
    def test_calls_drive_delete(self, tools, mock_drive_service):
        result = json.loads(tools.delete_document(document_id="doc-id-123"))
        assert result["status"] == "deleted"
        assert result["documentId"] == "doc-id-123"
        mock_drive_service.files().delete.assert_called_with(fileId="doc-id-123")


class TestAsyncVariants:
    @pytest.mark.asyncio
    async def test_acreate_document_delegates(self, tools):
        result = json.loads(await tools.acreate_document(title="Async Doc"))
        assert result["documentId"] == "doc-id-123"

    @pytest.mark.asyncio
    async def test_aget_document_text_delegates(self, tools):
        result = json.loads(await tools.aget_document_text(document_id="doc-id-123"))
        assert "Hello world" in result["text"]

    @pytest.mark.asyncio
    async def test_abatch_update_delegates(self, tools):
        requests = [{"insertText": {"location": {"index": 1}, "text": "x"}}]
        result = json.loads(await tools.abatch_update(document_id="doc-id-123", requests=requests))
        assert result["documentId"] == "doc-id-123"
