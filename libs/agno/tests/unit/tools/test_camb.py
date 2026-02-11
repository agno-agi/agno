"""Tests for CAMB AI agno toolkit."""

import json
from unittest.mock import MagicMock, Mock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


@patch("camb.client.CambAI")
@patch("camb.client.AsyncCambAI")
def test_init_with_api_key(mock_async, mock_sync):
    from agno.tools.camb import CambTools

    tools = CambTools(api_key="test-key")
    assert tools.api_key == "test-key"


@patch("camb.client.CambAI")
@patch("camb.client.AsyncCambAI")
def test_init_with_env(mock_async, mock_sync):
    from agno.tools.camb import CambTools

    with patch.dict("os.environ", {"CAMB_API_KEY": "env-key"}):
        tools = CambTools()
        assert tools.api_key == "env-key"


def test_init_no_key_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="CAMB_API_KEY not set"):
            from agno.tools.camb import CambTools
            CambTools()


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_text_to_speech(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client
    mock_client.text_to_speech.tts.return_value = [b"chunk1", b"chunk2"]

    tools = CambTools(api_key="test-key")
    result = tools.text_to_speech("Hello world")

    assert result.endswith(".wav")
    mock_client.text_to_speech.tts.assert_called_once()


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_translate(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client

    mock_result = Mock()
    mock_result.text = "Hola mundo"
    mock_client.translation.translation_stream.return_value = mock_result

    tools = CambTools(api_key="test-key")
    result = tools.translate("Hello world", source_language=1, target_language=2)

    assert result == "Hola mundo"


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_translate_api_error_workaround(mock_sync, mock_async):
    from camb.core.api_error import ApiError
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client
    mock_client.translation.translation_stream.side_effect = ApiError(
        status_code=200, body="Hola mundo"
    )

    tools = CambTools(api_key="test-key")
    result = tools.translate("Hello world", source_language=1, target_language=2)

    assert result == "Hola mundo"


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_transcribe(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client

    mock_create = Mock(task_id="task-1")
    mock_client.transcription.create_transcription.return_value = mock_create

    mock_status = Mock(status="completed", run_id="run-1")
    mock_client.transcription.get_transcription_task_status.return_value = mock_status

    mock_transcription = Mock(text="Hello", segments=[], speakers=[])
    mock_client.transcription.get_transcription_result.return_value = mock_transcription

    tools = CambTools(api_key="test-key")
    result = tools.transcribe(language=1, audio_url="https://example.com/audio.mp3")

    out = json.loads(result)
    assert out["text"] == "Hello"


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_transcribe_no_source(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    tools = CambTools(api_key="test-key")
    result = tools.transcribe(language=1)

    out = json.loads(result)
    assert "error" in out


# ---------------------------------------------------------------------------
# Voice List
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_list_voices(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client

    mock_voice = Mock(id=123, voice_name="Test Voice", gender=2, age=25, language=1)
    mock_client.voice_cloning.list_voices.return_value = [mock_voice]

    tools = CambTools(api_key="test-key")
    result = tools.list_voices()

    voices = json.loads(result)
    assert len(voices) == 1
    assert voices[0]["id"] == 123
    assert voices[0]["gender"] == "female"


# ---------------------------------------------------------------------------
# Voice Clone
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_clone_voice(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client

    mock_result = Mock(voice_id=999, message="Created")
    mock_client.voice_cloning.create_custom_voice.return_value = mock_result

    tools = CambTools(api_key="test-key")

    with patch("builtins.open", mock_open(read_data=b"audio")):
        result = tools.clone_voice("My Voice", "/fake/path.wav", gender=1)

    out = json.loads(result)
    assert out["voice_id"] == 999
    assert out["status"] == "created"


# ---------------------------------------------------------------------------
# Text to Sound
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_text_to_sound(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client

    mock_create = Mock(task_id="task-1")
    mock_client.text_to_audio.create_text_to_audio.return_value = mock_create

    mock_status = Mock(status="completed", run_id="run-1")
    mock_client.text_to_audio.get_text_to_audio_status.return_value = mock_status
    mock_client.text_to_audio.get_text_to_audio_result.return_value = [b"audio"]

    tools = CambTools(api_key="test-key")
    result = tools.text_to_sound("upbeat music")

    assert result.endswith(".wav")


# ---------------------------------------------------------------------------
# Audio Separation
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_separate_audio(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    mock_client = MagicMock()
    mock_sync.return_value = mock_client

    mock_create = Mock(task_id="task-1")
    mock_client.audio_separation.create_audio_separation.return_value = mock_create

    mock_status = Mock(status="completed", run_id="run-1")
    mock_client.audio_separation.get_audio_separation_status.return_value = mock_status

    mock_sep = Mock(
        vocals_url="https://example.com/vocals.wav",
        background_url="https://example.com/bg.wav",
        voice_url=None, instrumental_url=None, vocals=None, background=None,
    )
    mock_client.audio_separation.get_audio_separation_run_info.return_value = mock_sep

    tools = CambTools(api_key="test-key")

    with patch("builtins.open", mock_open(read_data=b"audio")):
        result = tools.separate_audio(audio_file_path="/fake/audio.mp3")

    out = json.loads(result)
    assert out["status"] == "completed"
    assert out["vocals"] == "https://example.com/vocals.wav"


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_selective_tools(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    tools = CambTools(api_key="test-key", enable_tts=True, enable_translation=True,
                      enable_transcription=False, enable_translated_tts=False,
                      enable_voice_clone=False, enable_voice_list=False,
                      enable_text_to_sound=False, enable_audio_separation=False)

    assert "text_to_speech" in tools.functions
    assert "translate" in tools.functions
    assert "transcribe" not in tools.functions


@patch("camb.client.AsyncCambAI")
@patch("camb.client.CambAI")
def test_all_flag(mock_sync, mock_async):
    from agno.tools.camb import CambTools

    tools = CambTools(api_key="test-key", all=True)
    assert len(tools.functions) == 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_gender_str():
    from agno.tools.camb import CambTools

    assert CambTools._gender_str(1) == "male"
    assert CambTools._gender_str(2) == "female"
    assert CambTools._gender_str(0) == "not_specified"
    assert CambTools._gender_str(99) == "unknown"


def test_detect_audio_format():
    from agno.tools.camb import CambTools

    assert CambTools._detect_audio_format(b"RIFF" + b"\x00" * 50) == "wav"
    assert CambTools._detect_audio_format(b"\xff\xfb" + b"\x00" * 50) == "mp3"
    assert CambTools._detect_audio_format(b"fLaC" + b"\x00" * 50) == "flac"
    assert CambTools._detect_audio_format(b"\x00" * 50) == "pcm"


def test_add_wav_header():
    from agno.tools.camb import CambTools

    pcm = b"\x00" * 100
    wav = CambTools._add_wav_header(pcm)
    assert wav.startswith(b"RIFF")
    assert wav.endswith(pcm)
