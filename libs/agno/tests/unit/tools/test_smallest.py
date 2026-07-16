"""Unit tests for Smallest AI tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.agent import Agent
from agno.tools.function import ToolResult
from agno.tools.smallest import SMALLEST_TTS_URL, SMALLEST_VOICES_URLS, SmallestTools


@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    return agent


@pytest.fixture
def smallest_tools():
    """Create SmallestTools instance with a test API key."""
    with patch.dict("os.environ", {"SMALLEST_API_KEY": "test_key"}):
        return SmallestTools()


def test_init_with_api_key():
    """Test initialization with API key."""
    tools = SmallestTools(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.model == "lightning_v3.1"
    assert tools.voice_id == "magnus"
    assert tools.sample_rate == 24000
    assert tools.speed == 1.0
    assert tools.output_format == "wav"


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch.dict("os.environ", {"SMALLEST_API_KEY": "env_key"}):
        tools = SmallestTools()
        assert tools.api_key == "env_key"


def test_init_missing_api_key():
    """Test initialization with missing API key logs an error but does not raise."""
    with patch("agno.tools.smallest.getenv", return_value=None):
        tools = SmallestTools()
        assert tools.api_key is None


def test_init_override_defaults():
    """Test initialization overriding defaults with the Pro model."""
    tools = SmallestTools(
        api_key="test_key",
        voice_id="meher",
        model="lightning_v3.1_pro",
        sample_rate=44100,
        speed=1.2,
        output_format="mp3",
    )
    assert tools.voice_id == "meher"
    assert tools.model == "lightning_v3.1_pro"
    assert tools.sample_rate == 44100
    assert tools.speed == 1.2
    assert tools.output_format == "mp3"


def test_feature_registration(smallest_tools):
    """Test that the expected tools are registered."""
    assert "get_voices" in smallest_tools.functions
    assert "text_to_speech" in smallest_tools.functions


def test_feature_registration_disabled():
    """Test disabling tools."""
    tools = SmallestTools(api_key="test_key", enable_get_voices=False)
    assert "get_voices" not in tools.functions
    assert "text_to_speech" in tools.functions


def test_text_to_speech_success(smallest_tools, mock_agent):
    """Test successful text-to-speech generation."""
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.smallest.httpx.post", return_value=mock_response) as mock_post:
        result = smallest_tools.text_to_speech(mock_agent, "Hello world")

    assert isinstance(result, ToolResult)
    assert result.content == "Audio generated successfully"
    assert result.audios is not None
    assert len(result.audios) == 1
    assert result.audios[0].content == b"audio data"
    assert result.audios[0].mime_type == "audio/wav"

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == SMALLEST_TTS_URL
    assert kwargs["json"]["text"] == "Hello world"
    assert kwargs["json"]["voice_id"] == "magnus"
    assert kwargs["json"]["model"] == "lightning_v3.1"
    assert kwargs["json"]["sample_rate"] == 24000
    assert kwargs["json"]["output_format"] == "wav"
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["headers"]["X-Source"] == "agno"


def test_text_to_speech_voice_override(smallest_tools, mock_agent):
    """Test text-to-speech with a per-call voice override."""
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.smallest.httpx.post", return_value=mock_response) as mock_post:
        smallest_tools.text_to_speech(mock_agent, "Hello world", voice_id="custom_voice")

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["voice_id"] == "custom_voice"


def test_text_to_speech_language_param(mock_agent):
    """Test that language defaults to en and can be overridden."""
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.smallest.httpx.post", return_value=mock_response) as mock_post:
        SmallestTools(api_key="test_key").text_to_speech(mock_agent, "Hello world")
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["language"] == "en"

        SmallestTools(api_key="test_key", model="lightning_v3.1_pro", language="de").text_to_speech(
            mock_agent, "Hallo Welt"
        )
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["language"] == "de"


def test_text_to_speech_mp3_mime_type(mock_agent):
    """Test that mp3 output format sets the correct mime type."""
    tools = SmallestTools(api_key="test_key", output_format="mp3")
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.smallest.httpx.post", return_value=mock_response) as mock_post:
        result = tools.text_to_speech(mock_agent, "Hello world")

    assert result.audios[0].mime_type == "audio/mpeg"
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Accept"] == "audio/mpeg"


def test_text_to_speech_saves_to_target_directory(mock_agent, tmp_path):
    """Test that audio is saved to disk when target_directory is set."""
    target_dir = tmp_path / "audio"
    tools = SmallestTools(api_key="test_key", target_directory=str(target_dir))
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.smallest.httpx.post", return_value=mock_response):
        tools.text_to_speech(mock_agent, "Hello world")

    saved_files = list(target_dir.glob("*.wav"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"audio data"


def test_text_to_speech_error(smallest_tools, mock_agent):
    """Test text-to-speech error handling."""
    with patch("agno.tools.smallest.httpx.post", side_effect=Exception("API error")):
        result = smallest_tools.text_to_speech(mock_agent, "Hello world")

    assert isinstance(result, ToolResult)
    assert "Error" in result.content
    assert not result.audios


def test_get_voices_success(smallest_tools):
    """Test successful voice listing."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "voices": [
            {
                "voiceId": "magnus",
                "displayName": "Magnus",
                "tags": {"gender": "male", "accent": "american", "language": ["en"]},
            },
            {
                "voiceId": "meher",
                "displayName": "Meher",
                "tags": {"gender": "female", "accent": "indian", "language": ["en", "hi"]},
            },
        ]
    }

    with patch("agno.tools.smallest.httpx.get", return_value=mock_response) as mock_get:
        result = smallest_tools.get_voices()

    args, kwargs = mock_get.call_args
    assert args[0] == SMALLEST_VOICES_URLS["lightning_v3.1"]
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["headers"]["X-Source"] == "agno"

    voices = json.loads(result)
    assert len(voices) == 2
    assert voices[0]["id"] == "magnus"
    assert voices[1]["id"] == "meher"
    assert voices[1]["languages"] == ["en", "hi"]


def test_get_voices_list_response(smallest_tools):
    """Test voice listing when the API returns a bare list."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = [{"id": "magnus", "name": "Magnus"}]

    with patch("agno.tools.smallest.httpx.get", return_value=mock_response):
        result = smallest_tools.get_voices()

    voices = json.loads(result)
    assert len(voices) == 1
    assert voices[0]["id"] == "magnus"
    assert voices[0]["name"] == "Magnus"


def test_get_voices_pro_model_uses_pro_catalog():
    """Test that the Pro model queries the Pro voice catalog endpoint."""
    tools = SmallestTools(api_key="test_key", model="lightning_v3.1_pro", voice_id="meher")
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"voices": []}

    with patch("agno.tools.smallest.httpx.get", return_value=mock_response) as mock_get:
        tools.get_voices()

    args, _ = mock_get.call_args
    assert args[0] == SMALLEST_VOICES_URLS["lightning_v3.1_pro"]


def test_get_voices_error(smallest_tools):
    """Test voice listing error handling."""
    with patch("agno.tools.smallest.httpx.get", side_effect=Exception("API error")):
        result = smallest_tools.get_voices()

    assert result.startswith("Error")
