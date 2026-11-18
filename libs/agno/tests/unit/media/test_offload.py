"""Tests for media offloading utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agno.media.media as media_module
from agno.media import File, Image
from agno.models.message import Message
from agno.run.workflow import WorkflowRunOutput
from agno.utils.media_offload import (
    _offload_single_media,
    arefresh_message_media_urls,
    iter_step_outputs,
    offload_run_media,
    offload_workflow_media,
    refresh_message_media_urls,
)
from agno.workflow.types import StepOutput


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
        _offload_single_media(img, storage, "session-1", "image")

        storage.upload.assert_called_once()
        assert img.media_reference is not None
        assert img.media_reference.storage_key == "agno/media/test-id.ext"
        assert img.content is None  # Content cleared after offload

    def test_skip_already_offloaded(self):
        storage = _mock_storage()
        from agno.media.reference import MediaReference

        ref = MediaReference(media_id="img-2", storage_key="key", storage_backend="s3")
        img = Image(url="https://example.com/img.png", media_reference=ref, id="img-2")
        _offload_single_media(img, storage, "session-1", "image")

        storage.upload.assert_not_called()

    def test_skip_url_only_media(self):
        storage = _mock_storage()
        img = Image(url="https://example.com/img.png")
        _offload_single_media(img, storage, "session-1", "image")

        storage.upload.assert_not_called()

    def test_offload_url_media_when_persist_remote_urls_enabled(self):
        storage = _mock_storage(persist_remote_urls=True)
        img = Image(url="https://example.com/img.png", id="img-url-1", mime_type="image/png")

        with patch.object(media_module, "bytes_and_mime_from_url", return_value=(b"downloaded-bytes", "image/png")):
            _offload_single_media(img, storage, "session-1", "image")

        storage.upload.assert_called_once()
        assert img.media_reference is not None
        assert img.media_reference.storage_key == "agno/media/test-id.ext"
        assert img.content is None

    def test_skip_external_file(self):
        storage = _mock_storage()
        f = File(external=MagicMock(), content=b"data")
        _offload_single_media(f, storage, "session-1", "file")

        storage.upload.assert_not_called()

    def test_offload_file_string_content(self):
        storage = _mock_storage()
        f = File(content="text content", mime_type="text/plain", id="file-1")
        _offload_single_media(f, storage, "session-1", "file")

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

        offload_run_media(run_response, storage, "session-1")

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

        offload_run_media(run_response, storage, "session-1")

        storage.upload.assert_not_called()

    def test_history_message_keeps_no_signed_url(self):
        """The refresh signs history media for this turn's model call; the row must not keep it."""
        from agno.media.reference import MediaReference

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

        ref = MediaReference(media_id="hist-img", storage_key="key-1", storage_backend="mock", bucket="test-bucket")
        msg = Message(role="user", content="test", from_history=True)
        msg.images = [Image(url="https://b.s3.amazonaws.com/key-1?X-Amz-Signature=abc", media_reference=ref)]
        run_response.messages = [msg]

        offload_run_media(run_response, storage, "session-1")

        assert msg.images[0].url is None
        storage.upload.assert_not_called()


class TestOffloadWorkflowMediaNestedSteps:
    """Loop/Condition/Router/Parallel/Steps wrap their children in a container StepOutput
    and hang them off ``StepOutput.steps``.

    Each container also copies its children's images, videos and audio up onto itself, so
    an end-to-end workflow test using those three cannot tell the nested traversal from
    the copy. None of them copies ``files``, and a hand-built container copies nothing at
    all, so both are exercised here through the ``steps`` traversal only.
    """

    def test_yields_children_of_a_container_step(self):
        grandchild = StepOutput(step_name="grandchild")
        child = StepOutput(step_name="child", steps=[grandchild])
        container = StepOutput(step_name="parallel", steps=[child])
        run = WorkflowRunOutput(run_id="wr", workflow_id="wf", step_results=[container])

        names = [s.step_name for s in iter_step_outputs(run)]
        assert names == ["parallel", "child", "grandchild"]

    def test_yields_step_results_entries_that_are_lists(self):
        """Loop iterations land in step_results as a list per iteration, not a StepOutput."""
        run = WorkflowRunOutput(run_id="wr", workflow_id="wf")
        run.step_results = [[StepOutput(step_name="iter-1"), StepOutput(step_name="iter-2")]]

        assert [s.step_name for s in iter_step_outputs(run)] == ["iter-1", "iter-2"]

    def test_offloads_file_nested_in_container_step(self):
        storage = _mock_storage()
        nested_file = File(content=b"nested-report-bytes", id="nested-file", mime_type="text/plain")
        container = StepOutput(step_name="parallel", steps=[StepOutput(step_name="p1", files=[nested_file])])
        run = WorkflowRunOutput(run_id="wr", workflow_id="wf", step_results=[container])

        offload_workflow_media(run, storage, "session-1")

        storage.upload.assert_called_once()
        assert nested_file.media_reference is not None
        assert nested_file.content is None

    def test_offloads_image_nested_two_containers_deep(self):
        storage = _mock_storage()
        deep_img = Image(content=b"deep-png-bytes", id="deep-img", mime_type="image/png")
        inner = StepOutput(step_name="inner", steps=[StepOutput(step_name="leaf", images=[deep_img])])
        outer = StepOutput(step_name="outer", steps=[inner])
        run = WorkflowRunOutput(run_id="wr", workflow_id="wf", step_results=[outer])

        offload_workflow_media(run, storage, "session-1")

        assert deep_img.media_reference is not None
        assert deep_img.content is None

    def test_scrub_drops_file_nested_in_container_step(self):
        """store_media=False takes the same traversal, so a nested file must not survive."""
        from agno.utils.agent import scrub_workflow_media

        nested = StepOutput(step_name="p1", files=[File(content=b"nested-report-bytes", id="nested-file")])
        container = StepOutput(step_name="parallel", steps=[nested])
        run = WorkflowRunOutput(run_id="wr", workflow_id="wf", step_results=[container])

        scrub_workflow_media(run)

        assert nested.files is None


class TestRefreshMessageMediaUrls:
    def test_refresh_urls(self):
        storage = _mock_storage()
        storage.get_url.return_value = "https://example.com/fresh-url"

        from agno.media.reference import MediaReference

        ref = MediaReference(
            media_id="img-1",
            storage_key="key-1",
            storage_backend="mock",
            bucket="test-bucket",
            url="https://old-url.com",
        )
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

    def test_skip_media_stored_on_another_backend(self):
        storage = _mock_storage()

        from agno.media.reference import MediaReference

        ref = MediaReference(media_id="img-1", storage_key="key-1", storage_backend="s3", bucket="other-bucket")
        img = Image(media_reference=ref, id="img-1")

        msg = Message(role="user", content="test")
        msg.images = [img]

        refresh_message_media_urls(msg, storage)

        storage.get_url.assert_not_called()
        storage.download.assert_not_called()


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

        from agno.media.reference import MediaReference

        ref = MediaReference(
            media_id="img-1",
            storage_key="key-1",
            storage_backend="mock-async",
            bucket="test-bucket",
            url="https://old-url.com",
        )
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


class TestStorageKeyScoping:
    def test_two_sessions_get_distinct_keys_for_the_same_bytes(self):
        """Deleting one session's media must not reach another session that sent the same file."""
        storage = _mock_storage()
        storage.upload.side_effect = lambda media_id, *a, **kw: f"{media_id}.png"

        first = Image(content=b"SAME BYTES", id="img", mime_type="image/png")
        second = Image(content=b"SAME BYTES", id="img", mime_type="image/png")
        _offload_single_media(first, storage, "session-A", "image")
        _offload_single_media(second, storage, "session-B", "image")

        assert first.media_reference.storage_key != second.media_reference.storage_key
        assert first.media_reference.storage_key.startswith("session-A-")
        assert second.media_reference.storage_key.startswith("session-B-")

    def test_a_long_session_id_does_not_overrun_the_key(self):
        """A filesystem name stops at 255 bytes, and a failed upload leaves base64 in the row."""
        storage = _mock_storage()
        storage.upload.side_effect = lambda media_id, *a, **kw: f"{media_id}.png"

        img = Image(content=b"BYTES", id="img", mime_type="image/png")
        _offload_single_media(img, storage, "s" * 500, "image")

        key = img.media_reference.storage_key
        assert len(key) < 255
        assert key.endswith(f"-img-{img.media_reference.content_hash[:16]}.png")

    def test_presigned_url_is_dropped_before_persistence(self):
        """A URL signed for this turn's model call expires, so it must not reach the row."""
        storage = _mock_storage()

        from agno.media.reference import MediaReference

        ref = MediaReference(media_id="img-1", storage_key="key-1", storage_backend="mock", bucket="test-bucket")
        img = Image(url="https://b.s3.amazonaws.com/key-1?X-Amz-Signature=abc&X-Amz-Expires=900", media_reference=ref)

        _offload_single_media(img, storage, "session-1", "image")

        assert img.url is None
        storage.upload.assert_not_called()

    def test_a_durable_url_survives_offload(self):
        """A caller's own public URL is not a signed one, so offload leaves it in place."""
        storage = _mock_storage(persist_remote_urls=True)
        storage.get_url.return_value = ""
        img = Image(url="https://example.com/logo.png", id="img", mime_type="image/png")

        with patch.object(media_module, "bytes_and_mime_from_url", return_value=(b"IMG", "image/png")):
            _offload_single_media(img, storage, "session-1", "image")

        assert img.url == "https://example.com/logo.png"
        assert img.media_reference is not None


def test_a_downloaded_url_gets_a_mime_type_from_its_path():
    """persist_remote_urls exists for URL-only media, which rarely carries a mime type.

    Without one the key has no extension, the object has no Content-Type, and the local
    backend writes no sidecar — so nothing records what the bytes are.
    """
    import tempfile
    from pathlib import Path

    from agno.media.storage.local import LocalMediaStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir, persist_remote_urls=True)
        image = Image(id="i", url="https://example.com/pics/photo.jpg")
        # Stubbed at the fetch so the test makes no network call
        with patch.object(media_module, "bytes_and_mime_from_url", return_value=(b"DOWNLOADED", None)):
            _offload_single_media(image, storage, "s1", "image")

        assert image.media_reference is not None
        assert image.media_reference.mime_type == "image/jpeg"
        assert image.media_reference.storage_key.endswith(".jpg")
        assert (Path(tmpdir) / f"{image.media_reference.storage_key}.meta.json").exists()
