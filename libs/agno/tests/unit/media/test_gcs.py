"""Tests for GCSMediaStorage with a mocked google-cloud-storage bucket."""

from unittest.mock import MagicMock

import pytest


def _capture_warnings(monkeypatch):
    """Collect log_warning messages. agno's logger does not propagate, so caplog sees nothing."""
    from agno.media.storage.gcs import gcs

    messages: list = []
    monkeypatch.setattr(gcs, "log_warning", lambda msg, *a, **kw: messages.append(str(msg)))
    return messages


def _storage_with_mock_blob():
    from agno.media.storage.gcs import GCSMediaStorage

    blob = MagicMock()
    bucket = MagicMock()
    bucket.blob.return_value = blob
    storage = GCSMediaStorage(bucket="test-bucket")
    storage._bucket = bucket
    return storage, bucket, blob


class TestGCSMediaStorage:
    def test_upload(self):
        storage, bucket, blob = _storage_with_mock_blob()

        key = storage.upload("media-1", b"content", mime_type="image/png", filename="photo.png")

        blob.upload_from_string.assert_called_once_with(b"content", content_type="image/png")
        assert key.startswith("agno/media/")
        assert key.endswith(".png")
        assert blob.metadata["content-sha256"]
        assert blob.metadata["original-filename"] == "photo.png"

    def test_upload_keeps_values_gcs_accepts_verbatim(self):
        """Unlike S3, GCS metadata is a JSON body, so newlines and non-ASCII must survive."""
        storage, bucket, blob = _storage_with_mock_blob()

        storage.upload("m", b"c", metadata={"note": "line1\nline2", "who": "café 日本語", 42: "int-key"})

        assert blob.metadata["note"] == "line1\nline2"
        assert blob.metadata["who"] == "café 日本語"
        assert blob.metadata["42"] == "int-key"

    def test_upload_caps_oversized_metadata(self):
        """An oversized metadata dict fails the whole GCS upload, which would leave the bytes
        inline for the database to store as base64 — so entries over the budget are dropped."""
        storage, bucket, blob = _storage_with_mock_blob()

        storage.upload("m", b"c", metadata={"ocr": "x" * (2 * 1024 * 1024)})

        assert "ocr" not in blob.metadata
        assert blob.metadata["content-sha256"]
        blob.upload_from_string.assert_called_once()

    def test_upload_keeps_the_filename_when_caller_metadata_fills_the_budget(self):
        """Same ordering s3.py uses: the framework's own key goes in first, because the
        sanitizer stops at the size budget and a large caller value would push it out."""
        storage, bucket, blob = _storage_with_mock_blob()

        storage.upload("m", b"c", filename="report.pdf", metadata={f"k{i}": "y" * 512 for i in range(128)})

        assert blob.metadata["original-filename"] == "report.pdf"

    def test_caller_metadata_still_wins_on_a_key_collision(self):
        storage, bucket, blob = _storage_with_mock_blob()

        storage.upload("m", b"c", filename="report.pdf", metadata={"original-filename": "caller.pdf"})

        assert blob.metadata["original-filename"] == "caller.pdf"

    def test_upload_metadata_budget_is_all_entries_together(self):
        storage, bucket, blob = _storage_with_mock_blob()

        storage.upload("m", b"c", metadata={f"k{i}": "y" * 512 for i in range(128)})

        kept = {k: v for k, v in blob.metadata.items() if k != "content-sha256"}
        assert 0 < len(kept) < 128
        assert sum(len(k.encode()) + len(v.encode()) for k, v in kept.items()) <= 8000

    def test_download(self):
        storage, bucket, blob = _storage_with_mock_blob()
        blob.download_as_bytes.return_value = b"file-content"

        result = storage.download("some/key.png")

        assert result == b"file-content"
        bucket.blob.assert_called_with("some/key.png")

    def test_download_missing_object_raises_filenotfound(self):
        """A missing GCS object must surface as FileNotFoundError so the router returns 404, not 500."""
        not_found = pytest.importorskip("google.cloud.exceptions").NotFound
        storage, bucket, blob = _storage_with_mock_blob()
        blob.download_as_bytes.side_effect = not_found("No such object: test-bucket/missing/key.png")

        with pytest.raises(FileNotFoundError):
            storage.download("missing/key.png")

    def test_download_missing_object_in_a_bucket_named_bucket(self):
        """GCS names the bucket in every missing-object message, so ruling the missing-bucket
        case out by looking for the word turned each missing object in a bucket like
        "prod-bucket-eu" into a 500 instead of a 404."""
        not_found = pytest.importorskip("google.cloud.exceptions").NotFound
        storage, bucket, blob = _storage_with_mock_blob()
        blob.download_as_bytes.side_effect = not_found("No such object: prod-bucket-eu/agno/img.png")

        with pytest.raises(FileNotFoundError):
            storage.download("agno/img.png")

    def test_download_missing_bucket_propagates(self):
        """A typo'd bucket is a misconfiguration, not absent media: it must not be reported back
        as a 404 that sends the caller looking for the wrong thing."""
        not_found = pytest.importorskip("google.cloud.exceptions").NotFound
        storage, bucket, blob = _storage_with_mock_blob()
        blob.download_as_bytes.side_effect = not_found("The specified bucket does not exist.")

        with pytest.raises(not_found):
            storage.download("agno/img.png")

    def test_get_url_signed(self):
        storage, bucket, blob = _storage_with_mock_blob()
        blob.generate_signed_url.return_value = "https://signed.example.com"

        url = storage.get_url("some/key.png")

        assert url == "https://signed.example.com"
        blob.generate_signed_url.assert_called_once()

    def test_get_url_signing_failure_falls_back_to_none(self):
        """User/ADC credentials can't sign; get_url must degrade to None so offload doesn't break."""
        storage, bucket, blob = _storage_with_mock_blob()
        blob.generate_signed_url.side_effect = AttributeError("you need a private key to sign")

        assert storage.get_url("some/key.png") is None

    def test_get_url_non_signing_credential_is_not_warned_about(self, monkeypatch):
        """The ADC case is expected, so it stays at debug; a warning would fire on every run."""
        storage, bucket, blob = _storage_with_mock_blob()
        blob.generate_signed_url.side_effect = AttributeError("you need a private key to sign")
        warnings = _capture_warnings(monkeypatch)

        assert storage.get_url("some/key.png") is None
        assert warnings == []

    def test_get_url_misconfiguration_is_warned_about(self, monkeypatch):
        """An expiry past GCS's V4 seven-day ceiling is a config error, not a credential
        limitation — it must not be reported as 'non-signing credentials'."""
        storage, bucket, blob = _storage_with_mock_blob()
        blob.generate_signed_url.side_effect = ValueError("Max allowed expiration interval is seven days")
        warnings = _capture_warnings(monkeypatch)

        assert storage.get_url("some/key.png", expires_in=604801) is None
        assert any("Could not sign GCS URL" in m for m in warnings)
        assert not any("non-signing credentials" in m for m in warnings)

    def test_get_url_expires_in_none_uses_configured_expiry(self):
        from datetime import timedelta

        storage, bucket, blob = _storage_with_mock_blob()
        storage.presigned_url_expiry = 120

        storage.get_url("k.png")

        assert blob.generate_signed_url.call_args.kwargs["expiration"] == timedelta(seconds=120)

    def test_get_url_explicit_expires_in_wins_including_zero(self):
        from datetime import timedelta

        storage, bucket, blob = _storage_with_mock_blob()
        storage.presigned_url_expiry = 3600

        storage.get_url("k.png", expires_in=0)

        assert blob.generate_signed_url.call_args.kwargs["expiration"] == timedelta(seconds=0)

    def test_get_url_public(self):
        from agno.media.storage.gcs import GCSMediaStorage

        storage = GCSMediaStorage(bucket="test-bucket", public=True)
        url = storage.get_url("some/key.png")

        assert url == "https://storage.googleapis.com/test-bucket/some/key.png"

    def test_exists_true(self):
        storage, bucket, blob = _storage_with_mock_blob()
        blob.exists.return_value = True

        assert storage.exists("some/key.png") is True

    def test_exists_false(self):
        storage, bucket, blob = _storage_with_mock_blob()
        blob.exists.side_effect = Exception("boom")

        assert storage.exists("nonexistent/key.png") is False

    def test_delete(self):
        storage, bucket, blob = _storage_with_mock_blob()

        assert storage.delete("some/key.png") is True
        blob.delete.assert_called_once()

    def test_delete_failure_returns_false(self):
        storage, bucket, blob = _storage_with_mock_blob()
        blob.delete.side_effect = Exception("gone")

        assert storage.delete("some/key.png") is False

    def test_delete_missing_object_is_a_no_op(self, monkeypatch):
        """Deleting twice is not an error: True means gone, matching S3 and local."""
        not_found = pytest.importorskip("google.api_core.exceptions").NotFound
        storage, bucket, blob = _storage_with_mock_blob()
        blob.delete.side_effect = not_found("No such object: test-bucket/some/key.png")
        warnings = _capture_warnings(monkeypatch)

        assert storage.delete("some/key.png") is True
        assert warnings == []

    def test_delete_on_a_missing_bucket_reports_failure(self, monkeypatch):
        """GCS answers NotFound for a missing bucket too, so accepting every NotFound reported a
        typo'd bucket as a successful delete forever. S3 reports that case False."""
        not_found = pytest.importorskip("google.api_core.exceptions").NotFound
        storage, bucket, blob = _storage_with_mock_blob()
        blob.delete.side_effect = not_found("The specified bucket does not exist.")
        warnings = _capture_warnings(monkeypatch)

        assert storage.delete("some/key.png") is False
        assert warnings

    def test_delete_many_counts_absent_keys_as_deleted(self):
        not_found = pytest.importorskip("google.api_core.exceptions").NotFound
        storage, bucket, blob = _storage_with_mock_blob()
        blob.delete.side_effect = [None, not_found("No such object: test-bucket/b"), None]

        assert storage.delete_many(["a", "b", "c"]) == 3

    def test_backend_name(self):
        from agno.media.storage.gcs import GCSMediaStorage

        assert GCSMediaStorage(bucket="test").backend_name == "gcs"

    def test_bucket_recorded_and_region_left_unset(self):
        from agno.media.storage.gcs import GCSMediaStorage

        storage = GCSMediaStorage(bucket="test")
        assert storage.bucket == "test"
        assert storage.region is None

    def test_backend_name_is_declared_on_every_backend(self):
        """Every shipped backend sets it, so no reference is ever minted with "unknown"."""
        from agno.media.storage.gcs import AsyncGCSMediaStorage, GCSMediaStorage
        from agno.media.storage.local import AsyncLocalMediaStorage, LocalMediaStorage
        from agno.media.storage.s3 import AsyncS3MediaStorage, S3MediaStorage

        assert LocalMediaStorage.backend_name == "local"
        assert AsyncLocalMediaStorage.backend_name == "local"
        assert S3MediaStorage.backend_name == "s3"
        assert AsyncS3MediaStorage.backend_name == "s3"
        assert GCSMediaStorage.backend_name == "gcs"
        assert AsyncGCSMediaStorage.backend_name == "gcs"

    def test_prefix_is_used_verbatim(self):
        from agno.media.storage.gcs import GCSMediaStorage

        for prefix, expected in (
            ("", "m.png"),
            ("nested/a/b/", "nested/a/b/m.png"),
            ("notrail", "notrailm.png"),
        ):
            storage = GCSMediaStorage(bucket="b", prefix=prefix)
            storage._bucket = MagicMock()
            assert storage.upload("m", b"c", mime_type="image/png") == expected


class TestAsyncGCSMediaStorage:
    @pytest.mark.asyncio
    async def test_delegates_to_sync(self):
        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket")
        blob = MagicMock()
        bucket = MagicMock()
        bucket.blob.return_value = blob
        blob.download_as_bytes.return_value = b"async-bytes"
        storage._sync._bucket = bucket

        key = await storage.upload("m", b"data", mime_type="image/png")
        assert key.endswith(".png")
        blob.upload_from_string.assert_called_once_with(b"data", content_type="image/png")

        assert await storage.download("some/key.png") == b"async-bytes"

    def test_backend_name_and_bucket(self):
        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket")
        assert storage.backend_name == "gcs"
        assert storage.bucket == "test-bucket"
        assert storage.region is None

    def test_bucket_is_a_plain_attribute(self):
        """base.MediaStorage declares ``bucket`` as an attribute, so a read-only property here
        would be an incompatible override."""
        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket")
        storage.bucket = "reassigned"
        assert storage.bucket == "reassigned"

    @pytest.mark.asyncio
    async def test_upload_does_not_block_the_event_loop(self):
        """The sync client is blocking, so every call has to leave the loop thread. Calling it
        inline starves every other request the server is serving."""
        import asyncio
        import threading
        import time

        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket")
        loop_thread = threading.current_thread()
        called_on: list = []

        def blocking_upload(*args, **kwargs):
            called_on.append(threading.current_thread())
            time.sleep(0.3)
            return "k"

        storage._sync.upload = blocking_upload  # type: ignore[method-assign]

        ticks = 0
        stop = False

        async def heartbeat():
            nonlocal ticks
            while not stop:
                await asyncio.sleep(0.01)
                ticks += 1

        hb = asyncio.create_task(heartbeat())
        await storage.upload("m", b"data")
        stop = True
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass

        assert called_on and called_on[0] is not loop_thread
        # 0.3 s of blocking at a 10 ms heartbeat is ~30 ticks; inline blocking yields 0.
        assert ticks >= 10, f"event loop was starved: only {ticks} ticks"

    @pytest.mark.asyncio
    async def test_delete_many_makes_one_thread_hop_for_the_batch(self):
        import threading

        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket")
        threads: set = set()

        def tracking_delete(key):
            threads.add(threading.current_thread())
            return True

        storage._sync.delete = tracking_delete  # type: ignore[method-assign]

        assert await storage.delete_many([f"k{i}" for i in range(20)]) == 20
        assert len(threads) == 1
        assert threading.current_thread() not in threads

    @pytest.mark.asyncio
    async def test_download_missing_object_raises_filenotfound(self):
        not_found = pytest.importorskip("google.api_core.exceptions").NotFound
        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket")
        blob = MagicMock()
        bucket = MagicMock()
        bucket.blob.return_value = blob
        blob.download_as_bytes.side_effect = not_found("No such object: test-bucket/missing/key.png")
        storage._sync._bucket = bucket

        with pytest.raises(FileNotFoundError):
            await storage.download("missing/key.png")

    @pytest.mark.asyncio
    async def test_get_url_passes_expires_in_through(self):
        from agno.media.storage.gcs import AsyncGCSMediaStorage

        storage = AsyncGCSMediaStorage(bucket="test-bucket", presigned_url_expiry=99)
        seen: dict = {}

        def fake_get_url(key, *, expires_in=None):
            seen["expires_in"] = expires_in
            return "https://signed"

        storage._sync.get_url = fake_get_url  # type: ignore[method-assign]

        assert await storage.get_url("k") == "https://signed"
        assert seen["expires_in"] is None
        await storage.get_url("k", expires_in=5)
        assert seen["expires_in"] == 5
