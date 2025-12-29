"""Tests for OpenAI Responses API file upload functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.media import File
from agno.models.message import Message
from agno.models.openai.responses import OpenAIResponses


class TestFileUploadMethods:
    """Test the file upload helper methods."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock OpenAI client."""
        return MagicMock()

    @pytest.fixture
    def model(self, mock_client):
        """Create a test OpenAIResponses model instance."""
        model_instance = OpenAIResponses(id="gpt-4o", api_key="test-key")
        model_instance.get_client = Mock(return_value=mock_client)
        return model_instance

    def test_upload_file_with_purpose_url(self, model, mock_client):
        """Test uploading a file from URL with specified purpose."""
        # Mock the file upload response
        mock_response = Mock()
        mock_response.id = "file-123"
        mock_client.files.create.return_value = mock_response

        # Create a file with URL
        file = File(url="https://example.com/test.pdf")

        # Mock file_url_content to return test data
        with patch.object(File, "file_url_content", return_value=(b"test content", "application/pdf")):
            file_id = model._upload_file_with_purpose(file, "user_data")

        assert file_id == "file-123"
        mock_client.files.create.assert_called_once()
        call_args = mock_client.files.create.call_args
        assert call_args[1]["purpose"] == "user_data"

    def test_upload_file_with_purpose_filepath(self, model, mock_client):
        """Test uploading a file from filepath with specified purpose."""
        # Mock the file upload response
        mock_response = Mock()
        mock_response.id = "file-456"
        mock_client.files.create.return_value = mock_response

        # Create a temporary file
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            f.write(b"test file content")
            temp_path = Path(f.name)

        try:
            # Create a file with filepath
            file = File(filepath=temp_path)

            file_id = model._upload_file_with_purpose(file, "assistants")

            assert file_id == "file-456"
            mock_client.files.create.assert_called_once()
            call_args = mock_client.files.create.call_args
            assert call_args[1]["purpose"] == "assistants"
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()

    def test_upload_file_with_purpose_content(self, model, mock_client):
        """Test uploading a file from raw content with specified purpose."""
        # Mock the file upload response
        mock_response = Mock()
        mock_response.id = "file-789"
        mock_client.files.create.return_value = mock_response

        # Create a file with content
        file = File(content=b"raw content bytes")

        file_id = model._upload_file_with_purpose(file, "user_data")

        assert file_id == "file-789"
        mock_client.files.create.assert_called_once()
        call_args = mock_client.files.create.call_args
        assert call_args[1]["purpose"] == "user_data"

    def test_upload_file_with_purpose_returns_none_for_invalid_url(self, model, mock_client):
        """Test that upload returns None when URL content is not available."""
        # Create a file with URL
        file = File(url="https://example.com/test.pdf")

        # Mock file_url_content property to return None (tuple with None)
        with patch.object(type(file), "file_url_content", new_callable=lambda: property(lambda self: None)):
            file_id = model._upload_file_with_purpose(file, "user_data")

        assert file_id is None
        mock_client.files.create.assert_not_called()

    def test_upload_file_with_purpose_raises_for_missing_file(self, model, mock_client):
        """Test that upload raises ValueError when filepath doesn't exist."""
        # Create a file with non-existent filepath
        file = File(filepath="/nonexistent/path/file.txt")

        with pytest.raises(ValueError, match="File not found"):
            model._upload_file_with_purpose(file, "assistants")

        mock_client.files.create.assert_not_called()

    def test_upload_file_calls_helper_with_assistants(self, model, mock_client):
        """Test that _upload_file calls helper with 'assistants' purpose."""
        mock_response = Mock()
        mock_response.id = "file-abc"
        mock_client.files.create.return_value = mock_response

        file = File(content=b"test content")

        file_id = model._upload_file(file)

        assert file_id == "file-abc"
        call_args = mock_client.files.create.call_args
        assert call_args[1]["purpose"] == "assistants"

    def test_upload_file_for_input_calls_helper_with_user_data(self, model, mock_client):
        """Test that _upload_file_for_input calls helper with 'user_data' purpose."""
        mock_response = Mock()
        mock_response.id = "file-xyz"
        mock_client.files.create.return_value = mock_response

        file = File(content=b"test content")

        file_id = model._upload_file_for_input(file)

        assert file_id == "file-xyz"
        call_args = mock_client.files.create.call_args
        assert call_args[1]["purpose"] == "user_data"


class TestFileHandlingInFormatMessages:
    """Test file handling in the _format_messages method."""

    @pytest.fixture
    def model(self):
        """Create a test OpenAIResponses model instance."""
        with patch.object(OpenAIResponses, "get_client"):
            return OpenAIResponses(id="gpt-4o", api_key="test-key")

    def test_format_messages_with_files_converts_to_input_file_blocks(self, model):
        """Test that files in messages are converted to input_file content blocks."""
        # Mock the upload method
        with patch.object(model, "_upload_file_for_input", return_value="file-123"):
            file = File(content=b"test pdf content", filename="test.pdf")
            message = Message(role="user", content="Please analyze this document", files=[file])

            formatted = model._format_messages([message])

            # Should have one formatted message
            assert len(formatted) == 1
            msg = formatted[0]

            # Content should be an array with input_file and input_text
            assert isinstance(msg["content"], list)
            assert len(msg["content"]) == 2

            # File should be first
            assert msg["content"][0]["type"] == "input_file"
            assert msg["content"][0]["file_id"] == "file-123"

            # Text should be second
            assert msg["content"][1]["type"] == "input_text"
            assert msg["content"][1]["text"] == "Please analyze this document"

    def test_format_messages_with_multiple_files(self, model):
        """Test that multiple files are all added to the content blocks."""
        # Mock the upload method to return different IDs
        file_ids = ["file-1", "file-2", "file-3"]
        with patch.object(model, "_upload_file_for_input", side_effect=file_ids):
            files = [
                File(content=b"content1", filename="file1.pdf"),
                File(content=b"content2", filename="file2.pdf"),
                File(content=b"content3", filename="file3.pdf"),
            ]
            message = Message(role="user", content="Analyze all documents", files=files)

            formatted = model._format_messages([message])

            msg = formatted[0]
            assert isinstance(msg["content"], list)
            assert len(msg["content"]) == 4  # 3 files + 1 text

            # Check all files are present (in reverse order due to insert(0))
            assert msg["content"][0]["type"] == "input_file"
            assert msg["content"][0]["file_id"] == "file-3"
            assert msg["content"][1]["type"] == "input_file"
            assert msg["content"][1]["file_id"] == "file-2"
            assert msg["content"][2]["type"] == "input_file"
            assert msg["content"][2]["file_id"] == "file-1"
            assert msg["content"][3]["type"] == "input_text"

    def test_format_messages_with_files_and_images(self, model):
        """Test that files and images are both handled correctly."""
        from agno.media import Image

        with patch.object(model, "_upload_file_for_input", return_value="file-456"):
            file = File(content=b"document content", filename="doc.pdf")
            image = Image(url="https://example.com/image.png")
            message = Message(role="user", content="Compare these", files=[file], images=[image])

            formatted = model._format_messages([message])

            msg = formatted[0]
            assert isinstance(msg["content"], list)

            # Should have file, text, and image blocks (at least 2 blocks total - file + text minimum)
            file_blocks = [b for b in msg["content"] if b.get("type") == "input_file"]
            text_blocks = [b for b in msg["content"] if b.get("type") == "input_text"]

            # Verify files are uploaded and added
            assert len(file_blocks) == 1
            assert file_blocks[0]["file_id"] == "file-456"
            assert len(text_blocks) == 1

            # Content should have at least 2 blocks (file + text, images may or may not be added depending on implementation)
            assert len(msg["content"]) >= 2

    def test_format_messages_skips_upload_failure(self, model):
        """Test that when file upload fails (returns None), the file is skipped."""
        # Mock upload to return None (failure)
        with patch.object(model, "_upload_file_for_input", return_value=None):
            file = File(content=b"test content", filename="test.pdf")
            message = Message(role="user", content="Analyze this", files=[file])

            formatted = model._format_messages([message])

            msg = formatted[0]
            # Content should only have text since file upload failed
            if isinstance(msg["content"], list):
                assert len(msg["content"]) == 1
                assert msg["content"][0]["type"] == "input_text"
            else:
                # If not a list, it should be just the text content
                assert msg["content"] == "Analyze this"

    def test_format_messages_without_files_unchanged(self, model):
        """Test that messages without files are formatted normally."""
        message = Message(role="user", content="Hello, world!")

        formatted = model._format_messages([message])

        assert len(formatted) == 1
        msg = formatted[0]
        assert msg["role"] == "user"
        assert msg["content"] == "Hello, world!"
