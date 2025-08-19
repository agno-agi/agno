# aac

import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.tools.models.groq import GroqTools

MOCK_API_KEY = "test-groq-api-key"


@pytest.fixture(autouse=True)
def mock_groq_env_key(monkeypatch):
    """Mock the GROQ_API_KEY environment variable."""
    monkeypatch.setenv("GROQ_API_KEY", MOCK_API_KEY)


@pytest.fixture
def mock_groq_client():
    """Fixture to mock the GroqClient."""
    with patch("agno.tools.models.groq.GroqClient") as mock_client_constructor:
        mock_client_instance = MagicMock()
        mock_client_constructor.return_value = mock_client_instance

        # Mock audio endpoints
        mock_client_instance.audio = MagicMock()
        mock_client_instance.audio.transcriptions = MagicMock()
        mock_client_instance.audio.translations = MagicMock()
        mock_client_instance.audio.speech = MagicMock()

        # Setup default return values for create methods
        mock_client_instance.audio.transcriptions.create.return_value = "Mocked transcription text"

        mock_client_instance.audio.translations.create.return_value = "Mocked translation text"

        mock_speech_response = MagicMock()
        mock_speech_response.read.return_value = b"mock_audio_bytes"
        mock_client_instance.audio.speech.create.return_value = mock_speech_response

        yield mock_client_instance


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
def test_groq_tools_init_success(mock_toolkit_init, mock_groq_client):
    """Test successful initialization with API key from env."""
    tools = GroqTools()
    assert tools.api_key == MOCK_API_KEY
    assert tools.transcription_model == "whisper-large-v3"
    assert tools.translation_model == "whisper-large-v3"
    assert tools.tts_model == "playai-tts"
    assert tools.tts_voice == "Chip-PlayAI"
    assert tools.tts_format == "wav"
    mock_groq_client  # Ensure fixture is used

    # Check tool registration by looking at the tools attribute
    # NOTE: This check might be invalid now as we mocked the base init
    #       which handles registration. Adjust based on how registration
    #       is actually handled/tested if needed separately.
    # registered_tool_names = [tool.name for tool in tools.tools]
    # assert "transcribe_audio" in registered_tool_names
    # assert "translate_audio" in registered_tool_names
    # assert "generate_speech" in registered_tool_names


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
def test_groq_tools_init_no_api_key(mock_toolkit_init, monkeypatch):
    """Test initialization failure when API key is not provided or found."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # The ValueError should still be raised by GroqTools.__init__ before super() potentially
    with pytest.raises(ValueError, match="GROQ_API_KEY not set"):
        GroqTools(api_key=None)


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
def test_groq_tools_init_with_params(mock_toolkit_init, mock_groq_client):
    """Test initialization with custom parameters."""
    tools = GroqTools(
        api_key="custom-key",
        transcription_model="whisper-large-v3-turbo",
        translation_model="custom-trans",
        tts_model="custom-tts",
        tts_voice="CustomVoice",
    )
    assert tools.api_key == "custom-key"
    assert tools.transcription_model == "whisper-large-v3-turbo"
    assert tools.translation_model == "custom-trans"
    assert tools.tts_model == "custom-tts"
    assert tools.tts_voice == "CustomVoice"
    mock_groq_client  # Ensure fixture is used


# --- Test transcribe_audio ---


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=True)
def test_transcribe_audio_local_file(mock_exists, mock_toolkit_init, mock_groq_client):
    """Test transcribe_audio with a local file path."""
    tools = GroqTools()
    mock_file_path = "/path/to/audio.wav"
    expected_transcript = "Mocked transcription text"

    mock_groq_client.audio.transcriptions.create.return_value = expected_transcript

    # Mock open to simulate reading the file
    with patch("builtins.open", mock_open(read_data=b"dummy audio data")) as mock_file:
        result = tools.transcribe_audio(mock_file_path)

    assert result == expected_transcript
    mock_groq_client.audio.transcriptions.create.assert_called_once_with(
        file=(os.path.basename(mock_file_path), b"dummy audio data"),
        model=tools.transcription_model,
        response_format="text",
    )
    mock_file.assert_called_once_with(mock_file_path, "rb")


@patch("groq.resources.audio.Transcriptions.create", side_effect=Exception("API Error"))
@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=True)
def test_transcribe_audio_error(mock_exists, mock_toolkit_init, mock_transcribe_create):
    """Test transcribe_audio handling API errors."""
    tools = GroqTools()
    mock_file_path = "/path/to/audio.wav"

    with patch("builtins.open", mock_open(read_data=b"dummy audio data")):
        result = tools.transcribe_audio(mock_file_path)

    assert "Failed to transcribe audio source" in result
    assert "API Error" in result


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=False)
def test_transcribe_audio_url(mock_exists, mock_toolkit_init, mock_groq_client):
    """Test transcribe_audio with a URL."""
    tools = GroqTools()
    mock_url = "https://example.com/audio.wav"
    expected_transcript = "Mocked transcription text"

    mock_groq_client.audio.transcriptions.create.return_value = expected_transcript

    result = tools.transcribe_audio(mock_url)

    assert result == expected_transcript
    mock_groq_client.audio.transcriptions.create.assert_called_once_with(
        url=mock_url,
        model=tools.transcription_model,
        response_format="text",
    )


@patch("groq.resources.audio.Transcriptions.create", side_effect=Exception("API Error"))
@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=False)  # Simulate URL case
def test_transcribe_audio_error_url(mock_exists, mock_toolkit_init, mock_transcribe_create):
    """Test transcribe_audio handling API errors with URL."""
    tools = GroqTools()
    mock_url = "https://example.com/audio.wav"

    result = tools.transcribe_audio(mock_url)

    assert "Failed to transcribe audio source" in result
    assert "API Error" in result


# --- Test translate_audio ---


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=True)
def test_translate_audio_local_file(mock_exists, mock_toolkit_init, mock_groq_client):
    """Test translate_audio with a local file path."""
    tools = GroqTools()
    mock_file_path = "/path/to/foreign_audio.mp3"
    expected_translation = "Mocked translation text"

    mock_groq_client.audio.translations.create.return_value = expected_translation

    with patch("builtins.open", mock_open(read_data=b"dummy audio data")) as mock_file:
        result = tools.translate_audio(mock_file_path)

    assert result == expected_translation
    mock_groq_client.audio.translations.create.assert_called_once_with(
        file=(os.path.basename(mock_file_path), b"dummy audio data"),
        model=tools.translation_model,
        response_format="text",
    )
    mock_file.assert_called_once_with(mock_file_path, "rb")


@patch("groq.resources.audio.Translations.create", side_effect=Exception("API Error"))
@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=True)
def test_translate_audio_error(mock_exists, mock_toolkit_init, mock_translate_create):
    """Test translate_audio handling API errors."""
    tools = GroqTools()
    mock_file_path = "/path/to/foreign_audio.mp3"

    with patch("builtins.open", mock_open(read_data=b"dummy audio data")):
        result = tools.translate_audio(mock_file_path)

    assert "Failed to translate audio source" in result
    assert "API Error" in result


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=False)
def test_translate_audio_url(mock_exists, mock_toolkit_init, mock_groq_client):
    """Test translate_audio with a URL."""
    tools = GroqTools()
    mock_url = "https://example.com/foreign_audio.mp3"
    expected_translation = "Mocked translation text"

    mock_groq_client.audio.translations.create.return_value = expected_translation

    result = tools.translate_audio(mock_url)

    assert result == expected_translation
    mock_groq_client.audio.translations.create.assert_called_once_with(
        url=mock_url,
        model=tools.translation_model,
        response_format="text",
    )


@patch("groq.resources.audio.Translations.create", side_effect=Exception("API Error"))
@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
@patch("os.path.exists", return_value=False)  # Simulate URL case
def test_translate_audio_error_url(mock_exists, mock_toolkit_init, mock_translate_create):
    """Test translate_audio handling API errors with URL."""
    tools = GroqTools()
    mock_url = "https://example.com/foreign_audio.mp3"

    result = tools.translate_audio(mock_url)

    assert "Failed to translate audio source" in result
    assert "API Error" in result


# --- Test generate_speech ---


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
def test_generate_speech_success(mock_toolkit_init, mock_groq_client):
    """Test generate_speech successfully creates an audio artifact."""
    tools = GroqTools()
    mock_agent = MagicMock(spec=Agent)
    mock_agent.add_audio = MagicMock()
    text_input = "Hello, this is a test."

    # Mock the response object from client.audio.speech.create
    mock_speech_response = MagicMock()
    mock_speech_response.read.return_value = b"dummy_audio_bytes"
    mock_groq_client.audio.speech.create.return_value = mock_speech_response

    result = tools.generate_speech(agent=mock_agent, text_input=text_input)

    assert "Speech generated successfully with ID:" in result
    mock_groq_client.audio.speech.create.assert_called_once_with(
        model=tools.tts_model, voice=tools.tts_voice, input=text_input, response_format=tools.tts_format
    )
    # Check that add_audio was called on the agent
    mock_agent.add_audio.assert_called_once()
    # Optionally check the details of the artifact passed to add_audio
    call_args = mock_agent.add_audio.call_args[0][0]
    assert isinstance(call_args, AudioArtifact)
    assert call_args.mime_type == "audio/wav"
    assert isinstance(call_args.id, str)


@patch("agno.tools.toolkit.Toolkit.__init__", return_value=None)  # Mock base init
def test_generate_speech_error(mock_toolkit_init, mock_groq_client):
    """Test generate_speech handling API errors."""
    tools = GroqTools()
    mock_agent = MagicMock(spec=Agent)
    text_input = "This will fail."

    # Simulate an error during the API call
    mock_groq_client.audio.speech.create.side_effect = Exception("API Error")

    result = tools.generate_speech(agent=mock_agent, text_input=text_input)

    assert "Failed to generate speech with Groq" in result
    assert "API Error" in result
    mock_groq_client.audio.speech.create.assert_called_once_with(
        model=tools.tts_model, voice=tools.tts_voice, input=text_input, response_format=tools.tts_format
    )
    mock_agent.add_audio.assert_not_called()
