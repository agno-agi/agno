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


def test_get_url_is_empty():
    """A local file is not addressable off this machine, so callers are told to stream the bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        content = b"data"
        key = storage.upload("test-2", content)
        assert storage.get_url(key) is None


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


def test_local_read_path_allows_keys_inside_root():
    """The traversal guard must not reject legitimate keys."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        key = storage.upload("ok-1", b"payload", mime_type="text/plain")

        assert storage.exists(key) is True
        assert storage.download(key) == b"payload"


# Keys the hand-rolled containment check waved through: they resolved to the storage root
# or a Windows device handle, and only failed later as an IsADirectoryError.
_REJECTED_KEYS = [
    "../secret",
    "../../etc/passwd",  # never reaches a syscall: the join rejects it first
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
        # exists/get_url report absence instead, because that is what S3 and GCS report and
        # get_url's contract on the ABC is None for a key the backend cannot address.
        assert storage.exists(bad_key) is False
        assert storage.get_url(bad_key) is None
        # delete is deliberately not asserted here: these keys name real host paths, and delete
        # joins inside its try, so a regressed containment check would unlink one of them. The
        # sibling delete tests cover the same refusal against a canary under tmpdir.

        assert canary.read_bytes() == b"CANARY"


def test_delete_refuses_an_escaping_key_without_raising():
    """``delete`` reports failure the way S3 and GCS do rather than raising: a key read back from
    the DB that does not resolve inside the root returns False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        outside = root / "outside"
        outside.mkdir()
        canary = outside / "secret"
        canary.write_bytes(b"CANARY")
        storage = LocalMediaStorage(base_path=str(root / "base"))

        # The absolute key names the canary rather than a real host path: delete() joins inside
        # its try, so a regressed containment check would unlink whatever the key points at —
        # and on a non-root runner the resulting PermissionError is swallowed into the False
        # this asserts, letting the test pass through the very regression it exists to catch.
        assert storage.delete("../outside/secret") is False
        assert storage.delete(str(canary)) is False
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
        # Absolute key points at the canary, not a host path — see the sibling delete test.
        batch = [good[0], "../outside/secret", str(outside / "secret"), "NUL.png", "", good[1], good[2]]

        assert storage.delete_many(batch) == 3
        assert [p.name for p in base.iterdir()] == []
        assert (outside / "secret").read_bytes() == b"CANARY"


def test_delete_stays_idempotent_for_a_real_key():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        key = storage.upload("k", b"payload", mime_type="text/plain")
        assert storage.delete(key) is True
        assert storage.delete(key) is True


def test_async_local_runs_off_the_event_loop():
    """Every AsyncLocalMediaStorage call has to leave the loop thread, so file I/O never blocks it."""

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
            assert await storage.get_url(key) is None
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
