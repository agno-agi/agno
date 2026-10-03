"""The contract every media-storage backend has to satisfy.

Covers the batch primitive ``delete_many`` on each backend and the ABC surface a caller
reads back off a MediaReference to know what it is talking to.
"""

import inspect
import tempfile
from pathlib import Path
from typing import Dict

import pytest

from agno.media import Image
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.media.storage.local import LocalMediaStorage
from agno.run.agent import RunOutput
from agno.utils.media_offload import offload_run_media


class _MinimalStorage(MediaStorage):
    """A third-party backend implementing only the abstract surface."""

    backend_name = "minimal"

    def __init__(self) -> None:
        self.store: Dict[str, bytes] = {}

    def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None) -> str:
        self.store[media_id] = content
        return media_id

    def download(self, storage_key: str) -> bytes:
        return self.store[storage_key]

    def get_url(self, storage_key: str, *, expires_in: int = 0) -> str:
        return ""

    def delete(self, storage_key: str) -> bool:
        self.store.pop(storage_key, None)
        return True

    def exists(self, storage_key: str) -> bool:
        return storage_key in self.store


# ---------------------------------------------------------------------------
# delete_many
# ---------------------------------------------------------------------------


def test_delete_many_removes_every_key_and_counts_them():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        keys = [storage.upload(f"media-{i}", b"payload", mime_type="text/plain") for i in range(5)]

        assert storage.delete_many(keys) == 5
        assert not any(storage.exists(key) for key in keys)


def test_delete_many_is_idempotent():
    """A second sweep over the same keys must not report failure — delete() is idempotent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        keys = [storage.upload(f"media-{i}", b"payload") for i in range(3)]

        assert storage.delete_many(keys) == 3
        assert storage.delete_many(keys) == 3


def test_delete_many_mixed_present_and_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        present = storage.upload("here", b"payload")

        assert storage.delete_many([present, "never-existed", "also-gone"]) == 3


def test_delete_many_empty_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmpdir:
        assert LocalMediaStorage(base_path=tmpdir).delete_many([]) == 0


def test_delete_many_falls_back_to_delete_for_a_third_party_backend():
    """A backend that only implements delete() still gets delete_many for free."""
    storage = _MinimalStorage()
    storage.upload("a", b"1")
    storage.upload("b", b"2")

    assert storage.delete_many(["a", "b"]) == 2
    assert storage.store == {}


def test_delete_many_counts_only_what_it_removed():
    """The return value is the count a cleanup pass reports, so it tracks real deletes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        keys = [storage.upload(f"media-{i}", b"payload") for i in range(4)]

        assert storage.delete_many(keys) == 4


def test_delete_many_deletes_unconditionally():
    """delete_many holds no reference count; the caller owns that decision."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        shared = storage.upload("shared-media", b"payload")

        assert storage.delete_many([shared]) == 1
        assert not storage.exists(shared)


class TestAsyncDeleteMany:
    @pytest.mark.asyncio
    async def test_local(self):
        from agno.media.storage.local import AsyncLocalMediaStorage

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            keys = [await storage.upload(f"media-{i}", b"payload") for i in range(3)]

            assert await storage.delete_many(keys) == 3
            assert not await storage.exists(keys[0])

    @pytest.mark.asyncio
    async def test_default_loop_for_a_third_party_async_backend(self):
        class _MinimalAsyncStorage(AsyncMediaStorage):
            backend_name = "minimal-async"  # type: ignore[assignment]

            def __init__(self) -> None:
                self.deleted: list = []

            async def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None) -> str:
                return media_id

            async def download(self, storage_key: str) -> bytes:
                return b""

            async def get_url(self, storage_key: str, *, expires_in: int = 0) -> str:
                return ""

            async def delete(self, storage_key: str) -> bool:
                self.deleted.append(storage_key)
                return True

            async def exists(self, storage_key: str) -> bool:
                return False

        storage = _MinimalAsyncStorage()
        assert await storage.delete_many(["x", "y"]) == 2
        assert storage.deleted == ["x", "y"]


# ---------------------------------------------------------------------------
# ABC contract the caller reads back off a MediaReference
# ---------------------------------------------------------------------------


class _UnnamedStorage(MediaStorage):
    """A third-party backend that never declares backend_name."""

    def __init__(self, base_path: str) -> None:
        self.base_path = base_path

    def upload(self, media_id, content, *, mime_type=None, filename=None, metadata=None) -> str:
        Path(self.base_path, media_id).write_bytes(content)
        return media_id

    def download(self, storage_key: str) -> bytes:
        return Path(self.base_path, storage_key).read_bytes()

    def get_url(self, storage_key: str, *, expires_in=None) -> str:
        return ""

    def delete(self, storage_key: str) -> bool:
        return True

    def exists(self, storage_key: str) -> bool:
        return Path(self.base_path, storage_key).exists()


class _EmptyNameStorage(LocalMediaStorage):
    """A backend whose backend_name resolves to the empty string."""

    @property
    def backend_name(self):
        return ""


@pytest.mark.parametrize("storage_class", [_UnnamedStorage, _EmptyNameStorage], ids=["absent", "empty"])
def test_offload_refuses_a_backend_without_a_name(storage_class):
    """A backend the reference cannot name is skipped before the upload, not after.

    Every MediaReference records backend_name, so a backend that never sets one — or whose
    property answers "" — has nothing to record and no reference can be built for it. Skipping
    leaves the media alone: it keeps its content, the row keeps its base64, and no object is
    written that nothing could point at.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = storage_class(base_path=tmpdir)
        run = RunOutput(run_id="r1", images=[Image(id="i1", mime_type="image/png", content=b"BYTES")])

        offload_run_media(run, storage, "s1")

        assert run.images[0].media_reference is None
        assert run.images[0].content == b"BYTES"
        assert not [f for f in Path(tmpdir).rglob("*") if f.is_file()]


def test_local_reports_its_directory_as_the_container():
    """Two local roots are otherwise indistinguishable, so a reference could not name its store."""
    with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
        first = LocalMediaStorage(base_path=one)
        second = LocalMediaStorage(base_path=two)
        assert first.bucket == str(Path(one).resolve())
        assert first.bucket != second.bucket
        assert first.region is None


def test_s3_and_gcs_report_their_container():
    from agno.media.storage.gcs import AsyncGCSMediaStorage, GCSMediaStorage
    from agno.media.storage.s3 import AsyncS3MediaStorage, S3MediaStorage

    s3 = S3MediaStorage(bucket="b", region="us-east-1")
    assert (s3.backend_name, s3.bucket, s3.region) == ("s3", "b", "us-east-1")

    async_s3 = AsyncS3MediaStorage(bucket="b", region="us-east-1")
    assert (async_s3.backend_name, async_s3.bucket, async_s3.region) == ("s3", "b", "us-east-1")

    gcs = GCSMediaStorage(bucket="b")
    assert (gcs.backend_name, gcs.bucket, gcs.region) == ("gcs", "b", None)

    async_gcs = AsyncGCSMediaStorage(bucket="b")
    assert (async_gcs.backend_name, async_gcs.bucket, async_gcs.region) == ("gcs", "b", None)


def test_every_backend_defaults_expires_in_to_none():
    """None means "use the backend's configured expiry" — the ABCs and all six agree.

    An explicit number is taken literally, including 0, so the default cannot be a
    number itself.
    """
    from agno.media.storage.gcs import AsyncGCSMediaStorage, GCSMediaStorage
    from agno.media.storage.local import AsyncLocalMediaStorage
    from agno.media.storage.s3 import AsyncS3MediaStorage, S3MediaStorage

    classes = [
        MediaStorage,
        AsyncMediaStorage,
        LocalMediaStorage,
        AsyncLocalMediaStorage,
        S3MediaStorage,
        AsyncS3MediaStorage,
        GCSMediaStorage,
        AsyncGCSMediaStorage,
    ]
    for cls in classes:
        default = inspect.signature(cls.get_url).parameters["expires_in"].default
        assert default is None, f"{cls.__name__}.get_url defaults expires_in to {default}"


def test_every_name_the_package_advertises_is_importable():
    """``agno.media.storage`` resolves its backends through a hand-written ``__getattr__``.

    Every test imports from the concrete submodule instead, so a typo in one of those branches
    would break only the public path — the one users are told to use — and ship silently.
    """
    import agno.media.storage as storage_package

    unresolvable = [name for name in storage_package.__all__ if not hasattr(storage_package, name)]
    assert unresolvable == []
    with pytest.raises(AttributeError):
        storage_package.NotABackend
