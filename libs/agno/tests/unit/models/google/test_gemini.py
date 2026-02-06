from unittest.mock import MagicMock, PropertyMock, patch

import pytest

pytest.importorskip("google.genai", reason="google-genai not installed")

from agno.media import File
from agno.models.google.gemini import Gemini


def test_gemini_get_client_with_credentials_vertexai():
    mock_credentials = MagicMock()
    model = Gemini(vertexai=True, project_id="test-project", location="test-location", credentials=mock_credentials)

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        _, kwargs = mock_client_cls.call_args
        assert kwargs["credentials"] == mock_credentials
        assert kwargs["vertexai"] is True
        assert kwargs["project"] == "test-project"
        assert kwargs["location"] == "test-location"


def test_gemini_get_client_without_credentials_vertexai():
    model = Gemini(vertexai=True, project_id="test-project", location="test-location")

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        _, kwargs = mock_client_cls.call_args
        assert "credentials" not in kwargs
        assert kwargs["vertexai"] is True


def test_gemini_get_client_ai_studio_mode():
    mock_credentials = MagicMock()
    model = Gemini(vertexai=False, api_key="test-api-key", credentials=mock_credentials)

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        _, kwargs = mock_client_cls.call_args
        assert "credentials" not in kwargs
        assert "api_key" in kwargs
        assert kwargs.get("vertexai") is not True


# --- Tests for _format_file_for_message --- #


class TestGeminiFormatFileForMessage:
    @pytest.fixture
    def model(self):
        return Gemini(id="gemini-2.0-flash", api_key="test-key")

    def test_bytes_with_mime(self, model):
        content = b"fake-pdf-bytes"
        f = File(content=content, mime_type="application/pdf")
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_bytes.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_bytes.assert_called_once_with(mime_type="application/pdf", data=content)
            assert result == mock_part

    def test_bytes_no_mime_falls_back_to_octet_stream(self, model):
        content = b"some bytes"
        f = File(content=content, mime_type=None)
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_bytes.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_bytes.assert_called_once_with(mime_type="application/octet-stream", data=content)
            assert result == mock_part

    def test_bytes_no_mime_with_filename_guesses_type(self, model):
        content = b"col1,col2\na,b"
        f = File(content=content, mime_type=None, filename="data.csv")
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_bytes.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_bytes.assert_called_once_with(mime_type="text/csv", data=content)
            assert result == mock_part

    def test_filepath_with_mime(self, model, tmp_path):
        content = b"small pdf content"
        p = tmp_path / "doc.pdf"
        p.write_bytes(content)
        f = File(filepath=str(p), mime_type="application/pdf")
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_bytes.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_bytes.assert_called_once_with(mime_type="application/pdf", data=content)
            assert result == mock_part

    def test_filepath_no_mime_guesses_from_extension(self, model, tmp_path):
        content = b"x,y\n1,2"
        p = tmp_path / "data.csv"
        p.write_bytes(content)
        f = File(filepath=str(p))
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_bytes.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_bytes.assert_called_once_with(mime_type="text/csv", data=content)
            assert result == mock_part

    def test_filepath_nonexistent_returns_none(self, model):
        f = File(filepath="/nonexistent/file.pdf", mime_type="application/pdf")

        with patch("agno.models.google.gemini.Part"):
            result = model._format_file_for_message(f)
            assert result is None

    def test_url_with_mime_uses_from_uri(self, model):
        f = File(url="https://example.com/doc.pdf", mime_type="application/pdf")
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_uri.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_uri.assert_called_once_with(
                file_uri="https://example.com/doc.pdf", mime_type="application/pdf"
            )
            assert result == mock_part

    def test_url_no_mime_downloads_content(self, model):
        f = File(url="https://example.com/doc.pdf")
        mock_part = MagicMock()

        with (
            patch("agno.models.google.gemini.Part") as MockPart,
            patch.object(
                type(f), "file_url_content", new_callable=PropertyMock, return_value=(b"downloaded", "application/pdf")
            ),
        ):
            MockPart.from_bytes.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"downloaded")
            assert result == mock_part

    def test_gcs_uri_with_mime(self, model):
        f = File(url="gs://bucket/doc.pdf", mime_type="application/pdf")
        mock_part = MagicMock()

        with patch("agno.models.google.gemini.Part") as MockPart:
            MockPart.from_uri.return_value = mock_part
            result = model._format_file_for_message(f)

            MockPart.from_uri.assert_called_once_with(file_uri="gs://bucket/doc.pdf", mime_type="application/pdf")
            assert result == mock_part
