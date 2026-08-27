"""Unit tests for Speko tools."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.agent import Agent
from agno.tools.function import ToolResult
from agno.tools.speko import SPEKO_BASE_URL, SPEKO_SAMPLE_RATE, SpekoTools

MODELS_RESPONSE = {
    "object": "list",
    "data": [
        {
            "id": "deepgram:aura-2",
            "api": "tts",
            "provider": "deepgram",
            "routable": True,
            "languages": ["en"],
            "latencyMs": 150,
            "costPerMinUsd": 15.0,
            "quality": 4.2,
            "qualityUnit": "MOS",
            "voices": [
                {"id": "aura-2-thalia-en", "name": "Thalia", "gender": "female", "styles": ["clear", "confident"]},
                {"id": "aura-2-orion-en", "name": "Orion", "gender": "male", "styles": ["deep"]},
            ],
        },
        {
            "id": "fishaudio:s2.1-pro",
            "api": "tts",
            "provider": "fishaudio",
            "routable": False,
            "voices": [{"id": "fish-1", "name": "Fish", "gender": "neutral", "styles": []}],
        },
        {
            "id": "soniox:stt-rt-v5",
            "api": "stt",
            "provider": "soniox",
            "routable": True,
            "languages": ["en", "es"],
            "latencyMs": 300,
            "costPerMinUsd": 0.1,
            "quality": 5.4,
            "qualityUnit": "% WER",
        },
    ],
    "languages": ["en", "es"],
}


@pytest.fixture
def mock_agent():
    agent = MagicMock(spec=Agent)
    return agent


@pytest.fixture
def speko_tools():
    """Create SpekoTools instance with a test API key."""
    with patch.dict("os.environ", {"SPEKO_API_KEY": "test_key"}):
        return SpekoTools()


def test_init_with_api_key():
    """Test initialization with API key."""
    tools = SpekoTools(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.tts_model == "auto"
    assert tools.stt_model == "auto"
    assert tools.voice is None
    assert tools.output_format == "wav"
    assert tools.language is None
    assert tools.objective is None


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch.dict("os.environ", {"SPEKO_API_KEY": "env_key"}):
        tools = SpekoTools()
        assert tools.api_key == "env_key"


def test_init_missing_api_key():
    """Test initialization with missing API key logs an error but does not raise."""
    with patch("agno.tools.speko.getenv", return_value=None):
        tools = SpekoTools()
        assert tools.api_key is None


def test_init_override_defaults():
    """Test initialization overriding defaults."""
    tools = SpekoTools(
        api_key="test_key",
        tts_model="deepgram:aura-2",
        stt_model="soniox:stt-rt-v5",
        voice="aura-2-thalia-en",
        output_format="pcm",
        language="es",
        objective="latency",
    )
    assert tools.tts_model == "deepgram:aura-2"
    assert tools.stt_model == "soniox:stt-rt-v5"
    assert tools.voice == "aura-2-thalia-en"
    assert tools.output_format == "pcm"
    assert tools.language == "es"
    assert tools.objective == "latency"


def test_init_invalid_output_format_raises():
    """Test that an invalid output format raises a clear error instead of failing later."""
    with pytest.raises(ValueError, match="Invalid output_format"):
        SpekoTools(api_key="test_key", output_format="mp3")


def test_init_invalid_objective_raises():
    """Test that an invalid routing objective raises a clear error instead of failing later."""
    with pytest.raises(ValueError, match="Invalid objective"):
        SpekoTools(api_key="test_key", objective="cheapest")


def test_init_default_base_url():
    """Test that base_url defaults to the Speko API endpoint."""
    tools = SpekoTools(api_key="test_key")
    assert tools.base_url == SPEKO_BASE_URL


def test_init_custom_base_url(mock_agent):
    """Test that a custom base_url is used for text-to-speech requests."""
    custom_url = "https://self-hosted.example.com/v1"
    tools = SpekoTools(api_key="test_key", base_url=custom_url)
    assert tools.base_url == custom_url

    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/wav"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        tools.text_to_speech(mock_agent, "Hello world")

    args, _ = mock_post.call_args
    assert args[0] == f"{custom_url}/audio/speech"


def test_feature_registration(speko_tools):
    """Test that the expected tools are registered."""
    assert "text_to_speech" in speko_tools.functions
    assert "transcribe_audio" in speko_tools.functions
    assert "list_voices" in speko_tools.functions
    assert "list_models" not in speko_tools.functions


def test_feature_registration_disabled():
    """Test disabling and enabling tools."""
    tools = SpekoTools(api_key="test_key", enable_list_voices=False, enable_list_models=True)
    assert "list_voices" not in tools.functions
    assert "list_models" in tools.functions
    assert "text_to_speech" in tools.functions

    tools = SpekoTools(api_key="test_key", all=True)
    assert "list_models" in tools.functions


def test_text_to_speech_success(speko_tools, mock_agent):
    """Test successful text-to-speech generation."""
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/wav"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        result = speko_tools.text_to_speech(mock_agent, "Hello world")

    assert isinstance(result, ToolResult)
    assert result.content == "Audio generated successfully"
    assert result.audios is not None
    assert len(result.audios) == 1
    assert result.audios[0].content == b"audio data"
    assert result.audios[0].mime_type == "audio/wav"
    assert result.audios[0].sample_rate == SPEKO_SAMPLE_RATE

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == f"{SPEKO_BASE_URL}/audio/speech"
    assert kwargs["json"]["model"] == "auto"
    assert kwargs["json"]["input"] == "Hello world"
    assert kwargs["json"]["response_format"] == "wav"
    assert "voice" not in kwargs["json"]
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["headers"]["X-Source"] == "agno"
    assert "X-Speko-Language" not in kwargs["headers"]
    assert "X-Speko-Objective" not in kwargs["headers"]


def test_text_to_speech_voice_override(speko_tools, mock_agent):
    """Test text-to-speech with a per-call voice override."""
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/wav"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        speko_tools.text_to_speech(mock_agent, "Hello world", voice="aura-2-thalia-en")

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["voice"] == "aura-2-thalia-en"


def test_text_to_speech_routing_headers(mock_agent):
    """Test that configured language and objective are sent as Speko routing headers."""
    tools = SpekoTools(api_key="test_key", language="es", objective="latency", voice="aura-2-thalia-en")
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/wav"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        tools.text_to_speech(mock_agent, "Hola mundo")

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-Speko-Language"] == "es"
    assert kwargs["headers"]["X-Speko-Objective"] == "latency"
    assert kwargs["json"]["voice"] == "aura-2-thalia-en"


def test_text_to_speech_pcm_mime_type(mock_agent):
    """Test that pcm output format sets the correct mime type."""
    tools = SpekoTools(api_key="test_key", output_format="pcm")
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/pcm;rate=24000"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        result = tools.text_to_speech(mock_agent, "Hello world")

    assert result.audios[0].mime_type == "audio/pcm"
    assert result.audios[0].format == "pcm"
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Accept"] == "audio/pcm"
    assert kwargs["json"]["response_format"] == "pcm"


def test_text_to_speech_saves_to_target_directory(mock_agent, tmp_path):
    """Test that audio is saved to disk when target_directory is set."""
    target_dir = tmp_path / "audio"
    tools = SpekoTools(api_key="test_key", target_directory=str(target_dir))
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/wav"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response):
        tools.text_to_speech(mock_agent, "Hello world")

    saved_files = list(target_dir.glob("*.wav"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"audio data"


def test_text_to_speech_saves_multiple_times_without_overwriting(mock_agent, tmp_path):
    """Test that repeated saves get unique filenames instead of overwriting each other."""
    target_dir = tmp_path / "audio"
    tools = SpekoTools(api_key="test_key", target_directory=str(target_dir))
    mock_response = MagicMock()
    mock_response.content = b"audio data"
    mock_response.headers = {"content-type": "audio/wav"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response):
        tools.text_to_speech(mock_agent, "Hello world")
        tools.text_to_speech(mock_agent, "Hello again")

    saved_files = list(target_dir.glob("*.wav"))
    assert len(saved_files) == 2


def test_text_to_speech_error(speko_tools, mock_agent):
    """Test text-to-speech error handling against a real HTTP error response."""
    request = httpx.Request("POST", f"{SPEKO_BASE_URL}/audio/speech")
    error_response = httpx.Response(
        401, json={"error": {"code": "invalid_api_key", "message": "Provide a valid Speko API key."}}, request=request
    )

    with patch("agno.tools.speko.httpx.post", return_value=error_response):
        result = speko_tools.text_to_speech(mock_agent, "Hello world")

    assert isinstance(result, ToolResult)
    assert "Error" in result.content
    assert not result.audios


def test_text_to_speech_unexpected_content_type(speko_tools, mock_agent):
    """Test that a non-audio 200 response (e.g. a JSON error body) is treated as an error."""
    mock_response = MagicMock()
    mock_response.content = b'{"error": "invalid voice"}'
    mock_response.text = '{"error": "invalid voice"}'
    mock_response.headers = {"content-type": "application/json"}
    mock_response.raise_for_status.return_value = None

    with patch("agno.tools.speko.httpx.post", return_value=mock_response):
        result = speko_tools.text_to_speech(mock_agent, "Hello world")

    assert isinstance(result, ToolResult)
    assert "Error" in result.content
    assert not result.audios


def test_transcribe_audio_success(speko_tools, tmp_path):
    """Test successful audio transcription with a multipart upload."""
    audio_file = tmp_path / "clip.wav"
    audio_file.write_bytes(b"RIFF fake wav bytes")

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"text": "Hello from Speko."}

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        result = speko_tools.transcribe_audio(str(audio_file))

    assert result == "Hello from Speko."
    args, kwargs = mock_post.call_args
    assert args[0] == f"{SPEKO_BASE_URL}/audio/transcriptions"
    assert kwargs["data"]["model"] == "auto"
    assert kwargs["files"]["file"][0] == "clip.wav"
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["headers"]["X-Source"] == "agno"


def test_transcribe_audio_pinned_model(tmp_path):
    """Test that a pinned STT model is sent in the multipart form."""
    audio_file = tmp_path / "clip.wav"
    audio_file.write_bytes(b"RIFF fake wav bytes")

    tools = SpekoTools(api_key="test_key", stt_model="soniox:stt-rt-v5")
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"text": "Pinned."}

    with patch("agno.tools.speko.httpx.post", return_value=mock_response) as mock_post:
        result = tools.transcribe_audio(str(audio_file))

    assert result == "Pinned."
    _, kwargs = mock_post.call_args
    assert kwargs["data"]["model"] == "soniox:stt-rt-v5"


def test_transcribe_audio_missing_file(speko_tools):
    """Test that a missing audio file returns an error instead of raising."""
    result = speko_tools.transcribe_audio("/nonexistent/clip.wav")
    assert result.startswith("Error")


def test_transcribe_audio_http_error(speko_tools, tmp_path):
    """Test transcription error handling against a real HTTP error response."""
    audio_file = tmp_path / "clip.wav"
    audio_file.write_bytes(b"RIFF fake wav bytes")

    request = httpx.Request("POST", f"{SPEKO_BASE_URL}/audio/transcriptions")
    error_response = httpx.Response(413, json={"error": {"code": "request_too_large"}}, request=request)

    with patch("agno.tools.speko.httpx.post", return_value=error_response):
        result = speko_tools.transcribe_audio(str(audio_file))

    assert result.startswith("Error")


def test_list_voices_success(speko_tools):
    """Test successful voice listing flattened from the routable TTS models."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = MODELS_RESPONSE

    with patch("agno.tools.speko.httpx.get", return_value=mock_response) as mock_get:
        result = speko_tools.list_voices()

    args, kwargs = mock_get.call_args
    assert args[0] == f"{SPEKO_BASE_URL}/models"
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["headers"]["X-Source"] == "agno"

    voices = json.loads(result)
    assert len(voices) == 2  # non-routable fishaudio voice excluded
    assert voices[0]["id"] == "aura-2-thalia-en"
    assert voices[0]["name"] == "Thalia"
    assert voices[0]["gender"] == "female"
    assert voices[0]["model"] == "deepgram:aura-2"
    assert voices[0]["provider"] == "deepgram"
    assert voices[1]["id"] == "aura-2-orion-en"


def test_list_voices_error(speko_tools):
    """Test voice listing error handling against a real HTTP error response."""
    request = httpx.Request("GET", f"{SPEKO_BASE_URL}/models")
    error_response = httpx.Response(500, json={"error": "internal"}, request=request)

    with patch("agno.tools.speko.httpx.get", return_value=error_response):
        result = speko_tools.list_voices()

    assert result.startswith("Error")


def test_list_models_success(speko_tools):
    """Test model listing returns all stages by default."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = MODELS_RESPONSE

    with patch("agno.tools.speko.httpx.get", return_value=mock_response):
        result = speko_tools.list_models()

    models = json.loads(result)
    assert len(models) == 3
    assert models[0]["id"] == "deepgram:aura-2"
    assert models[2]["api"] == "stt"


def test_list_models_api_filter(speko_tools):
    """Test model listing filtered to a single API stage."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = MODELS_RESPONSE

    with patch("agno.tools.speko.httpx.get", return_value=mock_response):
        result = speko_tools.list_models(api="stt")

    models = json.loads(result)
    assert len(models) == 1
    assert models[0]["id"] == "soniox:stt-rt-v5"
    assert models[0]["languages"] == ["en", "es"]


def test_list_models_error(speko_tools):
    """Test model listing error handling against a real HTTP error response."""
    request = httpx.Request("GET", f"{SPEKO_BASE_URL}/models")
    error_response = httpx.Response(503, json={"error": "unavailable"}, request=request)

    with patch("agno.tools.speko.httpx.get", return_value=error_response):
        result = speko_tools.list_models()

    assert result.startswith("Error")
