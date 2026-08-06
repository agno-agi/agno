"""Tests for LocalMediaStorage."""

import asyncio
import os
import tempfile
import threading
from pathlib import Path

import pytest

from agno.exceptions import PathSecurityError
from agno.media.storage.local import AsyncLocalMediaStorage, LocalMediaStorage


def test_upload_download():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"hello world"
        key = storage.upload("test-1", content, mime_type="text/plain")
        assert storage.exists(key)
        downloaded = storage.download(key)
        assert downloaded == content


def test_upload_with_filename():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"\x89PNG\r\n"
        key = storage.upload("img-1", content, filename="photo.png")
        assert key.endswith(".png")
        assert storage.exists(key)


def test_get_url_file_uri():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"data"
        key = storage.upload("test-2", content)
        url = storage.get_url(key)
        assert url.startswith("file://")


def test_get_url_with_base_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir, base_url="http://localhost:8080/media")
        content = b"data"
        key = storage.upload("test-3", content)
        url = storage.get_url(key)
        assert url.startswith("http://localhost:8080/media/")


def test_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"to delete"
        key = storage.upload("test-4", content, mime_type="text/plain")
        assert storage.exists(key)
        assert storage.delete(key)
        assert not storage.exists(key)


def test_metadata_sidecar():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"with meta"
        key = storage.upload(
            "meta-1",
            content,
            mime_type="application/pdf",
            filename="report.pdf",
            metadata={"department": "finance"},
        )
        sidecar_path = Path(tmpdir) / (key + ".meta.json")
        assert sidecar_path.exists()

        import json

        meta = json.loads(sidecar_path.read_text())
        assert meta["original-filename"] == "report.pdf"
        assert meta["mime_type"] == "application/pdf"
        assert meta["department"] == "finance"
        assert "content-sha256" in meta
        assert meta["size"] == len(content)


def test_sidecar_name_keeps_the_extension_so_it_cannot_collide():
    """``img.png`` and ``img.jpg`` must get their own sidecar, not share one."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        png = storage.upload("img", b"PNG-BYTES", filename="img.png", mime_type="image/png")
        jpg = storage.upload("img", b"JPG-BYTES", filename="img.jpg", mime_type="image/jpeg")
        assert png != jpg
        root = Path(tmpdir)
        assert (root / "img.png.meta.json").exists()
        assert (root / "img.jpg.meta.json").exists()
        assert storage.download(png) == b"PNG-BYTES"
        assert storage.download(jpg) == b"JPG-BYTES"


def test_local_path_traversal_blocked():
    """media.id with path-traversal sequences must not escape the storage root."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = os.path.join(tmpdir, "root")
        storage = LocalMediaStorage(base_path=root)
        key = storage.upload("../../escaped", b"x", mime_type="image/png")
        resolved = (Path(root) / key).resolve()
        assert str(resolved).startswith(str(Path(root).resolve()))
        assert not (Path(tmpdir) / "escaped.png").exists()


def test_multi_segment_key_still_resolves():
    """The guard preserves nested keys; only escapes are refused."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        nested = Path(tmpdir) / "sub" / "dir"
        nested.mkdir(parents=True)
        (nested / "img.png").write_bytes(b"NESTED")
        assert storage.exists("sub/dir/img.png")
        assert storage.download("sub/dir/img.png") == b"NESTED"
        assert storage.get_url("sub/dir/img.png").endswith("sub/dir/img.png")


def test_local_read_path_allows_keys_inside_root():
    """The traversal guard must not reject legitimate keys."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        key = storage.upload("ok-1", b"payload", mime_type="text/plain")

        assert storage.exists(key) is True
        assert storage.download(key) == b"payload"
        assert storage.get_url(key).startswith("file://")


# Keys that the hand-rolled containment check used to wave through: they resolved to the
# storage root itself, or to a Windows device handle, and only failed later as an
# IsADirectoryError (or, on Windows, a device write).
_REJECTED_KEYS = [
    "../secret",
    "../../etc/passwd",
    "a/../../secret",
    "/etc/passwd",
    "C:\\Windows\\x",
    "..\\..\\etc\\passwd",
    "\uff0e\uff0e/\uff0e\uff0e/etc",  # fullwidth dots, NFKC-folded to ../../
    "img\x00.png",
    "",
    "   ",
    ". ",
    "NUL.png",
    "com1.png",
    "\\\\server\\share\\x",
]


@pytest.mark.parametrize("bad_key", _REJECTED_KEYS)
def test_reads_refuse_keys_that_escape_or_name_a_device(bad_key):
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        outside = root / "outside"
        outside.mkdir()
        canary = outside / "secret"
        canary.write_bytes(b"CANARY")
        storage = LocalMediaStorage(base_path=str(root / "base"))

        # download raises: the caller asked for bytes and cannot have them.
        with pytest.raises(PathSecurityError):
            storage.download(bad_key)
        # exists/get_url/delete report absence instead, because that is what S3 and GCS report
        # and get_url's contract on the ABC is "" for a key the backend cannot address.
        assert storage.exists(bad_key) is False
        assert storage.get_url(bad_key) == ""
        assert storage.delete(bad_key) is False

        assert canary.read_bytes() == b"CANARY"


def test_delete_refuses_an_escaping_key_without_raising():
    """``delete`` reports failure the way S3 and GCS do rather than raising.

    The containment check used to sit outside the try, so a key read back from the DB that
    no longer resolves inside the root threw out of ``delete`` instead of returning False.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        outside = root / "outside"
        outside.mkdir()
        canary = outside / "secret"
        canary.write_bytes(b"CANARY")
        storage = LocalMediaStorage(base_path=str(root / "base"))

        assert storage.delete("../outside/secret") is False
        assert storage.delete("/etc/passwd") is False
        assert storage.delete("NUL.png") is False
        assert storage.delete("") is False

        assert canary.read_bytes() == b"CANARY"


def test_delete_many_finishes_the_batch_when_a_key_is_hostile():
    """One unusable key must not strand the rest of a cleanup batch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        outside = root / "outside"
        outside.mkdir()
        (outside / "secret").write_bytes(b"CANARY")
        base = root / "base"
        storage = LocalMediaStorage(base_path=str(base))

        good = [storage.upload(f"k{i}", b"payload", mime_type="text/plain") for i in range(3)]
        batch = [good[0], "../outside/secret", "/etc/passwd", "NUL.png", "", good[1], good[2]]

        assert storage.delete_many(batch) == 3
        assert [p.name for p in base.iterdir()] == []
        assert (outside / "secret").read_bytes() == b"CANARY"


def test_delete_stays_idempotent_for_a_real_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        key = storage.upload("k", b"payload", mime_type="text/plain")
        assert storage.delete(key) is True
        assert storage.delete(key) is True


def test_get_url_normalizes_base_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        for base_url in ("https://cdn.example.com/media", "https://cdn.example.com/media/"):
            storage = LocalMediaStorage(base_path=tmpdir, base_url=base_url)
            key = storage.upload("k", b"payload", mime_type="text/plain")
            assert storage.get_url(key) == f"https://cdn.example.com/media/{key}"
        # An empty base_url is not a base_url; fall back to the file:// URI.
        storage = LocalMediaStorage(base_path=tmpdir, base_url="")
        assert storage.get_url("k.txt").startswith("file://")


def test_async_local_runs_off_the_event_loop():
    """Every AsyncLocalMediaStorage call has to leave the loop thread.

    It used to call the synchronous backend inline, so a large write blocked the loop for
    the whole duration of the file I/O.
    """

    loop_thread: dict = {}
    ran_on: dict = {}

    class _Probe(LocalMediaStorage):
        def upload(self, *args, **kwargs):
            ran_on["upload"] = threading.get_ident()
            return super().upload(*args, **kwargs)

        def download(self, storage_key):
            ran_on["download"] = threading.get_ident()
            return super().download(storage_key)

        def get_url(self, storage_key, *, expires_in=None):
            ran_on["get_url"] = threading.get_ident()
            return super().get_url(storage_key, expires_in=expires_in)

        def exists(self, storage_key):
            ran_on["exists"] = threading.get_ident()
            return super().exists(storage_key)

        def delete(self, storage_key):
            ran_on["delete"] = threading.get_ident()
            return super().delete(storage_key)

    with tempfile.TemporaryDirectory() as tmpdir:

        async def exercise():
            loop_thread["id"] = threading.get_ident()
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            storage._sync = _Probe(base_path=tmpdir)
            key = await storage.upload("k", b"payload", mime_type="text/plain")
            assert await storage.download(key) == b"payload"
            assert await storage.exists(key)
            assert (await storage.get_url(key)).startswith("file://")
            assert await storage.delete(key) is True

        asyncio.run(exercise())

    assert set(ran_on) == {"upload", "download", "get_url", "exists", "delete"}
    for method, thread_id in ran_on.items():
        assert thread_id != loop_thread["id"], f"{method} ran on the event loop thread"


def test_async_delete_many_makes_one_thread_hop_for_the_whole_batch():
    """The override exists so a 500-key cleanup is one hop, not 500."""
    with tempfile.TemporaryDirectory() as tmpdir:
        hops = {"n": 0}

        async def exercise():
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            keys = [await storage.upload(f"k{i}", b"payload", mime_type="text/plain") for i in range(25)]

            real_to_thread = asyncio.to_thread

            async def counting(func, *args, **kwargs):
                hops["n"] += 1
                return await real_to_thread(func, *args, **kwargs)

            import agno.media.storage.local.async_local as async_local

            async_local.asyncio.to_thread = counting  # type: ignore[assignment]
            try:
                assert await storage.delete_many(keys) == 25
            finally:
                async_local.asyncio.to_thread = real_to_thread  # type: ignore[assignment]

        asyncio.run(exercise())
        assert hops["n"] == 1


def test_async_delete_many_counts_only_what_it_removed():
    with tempfile.TemporaryDirectory() as tmpdir:

        async def exercise():
            storage = AsyncLocalMediaStorage(base_path=tmpdir)
            keys = [await storage.upload(f"k{i}", b"payload", mime_type="text/plain") for i in range(4)]
            assert await storage.delete_many(keys) == 4

        asyncio.run(exercise())
