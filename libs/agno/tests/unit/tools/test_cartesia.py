"""Unit tests for Cartesia tools."""

import json

# import logging # Removed unused import
from base64 import b64encode  # Added for TTS test
from unittest.mock import MagicMock, patch  # Removed unused mock_open

import pytest

from agno.agent import Agent  # Added for TTS test
from agno.media import AudioArtifact  # Added for TTS test
from agno.tools.cartesia import CartesiaTools

# Import the specific logger instance used by the tool
# from agno.utils.log import logger as agno_logger_instance # Removed unused import


@pytest.fixture
def mock_cartesia_client():
    """Create a mock Cartesia client instance (not the class)."""
    mock_client = MagicMock()
    # Setup common mocks needed by remaining tools
    mock_client.voices = MagicMock()
    mock_client.tts = MagicMock()
    mock_client.localize = MagicMock()  # If localize_voice is tested

    # Mock the list method to return a mock pager
    mock_pager = MagicMock()
    # Configure mock voice objects to return strings for attributes
    mock_voice_obj1 = MagicMock()
    mock_voice_obj1.id = "voice1"
    mock_voice_obj1.name = "Voice One"
    mock_voice_obj1.description = "Desc 1"
    mock_voice_obj1.language = "en"

    mock_voice_obj2 = MagicMock()
    mock_voice_obj2.id = "voice2"
    mock_voice_obj2.name = "Voice Two"
    mock_voice_obj2.description = "Desc 2"
    mock_voice_obj2.language = "es"

    mock_pager.items = [mock_voice_obj1, mock_voice_obj2]
    mock_client.voices.list.return_value = mock_pager

    # Mock tts.bytes to return an iterator
    mock_client.tts.bytes.return_value = iter([b"audio data"])

    return mock_client


@pytest.fixture
def cartesia_tools(mock_cartesia_client):
    """Create CartesiaTools instance with mocked API client."""
    # Patch the Cartesia class during instantiation
    with patch("agno.tools.cartesia.cartesia.Cartesia") as mock_cartesia_class, patch.dict(
        "os.environ", {"CARTESIA_API_KEY": "test_key"}
    ):
        # Make the patched class return our mock client instance
        mock_cartesia_class.return_value = mock_cartesia_client
        tools = CartesiaTools()
        return tools


# Mock agent fixture
@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    agent.add_audio = MagicMock()
    return agent


def test_init_with_api_key(mock_cartesia_client):
    """Test initialization with API key."""
    with patch("agno.tools.cartesia.cartesia.Cartesia") as mock_cartesia_class:
        mock_cartesia_class.return_value = mock_cartesia_client
        tools = CartesiaTools(api_key="test_key")
        mock_cartesia_class.assert_called_once_with(api_key="test_key")
        assert tools.api_key == "test_key"
        # Check default model/voice IDs are set
        assert tools.model_id == "sonic-2"
        assert tools.default_voice_id == "78ab82d5-25be-4f7d-82b3-7ad64e5b85b2"


def test_init_with_env_var(mock_cartesia_client):
    """Test initialization with environment variable."""
    with patch("agno.tools.cartesia.cartesia.Cartesia") as mock_cartesia_class, patch.dict(
        "os.environ", {"CARTESIA_API_KEY": "env_key"}
    ), patch("os.getenv", return_value="env_key"):
        mock_cartesia_class.return_value = mock_cartesia_client
        tools = CartesiaTools()
        mock_cartesia_class.assert_called_once_with(api_key="env_key")
        assert tools.api_key == "env_key"
        assert tools.model_id == "sonic-2"
        assert tools.default_voice_id == "78ab82d5-25be-4f7d-82b3-7ad64e5b85b2"


def test_init_override_defaults(mock_cartesia_client):
    """Test initialization overriding default model/voice IDs."""
    with patch("agno.tools.cartesia.cartesia.Cartesia") as mock_cartesia_class, patch.dict(
        "os.environ", {"CARTESIA_API_KEY": "test_key"}
    ):
        mock_cartesia_class.return_value = mock_cartesia_client
        tools = CartesiaTools(model_id="override-model", default_voice_id="override-voice")
        mock_cartesia_class.assert_called_once_with(api_key="test_key")
        assert tools.model_id == "override-model"
        assert tools.default_voice_id == "override-voice"


def test_init_missing_api_key():
    """Test initialization with missing API key."""
    # Patch getenv where it's imported in the tools module
    with patch("agno.tools.cartesia.getenv", return_value=None), pytest.raises(ValueError):
        CartesiaTools()


def test_feature_registration(mock_cartesia_client):
    """Test that features are correctly registered based on flags."""
    with patch("agno.tools.cartesia.cartesia.Cartesia") as mock_cartesia_class, patch.dict(
        "os.environ", {"CARTESIA_API_KEY": "dummy"}
    ):
        mock_cartesia_class.return_value = mock_cartesia_client

        # Test with only TTS and List enabled (defaults)
        tools = CartesiaTools()
        assert len(tools.functions) == 2
        assert "text_to_speech" in tools.functions
        assert "list_voices" in tools.functions

        # Test with localize enabled as well
        tools = CartesiaTools(voice_localize_enabled=True)
        assert len(tools.functions) == 3
        assert "text_to_speech" in tools.functions
        assert "list_voices" in tools.functions
        assert "localize_voice" in tools.functions

        # Test with all disabled
        tools = CartesiaTools(
            text_to_speech_enabled=False,
            list_voices_enabled=False,
            voice_localize_enabled=False,
        )
        assert len(tools.functions) == 0


def test_list_voices(cartesia_tools, mock_cartesia_client):
    """Test listing voices correctly handles the pager and extracts data."""
    # Mock client already set up in fixture to return pager

    result_json_str = cartesia_tools.list_voices()
    result_data = json.loads(result_json_str)

    # Check the client method was called
    mock_cartesia_client.voices.list.assert_called_once_with()
    assert isinstance(result_data, list)
    assert len(result_data) == 2  # Based on mock_cartesia_client fixture

    # Check structure and content of the extracted data
    assert result_data[0]["id"] == "voice1"
    assert result_data[0]["name"] == "Voice One"
    assert result_data[0]["description"] == "Desc 1"
    assert result_data[0]["language"] == "en"
    assert result_data[1]["id"] == "voice2"
    assert result_data[1]["name"] == "Voice Two"
    assert result_data[1]["description"] == "Desc 2"
    assert result_data[1]["language"] == "es"


def test_list_voices_error(cartesia_tools, mock_cartesia_client):
    """Test error handling for list_voices."""
    mock_cartesia_client.voices.list.side_effect = Exception("List API Error")

    result_json_str = cartesia_tools.list_voices()
    result_data = json.loads(result_json_str)

    assert "error" in result_data
    assert "List API Error" in result_data["error"]
    assert "detail" in result_data


def test_text_to_speech(cartesia_tools, mock_cartesia_client, mock_agent):
    """Test text-to-speech functionality creates artifact."""
    # Mock client returns iterator with b"audio data"

    result = cartesia_tools.text_to_speech(
        agent=mock_agent,
        transcript="Hello world",
        # language="en",  # Removed: Language is no longer a parameter
    )

    # Verify TTS call arguments
    mock_cartesia_client.tts.bytes.assert_called_once()
    call_args = mock_cartesia_client.tts.bytes.call_args[1]  # Get kwargs

    assert call_args["model_id"] == cartesia_tools.model_id  # Check defaults used
    assert call_args["transcript"] == "Hello world"
    assert "voice" in call_args
    assert call_args["voice"]["mode"] == "id"
    assert call_args["voice"]["id"] == cartesia_tools.default_voice_id  # Check defaults used
    # assert call_args["language"] == "en"  # Removed assertion for language
    assert "output_format" in call_args

    # Verify hardcoded MP3 format
    output_format = call_args["output_format"]
    assert output_format["container"] == "mp3"
    assert output_format["sample_rate"] == 44100
    assert output_format["bit_rate"] == 128000  # Capped value used if default was > 192k
    assert output_format["encoding"] == "mp3"

    # Verify agent interaction
    mock_agent.add_audio.assert_called_once()
    # Check artifact content
    artifact_call_args = mock_agent.add_audio.call_args[0][0]
    assert isinstance(artifact_call_args, AudioArtifact)
    assert artifact_call_args.mime_type == "audio/mpeg"
    expected_base64 = b64encode(b"audio data").decode("utf-8")
    assert artifact_call_args.base64_audio == expected_base64

    # Verify return message
    assert result == "Audio generated and attached successfully."


def test_text_to_speech_error(cartesia_tools, mock_cartesia_client, mock_agent):
    """Test error handling for text_to_speech."""
    mock_cartesia_client.tts.bytes.side_effect = Exception("TTS API Error")

    result = cartesia_tools.text_to_speech(agent=mock_agent, transcript="Error test")

    mock_agent.add_audio.assert_not_called()
    assert result == "Error generating speech: TTS API Error"


# Keep localize_voice test if the method is potentially enabled/used
def test_localize_voice(cartesia_tools, mock_cartesia_client):
    """Test localizing a voice (assuming enabled)."""

    localized_voice_data = {
        "id": "localized_voice_id",
        "name": "Localized Voice",
        "language": "es",
        "description": "Voice localized to Spanish",
    }
    # Use the client from the specific tools instance
    mock_cartesia_client.voices.localize.return_value = localized_voice_data

    result = cartesia_tools.localize_voice(
        voice_id="original_voice_id",
        language="es",
        name="Localized Voice",
        description="Test Localization",
        original_speaker_gender="female",
    )
    result_data = json.loads(result)

    mock_cartesia_client.voices.localize.assert_called_once_with(
        voice_id="original_voice_id",
        language="es",
        name="Localized Voice",
        description="Test Localization",
        original_speaker_gender="female",
    )
    assert result_data["id"] == "localized_voice_id"
    assert result_data["language"] == "es"
