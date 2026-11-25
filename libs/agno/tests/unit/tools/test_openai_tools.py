"""Unit tests for OpenAITools (agno.tools.openai)."""

import base64
import inspect
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("openai")

from agno.tools.openai import (  # noqa: E402
    AUDIO_CHAT_MODELS,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TRANSCRIPTION_MODEL,
    DEFAULT_TTS_MODEL,
    RETIRING_MODELS,
    SPEECH_API_MODELS,
    OpenAITools,
)


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

    def fake_create(*, model, file):
        # Capture the actual file object the method handed to the client and
        # confirm it is still open at call time (so we are testing a real
        # handle, not a no-op).
        captured["file"] = file
        assert file.closed is False
        return MagicMock(text="hello world")

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

    def boom(*, model, file):
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
        mock_client.return_value.audio.transcriptions.create.return_value = MagicMock(text="ok")
        with patch("builtins.open", side_effect=tracking_open):
            for _ in range(5):
                tools.transcribe_audio(audio_file)

    assert len(opened) == 5
    assert all(handle.closed for handle in opened)


def test_default_transcription_model_is_current():
    """whisper-1 shuts down on February 26, 2027, so the default must be its replacement."""
    assert OpenAITools(api_key="test-key").transcription_model == "gpt-transcribe"
    assert DEFAULT_TRANSCRIPTION_MODEL not in RETIRING_MODELS


def test_transcribe_audio_sends_no_response_format(audio_file):
    """Several transcription models accept only the default JSON object, so none is sent."""
    tools = _build_tools()
    with patch("agno.tools.openai.OpenAIClient") as mock_client:
        create = mock_client.return_value.audio.transcriptions.create
        create.return_value = MagicMock(text="transcribed")
        tools.transcribe_audio(audio_file)

    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "gpt-transcribe"
    assert "response_format" not in kwargs


@pytest.mark.parametrize(
    "response, expected",
    [
        (MagicMock(text="from an object"), "from an object"),
        ({"text": "from a dict"}, "from a dict"),
        ("a bare string", "a bare string"),
    ],
)
def test_transcript_is_read_from_any_response_shape(audio_file, response, expected):
    """A JSON response, a mapping and a plain string all yield the transcript."""
    tools = _build_tools()
    with patch("agno.tools.openai.OpenAIClient") as mock_client:
        mock_client.return_value.audio.transcriptions.create.return_value = response
        assert tools.transcribe_audio(audio_file) == expected


@pytest.mark.parametrize("response", [{"no_text": 1}, object()])
def test_a_response_without_text_is_reported_not_stringified(audio_file, response):
    """Handing the model an object repr as if it were the transcript would be worse than failing."""
    tools = _build_tools()
    with patch("agno.tools.openai.OpenAIClient") as mock_client:
        mock_client.return_value.audio.transcriptions.create.return_value = response
        result = tools.transcribe_audio(audio_file)

    assert "Failed to transcribe audio" in result
    assert "carried no text" in result


def test_default_image_model_is_current():
    """gpt-image-2 shuts down on February 10, 2027, so the default must be its replacement."""
    assert OpenAITools(api_key="test-key").image_model == "gpt-image-2.6-sunburst"
    assert DEFAULT_IMAGE_MODEL not in RETIRING_MODELS


def test_generate_image_with_default_model_uses_base64_output():
    """GPT Image models always return base64 data, so no response_format is sent for the default."""
    fake_client = MagicMock()
    fake_client.images.generate.return_value = MagicMock(data=[MagicMock(b64_json=base64.b64encode(b"png").decode())])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key").generate_image(prompt="a yak")
    kwargs = fake_client.images.generate.call_args.kwargs
    assert kwargs["model"] == "gpt-image-2.6-sunburst"
    assert "response_format" not in kwargs
    assert result is not None


def _fake_image_client(data, output_format=None):
    fake_client = MagicMock()
    fake_client.images.generate.return_value = MagicMock(data=data, output_format=output_format)
    return fake_client


def _b64_item(payload: bytes):
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
        ({"image_quality": "standard"}, "Invalid quality for gpt-image-2.6-sunburst"),
        ({"image_model": "gpt-image-1.5", "image_size": "1792x1024"}, "Invalid size for gpt-image-1.5"),
        ({"image_model": "gpt-image-1-mini", "image_quality": "hd"}, "Invalid quality for gpt-image-1-mini"),
        ({"image_model": "gpt-image-2", "image_quality": "xhigh"}, "Invalid quality for gpt-image-2"),
        ({"image_complexity": "ultra"}, "Invalid complexity for gpt-image-2.6-sunburst"),
        ({"image_model": "gpt-image-2", "image_complexity": "high"}, "gpt-image-2 does not accept a complexity"),
        ({"image_n": 0}, "Invalid number of images"),
    ],
)
def test_invalid_image_options_raise_at_init(kwargs, message):
    with pytest.raises(ValueError, match=message):
        OpenAITools(api_key="test-key", **kwargs)


def test_valid_gpt_image_options_are_accepted():
    tools = OpenAITools(api_key="test-key", image_size="1536x1024", image_quality="high", image_n=3)
    assert (tools.image_size, tools.image_quality, tools.image_n) == ("1536x1024", "high", 3)


@pytest.mark.parametrize("quality", ["auto", "low", "medium", "high", "xhigh", "max"])
def test_sunburst_and_flare_accept_the_two_extra_quality_levels(quality):
    tools = OpenAITools(api_key="test-key", image_model="gpt-image-2.6-flare", image_quality=quality)
    assert tools.image_quality == quality


@pytest.mark.parametrize("complexity", ["low", "medium", "high"])
def test_image_complexity_is_sent_in_extra_body(complexity):
    """complexity postdates the openai floor this package supports, so it is not a named argument."""
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        OpenAITools(api_key="test-key", image_complexity=complexity).generate_image(prompt="a yak")

    kwargs = fake_client.images.generate.call_args.kwargs
    assert kwargs["extra_body"] == {"complexity": complexity}
    assert "complexity" not in kwargs


def test_image_complexity_is_accepted_by_the_installed_sdk_signature():
    """A named complexity argument would raise TypeError; extra_body is accepted on every version."""
    from openai.resources.images import Images

    parameters = inspect.signature(Images.generate).parameters
    assert "extra_body" in parameters
    assert "complexity" not in parameters


def test_image_complexity_is_omitted_when_unset():
    """Left unset, the model applies its own default, so nothing is sent at all."""
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        OpenAITools(api_key="test-key").generate_image(prompt="a yak")

    kwargs = fake_client.images.generate.call_args.kwargs
    assert "complexity" not in kwargs
    assert "extra_body" not in kwargs


@pytest.mark.parametrize("size", ["1792x1024", "2048x1152", "2048x2048"])
def test_default_model_custom_resolution_is_sent_unchanged(size):
    fake_client = _fake_image_client([_b64_item(b"one")])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        OpenAITools(api_key="test-key", image_size=size).generate_image(prompt="a yak")

    assert fake_client.images.generate.call_args.kwargs["size"] == size


@pytest.mark.parametrize("model", ["gpt-image-2.6-sunburst", "gpt-image-2.5-flare", "chatgpt-image-latest"])
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
    assert any("style option is deprecated" in call.args[0] for call in log_warning.call_args_list)


def test_unknown_image_model_is_not_validated():
    tools = OpenAITools(
        api_key="test-key",
        image_model="gpt-image-3",
        image_size="2048x2048",
        image_quality="ultra",
        image_complexity="extreme",
    )
    assert tools.image_model == "gpt-image-3"


def test_legacy_positional_arguments_still_bind_to_the_same_parameters():
    """image_complexity is keyword-only, so it cannot displace image_style or image_n."""
    fake_client = _fake_image_client([_b64_item(b"one"), _b64_item(b"two")])
    with patch("agno.tools.openai.log_warning"):
        tools = OpenAITools(
            "test-key",
            True,
            True,
            True,
            False,
            "whisper-1",
            "alloy",
            "tts-1",
            "mp3",
            "gpt-image-2",
            None,
            None,
            "vivid",
            2,
        )

    assert (tools.image_style, tools.image_n, tools.image_complexity) == ("vivid", 2, None)
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        tools.generate_image(prompt="a yak")
    assert fake_client.images.generate.call_args.kwargs["n"] == 2


def test_image_complexity_cannot_be_passed_positionally():
    with pytest.raises(TypeError):
        OpenAITools(
            "test-key",
            True,
            True,
            True,
            False,
            "gpt-transcribe",
            "alloy",
            "gpt-audio-1.5",
            "mp3",
            None,
            None,
            None,
            None,
            1,
            "high",
        )


def test_image_options_are_not_validated_when_image_generation_is_disabled():
    tools = OpenAITools(api_key="test-key", enable_image_generation=False, image_quality="standard")
    assert tools.image_quality == "standard"


def test_default_tts_model_is_current():
    """Every /v1/audio/speech model shuts down on January 6, 2027, so the default is an audio chat model."""
    assert OpenAITools(api_key="test-key").tts_model == "gpt-audio-1.5"
    assert DEFAULT_TTS_MODEL not in RETIRING_MODELS


def _fake_chat_client(data="YXVkaW8=", transcript="narrated"):
    fake_client = MagicMock()
    message = MagicMock(audio=MagicMock(data=data, transcript=transcript))
    fake_client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=message)])
    return fake_client


def test_generate_speech_uses_chat_completions_for_the_default_model():
    """The default model is served by chat completions, which returns base64 audio."""
    fake_client = _fake_chat_client(data=base64.b64encode(b"spoken").decode())
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key").generate_speech(agent=None, text_input="hello there")

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-audio-1.5"
    assert kwargs["modalities"] == ["text", "audio"]
    assert kwargs["audio"] == {"voice": "alloy", "format": "mp3"}
    assert kwargs["messages"][1] == {"role": "user", "content": "hello there"}
    assert result.audios[0].content == b"spoken"
    assert result.audios[0].mime_type == "audio/mp3"
    fake_client.audio.speech.create.assert_not_called()


def test_generate_speech_tells_the_audio_chat_model_to_narrate():
    """An audio chat model would otherwise answer the text instead of reading it out."""
    fake_client = _fake_chat_client()
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        OpenAITools(api_key="test-key").generate_speech(agent=None, text_input="Is a yak a good pet?")

    system_message = fake_client.chat.completions.create.call_args.kwargs["messages"][0]
    assert system_message["role"] == "system"
    assert "word for word" in system_message["content"]


def test_generate_speech_maps_pcm_to_the_chat_format_name():
    """Chat completions call raw PCM "pcm16"; the speech endpoint calls it "pcm"."""
    fake_client = _fake_chat_client()
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key", text_to_speech_format="pcm").generate_speech(
            agent=None, text_input="hello"
        )

    assert fake_client.chat.completions.create.call_args.kwargs["audio"]["format"] == "pcm16"
    assert result.audios[0].mime_type == "audio/pcm"


def test_generate_speech_reports_a_response_without_audio():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(audio=None))])
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key").generate_speech(agent=None, text_input="hello")

    assert "Failed to generate speech" in result.content
    assert result.audios is None


@pytest.mark.parametrize("model", sorted(SPEECH_API_MODELS))
def test_speech_api_models_still_use_the_speech_endpoint(model):
    """A pinned /v1/audio/speech model keeps working until OpenAI shuts it down."""
    fake_client = MagicMock()
    fake_client.audio.speech.create.return_value = MagicMock(content=b"legacy audio")
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key", text_to_speech_model=model).generate_speech(
            agent=None, text_input="hello"
        )

    kwargs = fake_client.audio.speech.create.call_args.kwargs
    assert kwargs == {"model": model, "voice": "alloy", "input": "hello", "response_format": "mp3"}
    assert result.audios[0].content == b"legacy audio"
    fake_client.chat.completions.create.assert_not_called()


def test_generate_speech_reports_a_failing_speech_endpoint():
    fake_client = MagicMock()
    fake_client.audio.speech.create.side_effect = RuntimeError("model_not_found")
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        result = OpenAITools(api_key="test-key", text_to_speech_model="tts-1").generate_speech(
            agent=None, text_input="hello"
        )

    assert "Failed to generate speech" in result.content
    assert "model_not_found" in result.content


@pytest.mark.parametrize(
    "kwargs, parameter, shutdown_date",
    [
        ({"text_to_speech_model": "tts-1"}, "text_to_speech_model", "January 6, 2027"),
        ({"image_model": "gpt-image-2"}, "image_model", "February 10, 2027"),
        ({"transcription_model": "whisper-1"}, "transcription_model", "February 26, 2027"),
    ],
)
def test_retiring_models_warn_with_the_date_and_replacement(kwargs, parameter, shutdown_date):
    """A model pinned to a retiring id is flagged at construction, before the date passes."""
    with patch("agno.tools.openai.log_warning") as log_warning:
        OpenAITools(api_key="test-key", **kwargs)

    warnings = [call.args[0] for call in log_warning.call_args_list]
    assert any(shutdown_date in message and parameter in message for message in warnings)


def test_current_defaults_do_not_warn():
    with patch("agno.tools.openai.log_warning") as log_warning:
        OpenAITools(api_key="test-key")

    assert log_warning.call_args_list == []


def test_a_retiring_model_for_a_disabled_tool_does_not_warn():
    """Nothing is sent for a tool that is switched off, so nothing is warned about."""
    with patch("agno.tools.openai.log_warning") as log_warning:
        OpenAITools(api_key="test-key", enable_speech_generation=False, text_to_speech_model="tts-1")

    assert log_warning.call_args_list == []


def test_only_known_audio_chat_models_leave_the_speech_endpoint():
    """The two sets must not overlap, or a model would be routed to an endpoint it is not served by."""
    assert AUDIO_CHAT_MODELS.isdisjoint(SPEECH_API_MODELS)
    assert DEFAULT_TTS_MODEL in AUDIO_CHAT_MODELS


@pytest.mark.parametrize("model", ["gpt-4o-mini-tts-2025-03-20", "some-future-speech-model"])
def test_an_unlisted_model_keeps_using_the_speech_endpoint(model):
    """Routing is an allowlist, so a model this version has not heard of cannot be sent somewhere new."""
    fake_client = MagicMock()
    fake_client.audio.speech.create.return_value = MagicMock(content=b"audio")
    with patch("agno.tools.openai.OpenAIClient", return_value=fake_client):
        with patch("agno.tools.openai.log_warning"):
            tools = OpenAITools(api_key="test-key", text_to_speech_model=model)
        result = tools.generate_speech(agent=None, text_input="hello")

    assert fake_client.audio.speech.create.call_args.kwargs["model"] == model
    fake_client.chat.completions.create.assert_not_called()
    assert result.audios[0].content == b"audio"


@pytest.mark.parametrize(
    "model, shutdown_date",
    [
        ("gpt-4o-mini-tts-2025-03-20", "January 6, 2027"),
        ("gpt-audio-2025-08-28", "January 20, 2027"),
    ],
)
def test_dated_snapshots_are_in_the_retirement_table(model, shutdown_date):
    """A snapshot id retires on its own schedule and has to be listed in its own right."""
    assert RETIRING_MODELS[model][0] == shutdown_date

    with patch("agno.tools.openai.log_warning") as log_warning:
        OpenAITools(api_key="test-key", text_to_speech_model=model)

    assert any(shutdown_date in call.args[0] for call in log_warning.call_args_list)


def test_every_speech_api_model_is_in_the_retirement_table():
    """They all shut down on January 6, 2027, so none may be missing a warning."""
    assert all(model in RETIRING_MODELS for model in SPEECH_API_MODELS)
