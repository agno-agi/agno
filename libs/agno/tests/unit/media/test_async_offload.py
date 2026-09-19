"""Tests for the async offload path and the URL-persistence contract.

``aoffload_run_media``/``aoffload_workflow_media`` are a separate implementation from the
sync pair, so they get their own coverage. ``AsyncLocalMediaStorage`` exercises the real
upload/download path without credentials.
"""

import tempfile
from unittest.mock import patch

import pytest

from agno.media import Image
from agno.media.reference import MediaReference
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.media.storage.local import AsyncLocalMediaStorage, LocalMediaStorage
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.utils.media_offload import (
    _offload_single_media,
    aoffload_run_media,
    aoffload_workflow_media,
    offload_run_media,
)
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow


class TestAsyncOffloadRunMedia:
    @pytest.mark.asyncio
    async def test_offloads_output_and_message_media(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            out_img = Image(content=b"OUTPUT-BYTES", id="out", mime_type="image/png")
            msg_img = Image(content=b"MESSAGE-BYTES", id="msg", mime_type="image/png")
            run = RunOutput(
                run_id="r1",
                images=[out_img],
                messages=[Message(role="user", content="hi", images=[msg_img])],
            )

            await aoffload_run_media(run, storage, "s1")

            for media, payload in ((out_img, b"OUTPUT-BYTES"), (msg_img, b"MESSAGE-BYTES")):
                assert media.media_reference is not None
                assert media.content is None
                assert await storage.download(media.media_reference.storage_key) == payload

    @pytest.mark.asyncio
    async def test_reference_records_size_and_content_hash(self):
        """The reference must describe the payload, otherwise integrity checks are impossible."""
        import hashlib

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            payload = b"\x89PNG\r\n" + b"x" * 500
            img = Image(content=payload, id="i", mime_type="image/png")

            await aoffload_run_media(RunOutput(run_id="r", images=[img]), storage, "s")

            ref = img.media_reference
            assert ref.size == len(payload)
            assert ref.content_hash == hashlib.sha256(payload).hexdigest()
            assert ref.media_type == "image"
            assert ref.storage_backend == "local"

    def test_sync_reference_records_size_and_content_hash(self):
        """Same contract on the sync path, which is a separate implementation."""
        import hashlib

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalMediaStorage(base_path=tmpdir)
            payload = b"\x89PNG\r\n" + b"y" * 300
            img = Image(content=payload, id="i", mime_type="image/png")

            offload_run_media(RunOutput(run_id="r", images=[img]), storage, "s")

            ref = img.media_reference
            assert ref.size == len(payload)
            assert ref.content_hash == hashlib.sha256(payload).hexdigest()
            assert ref.media_type == "image"
            assert ref.storage_backend == "local"

    @pytest.mark.asyncio
    async def test_skips_history_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            img = Image(content=b"HISTORY", id="h", mime_type="image/png")
            run = RunOutput(
                run_id="r",
                messages=[Message(role="user", content="old", from_history=True, images=[img])],
            )

            await aoffload_run_media(run, storage, "s")

            assert img.media_reference is None
            assert img.content == b"HISTORY"

    @pytest.mark.asyncio
    async def test_skips_already_offloaded_media(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            ref = MediaReference(media_id="i", storage_key="already.png", storage_backend="local")
            img = Image(url="file:///already.png", media_reference=ref, id="i")

            await aoffload_run_media(RunOutput(run_id="r", images=[img]), storage, "s")

            assert img.media_reference is ref
            assert not await storage.exists("already.png")

    @pytest.mark.asyncio
    async def test_idless_media_gets_distinct_keys(self):
        """Two id-less images must not overwrite each other on the same storage key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            a = Image(content=b"AAAA", mime_type="image/png")
            b = Image(content=b"BBBB", mime_type="image/png")

            await aoffload_run_media(RunOutput(run_id="r", images=[a, b]), storage, "s")

            assert a.media_reference.storage_key != b.media_reference.storage_key
            assert await storage.download(a.media_reference.storage_key) == b"AAAA"
            assert await storage.download(b.media_reference.storage_key) == b"BBBB"


class TestAsyncOffloadWorkflowMedia:
    @pytest.mark.asyncio
    async def test_offloads_step_output_and_executor_run_media(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            top = Image(content=b"TOP", id="top", mime_type="image/png")
            step_img = Image(content=b"STEP", id="step", mime_type="image/png")
            exec_img = Image(content=b"EXEC", id="exec", mime_type="image/png")
            run = WorkflowRunOutput(
                run_id="wr",
                workflow_id="wf",
                images=[top],
                step_results=[StepOutput(step_name="s1", images=[step_img])],
            )
            run.step_executor_runs = [RunOutput(run_id="ar", images=[exec_img])]

            await aoffload_workflow_media(run, storage, "s")

            for media, payload in ((top, b"TOP"), (step_img, b"STEP"), (exec_img, b"EXEC")):
                assert media.media_reference is not None, f"{media.id} was not offloaded"
                assert media.content is None
                assert await storage.download(media.media_reference.storage_key) == payload

    @pytest.mark.asyncio
    async def test_offloads_nested_workflow_run_media(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            nested_img = Image(content=b"NESTED", id="nested", mime_type="image/png")
            nested = WorkflowRunOutput(run_id="inner", workflow_id="inner-wf", images=[nested_img])
            outer = WorkflowRunOutput(run_id="outer", workflow_id="outer-wf")
            outer.step_executor_runs = [nested]

            await aoffload_workflow_media(outer, storage, "s")

            assert nested_img.media_reference is not None
            assert await storage.download(nested_img.media_reference.storage_key) == b"NESTED"


class TestAsyncOffloadWorkflowSessionMedia:
    """``Workflow._aoffload_workflow_session_media`` is the hook ``asave_session`` calls
    before the DB write. It has to handle either storage flavour (arun() accepts both),
    offload onto a copy so the caller's run keeps its bytes, and never drop a run.
    """

    @staticmethod
    def _session_with_image(image: Image) -> tuple:
        run = WorkflowRunOutput(run_id="wr", workflow_id="wf", images=[image])
        return WorkflowSession(session_id="s1", workflow_id="wf", runs=[run]), run

    @pytest.mark.asyncio
    async def test_async_storage_offloads_every_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            wf = Workflow(name="wf", id="wf", steps=[], media_storage=storage)
            img = Image(content=b"SESSION-BYTES", id="i", mime_type="image/png")
            session, original_run = self._session_with_image(img)

            await wf._aoffload_workflow_session_media(session)

            persisted = session.runs[0].images[0]
            assert persisted.media_reference is not None
            assert persisted.content is None
            assert await storage.download(persisted.media_reference.storage_key) == b"SESSION-BYTES"

    @pytest.mark.asyncio
    async def test_sync_storage_offloads_every_run(self):
        """arun() with a sync backend is a supported combination, not a skip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = LocalMediaStorage(base_path=tmpdir)
            wf = Workflow(name="wf", id="wf", steps=[], media_storage=storage)
            img = Image(content=b"SYNC-SESSION-BYTES", id="i", mime_type="image/png")
            session, _ = self._session_with_image(img)

            await wf._aoffload_workflow_session_media(session)

            persisted = session.runs[0].images[0]
            assert persisted.media_reference is not None
            assert persisted.content is None
            assert storage.download(persisted.media_reference.storage_key) == b"SYNC-SESSION-BYTES"

    @pytest.mark.asyncio
    async def test_caller_run_is_not_mutated(self):
        """The offload runs on a deep copy: the run the caller still holds keeps its bytes
        and never gains a reference to storage it did not ask for."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf = Workflow(name="wf", id="wf", steps=[], media_storage=AsyncLocalMediaStorage(base_path=tmpdir))
            img = Image(content=b"CALLER-BYTES", id="i", mime_type="image/png")
            session, original_run = self._session_with_image(img)

            await wf._aoffload_workflow_session_media(session)

            assert session.runs[0] is not original_run
            assert original_run.images[0] is img
            assert img.content == b"CALLER-BYTES"
            assert img.media_reference is None

    @pytest.mark.asyncio
    async def test_backend_outage_keeps_media_inline(self):
        """A backend outage must leave the bytes in the persisted run: the offloader swallows
        per-item failures, so nothing else would notice the media had gone missing."""

        class _BrokenStorage(AsyncMediaStorage):
            backend_name = "broken"

            async def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None):
                raise RuntimeError("simulated outage")

            async def download(self, storage_key):
                return b""

            async def get_url(self, storage_key, *, expires_in=3600):
                return ""

            async def delete(self, storage_key):
                return True

            async def exists(self, storage_key):
                return True

        wf = Workflow(name="wf", id="wf", steps=[], media_storage=_BrokenStorage())
        img = Image(content=b"KEEP-ME", id="i", mime_type="image/png")
        session, _ = self._session_with_image(img)

        await wf._aoffload_workflow_session_media(session)

        assert len(session.runs) == 1
        persisted = session.runs[0].images[0]
        assert persisted.content == b"KEEP-ME"
        assert persisted.media_reference is None

    @pytest.mark.asyncio
    async def test_offloader_error_falls_back_to_the_original_run(self):
        """If the offload raises outright, the untouched run is persisted rather than a
        copy the offloader may have left half-stripped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wf = Workflow(name="wf", id="wf", steps=[], media_storage=AsyncLocalMediaStorage(base_path=tmpdir))
            img = Image(content=b"FALLBACK", id="i", mime_type="image/png")
            session, original_run = self._session_with_image(img)

            with patch(
                "agno.utils.media_offload.aoffload_workflow_media",
                side_effect=RuntimeError("simulated failure"),
            ):
                await wf._aoffload_workflow_session_media(session)

            assert session.runs[0] is original_run
            assert session.runs[0].images[0].content == b"FALLBACK"

    @pytest.mark.asyncio
    async def test_unknown_storage_type_keeps_run(self):
        """An object that is neither storage flavour is ignored, and the run still gets
        persisted rather than silently dropped from the session."""
        wf = Workflow(name="wf", id="wf", steps=[], media_storage=object())
        img = Image(content=b"UNTOUCHED", id="i", mime_type="image/png")
        session, original_run = self._session_with_image(img)

        await wf._aoffload_workflow_session_media(session)

        assert session.runs == [original_run]
        assert img.content == b"UNTOUCHED"
        assert img.media_reference is None


class _PresignedUrlStorage(MediaStorage):
    """Backend whose get_url returns a presigned URL, i.e. one that expires."""

    backend_name = "presigning"

    def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None):
        return f"{media_id}.bin"

    def download(self, storage_key):
        return b""

    def get_url(self, storage_key, *, expires_in=3600):
        return f"https://bucket.s3.amazonaws.com/{storage_key}?X-Amz-Signature=deadbeef&X-Amz-Expires=3600"

    def delete(self, storage_key):
        return True

    def exists(self, storage_key):
        return True


class _AsyncPresignedUrlStorage(AsyncMediaStorage):
    """Async counterpart of _PresignedUrlStorage."""

    backend_name = "presigning"

    def __init__(self):
        self._sync = _PresignedUrlStorage()

    async def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None):
        return self._sync.upload(media_id, content)

    async def download(self, storage_key):
        return self._sync.download(storage_key)

    async def get_url(self, storage_key, *, expires_in=3600):
        return self._sync.get_url(storage_key)

    async def delete(self, storage_key):
        return True

    async def exists(self, storage_key):
        return True


class TestPresignedUrlIsNotPersisted:
    """A presigned URL goes stale and carries credentials, so it must never reach the DB.
    The read path (media router / refresh_message_media_urls) re-signs from storage_key."""

    def test_sync_offload_does_not_persist_presigned_url(self):
        img = Image(content=b"data", id="i", mime_type="image/png")
        _offload_single_media(img, _PresignedUrlStorage(), "s", "image")

        assert img.media_reference.url is None
        assert img.url is None

    @pytest.mark.asyncio
    async def test_async_offload_does_not_persist_presigned_url(self):
        img = Image(content=b"data", id="i", mime_type="image/png")
        run = RunOutput(run_id="r", images=[img])

        await aoffload_run_media(run, _AsyncPresignedUrlStorage(), "s")

        assert img.media_reference.url is None
        assert img.url is None

    def test_stable_public_url_is_persisted(self):
        """A plain public URL does not expire, so it is kept for the frontend."""

        class _PublicUrlStorage(_PresignedUrlStorage):
            backend_name = "public"

            def get_url(self, storage_key, *, expires_in=3600):
                return f"https://cdn.example.com/{storage_key}"

        img = Image(content=b"data", id="i", mime_type="image/png")
        _offload_single_media(img, _PublicUrlStorage(), "s", "image")

        expected = f"https://cdn.example.com/{img.media_reference.storage_key}"
        assert img.media_reference.url == expected
        assert img.url == expected
