"""Unit tests for OpenAITools."""

from unittest.mock import Mock, mock_open, patch

from agno.tools.openai import OpenAITools


def test_transcribe_audio_closes_file():
    """Test audio file handles are closed after transcription."""
    mocked_file = mock_open(read_data=b"audio")
    mock_client = Mock()
    mock_client.audio.transcriptions.create.return_value = "transcript"

    with (
        patch("agno.tools.openai.open", mocked_file),
        patch("agno.tools.openai.OpenAIClient", return_value=mock_client),
    ):
        tools = OpenAITools(api_key="test-key", enable_image_generation=False, enable_speech_generation=False)
        result = tools.transcribe_audio("test.wav")

    assert result == "transcript"
    mocked_file.assert_called_once_with("test.wav", "rb")
    mocked_file.return_value.__exit__.assert_called_once()
    mock_client.audio.transcriptions.create.assert_called_once_with(
        model="whisper-1",
        file=mocked_file.return_value.__enter__.return_value,
        response_format="text",
    )
