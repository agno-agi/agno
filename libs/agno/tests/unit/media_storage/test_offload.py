"""Tests for media offloading utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.media import File, Image
from agno.models.message import Message
from agno.utils.media_offload import (
    _offload_single_media,
    arefresh_message_media_urls,
    offload_run_media,
    refresh_message_media_urls,
)


def _mock_storage(persist_remote_urls: bool = False):
    storage = MagicMock()
    storage.backend_name = "mock"
    storage.bucket = "test-bucket"
    storage.region = "us-east-1"
    storage.persist_remote_urls = persist_remote_urls
    storage.upload.return_value = "agno/media/test-id.ext"
    storage.get_url.return_value = "https://example.com/presigned-url"
    return storage


class TestOffloadSingleMedia:
    def test_offload_image_with_content(self):
        storage = _mock_storage()
        img = Image(content=b"fake-png-bytes", id="img-1", mime_type="image/png")
        _offload_single_media(img, storage, "session-1", "run-1", "image")

        storage.upload.assert_called_once()
        assert img.media_reference is not None
        assert img.media_reference.storage_key == "agno/media/test-id.ext"
        assert img.content is None  # Content cleared after offload

    def test_skip_already_offloaded(self):
        storage = _mock_storage()
        from agno.media_storage.reference import MediaReference

        ref = MediaReference(media_id="img-2", storage_key="key", storage_backend="s3")
        img = Image(url="https://example.com/img.png", media_reference=ref, id="img-2")
        _offload_single_media(img, storage, "session-1", "run-1", "image")

        storage.upload.assert_not_called()

    def test_skip_url_only_media(self):
        storage = _mock_storage()
        img = Image(url="https://example.com/img.png")
        _offload_single_media(img, storage, "session-1", "run-1", "image")

        storage.upload.assert_not_called()

    def test_offload_url_media_when_persist_remote_urls_enabled(self):
        storage = _mock_storage(persist_remote_urls=True)
        img = Image(url="https://example.com/img.png", id="img-url-1", mime_type="image/png")

        with patch.object(Image, "get_content_bytes", return_value=b"downloaded-bytes"):
            _offload_single_media(img, storage, "session-1", "run-1", "image")

        storage.upload.assert_called_once()
        assert img.media_reference is not None
        assert img.media_reference.storage_key == "agno/media/test-id.ext"
        assert img.content is None

    def test_skip_external_file(self):
        storage = _mock_storage()
        f = File(external=MagicMock(), content=b"data")
        _offload_single_media(f, storage, "session-1", "run-1", "file")

        storage.upload.assert_not_called()

    def test_offload_file_string_content(self):
        storage = _mock_storage()
        f = File(content="text content", mime_type="text/plain", id="file-1")
        _offload_single_media(f, storage, "session-1", "run-1", "file")

        storage.upload.assert_called_once()
        # Verify bytes were passed (string encoded to utf-8)
        call_args = storage.upload.call_args
        assert isinstance(call_args[0][1], bytes)


class TestOffloadRunMedia:
    def test_offload_messages(self):
        storage = _mock_storage()
        run_response = MagicMock()
        run_response.input = None
        run_response.additional_input = None
        run_response.reasoning_messages = None
        run_response.images = None
        run_response.videos = None
        run_response.audio = None
        run_response.files = None
        run_response.response_audio = None

        msg = Message(role="user", content="test")
        msg.images = [Image(content=b"png-bytes", id="msg-img-1", mime_type="image/png")]
        run_response.messages = [msg]

        offload_run_media(run_response, storage, "session-1", "run-1")

        storage.upload.assert_called_once()
        assert msg.images[0].media_reference is not None

    def test_skip_history_messages(self):
        storage = _mock_storage()
        run_response = MagicMock()
        run_response.input = None
        run_response.additional_input = None
        run_response.reasoning_messages = None
        run_response.images = None
        run_response.videos = None
        run_response.audio = None
        run_response.files = None
        run_response.response_audio = None

        msg = Message(role="user", content="test", from_history=True)
        msg.images = [Image(content=b"png-bytes", id="hist-img", mime_type="image/png")]
        run_response.messages = [msg]

        offload_run_media(run_response, storage, "session-1", "run-1")

        storage.upload.assert_not_called()


class TestRefreshMessageMediaUrls:
    def test_refresh_urls(self):
        storage = _mock_storage()
        storage.get_url.return_value = "https://example.com/fresh-url"

        from agno.media_storage.reference import MediaReference

        ref = MediaReference(media_id="img-1", storage_key="key-1", storage_backend="s3", url="https://old-url.com")
        img = Image(url="https://old-url.com", media_reference=ref, id="img-1")

        msg = Message(role="user", content="test")
        msg.images = [img]

        refresh_message_media_urls(msg, storage)

        assert img.url == "https://example.com/fresh-url"
        assert img.media_reference.url == "https://example.com/fresh-url"
        storage.get_url.assert_called_once_with("key-1")

    def test_skip_media_without_reference(self):
        storage = _mock_storage()
        img = Image(url="https://example.com/img.png")

        msg = Message(role="user", content="test")
        msg.images = [img]

        refresh_message_media_urls(msg, storage)

        storage.get_url.assert_not_called()


def _mock_async_storage():
    storage = AsyncMock()
    storage.backend_name = "mock-async"
    storage.bucket = "test-bucket"
    storage.region = "us-east-1"
    storage.get_url.return_value = "https://example.com/fresh-async-url"
    return storage


class TestAsyncRefreshMessageMediaUrls:
    @pytest.mark.asyncio
    async def test_async_refresh_urls(self):
        storage = _mock_async_storage()

        from agno.media_storage.reference import MediaReference

        ref = MediaReference(media_id="img-1", storage_key="key-1", storage_backend="s3", url="https://old-url.com")
        img = Image(url="https://old-url.com", media_reference=ref, id="img-1")

        msg = Message(role="user", content="test")
        msg.images = [img]

        await arefresh_message_media_urls(msg, storage)

        assert img.url == "https://example.com/fresh-async-url"
        assert img.media_reference.url == "https://example.com/fresh-async-url"
        storage.get_url.assert_called_once_with("key-1")

    @pytest.mark.asyncio
    async def test_async_skip_media_without_reference(self):
        storage = _mock_async_storage()
        img = Image(url="https://example.com/img.png")

        msg = Message(role="user", content="test")
        msg.images = [img]

        await arefresh_message_media_urls(msg, storage)

        storage.get_url.assert_not_called()
