from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.deepseek import DeepSeek


def test_default_config():
    """Default DeepSeek configuration uses deepseek-v4-flash with thinking-friendly defaults."""
    model = DeepSeek()

    assert model.id == "deepseek-v4-flash"
    assert model.name == "DeepSeek"
    assert model.provider == "DeepSeek"
    assert model.base_url == "https://api.deepseek.com"
    # reasoning_effort is opt-in (matches OpenAIChat); the API uses its own default.
    assert model.reasoning_effort is None
    # use_thinking flag defaults to None (use model default).
    assert model.use_thinking is None
    # Structured output support is currently broken upstream.
    assert model.supports_native_structured_outputs is False


def test_requires_api_key():
    """DeepSeek raises an error when no API key is provided."""
    model = DeepSeek()

    with patch.dict("os.environ", {}, clear=True):
        model.api_key = None
        with pytest.raises(ModelAuthenticationError, match="DEEPSEEK_API_KEY not set"):
            model._get_client_params()


def test_thinking_enabled_by_default_for_flash():
    """get_request_params injects thinking mode for the default deepseek-v4-flash."""
    model = DeepSeek(api_key="test")
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_thinking_enabled_by_default_for_pro():
    """get_request_params injects thinking mode for deepseek-v4-pro."""
    model = DeepSeek(id="deepseek-v4-pro", api_key="test")
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_user_extra_body_merged_with_thinking():
    """A user-supplied extra_body is preserved and merged with the thinking flag."""
    model = DeepSeek(api_key="test", extra_body={"custom_key": "custom_value"})
    params = model.get_request_params()

    assert params["extra_body"]["custom_key"] == "custom_value"
    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_explicit_thinking_setting_preserved():
    """An explicit thinking setting in extra_body is never overwritten (raw escape hatch)."""
    model = DeepSeek(api_key="test", extra_body={"thinking": {"type": "disabled"}})
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_use_thinking_false_disables():
    """use_thinking=False turns thinking off on a thinking-capable model."""
    model = DeepSeek(api_key="test", use_thinking=False)
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_use_thinking_false_strips_reasoning_effort():
    """use_thinking=False strips reasoning_effort since it has no effect without thinking."""
    model = DeepSeek(api_key="test", use_thinking=False, reasoning_effort="max")
    params = model.get_request_params()

    assert "reasoning_effort" not in params


def test_use_thinking_true_forces_thinking_on_legacy_chat():
    """use_thinking=True forces thinking on even for the legacy non-thinking deepseek-chat."""
    model = DeepSeek(id="deepseek-chat", api_key="test", use_thinking=True)
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_deepseek_chat_is_non_thinking():
    """The deprecated deepseek-chat maps to non-thinking mode: no thinking flag injected."""
    model = DeepSeek(id="deepseek-chat", api_key="test")
    params = model.get_request_params()

    assert "thinking" not in params.get("extra_body", {})


def test_deepseek_chat_strips_reasoning_effort():
    """reasoning_effort has no effect in non-thinking mode and is stripped for deepseek-chat."""
    model = DeepSeek(id="deepseek-chat", api_key="test", reasoning_effort="max")
    params = model.get_request_params()

    assert "reasoning_effort" not in params


def test_deepseek_reasoner_is_thinking():
    """The deprecated deepseek-reasoner maps to thinking mode, so thinking is injected."""
    model = DeepSeek(id="deepseek-reasoner", api_key="test")
    params = model.get_request_params()

    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def _uploading_model(file_ids=("file-api-1", "file-api-2")):
    """DeepSeek model whose Files API client is mocked."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    model = DeepSeek(api_key="test")
    client = MagicMock()
    client.files.create.side_effect = [SimpleNamespace(id=i) for i in file_ids]
    model.get_client = lambda: client  # type: ignore[method-assign]
    return model, client


def test_pdf_file_is_uploaded_and_sent_as_flat_file_id_part():
    """Documents go through the Files API and are referenced by a flat file_id part."""
    from agno.media import File
    from agno.models.message import Message

    model, client = _uploading_model()
    message = Message(
        role="user",
        content="What is the price?",
        files=[File(content=b"%PDF-1.4", mime_type="application/pdf", filename="a.pdf")],
    )

    formatted = model._format_message(message)

    assert formatted["content"][0] == {"type": "file", "file_id": "file-api-1"}
    assert formatted["content"][1] == {"type": "text", "text": "What is the price?"}
    kwargs = client.files.create.call_args.kwargs
    assert kwargs["purpose"] == "text_recognition"
    assert kwargs["file"] == ("a.pdf", b"%PDF-1.4")


def test_file_parsing_purpose_is_configurable():
    from agno.media import File

    model, client = _uploading_model()
    model.file_parsing_purpose = "rich_layout_recognition"

    model._format_file_part(File(content=b"%PDF", mime_type="application/pdf"))

    assert client.files.create.call_args.kwargs["purpose"] == "rich_layout_recognition"


def test_text_files_use_user_data_purpose():
    """Plain text/spreadsheets are rejected by the parsing purposes, so they use user_data."""
    from agno.media import File

    model, client = _uploading_model()

    model._format_file_part(File(content=b"a,b\n1,2", mime_type="text/csv", filename="d.csv"))

    assert client.files.create.call_args.kwargs["purpose"] == "user_data"


def test_same_file_is_uploaded_once():
    """Re-formatting the same content across turns must not re-upload (and re-bill) it."""
    from agno.media import File

    model, client = _uploading_model()
    file = File(content=b"%PDF-1.4", mime_type="application/pdf")

    first = model._format_file_part(file)
    second = model._format_file_part(file)

    assert first == second == {"type": "file", "file_id": "file-api-1"}
    assert client.files.create.call_count == 1


def test_external_string_is_used_as_file_id_without_upload():
    from agno.media import File

    model, client = _uploading_model()

    part = model._format_file_part(File(external="file-api-existing"))

    assert part == {"type": "file", "file_id": "file-api-existing"}
    client.files.create.assert_not_called()


def test_upload_failure_raises_instead_of_dropping_the_file():
    """A failed upload must fail the run, not send the request without the document."""
    from agno.exceptions import ModelProviderError
    from agno.media import File

    model, client = _uploading_model()
    client.files.create.side_effect = RuntimeError("Failed to recognize the file")

    with pytest.raises(ModelProviderError, match="Failed to recognize the file"):
        model._format_file_part(File(content=b"%PDF", mime_type="application/pdf", filename="a.pdf"))


def test_unreadable_file_raises():
    from agno.exceptions import ModelProviderError
    from agno.media import File

    model, client = _uploading_model()

    with pytest.raises(ModelProviderError, match="missing.pdf"):
        model._format_file_part(File(filepath="does/not/exist/missing.pdf"))
    client.files.create.assert_not_called()


def test_file_only_message_keeps_the_file_part():
    """A message with files and no text must still carry its file parts."""
    from agno.media import File
    from agno.models.message import Message

    model, _ = _uploading_model()
    message = Message(role="user", content=None, files=[File(content=b"%PDF", mime_type="application/pdf")])

    formatted = model._format_message(message)

    assert formatted["content"] == [{"type": "file", "file_id": "file-api-1"}]


def test_storage_backed_file_is_read_through_get_content_bytes():
    """Files that only carry a media_reference (offloaded media) are resolved, not dropped."""
    from agno.media import File
    from agno.media.reference import MediaReference

    model, client = _uploading_model()
    file = File(
        media_reference=MediaReference(
            media_id="m1", storage_key="k/report.pdf", storage_backend="s3", filename="report.pdf"
        )
    )

    with patch.object(File, "get_content_bytes", return_value=b"%PDF-stored"):
        part = model._format_file_part(file)

    assert part == {"type": "file", "file_id": "file-api-1"}
    kwargs = client.files.create.call_args.kwargs
    assert kwargs["file"] == ("report.pdf", b"%PDF-stored")
    assert kwargs["purpose"] == "text_recognition"


def test_uploaded_file_id_is_persisted_on_the_file():
    """The DeepSeek id travels with File.id, so a reloaded session does not re-upload the file."""
    from agno.media import File

    model, client = _uploading_model()
    file = File(content=b"%PDF", mime_type="application/pdf")
    model._format_file_part(file)
    assert file.id == "deepseek://file-api-1"

    # Simulate a new process: a fresh model instance and a File rebuilt from stored session data.
    restored = File.model_validate(file.model_dump())
    fresh_model, fresh_client = _uploading_model()

    assert fresh_model._format_file_part(restored) == {"type": "file", "file_id": "file-api-1"}
    fresh_client.files.create.assert_not_called()


async def test_ainvoke_uploads_files_with_the_async_client():
    """arun must not block the event loop on a (slow, parsing) sync upload."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from agno.media import File
    from agno.models.message import Message
    from agno.models.openai.chat import OpenAIChat

    model, sync_client = _uploading_model()
    async_client = MagicMock()
    async_client.files.create = AsyncMock(return_value=SimpleNamespace(id="file-api-async"))
    model.get_async_client = lambda: async_client  # type: ignore[method-assign]
    file = File(content=b"%PDF", mime_type="application/pdf")
    messages = [Message(role="user", content="Summarise", files=[file])]

    async def fake_ainvoke(self, messages, **kwargs):
        # Formatting inside the parent call must reuse the async upload.
        return self._format_message(messages[0])

    with patch.object(OpenAIChat, "ainvoke", fake_ainvoke):
        formatted = await model.ainvoke(messages=messages, assistant_message=Message(role="assistant"))

    assert formatted["content"][0] == {"type": "file", "file_id": "file-api-async"}
    async_client.files.create.assert_awaited_once()
    sync_client.files.create.assert_not_called()
