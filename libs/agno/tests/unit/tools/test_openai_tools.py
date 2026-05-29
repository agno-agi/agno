from unittest.mock import MagicMock, mock_open, patch

import pytest

from agno.tools.openai import OpenAITools


@pytest.fixture(autouse=True)
def openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-api-key")


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)
@patch("agno.tools.openai.OpenAIClient")
def test_transcribe_audio_closes_file(mock_client_cls, mock_toolkit_init):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = "transcript"
    mock_client_cls.return_value = mock_client

    opened = mock_open(read_data=b"audio")
    with patch("builtins.open", opened):
        result = OpenAITools().transcribe_audio("/tmp/audio.wav")

    assert result == "transcript"
    opened.return_value.close.assert_called_once()
    mock_client.audio.transcriptions.create.assert_called_once_with(
        model="whisper-1",
        file=opened.return_value,
        response_format="text",
    )


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)
@patch("agno.tools.openai.OpenAIClient")
def test_transcribe_audio_closes_file_on_api_error(mock_client_cls, mock_toolkit_init):
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = RuntimeError("api down")
    mock_client_cls.return_value = mock_client

    opened = mock_open(read_data=b"audio")
    with patch("builtins.open", opened):
        result = OpenAITools().transcribe_audio("/tmp/audio.wav")

    assert "Failed to transcribe audio: api down" == result
    opened.return_value.close.assert_called_once()
