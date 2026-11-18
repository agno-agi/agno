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


def test_default_image_model_is_current():
    """dall-e-3 was shut down on May 12, 2026; the default must be a GPT Image model."""
    assert OpenAITools(api_key="test-key").image_model == "gpt-image-2"


def test_generate_image_with_default_model_uses_base64_output():
    """GPT Image models always return base64 data, so no response_format is sent for the default."""
    import base64
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_client.images.generate.return_value = MagicMock(data=[MagicMock(b64_json=base64.b64encode(b"png").decode())])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key").generate_image(prompt="a yak")
    kwargs = fake_client.images.generate.call_args.kwargs
    assert kwargs["model"] == "gpt-image-2"
    assert "response_format" not in kwargs
    assert result is not None


def _fake_image_client(data, output_format=None):
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_client.images.generate.return_value = MagicMock(data=data, output_format=output_format)
    return fake_client


def _b64_item(payload: bytes):
    import base64
    from unittest.mock import MagicMock

    return MagicMock(b64_json=base64.b64encode(payload).decode())


def test_generate_image_returns_every_image():
    fake_client = _fake_image_client([_b64_item(b"one"), _b64_item(b"two")], output_format="webp")
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key", image_n=2).generate_image(prompt="a yak")

    assert fake_client.images.generate.call_args.kwargs["n"] == 2
    assert result.content == "2 images generated successfully."
    assert [image.content for image in result.images] == [b"one", b"two"]
    assert all(image.mime_type == "image/webp" for image in result.images)


def test_generate_image_single_image_message_and_png_default():
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key").generate_image(prompt="a yak")

    assert fake_client.images.generate.call_args.kwargs["n"] == 1
    assert result.content == "Image generated successfully."
    assert result.images[0].mime_type == "image/png"


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"image_quality": "standard"}, "Invalid quality for gpt-image-2"),
        ({"image_model": "gpt-image-1.5", "image_size": "1792x1024"}, "Invalid size for gpt-image-1.5"),
        ({"image_model": "gpt-image-1-mini", "image_quality": "hd"}, "Invalid quality for gpt-image-1-mini"),
        ({"image_n": 0}, "Invalid number of images"),
    ],
)
def test_invalid_image_options_raise_at_init(kwargs, message):
    with pytest.raises(ValueError, match=message):
        OpenAITools(api_key="test-key", **kwargs)


def test_valid_gpt_image_options_are_accepted():
    tools = OpenAITools(api_key="test-key", image_size="1536x1024", image_quality="high", image_n=3)
    assert (tools.image_size, tools.image_quality, tools.image_n) == ("1536x1024", "high", 3)


@pytest.mark.parametrize("size", ["1792x1024", "2048x1152", "2048x2048"])
def test_gpt_image_2_custom_resolution_is_sent_unchanged(size):
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        OpenAITools(api_key="test-key", image_size=size).generate_image(prompt="a yak")

    assert fake_client.images.generate.call_args.kwargs["size"] == size


@pytest.mark.parametrize("model", ["gpt-image-2", "chatgpt-image-latest"])
def test_generate_image_never_sends_response_format(model):
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key", image_model=model).generate_image(prompt="a yak")

    assert "response_format" not in fake_client.images.generate.call_args.kwargs
    assert result.images[0].content == b"one"


def test_image_style_is_not_sent_and_logs_deprecation():
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.log_warning") as log_warning:
        tools = OpenAITools(api_key="test-key", image_style="vivid")
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        tools.generate_image(prompt="a yak")

    assert "style" not in fake_client.images.generate.call_args.kwargs
    assert "style option is deprecated" in log_warning.call_args.args[0]


def test_unknown_image_model_is_not_validated():
    tools = OpenAITools(api_key="test-key", image_model="gpt-image-3", image_size="2048x2048", image_quality="ultra")
    assert tools.image_model == "gpt-image-3"


def test_image_options_are_not_validated_when_image_generation_is_disabled():
    tools = OpenAITools(api_key="test-key", enable_image_generation=False, image_quality="standard")
    assert tools.image_quality == "standard"
