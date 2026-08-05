import os
from unittest.mock import MagicMock, patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.media import File, Video
from agno.models.message import Message
from agno.models.moonshot import MoonShot


def _mock_client(extracted_text="EXTRACTED TEXT", upload_status="ok", content_error=None):
    """Build a mocked OpenAI client for the Moonshot Files endpoints.

    Uploads return sequential Moonshot-style ids and the given status; files.retrieve
    reports the same status (so the status poll completes immediately); files.content
    returns the extracted text, or raises content_error if provided.
    """
    client = MagicMock()
    counter = {"n": 0}

    def fake_create(file, purpose):
        counter["n"] += 1
        result = MagicMock()
        result.id = f"moonshot-file-{counter['n']}"
        result.status = upload_status
        result.status_details = None
        return result

    def fake_retrieve(file_id):
        result = MagicMock()
        result.status = upload_status
        return result

    def fake_content(file_id):
        if content_error is not None:
            raise content_error
        result = MagicMock()
        result.text = extracted_text
        return result

    client.files.create.side_effect = fake_create
    client.files.retrieve.side_effect = fake_retrieve
    client.files.content.side_effect = fake_content
    return client


def _model_with_client(client, **kwargs):
    model = MoonShot(id="kimi-k3", api_key="test-api-key", **kwargs)
    model.get_client = lambda: client  # type: ignore[method-assign]
    return model


# ---------------------------------------------------------------------------
# Initialization and client params
# ---------------------------------------------------------------------------


def test_moonshot_initialization_with_api_key():
    model = MoonShot(id="kimi-k2.5", api_key="test-api-key")
    assert model.id == "kimi-k2.5"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://api.moonshot.ai/v1"


def test_moonshot_default_config():
    model = MoonShot(api_key="test-api-key")
    assert model.id == "kimi-k3"
    assert model.name == "Moonshot"
    assert model.provider == "Moonshot"
    # reasoning_effort is opt-in; the API defaults to "max" server-side for K3.
    assert model.reasoning_effort is None
    # use_thinking defaults to None (use the model default).
    assert model.use_thinking is None
    # Kimi supports response_format={"type": "json_schema"} natively.
    assert model.supports_native_structured_outputs is True


def test_moonshot_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = MoonShot(id="kimi-k2.5")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_moonshot_initialization_with_env_api_key():
    with patch.dict(os.environ, {"MOONSHOT_API_KEY": "env-api-key"}):
        model = MoonShot(id="kimi-k2.5")
        assert model.api_key == "env-api-key"


def test_moonshot_client_params():
    model = MoonShot(id="kimi-k2.5", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://api.moonshot.ai/v1"


# ---------------------------------------------------------------------------
# Reasoning request params
# ---------------------------------------------------------------------------


def test_use_thinking_default_sends_no_thinking_flag():
    """use_thinking=None means the thinking flag is not sent at all."""
    model = MoonShot(api_key="test")
    params = model.get_request_params()

    assert "thinking" not in params.get("extra_body", {})


def test_use_thinking_true_enables():
    model = MoonShot(api_key="test", use_thinking=True)
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_use_thinking_false_disables():
    model = MoonShot(api_key="test", use_thinking=False)
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_use_thinking_false_strips_reasoning_effort():
    """reasoning_effort has no effect with thinking off, so it is stripped."""
    model = MoonShot(api_key="test", use_thinking=False, reasoning_effort="max")
    params = model.get_request_params()

    assert "reasoning_effort" not in params


def test_reasoning_effort_passes_through():
    model = MoonShot(api_key="test", reasoning_effort="low")
    params = model.get_request_params()

    assert params["reasoning_effort"] == "low"


def test_user_extra_body_merged_with_thinking():
    """A user-supplied extra_body is preserved and merged with the thinking flag."""
    model = MoonShot(api_key="test", use_thinking=True, extra_body={"custom_key": "custom_value"})
    params = model.get_request_params()

    assert params["extra_body"]["custom_key"] == "custom_value"
    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_explicit_thinking_setting_preserved():
    """An explicit thinking setting in extra_body is never overwritten (raw escape hatch)."""
    model = MoonShot(api_key="test", use_thinking=True, extra_body={"thinking": {"type": "disabled"}})
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "disabled"}


# ---------------------------------------------------------------------------
# Message formatting: reasoning round-trip
# ---------------------------------------------------------------------------


def test_format_message_roundtrips_reasoning_content():
    model = MoonShot(api_key="test")
    message = Message(role="assistant", content="answer", reasoning_content="step by step")
    message_dict = model._format_message(message)

    assert message_dict["reasoning_content"] == "step by step"


def test_format_message_without_reasoning_content():
    model = MoonShot(api_key="test")
    message = Message(role="user", content="hi")
    message_dict = model._format_message(message)

    assert "reasoning_content" not in message_dict


# ---------------------------------------------------------------------------
# Message formatting: files (upload + extract)
# ---------------------------------------------------------------------------


def test_file_uploaded_extracted_and_injected():
    client = _mock_client()
    model = _model_with_client(client)
    file = File(content=b"pdf-bytes", filename="doc.pdf")
    message = Message(role="user", content="summarize this", files=[file])

    message_dict = model._format_message(message)

    client.files.create.assert_called_once()
    assert client.files.create.call_args.kwargs["purpose"] == "file-extract"
    text_parts = [p for p in message_dict["content"] if p.get("type") == "text"]
    assert any("EXTRACTED TEXT" in p["text"] for p in text_parts)
    # Kimi rejects OpenAI `file` parts - none may be emitted.
    assert all(p.get("type") != "file" for p in message_dict["content"])


def test_file_id_written_back_and_reused():
    """The Moonshot id is stored on the File, so a second format does not re-upload."""
    client = _mock_client()
    model = _model_with_client(client)
    file = File(content=b"pdf-bytes", filename="doc.pdf")
    message = Message(role="user", content="summarize this", files=[file])

    model._format_message(message)
    assert file.id == "moonshot-file-1"

    model._format_message(message)
    client.files.create.assert_called_once()


def test_stale_file_id_falls_back_to_upload():
    """A pre-set id that Moonshot does not recognize triggers a fresh upload."""
    client = _mock_client()
    calls = {"n": 0}

    def content_stale_then_ok(file_id):
        calls["n"] += 1
        if file_id == "not-a-moonshot-id":
            raise RuntimeError("404 resource_not_found_error")
        result = MagicMock()
        result.text = "EXTRACTED TEXT"
        return result

    client.files.content.side_effect = content_stale_then_ok
    model = _model_with_client(client)
    file = File(content=b"pdf-bytes", filename="doc.pdf", id="not-a-moonshot-id")
    message = Message(role="user", content="summarize this", files=[file])

    message_dict = model._format_message(message)

    client.files.create.assert_called_once()
    assert file.id == "moonshot-file-1"
    assert any("EXTRACTED TEXT" in str(p) for p in message_dict["content"])


def test_failed_upload_attaches_nothing():
    client = _mock_client()
    client.files.create.side_effect = RuntimeError("400 text extract error")
    model = _model_with_client(client)
    file = File(content=b"pdf-bytes", filename="doc.pdf")
    message = Message(role="user", content="summarize this", files=[file])

    message_dict = model._format_message(message)

    assert message_dict["content"] == [{"type": "text", "text": "summarize this"}]
    assert message.files == [file]  # restored after formatting


def test_file_upload_with_error_status_attaches_nothing():
    """An upload that reports a failed parse status is not attached."""
    client = _mock_client(upload_status="error")
    model = _model_with_client(client)
    file = File(content=b"pdf-bytes", filename="doc.pdf")
    message = Message(role="user", content="summarize this", files=[file])

    message_dict = model._format_message(message)

    assert message_dict["content"] == [{"type": "text", "text": "summarize this"}]
    client.files.content.assert_not_called()


# ---------------------------------------------------------------------------
# Message formatting: videos (upload + ms:// reference)
# ---------------------------------------------------------------------------


def test_video_uploaded_and_referenced():
    client = _mock_client()
    model = _model_with_client(client)
    video = Video(content=b"video-bytes")
    message = Message(role="user", content="describe this", videos=[video])

    message_dict = model._format_message(message)

    assert client.files.create.call_args.kwargs["purpose"] == "video"
    video_parts = [p for p in message_dict["content"] if p.get("type") == "video_url"]
    assert video_parts == [{"type": "video_url", "video_url": {"url": "ms://moonshot-file-1"}}]
    # The ms:// reference is written back so later turns reuse it.
    assert video.id == "ms://moonshot-file-1"


def test_video_not_reuploaded_and_not_duplicated():
    """Re-formatting the same message reuses the ms:// id and never accumulates parts."""
    client = _mock_client()
    model = _model_with_client(client)
    video = Video(content=b"video-bytes")
    message = Message(role="user", content="describe this", videos=[video])

    first = model._format_message(message)
    second = model._format_message(message)

    client.files.create.assert_called_once()
    for message_dict in (first, second):
        video_parts = [p for p in message_dict["content"] if p.get("type") == "video_url"]
        assert len(video_parts) == 1
    # The stored message content is never mutated by formatting.
    assert message.content == "describe this"


def test_media_restored_after_formatting():
    """Files and videos are hidden from the base class but always restored."""
    client = _mock_client()
    model = _model_with_client(client)
    file = File(content=b"pdf-bytes", filename="doc.pdf")
    video = Video(content=b"video-bytes")
    message = Message(role="user", content="look", files=[file], videos=[video])

    model._format_message(message)

    assert message.files == [file]
    assert message.videos == [video]
