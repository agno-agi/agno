"""Unit tests for OpenAITools (agno.tools.openai)."""

from unittest.mock import patch

import pytest

pytest.importorskip("openai")

from agno.tools.openai import OpenAITools  # noqa: E402


@pytest.fixture
def audio_file(tmp_path):
    """Create a small real file to stand in for an audio clip."""
    path = tmp_path / "clip.wav"
    path.write_bytes(b"fake audio bytes")
    return str(path)


def _build_tools() -> OpenAITools:
    """Build an OpenAITools instance without needing a real API key."""
    return OpenAITools(api_key="test-key", enable_transcription=True)


def test_transcribe_audio_closes_file_after_success(audio_file):
    """The audio file handle must be closed after a successful transcription.

    The handle passed to the OpenAI client is captured during the call and
    checked afterwards: it must report ``closed is True`` once
    ``transcribe_audio`` returns, proving the descriptor is not leaked.
    """
    captured = {}

    def fake_create(*, model, file, response_format):
        # Capture the actual file object the method handed to the client and
        # confirm it is still open at call time (so we are testing a real
        # handle, not a no-op).
        captured["file"] = file
        assert file.closed is False
        return "hello world"

    tools = _build_tools()
    with patch("agno.tools.openai.OpenAIClient") as mock_client:
        mock_client.return_value.audio.transcriptions.create.side_effect = fake_create
        result = tools.transcribe_audio(audio_file)

    assert result == "hello world"
    assert captured["file"].closed is True


def test_transcribe_audio_closes_file_when_api_raises(audio_file):
    """The handle must be closed even when the API call raises.

    The client is made to raise, and the captured handle must still report
    ``closed is True`` after the method returns its error string.
    """
    captured = {}

    def boom(*, model, file, response_format):
        captured["file"] = file
        raise RuntimeError("api down")

    tools = _build_tools()
    with patch("agno.tools.openai.OpenAIClient") as mock_client:
        mock_client.return_value.audio.transcriptions.create.side_effect = boom
        result = tools.transcribe_audio(audio_file)

    assert "Failed to transcribe audio" in result
    assert captured["file"].closed is True


def test_transcribe_audio_does_not_leak_descriptors_in_a_loop(audio_file):
    """Repeated calls must not accumulate open file descriptors.

    Tracks every handle opened for the audio path across many calls and asserts
    each one ends up closed.
    """
    opened = []
    real_open = open

    def tracking_open(file, *args, **kwargs):
        handle = real_open(file, *args, **kwargs)
        if file == audio_file:
            opened.append(handle)
        return handle

    tools = _build_tools()
    with patch("agno.tools.openai.OpenAIClient") as mock_client:
        mock_client.return_value.audio.transcriptions.create.return_value = "ok"
        with patch("builtins.open", side_effect=tracking_open):
            for _ in range(5):
                tools.transcribe_audio(audio_file)

    assert len(opened) == 5
    assert all(handle.closed for handle in opened)
