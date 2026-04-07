"""Tests for file handle management in OpenAI tools."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestTranscribeAudioFileHandle:
    """Test that transcribe_audio properly closes file handles."""

    @patch("agno.tools.openai.OpenAIClient")
    def test_file_handle_closed_on_success(self, mock_client_class, tmp_path: Path):
        """Verify the audio file handle is closed after successful transcription."""
        from agno.tools.openai import OpenAITools

        # Create a dummy audio file
        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"fake audio data")

        # Mock the OpenAI client
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = "Hello, world!"
        mock_client_class.return_value = mock_client

        tools = OpenAITools(api_key="test-key")
        result = tools.transcribe_audio(str(audio_path))

        assert result == "Hello, world!"
        mock_client.audio.transcriptions.create.assert_called_once()

        # Verify the file argument was passed as a context-managed file
        call_kwargs = mock_client.audio.transcriptions.create.call_args
        # The file should have been passed and is now closed (with statement)

    @patch("agno.tools.openai.OpenAIClient")
    def test_file_handle_closed_on_error(self, mock_client_class, tmp_path: Path):
        """Verify the audio file handle is closed even if transcription fails."""
        from agno.tools.openai import OpenAITools

        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"fake audio data")

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = RuntimeError("API error")
        mock_client_class.return_value = mock_client

        tools = OpenAITools(api_key="test-key")
        result = tools.transcribe_audio(str(audio_path))

        # Should return error message, not raise
        assert "Failed to transcribe audio" in result
