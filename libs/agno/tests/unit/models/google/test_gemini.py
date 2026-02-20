import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from agno.media import File
from agno.models.google.gemini import Gemini


def test_gemini_get_client_with_credentials_vertexai():
    """Test that credentials are correctly passed to the client when vertexai is True."""
    mock_credentials = MagicMock()
    model = Gemini(vertexai=True, project_id="test-project", location="test-location", credentials=mock_credentials)

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        # Verify credentials were passed to the client
        _, kwargs = mock_client_cls.call_args
        assert kwargs["credentials"] == mock_credentials
        assert kwargs["vertexai"] is True
        assert kwargs["project"] == "test-project"
        assert kwargs["location"] == "test-location"


def test_gemini_get_client_without_credentials_vertexai():
    """Test that client is initialized without credentials when not provided in vertexai mode."""
    model = Gemini(vertexai=True, project_id="test-project", location="test-location")

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        # Verify credentials were NOT passed to the client
        _, kwargs = mock_client_cls.call_args
        assert "credentials" not in kwargs
        assert kwargs["vertexai"] is True


def test_gemini_get_client_ai_studio_mode():
    """Test that credentials are NOT passed in Google AI Studio mode (non-vertexai)."""
    mock_credentials = MagicMock()
    # Even if credentials are provided, they shouldn't be passed if vertexai=False
    model = Gemini(vertexai=False, api_key="test-api-key", credentials=mock_credentials)

    with patch("agno.models.google.gemini.genai.Client") as mock_client_cls:
        model.get_client()

        # Verify credentials were NOT passed to the client
        _, kwargs = mock_client_cls.call_args
        assert "credentials" not in kwargs
        assert "api_key" in kwargs
        assert kwargs.get("vertexai") is not True


class TestFormatFileForMessage:
    def _make_model(self):
        model = Gemini(api_key="test-key")
        return model

    @patch("agno.models.google.gemini.Part")
    def test_bytes_with_mime_type(self, mock_part):
        model = self._make_model()
        f = File(content=b"hello", mime_type="text/plain")
        model._format_file_for_message(f)
        mock_part.from_bytes.assert_called_once_with(mime_type="text/plain", data=b"hello")

    @patch("agno.models.google.gemini.Part")
    def test_bytes_without_mime_type_guesses_from_filename(self, mock_part):
        model = self._make_model()
        f = File(content=b"data", filename="report.pdf")
        f.mime_type = None
        model._format_file_for_message(f)
        mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"data")

    @patch("agno.models.google.gemini.Part")
    def test_bytes_without_mime_type_or_filename_falls_back(self, mock_part):
        model = self._make_model()
        f = File(content=b"data")
        f.mime_type = None
        model._format_file_for_message(f)
        mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"data")

    @patch("agno.models.google.gemini.Part")
    def test_gcs_uri_without_mime_type(self, mock_part):
        model = self._make_model()
        f = File(url="gs://bucket/file.csv")
        f.mime_type = None
        model._format_file_for_message(f)
        mock_part.from_uri.assert_called_once_with(file_uri="gs://bucket/file.csv", mime_type="text/csv")

    @patch("agno.models.google.gemini.Part")
    def test_https_url_with_mime_type_sends_as_uri(self, mock_part):
        model = self._make_model()
        f = File(url="https://example.com/report.pdf", mime_type="application/pdf")
        model._format_file_for_message(f)
        mock_part.from_uri.assert_called_once_with(
            file_uri="https://example.com/report.pdf", mime_type="application/pdf"
        )

    @patch("agno.models.google.gemini.Part")
    def test_https_url_without_mime_type_falls_through_to_download(self, mock_part):
        model = self._make_model()
        f = File(url="https://example.com/report.pdf")
        f.mime_type = None
        # Mock the download property to return content with detected MIME
        with patch.object(
            type(f), "file_url_content", new_callable=lambda: property(lambda self: (b"pdf-data", "application/pdf"))
        ):
            model._format_file_for_message(f)
        mock_part.from_uri.assert_not_called()
        mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"pdf-data")

    @patch("agno.models.google.gemini.Part")
    def test_local_file_without_mime_type(self, mock_part):
        model = self._make_model()
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"hello world")
            tmp.flush()
            f = File(filepath=tmp.name)
            f.mime_type = None
            model._format_file_for_message(f)
            mock_part.from_bytes.assert_called_once_with(mime_type="text/plain", data=b"hello world")
            Path(tmp.name).unlink()

    @patch("agno.models.google.gemini.Part")
    def test_local_file_without_mime_type_or_extension_falls_back(self, mock_part):
        model = self._make_model()
        with tempfile.NamedTemporaryFile(suffix="", delete=False) as tmp:
            tmp.write(b"binary data")
            tmp.flush()
            f = File(filepath=tmp.name)
            f.mime_type = None
            model._format_file_for_message(f)
            mock_part.from_bytes.assert_called_once_with(mime_type="application/pdf", data=b"binary data")
            Path(tmp.name).unlink()
