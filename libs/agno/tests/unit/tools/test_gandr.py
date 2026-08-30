"""Unit tests for Gandr tools."""

from unittest.mock import MagicMock, patch

import pytest

from agno.agent import Agent
from agno.media import Audio
from agno.tools.function import ToolResult
from agno.tools.gandr import MAX_INPUT_CHARACTERS, GandrTools


@pytest.fixture
def mock_response():
    """Create a mock httpx response carrying audio bytes."""
    response = MagicMock()
    response.content = b"audio data"
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def gandr_tools():
    """Create GandrTools instance with the API key set via environment."""
    with patch.dict("os.environ", {"GANDR_API_KEY": "test_key"}):
        return GandrTools()


# Mock agent fixture
@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    return agent


def test_init_with_api_key():
    """Test initialization with API key."""
    tools = GandrTools(api_key="test_key")
    assert tools.api_key == "test_key"
    # Check defaults are set
    assert tools.model_id == "tts-1"
    assert tools.default_voice == "gandr-mia"
    assert tools.response_format == "mp3"
    assert tools.base_url == "https://tts.gandr.ai"


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch.dict("os.environ", {"GANDR_API_KEY": "env_key"}):
        tools = GandrTools()
        assert tools.api_key == "env_key"


def test_init_override_defaults():
    """Test initialization overriding default voice and format."""
    tools = GandrTools(api_key="test_key", default_voice="gandr-leo", response_format="wav")
    assert tools.default_voice == "gandr-leo"
    assert tools.response_format == "wav"


def test_init_missing_api_key():
    """Test initialization with missing API key."""
    # Patch getenv where it's imported in the tools module
    with patch("agno.tools.gandr.getenv", return_value=None), pytest.raises(ValueError):
        GandrTools()


def test_feature_registration():
    """Test that features are correctly registered based on flags."""
    with patch.dict("os.environ", {"GANDR_API_KEY": "dummy"}):
        # Test with TTS enabled (default)
        tools = GandrTools()
        assert len(tools.functions) == 1
        assert "text_to_speech" in tools.functions

        # Test with all disabled
        tools = GandrTools(enable_text_to_speech=False)
        assert len(tools.functions) == 0


def test_text_to_speech(gandr_tools, mock_agent, mock_response):
    """Test text-to-speech functionality creates artifact."""
    with patch("agno.tools.gandr.httpx.post", return_value=mock_response) as mock_post:
        result = gandr_tools.text_to_speech(agent=mock_agent, text="Hello world")

    # Verify request arguments
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[0][0] == "https://tts.gandr.ai/v1/audio/speech"
    call_kwargs = call_args[1]
    assert call_kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert call_kwargs["json"]["model"] == gandr_tools.model_id  # Check defaults used
    assert call_kwargs["json"]["input"] == "Hello world"
    assert call_kwargs["json"]["voice"] == gandr_tools.default_voice  # Check defaults used
    assert call_kwargs["json"]["response_format"] == "mp3"

    # Verify ToolResult is returned
    assert isinstance(result, ToolResult)
    assert result.content == "Audio generated and attached successfully."
    assert result.audios is not None
    assert len(result.audios) == 1

    # Check artifact content
    audio_artifact = result.audios[0]
    assert isinstance(audio_artifact, Audio)
    assert audio_artifact.mime_type == "audio/mpeg"
    expected_content = b"audio data"
    assert audio_artifact.content == expected_content


def test_text_to_speech_overrides(gandr_tools, mock_agent, mock_response):
    """Test voice and response_format overrides are passed through."""
    with patch("agno.tools.gandr.httpx.post", return_value=mock_response) as mock_post:
        result = gandr_tools.text_to_speech(
            agent=mock_agent,
            text="Hello world",
            voice="gandr-ava",
            response_format="pcm",
        )

    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["voice"] == "gandr-ava"
    assert call_kwargs["json"]["response_format"] == "pcm"

    # pcm responses are headerless s16le mono at 24000 Hz
    assert isinstance(result, ToolResult)
    assert result.audios is not None
    assert result.audios[0].mime_type == "audio/pcm"


def test_text_to_speech_input_too_long(gandr_tools, mock_agent):
    """Test the client side input length validation."""
    with patch("agno.tools.gandr.httpx.post") as mock_post:
        result = gandr_tools.text_to_speech(agent=mock_agent, text="a" * (MAX_INPUT_CHARACTERS + 1))

    # No request is made for oversized input
    mock_post.assert_not_called()
    assert isinstance(result, ToolResult)
    assert result.audios is None
    assert str(MAX_INPUT_CHARACTERS) in result.content
    assert "Split the text into shorter requests." in result.content


def test_text_to_speech_error(gandr_tools, mock_agent):
    """Test error handling for text_to_speech."""
    with patch("agno.tools.gandr.httpx.post", side_effect=Exception("TTS API Error")):
        result = gandr_tools.text_to_speech(agent=mock_agent, text="Error test")

    # Verify ToolResult is returned with error message
    assert isinstance(result, ToolResult)
    assert result.content == "Error generating speech: TTS API Error"
    assert result.audios is None
